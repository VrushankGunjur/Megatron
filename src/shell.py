import threading
import queue
import subprocess
import os
import signal
import time
class InteractiveShell:
    """
    Class that provides an interactive shell interface with real-time output.
    It allows sending commands to a persistent shell and captures all output.
    """
    def __init__(self, shell_command='/bin/bash'):
        self.shell_command = shell_command
        self.process = None
        self.output_buffer = queue.Queue()  # Thread-safe buffer for output lines
        self.output_monitor_thread = None
        self.running = False
        self.lock = threading.Lock()
        self.prompt_ready = threading.Event()
        self.callback = None  # Optional callback for output lines
        self.shell_ready = False
        self.cur_job = ""
        self.num_failures = 0

    def start(self):
        """Start the shell and begin monitoring its output"""

        if self.running:
            return
        
        # Start the shell process
        self.process = subprocess.Popen(
            self.shell_command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1,  # Line buffered
            preexec_fn=os.setsid  # Use process group for proper termination
        )
        
        self.running = True
        
        # Start the monitoring thread
        self.output_monitor_thread = threading.Thread(
            target=self._output_monitor,
            daemon=False
        )
        self.output_monitor_thread.start()

        self.shell_ready = True
        
        # Send an initial command to get the prompt
        self.execute_command("echo 'SHELL_READY'")
    
    def _output_monitor(self):
        """Thread function that reads and buffers output lines"""
        while self.running and self.process.poll() is None:
            try:
                line = self.process.stdout.readline()
                if not line:
                    # End of stream
                    break
                
                # Strip the newline
                line = line.rstrip('\n')
                
                print(f'output monitor got line {line}')
                # Add the line to our buffer
                self.output_buffer.put(line)
                
                # If we have a callback, call it
                if self.callback:
                    self.callback(line)
                
                # Check if this line indicates the shell is ready for input
                # TODO: change this to get the actual prompt line from machine
                if line.endswith('SHELL_READY') or 'sussybaka' in line:
                    self.prompt_ready.set()
                    self.shell_ready = True

            except (IOError, OSError) as e:
                # Handle pipe errors (e.g., when process terminates)
                error_msg = f"[ERROR] Shell output monitoring error: {str(e)}"
                self.output_buffer.put(error_msg)
                if self.callback:
                    self.callback(error_msg)
                break
    
    def set_output_callback(self, callback_function):
        """
        Set a callback function to be called for each line of output.
        The callback takes a single parameter: the line of output.
        """
        self.callback = callback_function
    
    def execute_command(self, command, wait_for_prompt=True, timeout=10):
        with self.lock:

            if not self.running:
                error_msg = "[ERROR] Shell is not running"
                self.output_buffer.put(error_msg)
                if self.callback:
                    self.callback(error_msg)
                return False

            ret = self.process.poll() 
            if ret is not None:
                error_msg = f"[ERROR] Shell process has terminated, exited w/ err code {ret} after too many failed restart attempts"
                if self.num_failures > 6:
                    self.output_buffer.put(error_msg)
                    if self.callback:
                        self.callback(error_msg)
                    return False
                print(error_msg)
                
                self.callback("shell process has terminated, attempting to restart (will take a second)")

                print('attempting to restart shell')
                self.process = subprocess.Popen(
                    self.shell_command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE,
                    universal_newlines=True,
                    bufsize=1,  # Line buffered
                    preexec_fn=os.setsid  # Use process group for proper termination
                )
                time.sleep(2)
                self.num_failures += 1


            # Clear the prompt event before sending the command
            self.prompt_ready.clear()
            
            try:
                # Add a newline if the command doesn't end with one
                if not command.endswith('\n'):
                    command += '\n'
                
                # Send the command
                self.process.stdin.write(command)
                self.process.stdin.flush()

                self.cur_job = command
                self.shell_ready = False
                
                # Wait for the prompt if requested
                if wait_for_prompt:
                    return self.prompt_ready.wait(timeout=timeout)
                return True
                
            except (IOError, OSError) as e:
                print('excepting')
                error_msg = f"[ERROR] Failed to send command: {str(e)}"
                self.output_buffer.put(error_msg)
                if self.callback:
                    self.callback(error_msg)
                return False
    
    def get_output(self, block=False, timeout=None):
        try:
            return self.output_buffer.get(block=block, timeout=timeout)
        except queue.Empty:
            return None
    
    def get_all_output(self):
        """Get all available lines from the buffer"""
        lines = []
        while not self.output_buffer.empty():
            lines.append(self.output_buffer.get())
        return lines
    
    def stop(self):
        """Stop the shell and monitoring thread"""
        with self.lock:
            if not self.running:
                return
            
            self.running = False
            
            # Send SIGTERM to the process group
            try:
                if self.process and self.process.poll() is None:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                    self.process.wait(timeout=2)
            except (subprocess.TimeoutExpired, OSError):
                # If it doesn't terminate gracefully, force kill
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                except OSError:
                    pass
            
            # Clean up
            if self.process:
                if self.process.stdout:
                    self.process.stdout.close()
                if self.process.stdin:
                    self.process.stdin.close()
            
            # Wait for monitoring thread to finish
            if self.output_monitor_thread and self.output_monitor_thread.is_alive():
                self.output_monitor_thread.join(timeout=1)


def interactive_shell_session():
    """Run an interactive shell session"""
    shell = InteractiveShell()
    
    # Define callback to print output immediately
    def print_output(line):
        print(f"> {line}")
    
    # Set the callback
    shell.set_output_callback(print_output)
    
    # Start the shell
    print("Starting interactive shell session...")
    shell.start()
    
    try:
        # Main interactive loop
        while True:
            # Get user input
            try:
                command = input("\nEnter command (or 'exit' to quit): ")
            except EOFError:
                break
            
            # Check for exit command
            if command.lower() in ('exit', 'quit', 'bye'):
                break
            
            # Execute the command (don't print the output as it will be handled by the callback)
            shell.execute_command(command)
            
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        # Clean up
        print("\nClosing shell session...")
        shell.stop()
        print("Session closed.")
