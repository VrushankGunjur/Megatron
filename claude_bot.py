import discord
from discord.ext import commands
import subprocess
import os
import asyncio
import logging
import sys
import pty
import fcntl
import select
import signal
import time
from dotenv import load_dotenv

from shell import PersistentShell

# Set up logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('ShellBot')

# Configure the bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Configuration
load_dotenv()


AUTHORIZED_USERS = [
    269194364201336832,
]
MAX_OUTPUT_LENGTH = 1990  # Discord message character limit (2000) with buffer

# Dictionary to store persistent shell sessions for each user
shell_sessions = {}

@bot.event
async def on_ready():
    logger.info(f'Bot logged in as {bot.user.name} ({bot.user.id})')
    logger.info(f'Authorized users: {AUTHORIZED_USERS}')

@bot.command(name='shell')
async def shell_command(ctx, *, command=None):
    """Execute a command in the user's persistent shell session"""
    # Check if user is authorized
    if ctx.author.id not in AUTHORIZED_USERS:
        await ctx.send("You are not authorized to use this command.")
        logger.warning(f'Unauthorized user {ctx.author.id} attempted to use shell command')
        return
    
    if command is None:
        await ctx.send("Please provide a command to execute.")
        return
    
    # Special command to restart shell session
    if command.strip() == "restart-session":
        if ctx.author.id in shell_sessions:
            shell_sessions[ctx.author.id].close()
            del shell_sessions[ctx.author.id]
            await ctx.send("Shell session restarted.")
        else:
            await ctx.send("No active shell session found.")
        return
    
    logger.info(f'User {ctx.author.id} executing command: {command}')
    
    # Get or create persistent shell for this user
    if ctx.author.id not in shell_sessions:
        shell_sessions[ctx.author.id] = PersistentShell(ctx.author.id, logger)
    
    shell = shell_sessions[ctx.author.id]
    
    # Run the shell command
    try:
        # Create a message to show the command is being processed
        processing_msg = await ctx.send(f"Processing command: `{command}`...")
        
        # Execute the command in the persistent shell
        output = await shell.execute(command)
        
        # Edit the processing message to indicate completion
        await processing_msg.edit(content=f"Completed command: `{command}`")
        
        # If there's output, send it
        if output:
            # Split output if it's too long
            if len(output) > MAX_OUTPUT_LENGTH:
                chunks = [output[i:i+MAX_OUTPUT_LENGTH] for i in range(0, len(output), MAX_OUTPUT_LENGTH)]
                for i, chunk in enumerate(chunks):
                    await ctx.send(f"```\n{chunk}\n```")
            else:
                await ctx.send(f"```\n{output}\n```")
        else:
            await ctx.send("Command executed with no output.")
            
    except Exception as e:
        await ctx.send(f"Failed to execute command: {str(e)}")
        logger.error(f'Error executing command: {str(e)}')

@bot.command(name='exit')
async def exit_command(ctx):
    """Close the persistent shell session"""
    if ctx.author.id not in AUTHORIZED_USERS:
        await ctx.send("You are not authorized to use this command.")
        return
    
    if ctx.author.id in shell_sessions:
        shell_sessions[ctx.author.id].close()
        del shell_sessions[ctx.author.id]
        await ctx.send("Shell session closed.")
    else:
        await ctx.send("No active shell session found.")

# Cleanup function for when the bot shuts down
async def cleanup_shells():
    logger.info("Cleaning up persistent shell sessions...")
    for user_id, shell in shell_sessions.items():
        shell.close()
    shell_sessions.clear()

# Register cleanup on bot shutdown
@bot.event
async def on_shutdown():
    await cleanup_shells()

# Run the bot
if __name__ == "__main__":
    try:
        bot.run(os.getenv("DISCORD_TOKEN"))
    finally:
        # Ensure cleanup happens even if the bot crashes
        asyncio.run(cleanup_shells())