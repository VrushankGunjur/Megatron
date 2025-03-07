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
from langchain_core.messages import ToolMessage, AIMessage, HumanMessage

from langchain_mistralai import ChatMistralAI
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.tools import tool
from langchain_core.rate_limiters import InMemoryRateLimiter
import pprint

import logging
import dspy

from signatures import Replanning, Planning, planning_signature, replanning_prompt

from pydantic import BaseModel, Field

# MISTRAL_SYSPROMPT = "Your task is to translate english to bash commands.
# Respond in a single bash command that can be run directly in the shell, don't
# use any formatting and respond in plaintext"

MISTRAL_SYSPROMPT = "You are a Discord bot whose task is to translate english to bash commands. Execute bash commands using the given tools. ALWAYS report command results back to the user via Discord message tool. Before taking any section, generate a plan and follow it until the end."

class ReplanningFormatter(BaseModel):
    new_plan: str = Field(description="The new plan to begin executing.")
    done: bool = Field(description="Should continue executing commands.")

class PlanningFormatter(BaseModel):
    plan: str = Field(description="The step-by-step plan outlining how to achieve the objective")

class ExecutionFormatter(BaseModel):
    command: str = Field(description="The bash command to execute next")

# parser = PydanticOutputParser(pydantic_object=ReplanningFormatter)

class State(TypedDict):
    # Messages have the type "list". The `add_messages` function
    # in the annotation defines how this state key should be updated
    # (in this case, it appends messages to the list, rather than overwriting them)
    messages: Annotated[list, add_messages]
    plan: Annotated[list, add_messages]

class Brain:
    def __init__(self):
        # self.logger = logging.getLogger("brain")

        self.channel = None
        self.discord_loop = None
        
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

        self.planning_llm = self.llm.with_structured_output(PlanningFormatter)
        self.execution_llm = self.llm.with_structured_output(ExecutionFormatter)
        self.replanning_llm = self.llm.with_structured_output(ReplanningFormatter)

        # Passed into lang graph for routing between continuing and ending
        # AGENTIC workflow 🌳🦊

        def route_tools(state: State):
            if state["done"]:
                return END
            else: 
                return "execution"

        # 👻
        def planning(state: State) -> State:
            # planner = dspy.Predict(Planning)

            response = self.planning_llm.invoke(state["messages"][-1].content + planning_signature)
            
            return {
                "messages": state["messages"] + [planning_signature, AIMessage(content=response.plan)],
                "done": False
            }
            
        def execution(state: State):
            execution_prompt = HumanMessage(content="""
                You are given a plan to enact a user's intent on a terminal
                shell. You are also given all of the commands that have been ran
                and their outputs so far. Your job is to come up with a bash command to run to
                achieve the next objective that hasn't been completed. Please
                generate only a bash command with no other text.
            """)
            
            messages = state["messages"] + [execution_prompt] 
            response = self.execution_llm.invoke(messages)
            self.shell.execute_command(response.command)

            cur_shell_outputs = []

            time.sleep(1)
            while not self.shell_out_buffer.empty():
                cur_shell_outputs.append(self.shell_out_buffer.get())
            
            tool_content_string = f"Shell output: \n {'\n'.join(cur_shell_outputs)}"
            tool_output = HumanMessage(content=tool_content_string)

            return {
                "messages": state["messages"] + [execution_prompt, AIMessage(content=response.command), tool_output],
                "done": False
            }

        def replanning(state: State):
            # wrap in SystemPrompt
            messages = state["messages"] + ["PLAN: " + replanning_prompt]
            response = self.replanning_llm.invoke(messages)

            # TODO: extract new plan and done from response
            # TODO: Put it back; in chat history 
            
            return {
                "messages": state["messages"] + ["PLAN: " + replanning_prompt, AIMessage(content=response.new_plan)],
                "done": response.done
            }

        self.graph_builder.add_node("planning", planning)
        self.graph_builder.add_node("execution", execution)
        self.graph_builder.add_node("replanning", replanning)
        
        self.graph_builder.add_edge(START, "planning")

        self.graph_builder.add_edge("planning", "execution")
        self.graph_builder.add_edge("execution", "replanning")
        self.graph_builder.add_conditional_edges("replanning", route_tools, {END: END, "execution": "execution"})

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