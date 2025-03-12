import os
import discord
import logging

from discord.ext import commands, tasks
from dotenv import load_dotenv
# from agent import MistralAgent
import subprocess
import time
import asyncio
import random

from shell import InteractiveShell
from brain import Brain
import discord_gui

PREFIX = "!"

import certifi
os.environ["SSL_CERT_FILE"] = certifi.where()

print(os.getenv("SSL_CERT_FILE"))
# Setup logging
logger = logging.getLogger("discord")

ALLOWED_USER_IDS = {203260138247684096, 249749629229465611, 203260138247684096, 344497041516527617}  # [Vrushank, Kenny, Alex, Stanley]

# Load the environment variables
load_dotenv()

# Create the bot with all intents
# The message content and members intent must be enabled in the Discord Developer Portal for the bot to work.
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

discord_gui.setup(bot)

# Import the Mistral agent from the agent.py file
# agent = MistralAgent()


# Get the token from the environment variables
token = os.getenv("DISCORD_TOKEN")
# channel = bot.get_channel(1339738567177670748)

brain = Brain()

bot.brain = brain
bot.allowed_user_ids = ALLOWED_USER_IDS

active_brains = {}  # Dictionary to track active brain instances by thread ID

@bot.event
async def on_ready():
    """
    Called when the client is done preparing the data received from Discord.
    Prints message on terminal when bot successfully connects to discord.

    https://discordpy.readthedocs.io/en/latest/api.html#discord.on_ready
    """
    logger.info(f"{bot.user} has connected to Discord!")
    brain.discord_loop = asyncio.get_running_loop()
    brain.channel = bot.get_channel(1339738567177670748)
    brain.start()

@bot.command()
async def myid(ctx):
    await ctx.send(f"Your Discord ID is: {ctx.author.id}")



# shell = InteractiveShell()
# reader = Reader(shell)

@bot.event
async def on_message(message: discord.Message):
    # Process commands first (this will handle !agent and other commands)
    await bot.process_commands(message)

    # Skip if from bot
    if message.author.bot:
        return
        
    # Try to handle with GUI handler
    if hasattr(bot, 'handle_gui_messages'):
        handled = await bot.handle_gui_messages(bot, message)
        return
        # if handled:
        #     return  # If GUI handled it, don't process further
    
    # Only process regular messages in the main channel
    if isinstance(message.channel, discord.Thread):
        return  # Skip processing in threads - these will be handled by their dedicated brains

    if message.author.id not in ALLOWED_USER_IDS:
        logger.info(f"User {message.author} is not allowed to use the bot.")
        return
    
    # For messages not handled by commands or GUI, suggest using !agent
    if "!agent" not in message.content:
        await message.reply(f"Please use `!agent` command to start a task. For example:\n`!agent {message.content}`")

# Commands
# This example command is here to show you how to add commands to the bot.
# Run !ping with any number of arguments to see the command in action.
# Feel free to delete this if your project will not need commands.
@bot.command(name="ping", help="Pings the bot.")
async def ping(ctx, *, arg=None):
    if arg is None:
        await ctx.send("Pong!")
    else:
        await ctx.send(f"Pong! Your argument was {arg}")

@bot.command(name="debug", help="Shows the current brain state")
async def debug_state(ctx):
    if ctx.author.id not in ALLOWED_USER_IDS:
        await ctx.send("You don't have permission to use this command.")
        return
        
    # Create a readable summary of the current state
    state_summary = brain.get_debug_info()
    
    # Split into chunks if needed (Discord has 2000 character limit)
    chunks = [state_summary[i:i+1900] for i in range(0, len(state_summary), 1900)]
    
    for chunk in chunks:
        await ctx.send(f"```\n{chunk}\n```")

@bot.command(name="agent", help="Run an AI agent task in a new thread")
async def agent_command(ctx, *, task=None):
    """Execute a task using the AI agent in a dedicated thread"""
    if ctx.author.id not in ALLOWED_USER_IDS:
        await ctx.send("⛔ You don't have permission to use this command.")
        return
        
    # Make sure a task was provided
    if not task:
        await ctx.send("Please provide a task for the agent to execute. For example: `!agent Build a sentiment analysis tool`")
        return
        
    # Create a thread for this specific task
    task_thread = await ctx.message.create_thread(
        name=f"Task: {task[:50]}" + ("..." if len(task) > 50 else ""),
        auto_archive_duration=60  # Minutes until auto-archive
    )
    
    # Create a new Brain instance specifically for this task
    task_brain = Brain()
    
    # Set up the new brain
    task_brain.discord_loop = asyncio.get_running_loop()
    task_brain.channel = task_thread  # Set the channel directly to the thread
    task_brain.start()
    
    # Store this brain in our active_brains dictionary
    active_brains[task_thread.id] = task_brain
    
    # Create a message within the thread 
    thread_msg = await task_thread.send(f"🧠 **Processing Task**:\n> {task}")
    
    # Pass the task to the brain
    task_brain.submit_msg(task, message_obj=thread_msg)
    
    # Acknowledge in the original channel
    await ctx.send(f"Task started in thread: {task_thread.mention}")
    
    # Set up thread archive listener to clean up the brain when thread is archived
    @bot.event
    async def on_thread_update(before, after):
        if after.id in active_brains and not before.archived and after.archived:
            # Clean up the brain when the thread is archived
            brain_to_close = active_brains.pop(after.id)
            del brain_to_close  # This will trigger __del__ which cleans up resources

# Start the bot, connecting it to the gateway
bot.run(token)