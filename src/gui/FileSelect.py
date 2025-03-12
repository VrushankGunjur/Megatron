import discord
import asyncio
import queue
import os

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
            # Directory navigation - no changes needed
            new_dir = selected_file["name"] 
            self.view.current_dir = new_dir
            await self.view.refresh_file_listing(interaction)
            await interaction.followup.send(f"Navigated to directory: {new_dir}", ephemeral=True)
        else:
            # File handling - optimized approach
            file_path = selected_file["name"]
            file_name = os.path.basename(file_path)
            
            # Send initial progress message (single message we'll update)
            progress_msg = await self.thread.send(f"⏳ **Processing:** `{file_name}`")
            
            output_queue = queue.Queue()
            original_callback = self.view.shell.callback
            
            try:
                self.view.shell.set_output_callback(lambda line: output_queue.put(line))
                
                # Single command to verify file exists and check size
                self.view.shell.execute_command(
                    f"if [ -f '{file_path}' ]; then "
                    f"  echo 'FILE_EXISTS'; "
                    f"  stat -c %s '{file_path}' 2>/dev/null || echo 'SIZE_UNKNOWN'; "
                    f"else "
                    f"  echo 'FILE_NOT_FOUND'; "
                    f"fi"
                )
                
                # Short sleep to get command output
                await asyncio.sleep(0.3)
                
                # Process output
                output_lines = []
                while not output_queue.empty():
                    output_lines.append(output_queue.get())
                
                # Check if file exists
                if 'FILE_NOT_FOUND' in '\n'.join(output_lines):
                    await progress_msg.edit(content=f"❌ **Error:** File '{file_name}' not found.")
                    await interaction.followup.send("File not found.", ephemeral=True)
                    return
                    
                # Get file size if available
                try:
                    # The second line should be the file size
                    file_size = int([line for line in output_lines if line != 'FILE_EXISTS'][0])
                    if file_size > 7 * 1024 * 1024:  # 7MB
                        await progress_msg.edit(content=f"⚠️ File too large: {file_size / 1024 / 1024:.2f} MB (max 7 MB)")
                        await interaction.followup.send("File is too large to download.", ephemeral=True)
                        return
                except (ValueError, IndexError):
                    # If we can't get size, just log it and continue
                    pass
                    
                # Create Discord file object directly from the source path
                try:
                    await progress_msg.edit(content=f"⏳ **Reading file...**")
                    discord_file = discord.File(file_path, filename=file_name)
                    
                    # Send file as attachment
                    await progress_msg.edit(content=f"✅ **Download ready:** `{file_name}`")
                    await self.view.thread.send(f"📄 **{file_name}** (Click to download):", file=discord_file)
                    
                    await interaction.followup.send("File prepared for download.", ephemeral=True)
                except Exception as e:
                    await progress_msg.edit(content=f"❌ **Error reading file:** {str(e)[:100]}")
                    await interaction.followup.send("Error reading file.", ephemeral=True)
            except Exception as e:
                await progress_msg.edit(content=f"❌ **Error:** {str(e)[:100]}")
                await interaction.followup.send("Error processing file.", ephemeral=True)
            finally:
                self.view.shell.set_output_callback(original_callback)