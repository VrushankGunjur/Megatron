import discord
from discord import ui
from discord.ui import Button, View, Select
import asyncio
import queue
import os
import io
from discord.ext import commands
from typing import Optional, Dict, List, Any, Union
from shell import InteractiveShell  # Import the shell class
import time

# Dictionary to track active sessions and GUI threads
active_sessions = {}
command_history = []  # Store recent commands
gui_threads = {}  # Map user IDs to their active GUI threads
gui_shells = {}    # Map user IDs to their dedicated shell instances
MAX_HISTORY = 20  # Maximum commands to remember

# Enhance the ContainerControlPanel with better visual organization
class ContainerControlPanel(View):
    """Main control panel with buttons for different container operations"""
    
    def __init__(self, brain, ctx, thread, shell):
        super().__init__(timeout=None)  # No timeout - controls stay active until thread is archived
        self.brain = brain
        self.ctx = ctx
        self.thread = thread
        self.user_id = ctx.author.id
        self.shell = shell
        
    async def _send_welcome_message(self):
        """Send a welcome message with container info for better context"""
        # First show loading message
        welcome_msg = await self.thread.send(
            "⏳ **Initializing Container Panel**\n"
            "> Gathering system information..."
        )
        
        # Get basic container info
        output_queue = queue.Queue()
        original_callback = self.shell.callback
        
        try:
            self.shell.set_output_callback(lambda line: output_queue.put(line))
            
            # # Update progress
            # await welcome_msg.edit(content="⏳ **Initializing Container Panel**\n> Reading system information...")
            
            # # Get hostname and system info
            # self.shell.execute_command("hostname && uname -sr && cat /etc/*release | grep PRETTY_NAME")
            # await asyncio.sleep(1)
            
            # # Get output
            # system_info = []
            # while not output_queue.empty():
            #     line = output_queue.get()
            #     if "SHELL_READY" not in line:
            #         system_info.append(line)
                    
            # # Get Python version
            # await welcome_msg.edit(content="⏳ **Initializing Container Panel**\n> Checking Python environment...")
            # self.shell.execute_command("python --version")
            # await asyncio.sleep(0.5)
            
            # while not output_queue.empty():
            #     line = output_queue.get()
            #     if "Python" in line and "SHELL_READY" not in line:
            #         system_info.append(line)
                    
            # # Format system info nicely
            # system_info_text = "\n".join([f"- {item}" for item in system_info if item.strip()])
            
            # Update with complete welcome message
            await welcome_msg.edit(content=(
                "## 🐳 **Container Control Panel**\n\n"
                "Welcome to your container management interface. Use the buttons below to interact with your container.\n"
                "- Run commands directly in the shell\n"
                "- Browse and manage files\n"
                "- Monitor container status\n"
                "- Start an interactive terminal\n\n"
                f"**System Information:**\n{system_info_text}\n\n"
                "*This panel will remain active until the thread is archived.*"
            ))
            
        except Exception as e:
            # If we can't get system info, fall back to basic welcome
            await welcome_msg.edit(content=(
                "## 🐳 **Container Control Panel**\n\n"
                "Welcome to your container management interface. Use the buttons below to interact with your container.\n"
                "- Run commands directly in the shell\n"
                "- Browse and manage files\n"
                "- Monitor container status\n"
                "- Start an interactive terminal\n\n"
                "*This panel will remain active until the thread is archived.*"
            ))
        finally:
            self.shell.set_output_callback(original_callback)
        
    # ===== COMMAND EXECUTION =====
    @discord.ui.button(label="Run Command", style=discord.ButtonStyle.primary, emoji="🔧", row=0)
    async def run_command_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Show initial loading indicator
        await interaction.response.defer(ephemeral=True)
        status_msg = await self.thread.send("⏳ **Opening command interface...**")
        
        try:
            # Wait briefly to simulate loading
            await asyncio.sleep(0.5)
            
            # Update status
            await status_msg.edit(content="⏳ **Preparing command interface...**")
            
            # Create and send modal
            modal = CommandModal(self.brain, self.thread, self.shell)
            await interaction.followup.send_modal(modal)
            
            # Update status message once the modal is shown
            await status_msg.edit(content="✅ **Command interface ready** - Fill out the form that appeared.")
            
        except Exception as e:
            await status_msg.edit(content=f"❌ **Error opening command interface:**\n```\n{str(e)}\n```")
            await interaction.followup.send("Error opening command interface.", ephemeral=True)
        
    @discord.ui.button(label="Terminal Session", style=discord.ButtonStyle.primary, emoji="💻", row=0)
    async def terminal_session_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        # Create progress message
        progress_msg = await self.thread.send(
            "⏳ **Starting terminal session:**\n"
            "> Initializing shell..."
        )
        
        try:
            # Use the existing thread
            terminal_thread = self.thread
            
            # Update progress
            await progress_msg.edit(content="⏳ **Starting terminal session:**\n> Configuring environment...")
            
            # Register this thread for terminal handling with direct shell access
            active_sessions[self.user_id] = {
                "type": "pure_terminal",
                "thread_id": terminal_thread.id,
                "shell": self.shell
            }
            
            # Get current directory for better user context
            output_queue = queue.Queue()
            original_callback = self.shell.callback
            
            try:
                self.shell.set_output_callback(lambda line: output_queue.put(line))
                self.shell.execute_command("pwd")
                await asyncio.sleep(0.5)
                
                current_dir = "/app"  # Default
                while not output_queue.empty():
                    line = output_queue.get()
                    if "/" in line and "SHELL_READY" not in line:
                        current_dir = line.strip()
            finally:
                self.shell.set_output_callback(original_callback)
            
            # Update progress
            await progress_msg.edit(content="⏳ **Starting terminal session:**\n> Session ready, initializing interface...")
            
            # Send complete welcome message
            await terminal_thread.send(
                "## 💻 **Interactive Terminal**\n"
                "> Type commands directly in this thread for raw shell access.\n"
                "> Commands execute directly in the container.\n"
                "> Type `exit` to end the terminal session.\n\n"
                f"**Current directory:** `{current_dir}`"
            )
            
            # Update final progress
            await progress_msg.edit(content="✅ **Terminal session started!** Type your commands directly in this thread.")
            await interaction.followup.send("Terminal session started. Type commands directly in this thread.", ephemeral=True)
            
        except Exception as e:
            await progress_msg.edit(content=f"❌ **Error starting terminal:**\n```\n{str(e)}\n```")
            await interaction.followup.send("Error starting terminal session.", ephemeral=True)
    
    # ===== FILE OPERATIONS =====    
    @discord.ui.button(label="File Manager", style=discord.ButtonStyle.success, emoji="📁", row=1)
    async def file_manager_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        # Create initial progress message
        progress_msg = await self.thread.send(
            "⏳ **Opening file manager:**\n"
            "> Scanning files in container..."
        )
        
        # Get file listing first
        output_queue = queue.Queue()
        original_callback = self.shell.callback
        
        try:
            self.shell.set_output_callback(lambda line: output_queue.put(line))
            
            # Update progress
            await progress_msg.edit(content="⏳ **Opening file manager:**\n> Reading directory contents...")
            self.shell.execute_command("ls -la /app")
            
            # Wait for command to finish
            await asyncio.sleep(1)
            
            # Update progress
            await progress_msg.edit(content="⏳ **Opening file manager:**\n> Processing file information...")
            
            # Collect output
            output_lines = []
            while not output_queue.empty():
                output_lines.append(output_queue.get())
                
            # Parse the file listing
            files = []
            for line in output_lines:
                if line.startswith("total") or "SHELL_READY" in line:
                    continue
                parts = line.split()
                if len(parts) >= 9:
                    file_name = " ".join(parts[8:])
                    file_type = "📁" if line.startswith("d") else "📄"
                    files.append({"name": file_name, "type": file_type})
            
            # Update progress with count
            file_count = len(files)
            await progress_msg.edit(content=f"⏳ **Opening file manager:**\n> Found {file_count} files/directories\n> Generating file browser...")
                    
            # Create file browser view
            file_view = FileBrowserView(self.brain, files[:25], self.thread, self.shell)
            
            # Success message
            await progress_msg.edit(content=f"✅ **File manager ready!**\n> Successfully loaded {min(len(files), 25)} of {len(files)} items.")
            await self.thread.send("## 📁 **Container File Browser**\nBrowse, download, and manage files in your container:", view=file_view)
            await interaction.followup.send("File browser opened. Use it to navigate, download and upload files.", ephemeral=True)
            
        except Exception as e:
            await progress_msg.edit(content=f"❌ **Error opening file manager:**\n```\n{str(e)}\n```")
            await interaction.followup.send("Error opening file browser.", ephemeral=True)
        finally:
            self.shell.set_output_callback(original_callback)
    
    # ===== CONTAINER INFO =====
    @discord.ui.button(label="Container Status", style=discord.ButtonStyle.secondary, emoji="📊", row=1)
    async def container_status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        # Create progress message
        progress_msg = await self.thread.send(
            "⏳ **Fetching container status:**\n"
            "> Initializing monitoring tools..."
        )
        
        try:
            # Update progress
            await progress_msg.edit(content="⏳ **Fetching container status:**\n> Collecting system metrics...")
            
            # Create basic system metrics preview
            output_queue = queue.Queue()
            original_callback = self.shell.callback
            
            try:
                self.shell.set_output_callback(lambda line: output_queue.put(line))
                
                # Get memory info
                self.shell.execute_command("free -h | head -2")
                await asyncio.sleep(0.5)
                
                # Get running processes count
                self.shell.execute_command("ps aux | wc -l")
                await asyncio.sleep(0.5)
                
                # Update progress
                await progress_msg.edit(content="⏳ **Fetching container status:**\n> Preparing status panel...")
                
                # Collect output
                output_lines = []
                while not output_queue.empty():
                    line = output_queue.get()
                    if "SHELL_READY" not in line:
                        output_lines.append(line)
                        
                # Create status preview
                memory_info = "\n".join([line for line in output_lines if "Mem" in line or "total" in line])
                process_count = next((line for line in output_lines if line.isdigit()), "0")
                
            finally:
                self.shell.set_output_callback(original_callback)
                
            # Update final progress
            await progress_msg.edit(content=f"✅ **Status panel ready!**\n> Found {process_count.strip()} active processes")
            
            # Execute status commands with the status view
            status_view = StatusView(self.brain, self.thread, self.shell)
            await status_view._send_header()
            await self.thread.send("## 📊 **Container Status**\nMonitor resources and system information:", view=status_view)
            
        except Exception as e:
            await progress_msg.edit(content=f"❌ **Error fetching status:**\n```\n{str(e)}\n```")
            
        await interaction.followup.send("Container status panel opened.", ephemeral=True)
        
    @discord.ui.button(label="Command History", style=discord.ButtonStyle.secondary, emoji="⏱️", row=2)
    async def history_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Create progress message
        await interaction.response.defer(ephemeral=True)
        progress_msg = await self.thread.send("⏳ **Retrieving command history...**")
        
        try:
            await asyncio.sleep(0.5)  # Brief delay
            
            if not command_history:
                await progress_msg.edit(content="ℹ️ **No command history available.**\nExecute some commands first to build history.")
                await interaction.followup.send("No command history available.", ephemeral=True)
                return
            
            # Update with count    
            await progress_msg.edit(content=f"⏳ **Retrieving command history...**\nFound {len(command_history)} commands.")
            
            # Create a nicely formatted history with most recent commands first
            history_text = "\n".join([f"`{i+1}.` `{cmd}`" for i, cmd in enumerate(command_history[:10])])
            
            # Final success
            await progress_msg.edit(content=f"✅ **Command history loaded!**\nDisplaying {min(len(command_history), 10)} of {len(command_history)} commands.")
            await self.thread.send(f"## ⏱️ **Command History**\nRecent commands (newest first):\n{history_text}")
            await interaction.followup.send("Command history displayed.", ephemeral=True)
            
        except Exception as e:
            await progress_msg.edit(content=f"❌ **Error retrieving history:**\n```\n{str(e)}\n```")
            await interaction.followup.send("Error retrieving command history.", ephemeral=True)
    
    # Add a help button
    @discord.ui.button(label="Help", style=discord.ButtonStyle.secondary, emoji="❓", row=2)
    async def help_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        progress_msg = await self.thread.send("⏳ **Loading help documentation...**")
        
        try:
            await asyncio.sleep(0.5)  # Brief delay to simulate loading
            
            help_text = (
                "## ❓ **Control Panel Help**\n\n"
                "### Available Commands:\n"
                "- **Run Command**: Execute a single bash command\n"
                "- **Terminal Session**: Start an interactive terminal right in this thread\n"
                "- **File Manager**: Browse, download and upload files\n"
                "- **Container Status**: View system resources and status\n"
                "- **Command History**: See recently executed commands\n\n"
                "*To end a terminal session, type `exit` in the thread.*"
            )
            
            await progress_msg.edit(content="✅ **Help documentation ready!**")
            await self.thread.send(help_text)
            await interaction.followup.send("Help information displayed.", ephemeral=True)
            
        except Exception as e:
            await progress_msg.edit(content=f"❌ **Error displaying help:**\n```\n{str(e)}\n```")
            await interaction.followup.send("Error displaying help information.", ephemeral=True)

# Update other view classes to accept and use thread parameter
class StatusView(View):
    def __init__(self, brain, thread, shell, timeout=300):
        super().__init__(timeout=timeout)
        self.brain = brain
        self.thread = thread
        self.shell = shell
        
    async def _send_header(self):
        """Send a descriptive header for the status panel"""
        header = (
            "Select which system information to display:"
        )
        await self.thread.send(header)
        
    @discord.ui.button(label="Processes", style=discord.ButtonStyle.secondary, emoji="⚙️", row=0)
    async def processes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.run_status_command(interaction, "ps aux | head -15", "Running Processes")
        
    @discord.ui.button(label="Disk Usage", style=discord.ButtonStyle.secondary, emoji="💾", row=0) 
    async def disk_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.run_status_command(interaction, "df -h", "Disk Usage")
        
    @discord.ui.button(label="Memory", style=discord.ButtonStyle.secondary, emoji="🧠", row=0)
    async def memory_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.run_status_command(interaction, "free -h", "Memory Usage")
        
    @discord.ui.button(label="Environment", style=discord.ButtonStyle.secondary, emoji="🌐", row=1)
    async def env_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.run_status_command(interaction, "env | sort", "Environment Variables")
        
    @discord.ui.button(label="System Info", style=discord.ButtonStyle.secondary, emoji="ℹ️", row=1)
    async def sysinfo_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.run_status_command(interaction, "uname -a && cat /etc/*release | grep PRETTY", "System Information")
    
    @discord.ui.button(label="Package List", style=discord.ButtonStyle.secondary, emoji="📦", row=1)
    async def packages_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.run_status_command(interaction, "pip list | head -15", "Installed Python Packages")
        
    async def run_status_command(self, interaction: discord.Interaction, command, title):
        await interaction.response.defer(ephemeral=True)
        output_queue = queue.Queue()
        original_callback = self.shell.callback
        
        try:
            self.shell.set_output_callback(lambda line: output_queue.put(line))
            self.shell.execute_command(command)
            
            # Add to command history
            if command not in command_history:
                command_history.append(command)
                if len(command_history) > MAX_HISTORY:
                    command_history.pop(0)
            
            # Wait for command to finish
            await asyncio.sleep(1)
            
            # Collect output
            output_lines = []
            while not output_queue.empty():
                output_lines.append(output_queue.get())
                
            output_text = "\n".join(output_lines)
            if "SHELL_READY" in output_text:
                output_text = output_text.replace("SHELL_READY", "")
            
            # Improved output formatting
            if len(output_text) > 1900:
                chunks = [output_text[i:i+1900] for i in range(0, len(output_text), 1900)]
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        await self.thread.send(f"### 📊 **{title}**\n```\n{chunk}\n```")
                    else:
                        await self.thread.send(f"```\n{chunk}\n```")
            else:
                await self.thread.send(f"### 📊 **{title}**\n```\n{output_text}\n```")
                
        finally:
            self.shell.set_output_callback(original_callback)
        
        await interaction.followup.send("Command executed. See results in thread.", ephemeral=True)

class FileBrowserView(View):
    """View for browsing and managing files in the container"""
    
    def __init__(self, brain, files, thread, shell, timeout=300):
        super().__init__(timeout=timeout)
        self.brain = brain
        self.files = files
        self.thread = thread
        self.shell = shell  # Use the dedicated shell
        self.current_dir = "/app"  # Default directory
        
        # Add a select menu for files if we have any
        if files:
            # Create a nicer display version showing just filenames, not full paths
            display_files = []
            for file in files:
                name = os.path.basename(file["name"])
                display_files.append({
                    "name": name,
                    "path": file["name"],  # Store the full path in a consistent key name
                    "type": file["type"]
                })
            self.add_item(FileSelect(display_files, thread))
            
    @discord.ui.button(label="Navigate Up", style=discord.ButtonStyle.secondary, emoji="⬆️", row=0)
    async def up_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        # Get parent directory
        parent_dir = os.path.dirname(self.current_dir)
        if (parent_dir and parent_dir != self.current_dir):
            self.current_dir = parent_dir
        else:
            self.current_dir = "/"  # Don't go above root
            
        await self.refresh_file_listing(interaction)
            
    @discord.ui.button(label="Home", style=discord.ButtonStyle.secondary, emoji="🏠", row=0)
    async def home_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        self.current_dir = "/app"
        await self.refresh_file_listing(interaction)
            
    @discord.ui.button(label="Upload File", style=discord.ButtonStyle.success, emoji="📤", row=1)
    async def upload_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Please upload a file with your next message. I'll add it to the container.", 
            ephemeral=True
        )
        
        # Store in active uploads to handle in on_message
        active_sessions[interaction.user.id] = {
            "type": "file_upload", 
            "channel_id": interaction.channel_id,
            "thread_id": self.thread.id,
            "target_dir": self.current_dir  # Save the target directory
        }
            
    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄", row=1)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.refresh_file_listing(interaction)
    
    async def refresh_file_listing(self, interaction):
        output_queue = queue.Queue()
        original_callback = self.shell.callback
        
        # Create initial progress message
        progress_msg = await self.thread.send(
            f"⏳ **Refreshing file listing:**\n"
            f"> Loading directory `{self.current_dir}`..."
        )
        
        try:
            self.shell.set_output_callback(lambda line: output_queue.put(line))
            
            # Check if directory exists first
            await progress_msg.edit(content=f"⏳ **Refreshing file listing:**\n> Verifying directory `{self.current_dir}`...")
            self.shell.execute_command(f"[ -d '{self.current_dir}' ] && echo 'EXISTS' || echo 'NOTFOUND'")
            await asyncio.sleep(0.5)
            
            # Check output
            check_output = []
            while not output_queue.empty():
                check_output.append(output_queue.get())
            
            if any('NOTFOUND' in line for line in check_output):
                await progress_msg.edit(content=f"❌ **Error:** Directory '{self.current_dir}' not found. Returning to default directory.")
                self.current_dir = "/app"  # Reset to safe default
                
                # Update progress message to reflect the directory change
                await progress_msg.edit(content=f"⏳ **Refreshing file listing:**\n> Switching to directory `{self.current_dir}`...")
            
            # Clear queue
            while not output_queue.empty():
                output_queue.get()
                
            # Now list files in the directory
            await progress_msg.edit(content=f"⏳ **Refreshing file listing:**\n> Reading files in `{self.current_dir}`...")
            self.shell.execute_command(f"ls -la '{self.current_dir}'")
            
            # Wait for command to finish
            await asyncio.sleep(1)
            
            # Collect output
            await progress_msg.edit(content=f"⏳ **Refreshing file listing:**\n> Processing file information...")
            output_lines = []
            while not output_queue.empty():
                output_lines.append(output_queue.get())
                
            # Parse the file listing
            files = []
            for line in output_lines:
                if line.startswith("total") or "SHELL_READY" in line:
                    continue
                parts = line.split()
                if len(parts) >= 9:
                    file_name = " ".join(parts[8:])
                    file_type = "📁" if line.startswith("d") else "📄"
                    
                    # Skip . and .. entries for simplicity
                    if file_name in [".", ".."]:
                        continue
                        
                    files.append({
                        "name": os.path.join(self.current_dir, file_name), 
                        "type": file_type
                    })
            
            # Update progress with file count
            await progress_msg.edit(
                content=f"⏳ **Refreshing file listing:**\n> Found {len(files)} items in `{self.current_dir}`\n> Generating view..."
            )
                    
            # Create new file browser view
            new_view = FileBrowserView(self.brain, files[:25], self.thread, self.shell)
            new_view.current_dir = self.current_dir
            
            # Send updated view
            await progress_msg.edit(content=f"✅ **Directory loaded:** `{self.current_dir}`\n> Displaying {min(len(files), 25)} of {len(files)} items")
            await self.thread.send(f"📁 **Container File Browser ({self.current_dir}):**", view=new_view)
            
            # Confirm refresh
            await interaction.followup.send(f"File listing refreshed for {self.current_dir}.", ephemeral=True)
            
        except Exception as e:
            await progress_msg.edit(content=f"❌ **Error refreshing directory:**\n```\n{str(e)}\n```")
            await interaction.followup.send("Error refreshing file listing.", ephemeral=True)
        finally:
            self.shell.set_output_callback(original_callback)

class FileSelect(discord.ui.Select):
    """Dropdown for selecting files"""
    
    def __init__(self, files, thread):
        options = []
        for i, file in enumerate(files[:25]):  # Discord limits to 25 options
            # Use basename/simple name for display
            display_name = file["name"][:100]  # Discord limits option labels to 100 chars
            options.append(discord.SelectOption(
                label=display_name,
                value=str(i),
                emoji=file["type"]
            ))
            
        super().__init__(
            placeholder="Select a file...",
            min_values=1,
            max_values=1,
            options=options
        )
        self.thread = thread
        
    async def callback(self, interaction: discord.Interaction):
        # Immediately defer the interaction to prevent timeout
        await interaction.response.defer(ephemeral=True)
        
        file_idx = int(self.values[0])
        selected_file = self.view.files[file_idx]
        
        # Check if it's a directory or a file
        if (selected_file["type"] == "📁"):
            # Navigate to this directory
            new_dir = selected_file["name"]  # Use "name" instead of "path" since that's the key in the original files list
            self.view.current_dir = new_dir
            
            # Refresh the file listing with the new directory
            await self.view.refresh_file_listing(interaction)
            await interaction.followup.send(f"Navigated to directory: {new_dir}", ephemeral=True)
        else:
            # For file operations, use "name" as the file path
            file_path = selected_file["name"]  # Use "name" instead of "path"
            file_name = os.path.basename(file_path)
            temp_path = f"/tmp/{file_name}"
            
            # Send initial progress message
            progress_msg = await self.thread.send(
                f"⏳ **Processing file:** `{file_name}`\n"
                "> Checking file..."
            )
            
            # Execute command to copy file to temp location for access
            output_queue = queue.Queue()
            original_callback = self.view.shell.callback
            
            try:
                self.view.shell.set_output_callback(lambda line: output_queue.put(line))
                
                # First check if file exists
                await progress_msg.edit(content=f"⏳ **Processing file:** `{file_name}`\n> Verifying file exists...")
                self.view.shell.execute_command(f"[ -f '{file_path}' ] && echo 'EXISTS' || echo 'NOTFOUND'")
                await asyncio.sleep(0.5)
                
                # Check output
                check_output = []
                while not output_queue.empty():
                    check_output.append(output_queue.get())
                
                if any('NOTFOUND' in line for line in check_output):
                    await progress_msg.edit(content=f"❌ **Error:** File '{file_name}' not found.")
                    await interaction.followup.send("File not found.", ephemeral=True)
                    return
                    
                # Clear queue
                while not output_queue.empty():
                    output_queue.get()
                
                # Check file size
                await progress_msg.edit(content=f"⏳ **Processing file:** `{file_name}`\n> Checking file size...")
                self.view.shell.execute_command(f"stat -c %s '{file_path}' || echo 'ERROR'")
                await asyncio.sleep(0.5)
                
                # Get file size
                size_output = []
                while not output_queue.empty():
                    size_output.append(output_queue.get())
                
                # Parse file size
                try:
                    file_size = int(size_output[0])
                    await progress_msg.edit(content=f"⏳ **Processing file:** `{file_name}`\n> File size: {file_size/1024:.1f} KB")
                    if file_size > 7 * 1024 * 1024:  # 7MB
                        await progress_msg.edit(content=f"⚠️ File is too large to download ({file_size / 1024 / 1024:.2f} MB). Maximum size is 7 MB.")
                        await interaction.followup.send("File is too large to download.", ephemeral=True)
                        return
                except (ValueError, IndexError):
                    # If we can't get the size, proceed anyway
                    await progress_msg.edit(content=f"⏳ **Processing file:** `{file_name}`\n> Unable to determine file size, proceeding anyway...")
                    
                # Clear queue
                while not output_queue.empty():
                    output_queue.get()
                    
                # Copy file to temp directory
                await progress_msg.edit(content=f"⏳ **Processing file:** `{file_name}`\n> Copying file to temporary location...")
                self.view.shell.execute_command(f"cp '{file_path}' '{temp_path}'")
                await asyncio.sleep(1)
                
                # Clear queue again
                while not output_queue.empty():
                    output_queue.get()
                    
                # Verify the file was copied successfully
                await progress_msg.edit(content=f"⏳ **Processing file:** `{file_name}`\n> Verifying file copy...")
                self.view.shell.execute_command(f"[ -f '{temp_path}' ] && echo 'SUCCESS' || echo 'FAILED'")
                await asyncio.sleep(0.5)
                
                verify_output = []
                while not output_queue.empty():
                    verify_output.append(output_queue.get())
                    
                if not any('SUCCESS' in line for line in verify_output):
                    await progress_msg.edit(content=f"❌ **Error:** Failed to copy file '{file_name}'.")
                    await interaction.followup.send("Failed to prepare file for download.", ephemeral=True)
                    return
                
                # Check if file exists in temp location
                if os.path.exists(temp_path):
                    # Update progress
                    await progress_msg.edit(content=f"⏳ **Processing file:** `{file_name}`\n> Preparing for download...")
                    
                    # Create Discord file object
                    discord_file = discord.File(temp_path, filename=file_name)
                    
                    # Send file as attachment
                    await progress_msg.edit(content=f"✅ **Download ready:** `{file_name}`")
                    await self.view.thread.send(
                        f"📄 **{file_name}** (Click to download):", 
                        file=discord_file
                    )
                    
                    # Remove temp file
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                    
                    await interaction.followup.send("File prepared for download.", ephemeral=True)
                else:
                    await progress_msg.edit(content=f"❌ **Error:** Could not access file {file_name}")
                    await interaction.followup.send("Error accessing file.", ephemeral=True)
            except Exception as e:
                await progress_msg.edit(content=f"❌ **Error accessing file:**\n```\n{str(e)}\n```")
                await interaction.followup.send("Error accessing file.", ephemeral=True)
            finally:
                self.view.shell.set_output_callback(original_callback)

class CommandModal(ui.Modal, title="Execute Command"):
    """Modal dialog for entering a command to execute"""
    
    command_input = ui.TextInput(
        label="Enter bash command",
        placeholder="ls -la",
        required=True,
        max_length=500
    )
    
    def __init__(self, brain, thread, shell):
        super().__init__()
        self.brain = brain
        self.thread = thread
        self.shell = shell  # Use the dedicated shell
        
    async def on_submit(self, interaction: discord.Interaction):
        command = self.command_input.value
        await interaction.response.send_message("Command submitted, see results in thread.", ephemeral=True)
        await self.thread.send(f"⚙️ **Executing command:**\n```bash\n{command}\n```")
        
        # Add to command history
        if command not in command_history:
            command_history.insert(0, command)  # Add to the beginning
            if len(command_history) > MAX_HISTORY:
                command_history.pop()  # Remove oldest
        
        # Execute the command
        output_queue = queue.Queue()
        original_callback = self.shell.callback
        
        try:
            self.shell.set_output_callback(lambda line: output_queue.put(line))
            self.shell.execute_command(command)
            
            # Wait for command to finish
            await asyncio.sleep(1)
            
            # Collect output
            output_lines = []
            while not output_queue.empty():
                output_lines.append(output_queue.get())
                
            output_text = "\n".join(output_lines)
            if "SHELL_READY" in output_text:
                output_text = output_text.replace("SHELL_READY", "")
            
            # Send output to thread
            if output_text.strip():
                if len(output_text) > 1900:
                    chunks = [output_text[i:i+1900] for i in range(0, len(output_text), 1900)]
                    for i, chunk in enumerate(chunks):
                        message = f"📤 **Command output {i+1}/{len(chunks)}:**\n```\n{chunk}\n```"
                        await self.thread.send(message)
                else:
                    await self.thread.send(f"📤 **Command output:**\n```\n{output_text}\n```")
            else:
                await self.thread.send("✅ Command executed with no output.")
                
        except Exception as e:
            await self.thread.send(f"❌ **Error executing command:**\n```\n{str(e)}\n```")
        finally:
            self.shell.set_output_callback(original_callback)

# Modify the setup function to support concurrent sessions

def setup(bot):
    bot._gui_cleanup_registered = False
    bot.handle_gui_messages = handle_gui_messages
    
    @bot.command(name="gui", help="Open a container control panel")
    async def gui_command(ctx):
        if ctx.author.id not in bot.allowed_user_ids:
            await ctx.send("⛔ You don't have permission to use this command.")
            return
        
        # Create a thread for the GUI session
        thread = await ctx.message.create_thread(
            name=f"GUI Session - {ctx.author.display_name}",
            auto_archive_duration=1440  # Minutes until auto-archive
        )
        
        # Create a dedicated shell instance for this GUI session
        dedicated_shell = InteractiveShell()
        dedicated_shell.set_output_callback(lambda line: print(f"[GUI Shell {thread.id}] {line}"))
        dedicated_shell.start()
        
        gui_threads[ctx.author.id] = thread
        gui_shells[ctx.author.id] = dedicated_shell
        
        # Create and send the control panel in the thread with the dedicated shell
        panel = ContainerControlPanel(bot.brain, ctx, thread, dedicated_shell)
        await panel._send_welcome_message() 
        await thread.send("## 🎛️ **Container Control Panel**", view=panel)
        
        if not bot._gui_cleanup_registered:
            @bot.event
            async def on_thread_update(before, after):
                # Check if this is one of our GUI threads and it just got archived
                if not before.archived and after.archived:
                    # Check all registered GUI threads
                    for user_id, registered_thread in list(gui_threads.items()):
                        if after.id == registered_thread.id:
                            # Clean up this thread's resources
                            if user_id in gui_shells:
                                shell_to_close = gui_shells.pop(user_id)
                                shell_to_close.stop()
                                print(f"[GUI] Cleaned up shell for thread {after.id}")
                            # Remove from thread tracking
                            if user_id in gui_threads:
                                del gui_threads[user_id]
                                print(f"[GUI] Removed thread {after.id} from tracking")
                            
                            # Clean up any active sessions
                            for session_user_id, session in list(active_sessions.items()):
                                if session.get("thread_id") == after.id:
                                    del active_sessions[session_user_id]
                                    print(f"[GUI] Cleaned up session for user {session_user_id}")
                
                # Also check active_brains from the bot module
                if hasattr(bot, "active_brains") and after.id in bot.active_brains and not before.archived and after.archived:
                    # Clean up the brain when the thread is archived
                    brain_to_close = bot.active_brains.pop(after.id)
                    del brain_to_close  # This will trigger __del__ which cleans up resources
            
            bot._gui_cleanup_registered = True
        
        await ctx.send(f"Control panel opened in thread: {thread.mention}")

async def handle_gui_messages(bot, message):
    """Process messages related to GUI functionality like terminal sessions and file uploads"""
    
    # Check if this is in a terminal session thread or a file upload
    if message.author.id in active_sessions and not message.content.startswith(bot.command_prefix):
        session = active_sessions[message.author.id]
        
        # Terminal session handler
        if session["type"] == "pure_terminal" and session["thread_id"] == message.channel.id:
            # Check for exit command
            if message.content.lower() == "exit":
                await message.channel.send("💤 **Terminal session ended**")
                del active_sessions[message.author.id]
                return True
            
            await message.add_reaction("⏳")
            
            # Get shell and execute command
            shell = session["shell"]
            command = message.content
            shell_output_buffer = queue.Queue()
            original_callback = shell.callback
            
            try:
                # Add to command history
                if command not in command_history:
                    command_history.insert(0, command)
                    if len(command_history) > MAX_HISTORY:
                        command_history.pop()
                
                # Execute command with typing indicator
                async with message.channel.typing():
                    shell.set_output_callback(lambda line: shell_output_buffer.put(line))
                    shell.execute_command(command, wait_for_prompt=False)
                    
                    await asyncio.sleep(1.5)
                    
                    output_lines = []
                    while not shell_output_buffer.empty():
                        output_lines.append(shell_output_buffer.get())
                    
                    output_text = "\n".join(output_lines)
                    output_text = output_text.replace("SHELL_READY", "")
                    has_error = "[ERROR]" in output_text
                    
                    if output_text.strip():
                        if len(output_text) > 1900:
                            chunks = [output_text[i:i+1900] for i in range(0, len(output_text), 1900)]
                            for i, chunk in enumerate(chunks):
                                if i == 0:
                                    await message.reply(f"```\n{chunk}\n```")
                                else:
                                    await message.channel.send(f"```\n{chunk}\n```")
                        else:
                            await message.reply(f"```\n{output_text}\n```")
                    else:
                        await message.reply("✅ Command executed with no output")
                    
                    # Add success/error reaction
                    if has_error:
                        await message.add_reaction("❌")
                    else:
                        await message.add_reaction("✅")
            
            except Exception as e:
                await message.reply(f"❌ **Error executing command:**\n```\n{str(e)}\n```")
                await message.add_reaction("❌")
            finally:
                # Always restore original callback
                shell.set_output_callback(original_callback)
                try:
                    await message.remove_reaction("⏳", bot.user)
                except:
                    pass
                
            return True  
            
        # File upload handler
        elif session["type"] == "file_upload" and message.attachments:
            # Add thread verification
            if "thread_id" in session and session["thread_id"] != message.channel.id:
                # Message is in the wrong thread, ignore it
                return False
            
            # Start with a loading indicator
            await message.add_reaction("⏳")
            
            attachment = message.attachments[0]
            
            # Send initial processing message
            processing_msg = await message.reply(
                f"⏳ **Processing upload:** `{attachment.filename}`\n"
                "> Downloading file..."
            )
            
            async with message.channel.typing():
                try:
                    # Download the attachment
                    await processing_msg.edit(content=f"⏳ **Processing upload:** `{attachment.filename}`\n> Downloading file... ({attachment.size/1024:.1f} KB)")
                    file_data = await attachment.read()
                    
                    # Get the dedicated shell for this session if available, otherwise use the bot's shell
                    shell = None
                    if message.author.id in gui_shells:
                        shell = gui_shells[message.author.id]
                    else:
                        shell = bot.brain.shell
                    
                    # Create a temporary file
                    await processing_msg.edit(content=f"⏳ **Processing upload:** `{attachment.filename}`\n> Preparing file for container...")
                    temp_path = f"/tmp/{attachment.filename}"
                    
                    # Get the target directory from the session
                    target_dir = session.get("target_dir", "/app")
                    
                    with open(temp_path, "wb") as f:
                        f.write(file_data)
                        
                    # Now use shell to move it to the container
                    output_queue = queue.Queue()
                    original_callback = shell.callback
                    
                    try:
                        shell.set_output_callback(lambda line: output_queue.put(line))
                        
                        # Make sure target directory exists
                        await processing_msg.edit(content=f"⏳ **Processing upload:** `{attachment.filename}`\n> Checking target directory...")
                        shell.execute_command(f"mkdir -p '{target_dir}'")
                        await asyncio.sleep(0.5)
                        
                        # Clear queue
                        while not output_queue.empty():
                            output_queue.get()
                        
                        # Copy from temp to container
                        await processing_msg.edit(content=f"⏳ **Processing upload:** `{attachment.filename}`\n> Copying to container...")
                        target_path = os.path.join(target_dir, attachment.filename)
                        copy_cmd = f"cp '{temp_path}' '{target_path}'"
                        shell.execute_command(copy_cmd)
                        
                        # Wait for command to finish
                        await asyncio.sleep(1)
                        
                        # Clear queue
                        while not output_queue.empty():
                            output_queue.get()
                            
                        # Verify file was copied successfully
                        await processing_msg.edit(content=f"⏳ **Processing upload:** `{attachment.filename}`\n> Verifying file...")
                        shell.execute_command(f"[ -f '{target_path}' ] && echo 'SUCCESS' || echo 'FAILED'")
                        await asyncio.sleep(0.5)
                        
                        verify_output = []
                        while not output_queue.empty():
                            verify_output.append(output_queue.get())
                        
                        if any('SUCCESS' in line for line in verify_output):
                            # Success! File was uploaded successfully
                            await processing_msg.edit(content=f"✅ **Upload complete:** `{attachment.filename}`\n> File saved to `{target_path}`")
                            await message.add_reaction("✅")
                            
                            # Get the thread if available
                            if "thread_id" in session:
                                thread = bot.get_channel(session["thread_id"])
                                if thread and thread.id != message.channel.id:  # Don't duplicate if we're already in the thread
                                    await thread.send(f"✅ File `{attachment.filename}` uploaded to container at `{target_path}`")
                        else:
                            # Failed to verify file
                            await processing_msg.edit(content=f"❌ **Upload failed:** `{attachment.filename}`\n> Could not verify file in container.")
                            await message.add_reaction("❌")
                        
                    except Exception as e:
                        await processing_msg.edit(content=f"❌ **Upload error:** `{attachment.filename}`\n> {str(e)}")
                        await message.add_reaction("❌")
                        
                    finally:
                        shell.set_output_callback(original_callback)
                        # Clean up the session
                        del active_sessions[message.author.id]
                        
                        # Clean up temp file
                        try:
                            os.remove(temp_path)
                        except:
                            pass
                        
                except Exception as e:
                    await processing_msg.edit(content=f"❌ **Upload failed:** `{attachment.filename}`\n> {str(e)}")
                    await message.add_reaction("❌")
                    
                    # Clean up the session
                    del active_sessions[message.author.id]
            
            try:
                # Remove processing indicator after we're done
                await message.remove_reaction("⏳", bot.user)
            except:
                pass
                
            return True  # Message was handled
            
    return False  # Message was not handled by GUI