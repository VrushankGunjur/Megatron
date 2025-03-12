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
        
        # Create initial progress message (one-time)
        progress_msg = await self.thread.send(f"⏳ **Loading files...**")
        
        try:
            self.shell.set_output_callback(lambda line: output_queue.put(line))
            
            # OPTIMIZATION 1: Combined shell script for directory validation and file listing
            combined_script = f"""
            if [ -d '{self.current_dir}' ]; then
                echo "DIR_EXISTS"
                cd '{self.current_dir}' && find . -maxdepth 1 -printf "%y|%f|%s\\n" | grep -v "^\\.|\\.$" | sort
            else
                echo "DIR_NOT_FOUND"
            fi
            """
            
            # Execute single combined command
            self.shell.execute_command(combined_script)
            
            # OPTIMIZATION 2: Shorter wait time
            await asyncio.sleep(0.3)
            
            # Process output
            output_lines = []
            while not output_queue.empty():
                output_lines.append(output_queue.get())
            
            # Check directory exists
            if any('DIR_NOT_FOUND' in line for line in output_lines):
                await progress_msg.edit(content=f"❌ **Error:** Directory '{self.current_dir}' not found. Returning to default directory.")
                self.current_dir = "/app"  # Reset to safe default
                
                # Recursive call to refresh with default directory
                await self.refresh_file_listing(interaction)
                return
            
            # OPTIMIZATION 3: Parse file listing more efficiently
            files = []
            for line in output_lines:
                if '|' not in line or line == "DIR_EXISTS":
                    continue
                    
                try:
                    file_type, file_name, file_size = line.split('|', 2)
                    # Convert file type (d=directory, f=regular file, etc)
                    icon = "📁" if file_type.strip() == "d" else "📄"
                    
                    # Skip . and .. entries
                    if file_name in [".", ".."]:
                        continue
                        
                    # Build full path
                    full_path = os.path.join(self.current_dir, file_name)
                    
                    files.append({
                        "name": full_path, 
                        "type": icon
                    })
                except ValueError:
                    # Skip invalid lines
                    continue
            
            # Create new file browser view
            new_view = FileBrowserView(self.brain, files[:25], self.thread, self.shell, self.active_sessions)
            new_view.current_dir = self.current_dir
            
            # OPTIMIZATION 4: Single final UI update
            await progress_msg.edit(content=f"✅ **Directory loaded:** `{self.current_dir}`\n> Showing {min(len(files), 25)} of {len(files)} items")
            await self.thread.send(f"📁 **File Browser ({self.current_dir}):**", view=new_view)
            
            # Confirm refresh
            await interaction.followup.send(f"File listing refreshed.", ephemeral=True)
            
        except Exception as e:
            await progress_msg.edit(content=f"❌ **Error:** {str(e)[:100]}")
            await interaction.followup.send("Error refreshing file listing.", ephemeral=True)
        finally:
            self.shell.set_output_callback(original_callback)