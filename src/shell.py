import threading
import queue
import os
import signal
import uuid
import time
import docker
import io
import atexit

class InteractiveShell:
    """
    Class that provides an interactive shell interface with real-time output.
    It allows sending commands to a persistent Docker container and captures all output.
    """
    def __init__(self, image="ubuntu:latest", container_name=None):
        self.image = image
        self.container_name = container_name or f"interactive-shell-{uuid.uuid4().hex[:8]}"
        self.container = None
        self.output_buffer = queue.Queue()  # Thread-safe buffer for output lines
        self.output_monitor_thread = None
        self.running = False
        self.lock = threading.Lock()
        self.prompt_ready = threading.Event()
        self.callback = None  # Optional callback for output lines
        self.docker_client = docker.from_env()
        self.socket = None  # For interactive shell communication
    
    def start(self):
        """Start the Docker container and begin monitoring its output"""
        if self.running:
            return
        
        try:
            # Check if the image exists, pull if not
            try:
                self.docker_client.images.get(self.image)
            except docker.errors.ImageNotFound:
                print(f"Pulling Docker image: {self.image}")
                self.docker_client.images.pull(self.image)
            
            # Start the container with a shell
            self.container = self.docker_client.containers.run(
                self.image,
                command=["/bin/bash"],  # Run bash directly
                detach=True,     # Run in background
                tty=True,        # Allocate a pseudo-TTY
                stdin_open=True, # Keep stdin open
                # remove=True,     # Remove the container when it exits
                name=self.container_name
            )
            
            self.running = True
            
            # Start the monitoring thread
            self.output_monitor_thread = threading.Thread(
                target=self._output_monitor,
                daemon=True  # Thread will exit when main program exits
            )
            self.output_monitor_thread.start()
            
            # Send an initial command to get the prompt
            self.execute_command("echo 'SHELL_READY'")
            
            # Log container creation
            info_msg = f"[INFO] Docker container '{self.container_name}' started with image '{self.image}'"
            self.output_buffer.put(info_msg)
            if self.callback:
                self.callback(info_msg)
                
        except Exception as e:
            error_msg = f"[ERROR] Failed to start Docker container: {str(e)}"
            print(error_msg)
            if self.callback:
                self.callback(error_msg)
            self.running = False
    
    def _output_monitor(self):
        """Thread function that reads and buffers output from Docker container logs"""
        last_log_time = None
        
        while self.running and self.container:
            try:
                # Get logs since last check
                if last_log_time:
                    logs = self.container.logs(
                        stdout=True, 
                        stderr=True,
                        since=last_log_time,
                        timestamps=True
                    )
                else:
                    logs = self.container.logs(
                        stdout=True, 
                        stderr=True,
                        tail=10,
                        timestamps=True
                    )
                
                # Update the last log time
                last_log_time = int(time.time())
                
                # Process logs if we have any
                if logs:
                    logs_str = logs.decode('utf-8', errors='replace')
                    # Split by lines, but first remove timestamps that Docker adds
                    lines = []
                    for line in logs_str.split('\n'):
                        if ' ' in line and line[0:4].isdigit():  # Simple timestamp detection
                            # Remove timestamp part
                            parts = line.split(' ', 1)
                            if len(parts) > 1:
                                line = parts[1]
                        lines.append(line)
                    
                    for line in lines:
                        if line.strip():
                            # Add the line to our buffer
                            self.output_buffer.put(line)
                            
                            # If we have a callback, call it
                            if self.callback:
                                self.callback(line)
                            
                            # Check if this line indicates the shell is ready for input
                            if line.endswith('SHELL_READY') or '$' in line or '#' in line or '>' in line:
                                self.prompt_ready.set()
                
                # Sleep briefly to avoid CPU spinning
                time.sleep(0.2)
                
            except Exception as e:
                error_msg = f"[ERROR] Docker container monitoring error: {str(e)}"
                self.output_buffer.put(error_msg)
                if self.callback:
                    self.callback(error_msg)
                time.sleep(1)  # Sleep on error to avoid tight loops
    
    def set_output_callback(self, callback_function):
        """
        Set a callback function to be called for each line of output.
        The callback takes a single parameter: the line of output.
        """
        self.callback = callback_function
    
    def execute_command(self, command, wait_for_prompt=True, timeout=10):
        """
        Send a command to the Docker container and optionally wait for the prompt.
        """
        # Special handling for exit/stop commands
        if command.strip().lower() in ('exit', 'quit', 'bye', 'shutdown', 'stop'):
            self.output_buffer.put("[INFO] Stopping Docker container as requested...")
            if self.callback:
                self.callback("[INFO] Stopping Docker container as requested...")
            self.stop()
            return True
            
        with self.lock:
            if not self.running or not self.container:
                error_msg = "[ERROR] Docker container is not running"
                self.output_buffer.put(error_msg)
                if self.callback:
                    self.callback(error_msg)
                return False
            
            # Clear the prompt event before sending the command
            self.prompt_ready.clear()
            
            try:
                # Add a newline if the command doesn't end with one
                if not command.endswith('\n'):
                    command += '\n'
                
                # Notify about command execution - more subtly
                info_msg = f"[COMMAND] Executing: {command.strip()}"
                # Still log it internally but don't send to Discord
                print(info_msg)
                self.output_buffer.put(info_msg)
                if self.callback:
                    self.callback(info_msg)
                
                # Execute the command in the container and capture output
                cmd = f"{command.strip()}; echo '=COMMAND_DONE='"
                exec_result = self.container.exec_run(
                    cmd=["/bin/bash", "-c", cmd],
                    stdout=True,
                    stderr=True,
                    stream=True
                )
                
                # Partial output flush logic added here
                PARTIAL_FLUSH_INTERVAL = 2  # seconds
                start_time = time.time()
                last_partial_flush = start_time
                output_lines = []
                output_received = False
                
                for output_chunk in exec_result.output:
                    if output_chunk:
                        chunk_str = output_chunk.decode('utf-8', errors='replace')
                        for line in chunk_str.splitlines():
                            if line.strip() == '=COMMAND_DONE=':
                                self.prompt_ready.set()
                                continue
                            if line.strip():  # Skip empty lines
                                output_lines.append(line)
                                output_received = True
                                
                    # Flush partial output if flush interval has passed
                    current_time = time.time()
                    if current_time - last_partial_flush >= PARTIAL_FLUSH_INTERVAL and output_lines:
                        for pline in output_lines:
                            self.output_buffer.put(pline)
                            if self.callback:
                                self.callback(pline)
                        output_lines = []
                        last_partial_flush = current_time
                
                # Flush any remaining lines after stream completes
                if output_lines:
                    for pline in output_lines:
                        self.output_buffer.put(pline)
                        if self.callback:
                            self.callback(pline)
                
                # For small outputs (like ls), the old logic can be removed or kept as fallback:
                if not output_received:
                    no_output_msg = "[INFO] Command executed successfully (no output)"
                    self.output_buffer.put(no_output_msg)
                    if self.callback:
                        self.callback(no_output_msg)
                
                # Wait for the prompt if requested
                if wait_for_prompt:
                    prompt_result = self.prompt_ready.wait(timeout=timeout)
                    if not prompt_result:
                        timeout_msg = f"[WARNING] Command timed out after {timeout} seconds"
                        self.output_buffer.put(timeout_msg)
                        if self.callback:
                            self.callback(timeout_msg)
                    return prompt_result
                return True
                
            except Exception as e:
                error_msg = f"[ERROR] Failed to send command to Docker container: {str(e)}"
                self.output_buffer.put(error_msg)
                if self.callback:
                    self.callback(error_msg)
                return False
    
    def get_output(self, block=False, timeout=None):
        """
        Get a line from the output buffer.
        
        Args:
            block (bool): If True, block until a line is available
            timeout (float): If blocking, wait up to timeout seconds
            
        Returns:
            str or None: A line of output or None if no output is available
        """
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
    
    def force_stop(self):
        """Force stop the Docker container even if locks are held"""
        try:
            self.running = False
            # Find and stop container by name regardless of our tracked instance
            try:
                client = docker.from_env()
                containers = client.containers.list(all=True)
                for container in containers:
                    if container.name == self.container_name:
                        print(f"🛑 Force stopping container: {self.container_name}")
                        try:
                            container.stop(timeout=1)
                            print(f"✅ Container {self.container_name} stopped")
                        except:
                            # If stop fails, try kill
                            try:
                                print(f"⚠️ Stop failed, attempting to kill container {self.container_name}")
                                container.kill()
                                print(f"✅ Container {self.container_name} killed")
                            except:
                                print(f"❌ Failed to kill container {self.container_name}")
                        
                        # Try to remove the container
                        try:
                            container.remove(force=True)
                            print(f"🗑️ Container {self.container_name} removed")
                        except:
                            print(f"❌ Failed to remove container {self.container_name}")
                        break
            except Exception as e:
                print(f"❌ Error during force container cleanup: {e}")
                
            # Clean up our instance reference
            self.container = None
            
            # Wait for monitoring thread to finish
            if self.output_monitor_thread and self.output_monitor_thread.is_alive():
                self.output_monitor_thread.join(timeout=1)
                
            print(f"🏁 Container {self.container_name} cleanup completed")
        except Exception as e:
            print(f"❌ Error during force_stop: {e}")
    
    def stop(self):
        """Stop the Docker container and monitoring thread"""
        with self.lock:
            if not self.running:
                return
            
            self.running = False
            
            # Stop and remove the container
            try:
                if self.container:
                    self.container.stop(timeout=2)
                    # Also remove the container
                    try:
                        self.container.remove(force=True)
                    except:
                        pass
                        
                    info_msg = f"[INFO] Docker container '{self.container_name}' stopped and removed"
                    self.output_buffer.put(info_msg)
                    if self.callback:
                        self.callback(info_msg)
            except Exception as e:
                error_msg = f"[ERROR] Failed to stop Docker container: {str(e)}"
                self.output_buffer.put(error_msg)
                if self.callback:
                    self.callback(error_msg)
                # Try force stop as a fallback
                self.force_stop()
            
            # Wait for monitoring thread to finish
            if self.output_monitor_thread and self.output_monitor_thread.is_alive():
                self.output_monitor_thread.join(timeout=1)

    def __del__(self):
        """Destructor to ensure container is stopped"""
        try:
            self.force_stop()
        except:
            pass

# Register a function to clean up any Docker containers on exit
# This creates a list of known containers to clean up
_containers_to_cleanup = []

def register_container_for_cleanup(container_name):
    """Register a container name for cleanup on program exit"""
    global _containers_to_cleanup
    if container_name not in _containers_to_cleanup:
        _containers_to_cleanup.append(container_name)

def cleanup_containers(return_count=False):
    """Clean up any registered containers"""
    global _containers_to_cleanup
    if not _containers_to_cleanup:
        if return_count:
            return 0
        return
        
    print("🧹 Cleaning up Docker containers...")
    count = 0
    try:
        client = docker.from_env()
        for name in _containers_to_cleanup:
            try:
                containers = client.containers.list(all=True)
                for container in containers:
                    if container.name == name:
                        print(f"🛑 Stopping container: {name}")
                        try:
                            # Use shorter timeouts to avoid blocking
                            container.stop(timeout=1)
                            container.remove(force=True)
                            print(f"✅ Container {name} removed successfully")
                            count += 1
                        except:
                            try:
                                print(f"⚠️ Stop failed for {name}, attempting to kill...")
                                container.kill()
                                container.remove(force=True)
                                print(f"✅ Container {name} forcibly removed")
                                count += 1
                            except:
                                print(f"❌ Failed to remove container {name}")
            except Exception as e:
                print(f"❌ Error cleaning up container {name}: {e}")
    except Exception as e:
        print(f"❌ Error in cleanup: {e}")
        
    # Clear the list to avoid duplicate cleanup attempts
    _containers_to_cleanup = []
    
    if return_count:
        return count

# Register the cleanup function to run on normal interpreter exit
atexit.register(cleanup_containers)

def interactive_shell_session():
    """Run an interactive shell session inside a Docker container"""
    shell = InteractiveShell(image="ubuntu:latest")
    
    # Define callback to print output immediately
    def print_output(line):
        print(f"> {line}")
    
    # Set the callback
    shell.set_output_callback(print_output)
    
    # Start the shell
    print("Starting interactive Docker shell session...")
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
        print("\nClosing Docker shell session...")
        shell.stop()
        print("Session closed.")
