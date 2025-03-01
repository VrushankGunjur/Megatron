import threading
import time
import queue
from shell import InteractiveShell
# from cleanup import register_container_for_cleanup
import discord
import asyncio
from agent import MistralAgent

class Brain:

    def __init__(self):
        self.channel = None
        self.discord_loop = None

        self.chat_state = queue.Queue()
        self.shell_state = queue.Queue()
        
        self.incoming_msg_buffer = queue.Queue()        # thread safe
        self.shell_out_buffer = queue.Queue()           # thread safe
        
        # New output bundling system
        self.output_bundle = []
        self.bundle_lock = threading.Lock()
        self.last_output_time = 0
        self.bundle_timer = None
        self.command_start_time = 0
        self.current_command = None

        self.shell = InteractiveShell()
        self.shell.set_output_callback(self._drain_shell)
        self.shell.start()
        
        # Register the container for cleanup
        # if hasattr(self.shell, 'container_name'):
        #     register_container_for_cleanup(self.shell.container_name)

        # Thread control flag
        self.running = True
        
        # start a thread on brain_main
        self.mthread = threading.Thread(target=self._brain_main)
        self.mthread.daemon = True  # Make thread a daemon so it exits when the main program does
        self.mthread.start()
        
        self.agent = MistralAgent()

    def shutdown(self):
        """Safely shut down the brain and all its components"""
        print("🧠 Brain shutting down...")
        # Stop the main loop
        self.running = False
        
        # Stop the shell first - with a shorter timeout to avoid blocking
        try:
            if self.shell:
                print("🐳 Shutting down Docker container...")
                try:
                    # Try force stop directly - it's more reliable for clean exit
                    self.shell.force_stop()
                except Exception as e:
                    print(f"❌ Error force stopping shell: {e}")
        except Exception as e:
            print(f"❌ Error during shell shutdown: {e}")
                
        # Don't wait for the thread - it's a daemon and will exit when program does
        print("✅ Brain shutdown complete")

    def __del__(self):
        """Destructor to ensure clean shutdown"""
        try:
            self.shutdown()
        except:
            pass

    def _drain_shell(self, line: str):
        self.shell_out_buffer.put(line)
        print(f"Shell output: {line}")
        
        # Skip empty lines and command execution messages (we already show those)
        if not line or line.isspace() or line.startswith("[COMMAND] Executing:"):
            return
            
        # Skip info messages about the container starting
        if line.startswith("[INFO] Docker container") and "started with image" in line:
            return
            
        if self.discord_loop is not None:
            # Bundle the output instead of sending immediately
            with self.bundle_lock:
                # Store this line
                self.output_bundle.append(line)
                now = time.time()
                self.last_output_time = now
                
                # If this is the first item in the bundle, start a timer
                if len(self.output_bundle) == 1:
                    # Cancel any existing timer
                    if self.bundle_timer:
                        self.bundle_timer.cancel()
                    
                    # Create a new timer that will flush after a delay
                    self.bundle_timer = threading.Timer(0.5, self._flush_output_bundle)
                    self.bundle_timer.daemon = True
                    self.bundle_timer.start()
                    
                # If bundle is getting large or has been building for a while, flush it immediately
                elapsed = now - self.command_start_time if self.command_start_time else 0
                if len(self.output_bundle) >= 25 or (len(self.output_bundle) > 5 and elapsed > 2.0):
                    self._flush_output_bundle()

    def _flush_output_bundle(self):
        """Send the collected output as a single Discord message"""
        with self.bundle_lock:
            # Cancel any pending timer
            if self.bundle_timer:
                self.bundle_timer.cancel()
                self.bundle_timer = None
                
            # If nothing to send, return
            if not self.output_bundle:
                return
                
            # Create a cleaner formatted message
            message_lines = []
            
            # Add a clean header for the output
            if "[ERROR]" in '\n'.join(self.output_bundle):
                message_lines.append("❌ ERROR OUTPUT:")
            else:
                message_lines.append("✅ COMMAND OUTPUT:")
                
            message_lines.append("")  # Empty line for spacing
            
            # Add all the bundled output lines
            message_lines.extend(self.output_bundle)
            
            # Create the final message
            message = "\n".join(message_lines)
            
            # Clear the bundle
            self.output_bundle = []
            
            # Send the message through Discord's event loop
            try:
                asyncio.run_coroutine_threadsafe(
                    self._send_discord_msg(message), 
                    self.discord_loop
                )
            except Exception as e:
                print(f"Error scheduling Discord message: {e}")

    def submit_msg(self, msg: str):
        # this should only be called externally
        print(f"submitting msg: {msg}")
        # Reset the command and bundle when a new command is submitted
        self.current_command = None
        self._flush_output_bundle()
        self.incoming_msg_buffer.put(msg)

    def _brain_main(self):
        while self.running:
            try:
                time.sleep(1)
                # check if there is a message in the incoming_msg_buffer
                if not self.incoming_msg_buffer.empty():
                    msg = self.incoming_msg_buffer.get()
                    try:
                        completion = self.agent.run(msg)
                        print(f"sending \"{completion}\" to shell")
                        
                        # Check if this is a rate limit or error message (echo command)
                        if completion.startswith("echo '") and completion.endswith("'"):
                            # This is an error message, handle it specially
                            error_msg = completion[6:-1]  # Remove the echo '' wrapper
                            self.shell_out_buffer.put(f"⚠️ {error_msg}")
                            
                            # Create a bundle with just this error message
                            with self.bundle_lock:
                                self.output_bundle = [f"⚠️ {error_msg}"]
                                self._flush_output_bundle()
                        else:
                            # Normal command execution
                            self.shell.execute_command(completion)
                    except Exception as e:
                        error_msg = f"Error running agent: {e}"
                        print(error_msg)
                        
                        # Send the error to Discord
                        with self.bundle_lock:
                            self.output_bundle = [f"❌ {error_msg}"]
                            self._flush_output_bundle()
                        
            except Exception as e:
                print(f"Error in brain main loop: {e}")
                # Don't crash the thread loop on exceptions
                time.sleep(1)

    async def _send_discord_msg(self, msg: str):
        try:
            if self.channel is None:
                print("Error: Discord channel not set")
                return
                
            # Don't send empty messages
            if not msg or msg.isspace():
                return
                
            # Limit message length to Discord's limit (2000 chars)
            if len(msg) > 1900:  # Leave some room for formatting
                chunks = [msg[i:i+1900] for i in range(0, len(msg), 1900)]
                for chunk in chunks:
                    await self.channel.send(f"```{chunk}```")
            else:
                await self.channel.send(f"```{msg}```")
                
            print(f"Message sent to Discord: '{msg}'")
        except Exception as e:
            print(f"Error sending message to Discord: {e}")