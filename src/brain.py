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
from langchain_core.messages import ToolMessage, AIMessage

from langchain_mistralai import ChatMistralAI
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.tools import tool
from langchain_core.rate_limiters import InMemoryRateLimiter

import logging
import dspy

from mistralLM import Mistral
from signatures import Replanning, Planning, planning_signature, replanning_prompt

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
        dspy.settings.configure(lm=Mistral(model="mistral-large-latest", api_key="GG92nvhLbocT2jn7YeDmRSK0KmURoGIC"))

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

        # Passed into lang graph for routing between continuing and ending
        # AGENTIC workflow 🌳🦊

        def route_tools(state: State):
            if isinstance(state, list):
                last_message = state[-1]
            elif messages := state.get("messages", []):
                last_message = messages[-1]
            else:
                raise ValueError(f"No messages found in input state to tool_edge: {state}")
 
            if last_message["done"] == "no":
                return "execute"
            
            return END


        # 👻
        def planning(state: State) -> State:
            planner = dspy.Predict(Planning)

            planning_signature = 
            
            response = planner(
                objective=state["messages"][-1].content
            )

            #messages = [planning_prompt] + state["messages"]
            #response = self.llm.invoke(messages)
            return {
                "messages": state["messages"] + [planning_signature, AIMessage(content=response.plan)],
                "done": state.done
            }
            
        def execution(state: State):
            execution_prompt = SystemMessage(content="""
                You are given a plan to enact a user's intent on a terminal
                shell. You are also given all of the commands that have been ran
                and their outputs so far. Your job is to come up with a bash command to run to
                achieve the next objective that hasn't been completed. 
            """)
            
            messages = [execution_prompt] + state["messages"]
            response = self.llm.invoke(messages)
            self.shell.execute(response.content)

            cur_shell_outputs = []

            time.sleep(1)
            while not self.shell_out_buffer.empty():
                cur_shell_outputs.append(self.shell_out_buffer.get())

            tool_output = ToolMessage(content="Shell output:\n" + "\n".join(cur_shell_outputs))
            return {
                "messages": state["messages"] + [execution_prompt, AIMessage(content=response), ToolMessage(content=tool_output)],
                "done": state.done
            }

        def replanning(state: State):
            replanner = dspy.Predict(Replanning)
            response = replanner(
                history=[item.content for item in state["messages"]]
            )


            # TODO: add response 
            
            return {
                "messages": state["messages"] + [SystemMessage(content=replanning_prompt), SystemMessage(content=response.new_plan)],
                "done": response.done
            }

        self.graph_builder.add_node("planning", planning)
        self.graph_builder.add_node("execution", execution)
        self.graph_builder.add_node("replanning", replanning)
        
        self.graph_builder.add_edge(START, "planning")

        self.graph_builder.add_edge("planning", "execution")
        self.graph_builder.add_edge("execution", "replanning")
        self.graph_builder.add_conditional_edges("replanning", route_tools)

        self.graph = self.graph_builder.compile()

        # start a thread on brain_main
        self.mthread = threading.Thread(target=self._brain_main)
        self.mthread.start()
        # self.agent = MistralAgent()

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