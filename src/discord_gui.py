import discord
from discord import ui
from discord.ui import Button, View, Select
import asyncio
import queue
import os
import io
from discord.ext import commands
from typing import Optional, Dict, List, Any, Union

# Dictionary to track active sessions and GUI threads
active_sessions = {}
command_history = []  # Store recent commands
gui_threads = {}  # Map user IDs to their active GUI threads
MAX_HISTORY = 20  # Maximum commands to remember

class ContainerControlPanel(View):
    """Main control panel with buttons for different container operations"""
    
    def __init__(self, brain, ctx, thread, timeout=300):
        super().__init__(timeout=timeout)
        self.brain = brain
        self.ctx = ctx
        self.thread = thread  # Store reference to the thread
        self.user_id = ctx.author.id
        
    @discord.ui.button(label="Run Command", style=discord.ButtonStyle.primary, emoji="⚙️", custom_id="run_command")
    async def run_command_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = CommandModal(self.brain, self.thread)
        await interaction.response.send_modal(modal)
        
    @discord.ui.button(label="File Manager", style=discord.ButtonStyle.success, emoji="📁", custom_id="file_manager")
    async def file_manager_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        # Get file listing first
        output_queue = queue.Queue()
        original_callback = self.brain.shell.callback
        
        try:
            self.brain.shell.set_output_callback(lambda line: output_queue.put(line))
            self.brain.shell.execute_command("ls -la /app")
            
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
            file_view = FileBrowserView(self.brain, files[:25], self.thread)  # Pass thread to view
            await self.thread.send("📁 **Container File Browser:**", view=file_view)
            await interaction.followup.send("File browser opened in thread.", ephemeral=True)
            
        finally:
            self.brain.shell.set_output_callback(original_callback)
        
    @discord.ui.button(label="Container Status", style=discord.ButtonStyle.secondary, emoji="🖥️", custom_id="container_status")
    async def container_status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        # Execute status commands
        status_view = StatusView(self.brain, self.thread)
        await self.thread.send("🖥️ **Container Status**", view=status_view)
        await interaction.followup.send("Status panel opened in thread.", ephemeral=True)
        
    @discord.ui.button(label="Command History", style=discord.ButtonStyle.secondary, emoji="📜", custom_id="command_history")
    async def history_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not command_history:
            await interaction.response.send_message("No command history available.", ephemeral=True)
            return
            
        history_text = "\n".join([f"{i+1}. `{cmd}`" for i, cmd in enumerate(command_history)])
        await self.thread.send(f"📜 **Command History:**\n{history_text}")
        await interaction.response.send_message("Command history shown in thread.", ephemeral=True)

# Update other view classes to accept and use thread parameter
class StatusView(View):
    def __init__(self, brain, thread, timeout=60):
        super().__init__(timeout=timeout)
        self.brain = brain
        self.thread = thread
        # Add commands to run
        self.status_commands = [
            {"name": "Process List", "cmd": "ps aux"},
            {"name": "Disk Usage", "cmd": "df -h"},
            {"name": "Memory Usage", "cmd": "free -h"}
        ]
        
    @discord.ui.button(label="Process List", style=discord.ButtonStyle.secondary, emoji="📊", row=0)
    async def processes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.run_status_command(interaction, "ps aux")
        
    @discord.ui.button(label="Disk Usage", style=discord.ButtonStyle.secondary, emoji="💾", row=0) 
    async def disk_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.run_status_command(interaction, "df -h")
        
    @discord.ui.button(label="Memory Usage", style=discord.ButtonStyle.secondary, emoji="🧠", row=0)
    async def memory_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.run_status_command(interaction, "free -h")
        
    @discord.ui.button(label="Environment", style=discord.ButtonStyle.secondary, emoji="🌐", row=1)
    async def env_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.run_status_command(interaction, "env")
        
    async def run_status_command(self, interaction: discord.Interaction, command):
        await interaction.response.defer(ephemeral=True)
        output_queue = queue.Queue()
        original_callback = self.brain.shell.callback
        
        try:
            self.brain.shell.set_output_callback(lambda line: output_queue.put(line))
            self.brain.shell.execute_command(command)
            
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
            
            # Send output to thread instead of followup
            if len(output_text) > 1900:
                chunks = [output_text[i:i+1900] for i in range(0, len(output_text), 1900)]
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        await self.thread.send(f"📊 **{command} Output:**\n```\n{chunk}\n```")
                    else:
                        await self.thread.send(f"```\n{chunk}\n```")
            else:
                await self.thread.send(f"📊 **{command} Output:**\n```\n{output_text}\n```")
                
        finally:
            self.brain.shell.set_output_callback(original_callback)
        
        await interaction.followup.send("Command executed. See results in thread.", ephemeral=True)

class FileBrowserView(View):
    """View for browsing and managing files in the container"""
    
    def __init__(self, brain, files, thread, timeout=60):
        super().__init__(timeout=timeout)
        self.brain = brain
        self.files = files
        self.thread = thread
        
        # Add a select menu for files if we have any
        if files:
            self.add_item(FileSelect(files, thread))
            
    @discord.ui.button(label="Upload File", style=discord.ButtonStyle.success, emoji="📤")
    async def upload_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Please upload a file with your next message. I'll add it to the container.", 
            ephemeral=True
        )
        
        # Store in active uploads to handle in on_message
        active_sessions[interaction.user.id] = {"type": "file_upload", "channel_id": interaction.channel_id}
            
class FileSelect(discord.ui.Select):
    """Dropdown for selecting files"""
    
    def __init__(self, files, thread):
        options = []
        for i, file in enumerate(files[:25]):  # Discord limits to 25 options
            options.append(discord.SelectOption(
                label=file["name"][:100],  # Discord limits option labels to 100 chars
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
        file_idx = int(self.values[0])
        selected_file = self.view.files[file_idx]
        
        # Simple file viewer action
        if selected_file["type"] == "📄":
            # Read file content
            output_queue = queue.Queue()
            original_callback = self.view.brain.shell.callback
            
            try:
                self.view.brain.shell.set_output_callback(lambda line: output_queue.put(line))
                self.view.brain.shell.execute_command(f"cat {selected_file['name']}")
                
                # Wait for command to finish
                await asyncio.sleep(1)
                
                # Collect output
                output_lines = []
                while not output_queue.empty():
                    output_lines.append(output_queue.get())
                    
                output_text = "\n".join(output_lines)
                if "SHELL_READY" in output_text:
                    output_text = output_text.replace("SHELL_READY", "")
                
                # Send content to thread instead of interaction response
                if len(output_text) > 1900:
                    chunks = [output_text[i:i+1900] for i in range(0, len(output_text), 1900)]
                    for i, chunk in enumerate(chunks):
                        if i == 0:
                            await self.view.thread.send(f"📄 **Content of {selected_file['name']}:**\n```\n{chunk}\n```")
                        else:
                            await self.view.thread.send(f"```\n{chunk}\n```")
                else:
                    await self.view.thread.send(f"📄 **Content of {selected_file['name']}:**\n```\n{output_text}\n```")
                    
            finally:
                self.view.brain.shell.set_output_callback(original_callback)
                
            await interaction.response.send_message("File content shown in thread.", ephemeral=True)
        else:
            # Directory listing
            await interaction.response.send_message(f"📁 Directory: {selected_file['name']} - Use the file manager to navigate.")

class CommandModal(ui.Modal, title="Execute Command"):
    """Modal dialog for entering a command to execute"""
    
    command_input = ui.TextInput(
        label="Enter bash command",
        placeholder="ls -la",
        required=True,
        max_length=500
    )
    
    def __init__(self, brain, thread):
        super().__init__()
        self.brain = brain
        self.thread = thread
        
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
        original_callback = self.brain.shell.callback
        
        try:
            self.brain.shell.set_output_callback(lambda line: output_queue.put(line))
            self.brain.shell.execute_command(command)
            
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
            self.brain.shell.set_output_callback(original_callback)

# Command to register with the bot
def setup(bot):
    @bot.command(name="gui", help="Open a container control panel")
    async def gui_command(ctx):
        if ctx.author.id not in bot.allowed_user_ids:
            await ctx.send("⛔ You don't have permission to use this command.")
            return
        
        # Create a thread for the GUI session
        thread = await ctx.message.create_thread(
            name=f"GUI Session - {ctx.author.display_name}",
            auto_archive_duration=60  # Minutes until auto-archive
        )
        
        # Store the thread reference
        gui_threads[ctx.author.id] = thread
        
        # Create and send the control panel in the thread
        panel = ContainerControlPanel(bot.brain, ctx, thread)
        await thread.send("## 🎛️ **Container Control Panel**", view=panel)
        
        # Notify in original channel
        await ctx.send(f"Control panel opened in thread: {thread.mention}")
        
    @bot.event
    async def on_message(message):
        # Must process commands first
        await bot.process_commands(message)
        
        # Check if this is an expected file upload
        if message.author.id in active_sessions and not message.content.startswith(bot.command_prefix):
            session = active_sessions[message.author.id]
            
            if session["type"] == "file_upload" and message.attachments:
                attachment = message.attachments[0]
                
                # Download the attachment
                file_data = await attachment.read()
                
                # Get the brain and shell from the bot
                brain = bot.brain
                
                # Create a temporary file
                temp_path = f"/tmp/{attachment.filename}"
                
                with open(temp_path, "wb") as f:
                    f.write(file_data)
                    
                # Now use shell to move it to the container
                output_queue = queue.Queue()
                original_callback = brain.shell.callback
                
                try:
                    brain.shell.set_output_callback(lambda line: output_queue.put(line))
                    
                    # Copy from temp to container
                    copy_cmd = f"cp {temp_path} /app/{attachment.filename}"
                    brain.shell.execute_command(copy_cmd)
                    
                    # Wait for command to finish
                    await asyncio.sleep(1)
                    
                    # Clear queue
                    while not output_queue.empty():
                        output_queue.get()
                        
                    await message.channel.send(f"✅ File `{attachment.filename}` uploaded to container at `/app/{attachment.filename}`")
                    
                except Exception as e:
                    await message.channel.send(f"❌ Error uploading file: {str(e)}")
                finally:
                    brain.shell.set_output_callback(original_callback)
                    # Clean up the session
                    del active_sessions[message.author.id]
                    
                    # Clean up temp file
                    try:
                        os.remove(temp_path)
                    except:
                        pass