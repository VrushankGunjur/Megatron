import discord
from discord.ui import View
import asyncio
import queue
import os

from FileSelect import FileSelect

class FileBrowserView(View):
    """View for browsing and managing files in the container"""
    
    def __init__(self, brain, files, thread, shell, active_sessions, timeout=300):
        super().__init__(timeout=timeout)
        self.brain = brain
        self.files = files
        self.thread = thread
        self.shell = shell  # Use the dedicated shell
        self.current_dir = "/app"  # Default directory
        self.active_sessions = active_sessions
        
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
        # TODO: lock this or use thread safe dict
        self.active_sessions[interaction.user.id] = {
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
        
        try:
            self.shell.set_output_callback(lambda line: output_queue.put(line))
            
            # Check if directory exists first
            self.shell.execute_command(f"[ -d '{self.current_dir}' ] && echo 'EXISTS' || echo 'NOTFOUND'")
            await asyncio.sleep(0.5)
            
            # Check output
            check_output = []
            while not output_queue.empty():
                check_output.append(output_queue.get())
            
            if any('NOTFOUND' in line for line in check_output):
                await self.thread.send(f"❌ **Error:** Directory '{self.current_dir}' not found.")
                self.current_dir = "/app"  # Reset to safe default
            
            # Clear queue
            while not output_queue.empty():
                output_queue.get()
                
            # Now list files in the directory
            self.shell.execute_command(f"ls -la '{self.current_dir}'")
            
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
                    
                    # Skip . and .. entries for simplicity
                    if file_name in [".", ".."]:
                        continue
                        
                    files.append({
                        "name": os.path.join(self.current_dir, file_name), 
                        "type": file_type
                    })
                    
            # Create new file browser view
            new_view = FileBrowserView(self.brain, files[:25], self.thread, self.shell)
            new_view.current_dir = self.current_dir
            
            # Send updated view
            await self.thread.send(f"📁 **Container File Browser ({self.current_dir}):**", view=new_view)
            
            # Confirm refresh
            await interaction.followup.send("File listing refreshed.", ephemeral=True)
            
        finally:
            self.shell.set_output_callback(original_callback)