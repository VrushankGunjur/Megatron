import discord
from discord.ui import View 
import asyncio
import queue


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
            # if command not in command_history:
            #     command_history.append(command)
            #     if len(command_history) > MAX_HISTORY:
            #         command_history.pop(0)
            
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