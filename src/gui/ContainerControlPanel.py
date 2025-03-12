import discord
from discord.ui import View
import asyncio
import queue

from .CommandModal import CommandModal
from .FileBrowserView import FileBrowserView
from .StatusView import StatusView


class ContainerControlPanel(View):
    """Main control panel with buttons for different container operations"""
    
    def __init__(self, brain, ctx, thread, shell, active_sessions):
        super().__init__(timeout=None)  # No timeout - controls stay active until thread is archived
        self.brain = brain
        self.ctx = ctx
        self.thread = thread
        self.user_id = ctx.author.id
        self.shell = shell
        self.active_sessions = active_sessions
        
    async def _send_welcome_message(self):
        """Send a welcome message with container info for better context"""
        welcome_msg = (
            "## 🐳 **Container Control Panel**\n\n"
            "Welcome to your container management interface. Use the buttons below to interact with your container.\n"
            "- Run commands directly in the shell\n"
            "- Browse and manage files\n"
            "- Monitor container status\n"
            "- Start an interactive terminal\n\n"
            "*This panel will remain active until the thread is archived.*"
        )
        await self.thread.send(welcome_msg)
        
    # ===== COMMAND EXECUTION =====
    @discord.ui.button(label="Run Command", style=discord.ButtonStyle.primary, emoji="🔧", row=0)
    async def run_command_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = CommandModal(self.brain, self.thread, self.shell)
        await interaction.response.send_modal(modal)
        
    @discord.ui.button(label="Terminal Session", style=discord.ButtonStyle.primary, emoji="💻", row=0)
    async def terminal_session_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        # Use the existing thread
        terminal_thread = self.thread
        
        # Register this thread for terminal handling with direct shell access
        self.active_sessions[self.user_id] = {
            "type": "pure_terminal",
            "thread_id": terminal_thread.id,
            "shell": self.shell
        }
        
        # Send welcome message in current thread
        await terminal_thread.send(
            "## 💻 **Interactive Terminal**\n"
            "> Type commands directly in this thread for raw shell access.\n"
            "> Commands execute directly in the container.\n"
            "> Type `exit` to end the terminal session.\n\n"
            "**Current directory:** `/app`"
        )
        
        await interaction.followup.send("Terminal session started. Type commands directly in this thread.", ephemeral=True)
    
    # ===== FILE OPERATIONS =====    
    @discord.ui.button(label="File Manager", style=discord.ButtonStyle.success, emoji="📁", row=1)
    async def file_manager_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        # Get file listing first
        output_queue = queue.Queue()
        original_callback = self.shell.callback
        
        try:
            self.shell.set_output_callback(lambda line: output_queue.put(line))
            self.shell.execute_command("ls -la /app")
            
            # Wait for command to finish
            await asyncio.sleep(1)
            
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
                    
            # Create file browser view
            file_view = FileBrowserView(self.brain, files[:25], self.thread, self.shell)
            await self.thread.send("## 📁 **Container File Browser**\nBrowse, download, and manage files in your container:", view=file_view)
            await interaction.followup.send("File browser opened. Use it to navigate, download and upload files.", ephemeral=True)
            
        finally:
            self.shell.set_output_callback(original_callback)
    
    # ===== CONTAINER INFO =====
    @discord.ui.button(label="Container Status", style=discord.ButtonStyle.secondary, emoji="📊", row=1)
    async def container_status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        # Execute status commands
        status_view = StatusView(self.brain, self.thread, self.shell)
        await status_view._send_header()
        await self.thread.send("## 📊 **Container Status**\nMonitor resources and system information:", view=status_view)
        
    # @discord.ui.button(label="Command History", style=discord.ButtonStyle.secondary, emoji="⏱️", row=2)
    # async def history_button(self, interaction: discord.Interaction, button: discord.ui.Button):
    #     # if not command_history:
    #     #     await interaction.response.send_message("No command history available.", ephemeral=True)
    #     #     return
            
    #     # Create a nicely formatted history with most recent commands first
    #     # history_text = "\n".join([f"`{i+1}.` `{cmd}`" for i, cmd in enumerate(command_history[:10])])
    #     await self.thread.send(f"## ⏱️ **Command History**\nRecent commands (newest first):\n{history_text}")
    #     await interaction.response.send_message("Command history displayed.", ephemeral=True)
    
    # Add a help button
    @discord.ui.button(label="Help", style=discord.ButtonStyle.secondary, emoji="❓", row=2)
    async def help_button(self, interaction: discord.Interaction, button: discord.ui.Button):
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
        await self.thread.send(help_text)
        await interaction.response.send_message("Help information displayed.", ephemeral=True)