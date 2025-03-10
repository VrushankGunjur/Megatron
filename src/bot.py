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
    """
    Called when a message is sent in any channel the bot can see.

    https://discordpy.readthedocs.io/en/latest/api.html#discord.on_message
    """
    # Don't delete this line! It's necessary for the bot to process commands.
    await bot.process_commands(message)

    # Ignore messages from self or other bots to prevent infinite loops.
    if message.author.bot or message.content.startswith("!"):
        return

    if message.author.id not in ALLOWED_USER_IDS:
        logger.info(f"User {message.author} is not allowed to use the bot.")
        return
    
    # Process the message with the agent you wrote
    # Open up the agent.py file to customize the agent
    logger.info(f"Processing message from {message.author}: {message.content}")

    # Pass both the message content and the original message object
    brain.submit_msg(message.content, message_obj=message)

    # Send the response back to the channel
    await message.reply(f"**Executing your request:**\n> {message.content}")

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

# Start the bot, connecting it to the gateway
bot.run(token)