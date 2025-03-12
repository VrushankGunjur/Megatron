import discord
from discord.ui import View
import asyncio
import queue

from .CommandModal import CommandModal
from .FileBrowserView import FileBrowserView
from .StatusView import StatusView


class ContainerControlPanel(View):
    """Main control panel with buttons for different container operations"""
    
    def __init__(self, brain, ctx, thread, shell, active_sessions, gui_threads):
        super().__init__(timeout=None)  # No timeout - controls stay active until thread is archived
        self.brain = brain
        self.ctx = ctx
        self.thread = thread
        self.user_id = ctx.author.id
        self.shell = shell
        self.active_sessions = active_sessions
        self.gui_threads = gui_threads
        
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

            # Update with complete welcome message
            await welcome_msg.edit(content=(
                "## 🐳 **Container Control Panel**\n\n"
                "Welcome to your container management interface. Use the buttons below to interact with your container.\n"
                "- Run commands directly in the shell\n"
                "- Browse and manage files\n"
                "- Monitor container status\n"
                "- Start an interactive terminal\n\n"
                "⚠️ **Note:** Only the user who created this session can interact with it.\n\n"
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
        
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only allow the original user to interact with this view"""
        # Find the thread owner
        thread_id = interaction.channel.id
        thread_owner = None
        
        for user_id, thread in self.gui_threads.items():
            if thread.id == thread_id:
                thread_owner = user_id
                break
        
        # If the interaction user is not the thread owner, deny it
        if thread_owner is not None and interaction.user.id != thread_owner:
            await interaction.response.send_message(
                "⛔ **Access denied**: Only the user who created this GUI session can use these controls.",
                ephemeral=True
            )
            return False
        
        return True

    # ===== COMMAND EXECUTION =====
    @discord.ui.button(label="Run Command", style=discord.ButtonStyle.primary, emoji="🔧", row=0)
    async def run_command_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Show initial loading indicator
        status_msg = await self.thread.send("⏳ **Opening command interface...**")
    
        try:
            # Create and send modal directly with the interaction response
            modal = CommandModal(self.brain, self.thread, self.shell)
            await interaction.response.send_modal(modal)
            
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
            self.active_sessions[self.user_id] = {
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
            file_view = FileBrowserView(self.brain, files[:25], self.thread, self.shell, self.active_sessions)
            
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
        
    # @discord.ui.button(label="Command History", style=discord.ButtonStyle.secondary, emoji="⏱️", row=2)
    # async def history_button(self, interaction: discord.Interaction, button: discord.ui.Button):
    #     # Create progress message
    #     await interaction.response.defer(ephemeral=True)
    #     progress_msg = await self.thread.send("⏳ **Retrieving command history...**")
        
    #     try:
    #         await asyncio.sleep(0.5)  # Brief delay
            
    #         # if not command_history:
    #         #     await progress_msg.edit(content="ℹ️ **No command history available.**\nExecute some commands first to build history.")
    #         #     await interaction.followup.send("No command history available.", ephemeral=True)
    #         #     return
            
    #         # Update with count    
    #         # await progress_msg.edit(content=f"⏳ **Retrieving command history...**\nFound {len(command_history)} commands.")
            
    #         # # Create a nicely formatted history with most recent commands first
    #         # history_text = "\n".join([f"`{i+1}.` `{cmd}`" for i, cmd in enumerate(command_history[:10])])
            
    #         # # Final success
    #         # await progress_msg.edit(content=f"✅ **Command history loaded!**\nDisplaying {min(len(command_history), 10)} of {len(command_history)} commands.")
    #         await self.thread.send(f"## ⏱️ **Command History**\nRecent commands (newest first):\n{history_text}")
    #         await interaction.followup.send("Command history displayed.", ephemeral=True)
            
    #     except Exception as e:
    #         await progress_msg.edit(content=f"❌ **Error retrieving history:**\n```\n{str(e)}\n```")
    #         await interaction.followup.send("Error retrieving command history.", ephemeral=True)
    
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