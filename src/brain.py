import threading
import time
import queue
from shell import InteractiveShell
import asyncio
from datetime import datetime

from typing import Annotated
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain.schema import SystemMessage
from langchain_core.messages import AIMessage, HumanMessage

from langchain_mistralai import ChatMistralAI
from langchain_core.rate_limiters import InMemoryRateLimiter

import logging

# from prompts import planning_prompt, replanning_prompt, execution_prompt, summarize_prompt
# from prompts import ReplanningFormatter, PlanningFormatter, ExecutionFormatter, SummarizeFormatter

from prompts import *

import os

from Logging import LoggingCallbackHandler

CONTEXT_WINDOW = 25

class State(TypedDict):
    # Messages have the type "list". The `add_messages` function
    # in the annotation defines how this state key should be updated
    # (in this case, it appends messages to the list, rather than overwriting them)
    messages: Annotated[list, add_messages]
    plan: Annotated[list, add_messages]
    done: bool

class Brain:
    def __init__(self):
        self.channel = None
        self.discord_loop = None
        self.active_thread = None  # Store reference to active thread
        self.original_message = None  # Store the original message object
        
        self.incoming_msg_buffer = queue.Queue()        # thread safe
        self.shell_out_buffer = queue.Queue()           # thread safe

        # Progress tracking
        self.current_state = "idle"
        self.progress_updates = []
        self.last_progress_time = None
        self.progress_update_interval = 30  # send progress updates every 30 seconds for long-running tasks

        self.logger = self._setup_logger()
        self.logging_handler = LoggingCallbackHandler(self.logger)
        
        self.shell = InteractiveShell()
        self.shell.set_output_callback(self._drain_shell)
        self.shell.start()   
        self._shutdown_flag = False
    
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
            # for handler in module_logger.handlers[:]:
            #     module_logger.removeHandler(handler)
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
        self.base_model_type = "mistral-large-latest"
        # self.base_model_type = "codestral-latest"
        self.llm = ChatMistralAI(model=self.base_model_type, rate_limiter=self.rate_limiter)

        self.planning_llm = self.llm.with_structured_output(PlanningFormatter)
        self.execution_llm = self.llm.with_structured_output(ExecutionFormatter)
        self.replanning_llm = self.llm.with_structured_output(ReplanningFormatter)
        self.summarize_llm = self.llm.with_structured_output(SummarizeFormatter)

        def route_tools(state: State):
            if state["done"]:
                self._add_state_transition("routing", "Task complete, moving to summarization")
                return "summarize"
            else: 
                self._add_state_transition("routing", "Continuing execution")
                return "execution"

        def planning(state: State) -> State:
            self._add_state_transition("planning", "Started planning phase")
            self.logger.info("Starting planning phase")
            response = self.planning_llm.invoke(state["messages"][-1].content + planning_prompt)
            self.logger.debug(f"Planning response: {response.plan}")

            if 'PLAN MARKED UNSAFE' in response:
                plan_message = "This agent command is unsafe. Please try another command."
            else:
                plan_message = "📋 **Initial Plan:**\n```\n" + response.plan + "\n```"
            # Create thread for the first message
            self.send_discord_msg(plan_message)
            
            self._add_progress_update("Planning phase complete")
            return {
                "messages": state["messages"] + [planning_prompt, AIMessage(content=response.plan)],
                "done": False
            }
            
        def execution(state: State):    
            self._add_state_transition("execution", "Executing next command")

            messages = state["messages"][-CONTEXT_WINDOW:] + [HumanMessage(content=execution_prompt)] 
            response = self.execution_llm.invoke(messages)
            
            if response.unsafe:
                self.logger.info("[PLAN MARKED UNSAFE] {}")
            
            # Log the command being executed
            self.logger.info(f"[COMMAND EXECUTED] {response.command}")
            self._add_progress_update(f"Executing: {response.command}")
            
            # Send command execution message to Discord
            command_message = f"⚙️ **Executing Command:**\n```bash\n{response.command}\n```"
            self.send_discord_msg(command_message)
            
            self.shell.execute_command(response.command)

            cur_shell_outputs = []

            # TODO: we need something more robust than waiting
            self._add_progress_update("Waiting for command output...")
            time.sleep(1)
            while not self.shell_out_buffer.empty():
                cur_shell_outputs.append(self.shell_out_buffer.get())
            
            tool_content_string = f"Shell output: \n {'\n'.join(cur_shell_outputs)}"
            tool_output = HumanMessage(content=tool_content_string)
            self._add_progress_update("Received command output")

            # TODO: when will we see this error string? is this a linux thing?
            if "[ERROR]" in tool_content_string:
                self._add_state_transition("error", "Command execution failed")
                self.send_discord_msg("❌ **Error:**\n" + tool_content_string)
                return {
                    "messages": messages,
                    "done": True
                }

            return {
                "messages": messages + [execution_prompt, AIMessage(content=response.command), tool_output],
                "done": False
            }

        def replanning(state: State):
            self._add_state_transition("replanning", "Analyzing results and updating plan")
            # wrap in SystemPrompt
            messages = state["messages"][-CONTEXT_WINDOW:] + [HumanMessage(content="PLAN: " + replanning_prompt)]
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
                self._add_progress_update("Task complete, preparing summary")
            else:
                self._add_progress_update("Plan updated, continuing execution")

            return {
                "messages": messages + [HumanMessage(content="PLAN: " + replanning_prompt), AIMessage(content=response.new_plan)],
                "done": response.done
            }
        
        def summarize(state: State):
            self._add_state_transition("summarizing", "Creating final task summary")
            assert state["done"], "Task graph should be done"
            self.logger.info("Starting summarization phase")
            response = self.summarize_llm.invoke("\n".join([state["messages"][i].content for i in range(len(state["messages"]))]) + summarize_prompt)
            self.logger.debug(f"Summarization response: {response.summary}")

            summary_message = "📋 **Task Summary:**\n```\n" + response.summary + "\n```"
            # Create thread for the first message
            self.send_discord_msg(summary_message)
            
            # if response.done:
            self.send_discord_msg("🎉 **All done!** Task completed successfully.")
            self._add_state_transition("idle", "Task completed successfully")

            return {
                "messages": state["messages"] + [summarize_prompt, AIMessage(content=response.summary)],
                "done": True
            }

        self.graph_builder.add_node("planning", planning)
        self.graph_builder.add_node("execution", execution)
        self.graph_builder.add_node("replanning", replanning)
        self.graph_builder.add_node("summarize", summarize)
        
        self.graph_builder.add_edge(START, "planning")

        self.graph_builder.add_edge("planning", "execution")
        self.graph_builder.add_edge("execution", "replanning")
        self.graph_builder.add_conditional_edges("replanning", route_tools, {"summarize": "summarize", "execution": "execution"})
        self.graph_builder.add_edge("summarize", END)

        self.graph = self.graph_builder.compile()

        # start a thread on brain_main
        self.mthread = threading.Thread(target=self._brain_main)
        self.mthread.start()
        # self.agent = MistralAgent()

    # should only be called by `self.shell` as a callback
    def _drain_shell(self, line: str):
        self.shell_out_buffer.put(line)
        
        self.logger.info(f"Brain received line from shell: `{line}`")
        if self.current_state == "execution":
            self._add_progress_update(f"Shell output: {line[:50]}{'...' if len(line) > 50 else ''}")

    def __del__(self):
        self.mthread.join()
        self.shell.stop()

    # Message submission - update to accept message object
    def submit_msg(self, msg: str, message_obj=None):
        # Replace print with logger
        self.logger.info(f"Message being submitted to brain: `{msg}`")
        self._add_state_transition("receiving", f"Received new task: {msg[:50]}{'...' if len(msg) > 50 else ''}")
        self.incoming_msg_buffer.put(msg)
        # Store the original message for thread creation
        if message_obj is not None:
            self.original_message = message_obj
            # Reset active_thread since this is a new conversation
            self.active_thread = None

    def _brain_main(self):
        while not self._shutdown_flag:
            time.sleep(1)

            # Check if we should send a progress update
            self._check_progress_update()

            if not self.incoming_msg_buffer.empty():
                sys_prompt = SystemMessage(MISTRAL_SYSPROMPT)
                msg = self.incoming_msg_buffer.get()
                self._add_state_transition("processing", "Processing task")

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
                    self._add_state_transition("idle", "Task processing complete")
                except Exception as e:
                    self.logger.error(f"Error during graph execution: {str(e)}")
                    self._add_state_transition("error", f"Error: {str(e)}")
                    self.send_discord_msg(f"An error occurred: {str(e)}")

            # check if there is a new message in the shell_out_buffer

    # Track state transitions
    def _add_state_transition(self, new_state, message):
        """Change the current state and log the transition"""
        old_state = self.current_state
        self.current_state = new_state
        update = self._add_progress_update(f"State: {old_state} → {new_state}: {message}")
        return update
        
    # Add progress update entry with timestamp
    def _add_progress_update(self, message):
        """Add a timestamped progress update"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        update = f"[{timestamp}] {message}"
        self.progress_updates.append(update)
        self.logger.info(f"Progress: {update}")
        
        # Reset the progress update timer
        self.last_progress_time = datetime.now()
        
        # Keep only the most recent 100 updates
        if len(self.progress_updates) > CONTEXT_WINDOW:
            self.progress_updates = self.progress_updates[-CONTEXT_WINDOW:]
        return update
        
    # Check if we should send a progress update to Discord
    def _check_progress_update(self):
        """Send periodic progress updates for long-running tasks"""
        if (self.last_progress_time and 
            self.current_state not in ["idle", "error"] and
            self.active_thread and
            (datetime.now() - self.last_progress_time).seconds > self.progress_update_interval):
            
            # Send a progress update
            update_msg = f"⏳ **Status Update:** Currently in `{self.current_state}` state"
            if len(self.progress_updates) > 0:
                update_msg += f"\n\nLast action: {self.progress_updates[-1]}"
                
            self.send_discord_msg(update_msg)
            self.last_progress_time = datetime.now()
    
    # Get current progress info
    def get_progress_info(self):
        """Returns a structured object with current progress information"""
        return {
            "current_state": self.current_state,
            "updates": self.progress_updates[-10:],  # Last 10 updates
            "time_in_state": (datetime.now() - self.last_progress_time).seconds if self.last_progress_time else 0
        }

    # Discord message sending with thread support
    def send_discord_msg(self, msg: str, create_thread=False):
        assert self.discord_loop is not None and self.discord_loop.is_running(), \
                "Trying to send msg before discord loop is initialized"
        
        self.logger.info(f"Brain sending message to discord: `{msg}`")
        asyncio.run_coroutine_threadsafe(self._send_discord_msg(msg, create_thread), self.discord_loop)

    async def _send_discord_msg(self, msg: str, create_thread=False):
        self.logger.info(f"Channel: {self.channel}")
        self.logger.info(f"Event loop: {self.discord_loop}")
        self.logger.info(f"Brain sending message to discord: `{msg}`")
        
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
        
        # Add progress information
        info.append("=== PROGRESS STATUS ===")
        info.append(f"Current State: {self.current_state.upper()}")
        
        # Add recent progress updates
        if self.progress_updates:
            info.append("\nRecent Progress:")
            for update in self.progress_updates[-5:]:
                info.append(f"• {update}")
        
        info.append("\n")
                
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

    def shutdown(self):
        """Cleanly shut down the brain and terminate all processes"""
        self.logger.info("Shutting down brain...")
        
        # Set a flag to stop the main thread loop
        self._shutdown_flag = True
        
        # Join the main thread if it's running
        if hasattr(self, 'mthread') and self.mthread and self.mthread.is_alive():
            self.logger.info("Waiting for brain thread to terminate...")
            self.mthread.join(timeout=5)
        
        # Stop the shell if it's running
        if hasattr(self, 'shell') and self.shell:
            self.logger.info("Stopping shell...")
            self.shell.stop()
        
        self.graph = None
        self.graph_builder = None
        import gc 
        gc.collect()
        
        # Log the shutdown
        self.logger.info("Brain shutdown complete")
        
        return True