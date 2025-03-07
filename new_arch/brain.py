import threading
import time
import queue
from shell import InteractiveShell
import discord
import asyncio
from agent import MistralAgent
from typing import Dict, Any, TypedDict, Annotated
from langgraph.graph import StateGraph, START, END


class BrainState(TypedDict):
    messages: list[str]
    command: str
    shell_output: str
    current_task: str


class Brain:

    def __init__(self):
        self.channel = None
        self.discord_loop = None

        self.chat_state = queue.Queue()
        self.shell_state = queue.Queue()
        
        self.incoming_msg_buffer = queue.Queue()        # thread safe
        self.shell_out_buffer = queue.Queue()           # thread safe

        self.shell = InteractiveShell()
        self.shell.set_output_callback(self._drain_shell)
        self.shell.start()

        # Initialize the agent
        self.agent = MistralAgent()
        
        # Set up the LangGraph workflow
        self.graph = self._build_graph()
        
        # start a thread on brain_main
        self.mthread = threading.Thread(target=self._brain_main)
        self.mthread.start()
        

    def _build_graph(self) -> StateGraph:
        # Define the state graph
        graph = StateGraph(BrainState)
        
        # Add nodes to the graph
        graph.add_node("process_message", self._process_message)
        graph.add_node("execute_command", self._execute_command)
        graph.add_node("handle_shell_output", self._handle_shell_output)
        
        # Define the edges
        graph.add_edge(START, "process_message")
        graph.add_edge("process_message", "execute_command")
        graph.add_edge("execute_command", "handle_shell_output")
        graph.add_edge("handle_shell_output", END)
        
        # Set the entry point
        graph.set_entry_point("process_message")
        
        # Compile the graph
        return graph.compile()

    def _process_message(self, state: BrainState) -> BrainState:
        """Process the user message and generate a command."""
        message = state["messages"][-1]
        command = self.agent.run(message)
        return {"messages": state["messages"], "command": command, "shell_output": "", "current_task": "process_message"}

    def _execute_command(self, state: BrainState) -> BrainState:
        """Execute the command in the shell."""
        command = state["command"]
        print(f"sending \"{command}\" to shell")
        self.shell.execute_command(command)
        # Note: Shell output will be handled by the callback
        return {"messages": state["messages"], "command": command, "shell_output": "", "current_task": "execute_command"}

    def _handle_shell_output(self, state: BrainState) -> BrainState:
        """Handle the shell output."""
        # This will be called after shell output is available
        shell_output = ""
        while not self.shell_out_buffer.empty():
            shell_output += self.shell_out_buffer.get() + "\n"
        
        return {"messages": state["messages"], "command": state["command"], "shell_output": shell_output, "current_task": "handle_shell_output"}

    def _drain_shell(self, line: str):
        self.shell_out_buffer.put(line)
        
        print(line)
        # loop = self.discord_loop()
        if self.discord_loop is not None and self.discord_loop.is_running():
            print("Trying to send discord msg back..")
            asyncio.run_coroutine_threadsafe(self._send_discord_msg(line), self.discord_loop)

    def __del__(self):
        self.mthread.join()
        self.shell.stop()

    def submit_msg(self, msg: str):
        # this should only be called externally
        print(f"submitting msg: {msg}")
        self.incoming_msg_buffer.put(msg)

    def _brain_main(self):
        while True:
            time.sleep(1)
            print("Hello from Brain")

            # check if there is a message in the incoming_msg_buffer
            if not self.incoming_msg_buffer.empty():
                msg = self.incoming_msg_buffer.get()
                
                # Run the LangGraph workflow
                initial_state = {"messages": [msg], "command": "", "shell_output": "", "current_task": ""}
                result = self.graph.invoke(initial_state)
                
                # The result contains the final state after the workflow completes
                print(f"Workflow completed with result: {result}")

    async def _send_discord_msg(self, msg: str):
        print("Channel:", self.channel)
        print("Event loop:", self.discord_loop)
        print(f"sending \"{msg}\" to discord")
        await self.channel.send(msg)