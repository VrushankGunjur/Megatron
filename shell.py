import fcntl
import time
import pty
import subprocess
import os
import select
import asyncio
import signal
import logging

class PersistentShell:
    def __init__(self, user_id, logger):
        self.user_id = user_id
        self.master_fd = None
        self.slave_fd = None
        self.process = None
        self.buffer = ""
        self.running = False
        self.current_command = None
        self.last_activity = time.time()
        self.logger = logger

    async def start(self):
        """Start a new persistent shell process"""
        if self.running:
            return True
        
        try:
            # Create pseudoterminal
            self.master_fd, self.slave_fd = pty.openpty()
            
            # Set non-blocking mode for master
            flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
            fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            
            # Determine which shell to use
            shell = '/bin/bash'
            
            # Start the shell process
            self.process = subprocess.Popen(
                [shell],
                stdin=self.slave_fd,
                stdout=self.slave_fd,
                stderr=self.slave_fd,
                text=True,
                preexec_fn=os.setsid,  # Create a new process group
                env=os.environ.copy()
            )
            
            self.running = True
            self.last_activity = time.time()
            self.logger.info(f'Started persistent shell for user {self.user_id}')
            
            # Initial read to clear any welcome message
            await asyncio.sleep(0.5)
            self._read_output()
            self.buffer = ""
            
            return True
        except Exception as e:
            self.logger.error(f'Failed to start shell for user {self.user_id}: {str(e)}')
            self.close()
            return False

    def close(self):
        """Close the shell process and clean up resources"""
        if self.process:
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                self.process.terminate()
                self.process.wait(timeout=2)
            except:
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                    self.process.kill()
                except:
                    pass
        
        for fd in [self.master_fd, self.slave_fd]:
            if fd is not None:
                try:
                    os.close(fd)
                except:
                    pass
        
        self.master_fd = None
        self.slave_fd = None
        self.process = None
        self.running = False
        self.buffer = ""
        self.logger.info(f'Closed persistent shell for user {self.user_id}')

    def _read_output(self):
        """Read available output from the shell process"""
        if not self.running or self.master_fd is None:
            return ""
        
        output = ""
        try:
            # Check if there's data available to read
            r, _, _ = select.select([self.master_fd], [], [], 0.1)
            if self.master_fd in r:
                chunk = os.read(self.master_fd, 4096)
                if chunk:
                    output = chunk.decode('utf-8', errors='replace')
                    self.buffer += output
        except (OSError, IOError) as e:
            if e.errno != 11:  # Resource temporarily unavailable
                self.logger.error(f'Error reading from shell: {str(e)}')
        except Exception as e:
            self.logger.error(f'Unexpected error reading from shell: {str(e)}')
        
        return output

    async def execute(self, command):
        """Execute a command in the persistent shell"""
        if not self.running:
            if not await self.start():
                return "Failed to start shell session."
        
        self.current_command = command
        self.last_activity = time.time()
        
        # Clear buffer before executing new command
        self.buffer = ""
        
        # Send command to the shell with newline
        try:
            os.write(self.master_fd, (command + '\n').encode('utf-8'))
        except Exception as e:
            self.logger.error(f'Error sending command to shell: {str(e)}')
            return f"Error sending command: {str(e)}"
        
        # Wait for command to complete and collect output
        output = ""
        timeout = 30  # seconds
        start_time = time.time()
        
        # Keep reading output until we reach the timeout or get a prompt
        while time.time() - start_time < timeout:
            await asyncio.sleep(0.1)
            new_output = self._read_output()
            
            # Check if the command has completed (prompt is showing)
            # Note: This is a simplistic approach and might need adjustment for different shells
            # Common shell prompts often end with $, >, or #
            self.logger.info(self.buffer)
            if 'bash-3.2' in self.buffer.rstrip():
                output = self.buffer
                output = output.rstrip('bash-3.2$').strip()
                break
            # if self.buffer.rstrip().endswith('$ ') or self.buffer.rstrip().endswith('> ') or self.buffer.rstrip().endswith('# '):
            #     # Remove the prompt from the output
            #     prompt_line = self.buffer.rstrip().split('\n')[-1]
            #     if prompt_line.endswith(('$ ', '> ', '# ', "v")):
            #         output = self.buffer[:-len(prompt_line)]
            #         break
            
            # If no new output and nothing in buffer, break
            if not new_output and not self.buffer:
                break
        
        # If we hit the timeout, indicate it in the output
        if time.time() - start_time >= timeout:
            output += "\n[Command timed out after 30 seconds]"
        
        self.current_command = None
        
        # Remove the command from the output if it's echoed back
        if output.startswith(command):
            output = output[len(command):].lstrip('\r\n')
        
        return output.strip()
