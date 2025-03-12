import discord
from discord import ui
import asyncio
import queue

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
        # if command not in command_history:
        #     command_history.insert(0, command)  # Add to the beginning
        #     if len(command_history) > MAX_HISTORY:
        #         command_history.pop()  # Remove oldest
        
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