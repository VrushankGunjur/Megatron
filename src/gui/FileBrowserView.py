import discord
from discord.ui import View
import asyncio
import queue
import os

from .FileSelect import FileSelect

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
            new_view = FileBrowserView(self.brain, files[:25], self.thread, self.shell, self.active_sessions)
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