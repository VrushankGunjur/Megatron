import os
import discord
import logging
import signal
import atexit
import sys

from discord.ext import commands, tasks
from dotenv import load_dotenv
import subprocess
import time
import asyncio
import random

from shell import InteractiveShell
from brain import Brain
from gui import discord_gui


PREFIX = "!"

import certifi
os.environ["SSL_CERT_FILE"] = certifi.where()

print(os.getenv("SSL_CERT_FILE"))
# Setup logging
logger = logging.getLogger("discord")

#ALLOWED_USER_IDS = {269194364201336832, 203260138247684096, 249749629229465611, 344497041516527617}  # [Vrushank, Kenny, Alex, Stanley]

# Load the environment variables
load_dotenv()

# Create the bot with all intents
# The message content and members intent must be enabled in the Discord Developer Portal for the bot to work.
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)
bot.remove_command('help')

discord_gui.setup(bot)

# Import the Mistral agent from the agent.py file
# agent = MistralAgent()


# Get the token from the environment variables
token = os.getenv("DISCORD_TOKEN")
# channel = bot.get_channel(1339738567177670748)

brain = Brain()

bot.brain = brain
# bot.allowed_user_ids = ALLOWED_USER_IDS

active_brains = {}  # Dictionary to track active brain instances by thread ID

default_model = "mistral-large-latest"

# Create a function to send a shutdown message
async def send_shutdown_message():
    """Send a message when the bot is shutting down"""
    try:
        channel = bot.get_channel(1339738567177670748)  # Same channel as in on_ready
        if channel:
            await channel.send("🔌 **Bot is shutting down...**")
            # Give Discord API a moment to process the message
            await asyncio.sleep(1)
    except Exception as e:
        print(f"Failed to send shutdown message: {e}")

@bot.event
async def on_ready():
    """
    Called when the client is done preparing the data received from Discord.
    Prints message on terminal when bot successfully connects to discord.

    https://discordpy.readthedocs.io/en/latest/api.html#discord.on_ready
    """
    logger.info(f"{bot.user} has connected to Discord!")
    brain.discord_loop = asyncio.get_running_loop()
    channel = bot.get_channel(1339738567177670748)
    brain.channel = channel
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

    # if message.author.id not in ALLOWED_USER_IDS:
    #     logger.info(f"User {message.author} is not allowed to use the bot.")
    #     return
    
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
    # Create a readable summary of the current state
    state_summary = brain.get_debug_info()
    
    # Split into chunks if needed (Discord has 2000 character limit)
    chunks = [state_summary[i:i+1900] for i in range(0, len(state_summary), 1900)]
    
    for chunk in chunks:
        await ctx.send(f"```\n{chunk}\n```")

@bot.command(name="agent", help="Run an AI agent task in a new thread")
async def agent_command(ctx, *, task=None):
    """Execute a task using the AI agent in a dedicated thread"""

        
    # Make sure a task was provided
    if not task:
        await ctx.send("Please provide a task for the agent to execute. For example: `!agent Build a sentiment analysis tool`")
        return
        
    # Create a thread for this specific task
    if not (ctx.channel.type == discord.ChannelType.public_thread or ctx.channel.type == discord.ChannelType.private_thread):
        task_thread = await ctx.message.create_thread(
            name=f"Task: {task[:50]}" + ("..." if len(task) > 50 else ""),
            auto_archive_duration=60  # Minutes until auto-archive
        )
    else:
        await ctx.send("🛑! agent can only be run as a new process in the channel. Please exit the thread and go back to the channel")
        return
    
    # Create a new Brain instance specifically for this task
    global default_model
    task_brain = Brain(default_model=default_model)
    
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

@bot.command(name="kill", help="Stop the current agent task")
async def kill_command(ctx):
    """Terminate the current thread's brain instance"""
    # Only process in threads
    if not isinstance(ctx.channel, discord.Thread):
        await ctx.send("This command can only be used within a task thread.")
        return
    
    thread_id = ctx.channel.id
    
    # Check if this thread has an active brain
    if thread_id in active_brains:
        # Get the brain
        thread_brain = active_brains[thread_id]
        
        # Send feedback message
        await ctx.send("🛑 **Terminating task...**")
        
        # Shutdown the brain
        success = thread_brain.shutdown()
        
        # Remove from active brains
        if success:
            del active_brains[thread_id]
            await ctx.send("✅ **Task terminated successfully**")
        else:
            await ctx.send("⚠️ **Error terminating task**")
    else:
        await ctx.send("No active task found in this thread.")

@bot.command(name="toggle", help="Toggle between GPT 4o and Mistral models.")
async def toggle_command(ctx):
    global default_model
    if default_model == "mistral-large-latest":
        default_model = "gpt-4o"
    else:
        default_model = "mistral-large-latest"
    
    await ctx.send(f"Model toggled to {default_model}")

@bot.command(name="help", help="Show detailed help information about all commands")
async def help_command(ctx):
    """Provide comprehensive help information about all bot commands and features"""
    
    # Create a more visually striking embed with thumbnail
    embed = discord.Embed(
        title="📚 Command Guide",
        description="Your AI-powered container assistant",
        color=discord.Color.from_rgb(114, 137, 218),  # Discord blurple color
        timestamp=ctx.message.created_at
    )
        
    
    embed.add_field(
        name="🤖 __AI Agent Commands__",
        value="─────────────────────",
        inline=False
    )
    
    # Agent Command - Enhanced with emoji and formatting
    embed.add_field(
        name="📋 !agent [task]",
        value=(
            "Run your task with AI assistance\n"
            "> `!agent Create a Python script that prints Hello World`\n"
            "```\n"
            "• Creates a dedicated thread for your task\n"
            "• Breaks down the task into steps\n"
            "• Executes commands automatically\n"
            "• Provides progress updates and summary\n"
            "```"
        ),
        inline=False
    )
    
    # Debug Command
    embed.add_field(
        name="🔍 !debug",
        value=(
            "View the current state of the AI agent\n"
            "> `!debug`\n"
            "```\n"
            "• Shows current state and progress\n"
            "• Displays execution plan\n"
            "• Lists recent commands and results\n"
            "```"
        ),
        inline=False
    )
    
    # Container Management Category
    embed.add_field(
        name="🖥️ __Container Management__",
        value="─────────────────────",
        inline=False
    )
    
    # GUI Command - Enhanced
    embed.add_field(
        name="🎛️ !gui",
        value=(
            "Open a graphical control panel\n"
            "> `!gui`\n"
            "```\n"
            "• Run Command: Execute bash commands\n"
            "• Terminal: Start an interactive shell\n"
            "• File Manager: Browse and transfer files\n"
            "• Status: View system resources\n"
            "```"
        ),
        inline=False
    )
    
    # Process Management Category
    embed.add_field(
        name="⚙️ __Process Management__",
        value="─────────────────────",
        inline=False
    )
    
    # Kill Command
    embed.add_field(
        name="🛑 !kill",
        value=(
            "Terminate active tasks\n"
            "> `!kill`\n"
            "```\n"
            "• Use in a task thread to stop it\n"
            "• Works on agent tasks and GUI sessions\n"
            "• Only available in threads\n"
            "```"
        ),
        inline=False
    )

    embed.add_field(
        name="🔄 !toggle",
        value=(
            "Toggle between GPT 4o and Mistral models\n"
            "> `!toggle`\n"
            "```\n"
            "• Mistral is faster but less intelligent (default).\n"
            "• GPT 4o is slower but more intelligent.\n"
            "```"
        ),
        inline=False
    )
    
    # Utility Commands Category
    embed.add_field(
        name="🔧 __Utility Commands__",
        value="─────────────────────",
        inline=False
    )
    
    # Other Commands
    embed.add_field(
        name="🆔 !myid",
        value="Display your Discord user ID",
        inline=True
    )
    
    embed.add_field(
        name="🏓 !ping",
        value="Check if the bot is responding",
        inline=True
    )
    
    # Tips in a nice box
    embed.add_field(
        name="💡 __Tips__",
        value=(
            "```\n"
            "• Each agent task runs in its own thread\n"
            "• Type 'exit' to end terminal sessions\n"
            "• File uploads limited to 7MB\n"
            "• Multiple tasks can run simultaneously\n"
            "```"
        ),
        inline=False
    )
    
    # Better footer with version info
    embed.set_footer(text="All commands use the ! prefix")
    
    await ctx.send(embed=embed)

@bot.command(name="about", help="Show information about the bot and repository")
async def about_command(ctx):
    """Display information about the bot and its GitHub repository"""
    
    # Create an attractive embed with GitHub info
    embed = discord.Embed(
        title="🤖 Megatron AI Assistant",
        url="https://github.com/VrushankGunjur/Megatron",
        description="An AI-powered Discord bot that executes tasks in a containerized environment",
        color=discord.Color.from_rgb(36, 41, 46),  # GitHub dark color
        timestamp=ctx.message.created_at
    )
    
    # Add GitHub logo as thumbnail
    embed.set_thumbnail(url="https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png")
    
    # Add repository information
    embed.add_field(
        name="📦 Repository",
        value="[VrushankGunjur/Megatron](https://github.com/VrushankGunjur/Megatron)",
        inline=False
    )
    
    # Add features section
    embed.add_field(
        name="✨ Features",
        value=(
            "• Execute bash commands in a Docker container\n"
            "• Interactive terminal through Discord\n"
            "• AI-powered task planning and execution\n"
            "• File management and container control\n"
            "• Multi-user support with dedicated sessions"
        ),
        inline=False
    )
    
    # Add technologies used
    embed.add_field(
        name="🔧 Technologies",
        value=(
            "• Python with discord.py\n"
            "• Docker containerization\n"
            "• LangChain & LangGraph\n"
            "• Mistral integration\n"
            "• Interactive shell execution"
        ),
        inline=True
    )
    
    # Add contributors section
    embed.add_field(
        name="👥 Contributors",
        value=(
            "• [Vrushank Gunjur](https://github.com/VrushankGunjur)\n"
            "• Kenny Dao\n"
            "• [Alex Waitz](https://ajwaitz.org)\n"
            "• Stanley"
        ),
        inline=True
    )
    
    # Add footer with GitHub info
    embed.set_footer(
        text="View source code and contribute on GitHub",
        icon_url="https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png"
    )
    
    await ctx.send(embed=embed)

# Start the bot, connecting it to the gateway
bot.run(token)