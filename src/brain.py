import threading
import time
import queue
from shell import InteractiveShell
import discord
import asyncio
from agent import MistralAgent

from typing import Annotated
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain.schema import SystemMessage

from langchain_mistralai import ChatMistralAI
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.tools import tool
from langchain_core.rate_limiters import InMemoryRateLimiter

import logging
import pprint


# MISTRAL_SYSPROMPT = "Your task is to translate english to bash commands.
# Respond in a single bash command that can be run directly in the shell, don't
# use any formatting and respond in plaintext"



MISTRAL_SYSPROMPT = "You are a Discord bot whose task is to translate english to bash commands. Execute bash commands using the given tools. ALWAYS report command results back to the user via Discord message tool. Before taking any section, generate a plan and follow it until the end."


class State(TypedDict):
    # Messages have the type "list". The `add_messages` function
    # in the annotation defines how this state key should be updated
    # (in this case, it appends messages to the list, rather than overwriting them)
    messages: Annotated[list, add_messages]

class Brain:
    def __init__(self):
        # self.logger = logging.getLogger("brain")

        self.channel = None
        self.discord_loop = None

        # self.chat_state = queue.Queue()
        # self.shell_state = queue.Queue()
        
        self.incoming_msg_buffer = queue.Queue()        # thread safe
        self.shell_out_buffer = queue.Queue()           # thread safe

        self.shell = InteractiveShell()
        self.shell.set_output_callback(self._drain_shell)
        self.shell.start()
    
    def start(self):
        # Lang graph setup
        self.graph_builder = StateGraph(State)
        self.rate_limiter = InMemoryRateLimiter(
            requests_per_second=0.1,  # <-- Super slow! We can only make a request once every 10 seconds!!
            check_every_n_seconds=0.1,  # Wake up every 100 ms to check whether allowed to make a request,
            max_bucket_size=10,  # Controls the maximum burst size.
        )
        self.llm = ChatMistralAI(model="mistral-large-latest", rate_limiter=self.rate_limiter)

        @tool
        def send_discord_msg_tool(msg: str) -> str:
            """Send a message to Discord.
            Args:
                cmd: Bash shell command string.
            """
            
            self.send_discord_msg(msg) 
            return "Message sent to discord!" 
        
        @tool
        def execute_shell_cmd_tool(cmd: str) -> str:
            """Execute a shell command.
            Args:
                cmd: Bash shell command string.
            """
            
            self.shell.execute_command(cmd)

            time.sleep(1)

            outputs = []

            while not self.shell_out_buffer.empty():
                outputs.append(self.shell_out_buffer.get())

            return "Outputs:\n" + "\n".join(outputs)
        
        # @tool
        # def get_shell_output_tool() -> str:
        #     """Get all unseen output from the shell."""
            
        #     outputs = []

        #     while not self.shell_out_buffer.empty():
        #         outputs.append(self.shell_out_buffer.get())

        #     print("Get shell tool is returning", outputs)

        #     return "\n".join(outputs)

        # Set up tools
        self.tools = [send_discord_msg_tool, execute_shell_cmd_tool]
        self.llm = self.llm.bind_tools(self.tools)

        self.tool_node = ToolNode(tools=self.tools)

        # Constructing the graph
        self.graph_builder.add_node("chatbot", self.chatbot)
        self.graph_builder.add_node("tools", self.tool_node)

        self.graph_builder.add_conditional_edges(
            "chatbot",
            tools_condition,
        )

        # self.graph_builder.add_edge("tools", "chatbot")
        self.graph_builder.set_entry_point("chatbot")

        # TODO(waitz): do we need to set END?
        # self.graph_builder.add_edge(START, "chatbot")

        self.graph_builder.add_edge("tools", "chatbot")

        # self.graph_builder.add_edge("chatbot", END)

        self.graph = self.graph_builder.compile()

        # start a thread on brain_main
        self.mthread = threading.Thread(target=self._brain_main)
        self.mthread.start()
        # self.agent = MistralAgent()

    def chatbot(self, state: State):
        message = self.llm.invoke(state["messages"])
        return {"messages": [message]}

    # should only be called by `self.shell` as a callback
    def _drain_shell(self, line: str):
        self.shell_out_buffer.put(line)
        
        print(f"Brain received line from shell: `{line}`")

    def __del__(self):
        self.mthread.join()
        self.shell.stop()

    def submit_msg(self, msg: str):
        # this should only be called externally
        print(f"Message being submitted to brain: `{msg}`")
        self.incoming_msg_buffer.put(msg)

    def _brain_main(self):
        while True:
            time.sleep(1)
            print("Brain taking a step.")

            # check if there is a message in the incoming_msg_buffer
            if not self.incoming_msg_buffer.empty():
                sys_prompt = SystemMessage(MISTRAL_SYSPROMPT)
                msg = self.incoming_msg_buffer.get()

                # Prompting, interacting with shell, and responding to discord happens
                # in lang graph
                output = self.graph.invoke({"messages": [sys_prompt, msg]}, debug=True)

                print(f"Output from graph:")
                pprint.pprint(output)

                # completion = self.agent.run(msg)

                # print(f"Brain sending command to shell: `{completion}`")
                
                # self.shell.execute_command(completion)     # this shouldn't bloc

            # check if there is a new message in the shell_out_buffer

    def send_discord_msg(self, msg: str):
        assert self.discord_loop is not None and self.discord_loop.is_running(), \
                "Trying to send msg before discord loop is initialized"

        print(f"Brain sending message to discord: `{msg}`")
        asyncio.run_coroutine_threadsafe(self._send_discord_msg(msg), self.discord_loop)

    async def _send_discord_msg(self, msg: str):
        print("Channel:", self.channel)
        print("Event loop:", self.discord_loop)
        print(f"Brain sending message to discord: `{msg}`")
        await self.channel.send(msg)