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

from signatures import Replanning, Planning, planning_prompt, replanning_prompt, execution_prompt

from pydantic import BaseModel, Field

import os
from langchain.callbacks.tracers import ConsoleCallbackHandler
from langsmith import Client

from langchain.callbacks.base import BaseCallbackHandler
from langchain.callbacks import FileCallbackHandler

class LoggingCallbackHandler(BaseCallbackHandler):
    """Enhanced callback handler that logs LangChain/LangGraph events to a Python logger"""
    
    def __init__(self, logger):
        self.logger = logger
        self.step_counts = {
            "llm": 0,
            "chain": 0,
            "tool": 0,
            "retriever": 0
        }
        self.start_times = {}
        
    def _format_dict(self, obj, max_length=None): 
        """Format dictionaries"""
        if isinstance(obj, dict):
            formatted = {}
            for k, v in obj.items():
                if isinstance(v, dict):
                    formatted[k] = self._format_dict(v)
                else:
                    formatted[k] = v
            return formatted
        return obj
    
    def _get_elapsed_time(self, event_id):
        """Calculate elapsed time for an event in ms"""
        if event_id in self.start_times:
            elapsed = (time.time() - self.start_times[event_id]) * 1000
            del self.start_times[event_id]
            return f"({elapsed:.2f}ms)"
        return ""
        
    # LLM events
    def on_llm_start(self, serialized, prompts, **kwargs):
        """Log when an LLM starts processing"""
        self.step_counts["llm"] += 1
        event_id = f"llm_{self.step_counts['llm']}"
        self.start_times[event_id] = time.time()
        
        model = serialized.get("id", ["unknown"])[-1]
        self.logger.debug(f"[LLM START] Model: {model}, Prompt tokens: {len(''.join(prompts))//4}")
        
        if prompts and self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(f"[LLM PROMPT] {prompts[0]}") 
        
    def on_llm_end(self, response, **kwargs):
        """Log when an LLM completes processing"""
        event_id = f"llm_{self.step_counts['llm']}"
        elapsed = self.__get_elapsed_time(event_id)
        
        # Extract token usage when available
        token_info = ""
        if hasattr(response, 'llm_output') and response.llm_output:
            usage = response.llm_output.get('token_usage', {})
            if usage:
                token_info = f"(Input: {usage.get('prompt_tokens', '?')}, " \
                             f"Output: {usage.get('completion_tokens', '?')}, " \
                             f"Total: {usage.get('total_tokens', '?')})"
        
        self.logger.debug(f"[LLM END] {elapsed} {token_info}")
        
        if hasattr(response, 'generations') and response.generations:
            for i, gen in enumerate(response.generations[0]):
                if hasattr(gen, 'text'):
                    self.logger.debug(f"[LLM GEN {i+1}] {gen.text}")  # No truncation
                    
    def on_llm_error(self, error, **kwargs):
        """Log when an LLM encounters an error"""
        self.logger.error(f"[LLM ERROR] {str(error)}")
    
    # Chain events
    def on_chain_start(self, serialized, inputs, **kwargs):
        """Log when a chain starts processing"""
        self.step_counts["chain"] += 1
        event_id = f"chain_{self.step_counts['chain']}"
        self.start_times[event_id] = time.time()
        
        chain_name = kwargs.get('name', serialized.get('id', ['unnamed'])[-1])
        self.logger.debug(f"[CHAIN START] {chain_name}")
        
        if self.logger.isEnabledFor(logging.DEBUG):
            formatted_inputs = self._format_dict(inputs)
            self.logger.debug(f"[CHAIN INPUTS] {pprint.pformat(formatted_inputs, compact=True)}")  # No truncation
            
    def on_chain_end(self, outputs, **kwargs):
        """Log when a chain completes"""
        chain_name = kwargs.get('name', 'unnamed')
        event_id = f"chain_{self.step_counts['chain']}"
        elapsed = self._get_elapsed_time(event_id)
        
        self.logger.debug(f"[CHAIN END] {chain_name} {elapsed}")
        
        if self.logger.isEnabledFor(logging.DEBUG):
            formatted_outputs = self._format_dict(outputs)
            self.logger.debug(f"[CHAIN OUTPUTS] {pprint.pformat(formatted_outputs, compact=True)}")  # No truncation
            
    def on_chain_error(self, error, **kwargs):
        """Log when a chain encounters an error"""
        chain_name = kwargs.get('name', 'unnamed')
        self.logger.error(f"[CHAIN ERROR] {chain_name}: {str(error)}")
        
        # Include traceback for debugging
        import traceback
        self.logger.error(f"[CHAIN ERROR TRACE] {traceback.format_exc()}")
    
    # Tool events
    def on_tool_start(self, serialized, input_str, **kwargs):
        """Log when a tool starts execution"""
        self.step_counts["tool"] += 1
        event_id = f"tool_{self.step_counts['tool']}"
        self.start_times[event_id] = time.time()
        
        tool_name = kwargs.get('name', serialized.get('name', 'unnamed_tool'))
        self.logger.debug(f"[TOOL START] {tool_name}: {input_str}") 
        
    def on_tool_end(self, output, **kwargs):
        """Log when a tool completes execution"""
        tool_name = kwargs.get('name', 'unnamed_tool')
        event_id = f"tool_{self.step_counts['tool']}"
        elapsed = self._get_elapsed_time(event_id)
        
        if isinstance(output, str):
            output_str = output
        else:
            output_str = str(output)
            
        self.logger.debug(f"[TOOL END] {tool_name} {elapsed}: {output_str}") 
        
    def on_tool_error(self, error, **kwargs):
        """Log when a tool encounters an error"""
        tool_name = kwargs.get('name', 'unnamed_tool')
        self.logger.error(f"[TOOL ERROR] {tool_name}: {str(error)}")
    
    # Agent events
    def on_agent_action(self, action, **kwargs):
        """Log when an agent decides on an action"""
        self.logger.debug(f"[AGENT ACTION] Tool: {action.tool}, Input: {action.tool_input}")  
        
    def on_agent_finish(self, finish, **kwargs):
        """Log when an agent completes its execution"""
        self.logger.debug(f"[AGENT FINISH] {finish.return_values}")

MISTRAL_SYSPROMPT = "You are an agent with access to a Docker container. Your task is to execute a series of bash commands to achieve a given objective. Respond with the appropriate bash command to execute next, based on the current state and the provided plan. Do not include any additional text or formatting in your response. The packages that are currently installed are sudo, nano, vim, and the dependencies listed in requirements.txt."

class ReplanningFormatter(BaseModel):
    new_plan: str = Field(description="The new plan to begin executing.")
    done: bool = Field(description="Whether you should continue executing commands.")
    explanation: str = Field(description="An explanation of how the plan was changed and why these changes were made. Elaborate what commands were run and their results.")

class PlanningFormatter(BaseModel):
    plan: str = Field(description="The step-by-step plan outlining how to achieve the objective")

class ExecutionFormatter(BaseModel):
    command: str = Field(description="The bash command to execute next")

class State(TypedDict):
    # Messages have the type "list". The `add_messages` function
    # in the annotation defines how this state key should be updated
    # (in this case, it appends messages to the list, rather than overwriting them)
    messages: Annotated[list, add_messages]
    plan: Annotated[list, add_messages]

class Brain:
    def __init__(self):
        self.channel = None
        self.discord_loop = None
        self.active_thread = None  # Store reference to active thread
        self.original_message = None  # Store the original message object
        
        self.incoming_msg_buffer = queue.Queue()        # thread safe
        self.shell_out_buffer = queue.Queue()           # thread safe

        self.logger = self._setup_logger()
        self.logging_handler = LoggingCallbackHandler(self.logger)
        
        self.shell = InteractiveShell()
        self.shell.set_output_callback(self._drain_shell)
        self.shell.start()   
    
    def _setup_logger(self):
        """Set up a unified logging system with timestamped log files"""
        log_dir = '/app/logs'
        os.makedirs(log_dir, exist_ok=True)

        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        unified_log_path = f"{log_dir}/bot_debug_{timestamp}.log"
        
        # Create a RotatingFileHandler for better log management
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            unified_log_path,
            maxBytes=10*1024*1024,  # 10 MB
            backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)
        
        # Create a console handler for terminal output
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        
        # Use a consistent format
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
        file_handler.setFormatter(formatter)
        console.setFormatter(formatter)
        
        # Configure brain logger (our main logger)
        logger = logging.getLogger("brain")
        logger.setLevel(logging.DEBUG)
        # Clear any existing handlers
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        logger.handlers = []
        # Add our handlers
        logger.addHandler(file_handler)
        logger.addHandler(console)
        # Disable propagation to root logger to prevent duplicates
        logger.propagate = False
        
        # Configure the root logger - use same timestamped file
        root_handler = logging.FileHandler(unified_log_path)
        root_handler.setFormatter(formatter)
        root_handler.setLevel(logging.WARNING)  # Only warnings and above from root
        
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.WARNING)
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        root_logger.addHandler(root_handler)
        
        # Configure LangChain and LangGraph loggers to use the same timestamped file
        for module_name in ["langchain", "langgraph"]:
            module_logger = logging.getLogger(module_name)
            module_logger.setLevel(logging.INFO)
            # Remove existing handlers
            for handler in module_logger.handlers[:]:
                module_logger.removeHandler(handler)
            # Create a dedicated handler for each module
            module_handler = logging.FileHandler(unified_log_path)
            module_handler.setFormatter(formatter)
            module_handler.setLevel(logging.INFO)
            module_logger.addHandler(module_handler)
            # Disable propagation
            module_logger.propagate = False
        
        # Test the logger
        logger.info(f"Logging started at {timestamp} - Log file: {unified_log_path}")
        
        return logger
    
    def start(self):
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
            self.logger.info("Starting planning phase")
            response = self.planning_llm.invoke(state["messages"][-1].content + planning_prompt)
            self.logger.debug(f"Planning response: {response.plan}")

            plan_message = "📋 **Initial Plan:**\n```\n" + response.plan + "\n```"
            # Create thread for the first message
            self.send_discord_msg(plan_message, create_thread=True)
            
            return {
                "messages": state["messages"] + [planning_prompt, AIMessage(content=response.plan)],
                "done": False
            }
            
        def execution(state: State):    
            messages = state["messages"] + [HumanMessage(content=execution_prompt)] 
            response = self.execution_llm.invoke(messages)
            
            # Log the command being executed
            self.logger.info(f"[COMMAND EXECUTED] {response.command}")
            
            # Send command execution message to Discord
            command_message = f"⚙️ **Executing Command:**\n```bash\n{response.command}\n```"
            self.send_discord_msg(command_message)
            
            self.shell.execute_command(response.command)

            cur_shell_outputs = []

            time.sleep(1)
            while not self.shell_out_buffer.empty():
                cur_shell_outputs.append(self.shell_out_buffer.get())
            
            tool_content_string = f"Shell output: \n {'\n'.join(cur_shell_outputs)}"
            tool_output = HumanMessage(content=tool_content_string)

            if "[ERROR]" in tool_content_string:
                self.send_discord_msg("❌ **Error:**\n" + tool_content_string)
                return {
                    "messages": state["messages"],
                    "done": True
                }

            return {
                "messages": state["messages"] + [execution_prompt, AIMessage(content=response.command), tool_output],
                "done": False
            }

        def replanning(state: State):
            # wrap in SystemPrompt
            messages = state["messages"] + [HumanMessage(content="PLAN: " + replanning_prompt)]
            response = self.replanning_llm.invoke(messages)

            changes_message = (
                "---\n\n"
                "# 🔄 **Progress Report**\n\n"
                "## 📝 **Analysis & Reasoning:**\n"
                f"{response.explanation}\n\n"
                "## 📋 **Updated Execution Plan:**\n"
                f"```\n{response.new_plan}\n```\n\n"
            )

            # Send to the thread - no need to create a new one
            self.send_discord_msg(changes_message)
            if response.done:
                self.send_discord_msg("🎉 **All done!** Task completed successfully.")
            return {
                "messages": state["messages"] + [HumanMessage(content="PLAN: " + replanning_prompt), AIMessage(content=response.new_plan)],
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
        
        self.logger.info(f"Brain received line from shell: `{line}`")

    def __del__(self):
        self.mthread.join()
        self.shell.stop()

    # Message submission - update to accept message object
    def submit_msg(self, msg: str, message_obj=None):
        # Replace print with logger
        self.logger.info(f"Message being submitted to brain: `{msg}`")
        self.incoming_msg_buffer.put(msg)
        # Store the original message for thread creation
        if message_obj is not None:
            self.original_message = message_obj
            # Reset active_thread since this is a new conversation
            self.active_thread = None

    def _brain_main(self):
        while True:
            time.sleep(1)

            if not self.incoming_msg_buffer.empty():
                sys_prompt = SystemMessage(MISTRAL_SYSPROMPT)
                msg = self.incoming_msg_buffer.get()

                # Just use the logging handler - it will route to bot_debug.log
                config = {
                    "recursion_limit": 100,
                    "callbacks": [self.logging_handler]
                }
                
                try:
                    output = self.graph.invoke(
                        {"messages": [sys_prompt, msg]},
                        config
                    )
                    self.logger.info("Graph execution completed")
                except Exception as e:
                    self.logger.error(f"Error during graph execution: {str(e)}")
                    self.send_discord_msg(f"An error occurred: {str(e)}")

            # check if there is a new message in the shell_out_buffer

    # Discord message sending with thread support
    def send_discord_msg(self, msg: str, create_thread=False):
        assert self.discord_loop is not None and self.discord_loop.is_running(), \
                "Trying to send msg before discord loop is initialized"
        
        self.logger.info(f"Brain sending message to discord: `{msg}`")
        asyncio.run_coroutine_threadsafe(self._send_discord_msg(msg, create_thread), self.discord_loop)

    async def _send_discord_msg(self, msg: str, create_thread=False):
        print("Channel:", self.channel)
        print("Event loop:", self.discord_loop)
        print(f"Brain sending message to discord: `{msg}`")
        
        if self.active_thread:
            # If we have an active thread, send there
            await self.active_thread.send(msg)
        elif create_thread and self.original_message:
            # Create a new thread from the original message
            task_name = self.original_message.content[:50] + "..." if len(self.original_message.content) > 50 else self.original_message.content
            self.active_thread = await self.original_message.create_thread(
                name=f"Task: {task_name}", 
                auto_archive_duration=60  # Minutes until thread auto-archives
            )
            await self.active_thread.send(msg)
        else:
            # Default fallback - send to the channel
            await self.channel.send(msg)

    def get_debug_info(self):
        """Returns a formatted string with current brain state for debugging"""
        info = []
        
        # Add current execution plan
        if hasattr(self, 'graph') and self.graph:
            last_state = getattr(self.graph, '_last_state', {})
            
            # Format the current plan
            info.append("=== CURRENT PLAN ===")
            for msg in last_state.get('messages', []):
                if isinstance(msg, AIMessage) and len(msg.content) > 0:
                    if "1." in msg.content and "2." in msg.content:  # Likely a plan
                        info.append(f"\n{msg.content}\n")
            
            # Last executed command
            info.append("=== LAST COMMAND ===")
            for msg in reversed(last_state.get('messages', [])):
                if isinstance(msg, AIMessage) and not ("1." in msg.content and "2." in msg.content):
                    info.append(f"{msg.content}")
                    break
            
            # Last shell output
            info.append("\n=== LAST OUTPUT ===")
            for msg in reversed(last_state.get('messages', [])):
                if isinstance(msg, HumanMessage) and msg.content.startswith("Shell output:"):
                    output = msg.content.replace("Shell output: \n", "").strip()
                    info.append(f"{output}")
                    break
        
        return "\n".join(info)