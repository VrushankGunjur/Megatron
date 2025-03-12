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