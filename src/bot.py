import os
import discord
import logging
import signal
import sys
import atexit

from discord.ext import commands, tasks
from dotenv import load_dotenv
import subprocess
import time
import asyncio
import random

from shell import InteractiveShell
from cleanup import cleanup_all_shell_containers
from brain import Brain

PREFIX = "!"

import certifi
os.environ["SSL_CERT_FILE"] = certifi.where()

print(os.getenv("SSL_CERT_FILE"))
# Setup logging
logger = logging.getLogger("discord")
logging.basicConfig(level=logging.INFO)

ALLOWED_USER_IDS = {249749629229465611} # 269194364201336832, 249749629229465611, 203260138247684096, 344497041516527617}  # [Vrushank, Kenny, Alex, Stanley]

# Load the environment variables
load_dotenv()

# Create the bot with all intents
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Get the token from the environment variables
token = os.getenv("DISCORD_TOKEN")

brain = Brain()

# Global variable to prevent multiple shutdown attempts
shutdown_in_progress = False

# Make this function async so it doesn't block the event loop
async def async_cleanup():
    """Asynchronous cleanup function"""
    logger.info("Bot is shutting down, cleaning up resources...")
    
    # First, send a notification to Discord if possible
    try:
        if brain.channel:
            await brain.channel.send("```🧹 Cleanup initiated. Shutting down Docker container and resources...```")
    except Exception as e:
        logger.error(f"Failed to send cleanup notification to Discord: {e}")
    
    # First, try to shut down the brain (do this in a thread to avoid blocking)
    def shutdown_brain():
        try:
            logger.info("Shutting down brain and Docker container...")
            brain.shutdown()
            logger.info("✅ Brain and Docker container shutdown complete")
        except Exception as e:
            logger.error(f"❌ Error shutting down brain: {e}")
    
    # Run brain shutdown in a thread
    shutdown_thread = threading.Thread(target=shutdown_brain)
    shutdown_thread.daemon = True
    shutdown_thread.start()
    
    # Give the brain a short time to clean up
    await asyncio.sleep(1)
    
    # Then make sure all containers are stopped (also in a thread)
    def stop_containers():
        try:
            logger.info("Cleaning up any remaining Docker containers...")
            containers = cleanup_all_shell_containers(return_count=True)
            logger.info(f"✅ Cleaned up {containers} Docker containers")
        except Exception as e:
            logger.error(f"❌ Error cleaning up containers: {e}")
    
    # Run container cleanup in a thread
    container_thread = threading.Thread(target=stop_containers)
    container_thread.daemon = True
    container_thread.start()
    
    # Give containers a moment to stop
    await asyncio.sleep(1)
    
    # Send final status to Discord if possible
    try:
        if brain.channel:
            await brain.channel.send("```✅ Cleanup complete. Bot shutting down.```")
    except:
        pass
        
    logger.info("🏁 Cleanup complete - ready for shutdown")

# Improved cleanup function that works for both normal exits and signals
def cleanup():
    """Synchronous cleanup function for atexit"""
    global shutdown_in_progress
    if shutdown_in_progress:
        return
        
    shutdown_in_progress = True
    logger.info("Running synchronous cleanup on exit")
    
    # Just do basic brain shutdown first
    try:
        if hasattr(brain, 'shell') and brain.shell:
            brain.shell.force_stop()
    except:
        pass
    
    # Then directly clean up containers without going through brain
    try:
        cleanup_all_shell_containers()
    except:
        pass

# Register the cleanup function to run on exit
atexit.register(cleanup)

# Handle termination signals gracefully
def signal_handler(sig, frame):
    """Handle termination signals by scheduling a clean shutdown"""
    global shutdown_in_progress
    if shutdown_in_progress:
        return
        
    shutdown_in_progress = True
    logger.info(f"Received signal {sig}, initiating graceful shutdown...")
    
    # Schedule bot.close() to run on the event loop
    # This is critical for cleanly disconnecting from Discord
    if bot and bot.loop:
        # Schedule the bot closure and cleanup on the event loop
        asyncio.create_task(handle_shutdown())
        
        # Keep the loop running for up to 5 more seconds to complete shutdown
        # This prevents immediate termination and allows Discord to disconnect cleanly
        if not bot.loop.is_closed():
            try:
                bot.loop.run_until_complete(asyncio.sleep(5))
            except:
                pass

# Define a proper shutdown sequence
async def handle_shutdown():
    """Proper sequence for shutting down the bot"""
    try:
        logger.info("🚨 Executing shutdown sequence")
        
        # First run our async cleanup
        await async_cleanup()
        
        # Then properly close the Discord connection
        if bot:
            logger.info("Closing Discord connection...")
            await bot.close()
            
        # Signal to the main thread we're ready to exit
        logger.info("✅ Shutdown sequence completed successfully")
    except Exception as e:
        logger.error(f"❌ Error during shutdown sequence: {e}")

# Register the signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
if hasattr(signal, 'SIGBREAK'):  # Windows only
    signal.signal(signal.SIGBREAK, signal_handler)

@bot.event
async def on_ready():
    """
    Called when the client is done preparing the data received from Discord.
    Prints message on terminal when bot successfully connects to discord.

    https://discordpy.readthedocs.io/en/latest/api.html#discord.on_ready
    """
    logger.info(f"{bot.user} has connected to Discord!")
    try:
        # Get the event loop and channel
        brain.discord_loop = asyncio.get_running_loop()
        channel_id = 1339738567177670748  # Your channel ID
        brain.channel = bot.get_channel(channel_id)
        
        if brain.channel is None:
            logger.error(f"Could not find channel with ID {channel_id}")
            # Try getting the channel through a different method
            for guild in bot.guilds:
                brain.channel = discord.utils.get(guild.text_channels, id=channel_id)
                if brain.channel:
                    break
            
            if brain.channel is None:
                logger.error(f"Still could not find channel with ID {channel_id}")
            else:
                logger.info(f"Found channel through guild search: {brain.channel.name}")
        else:
            logger.info(f"Connected to channel: {brain.channel.name}")
            
        # Test message to confirm channel connection
        if brain.channel:
            await brain.channel.send("```Bot connected and ready to process commands in Docker container!```")
    except Exception as e:
        logger.error(f"Error during on_ready: {str(e)}")

@bot.command()
async def myid(ctx):
    await ctx.send(f"Your Discord ID is: {ctx.author.id}")

@bot.event
async def on_message(message: discord.Message):
    """
    Called when a message is sent in any channel the bot can see.
    """
    # Don't delete this line! It's necessary for the bot to process commands.
    await bot.process_commands(message)

    # Ignore messages from self or other bots to prevent infinite loops.
    if message.author.bot or message.content.startswith("!"):
        return

    if message.author.id not in ALLOWED_USER_IDS:
        logger.info(f"User {message.author} is not allowed to use the bot.")
        return
    
    # Process the message with the agent
    logger.info(f"Processing message from {message.author}: {message.content}")
    
    # Get the command from the agent before executing
    try:
        command = brain.agent.run(message.content)
        # Send the response back to the channel with the command
        await message.reply(f"```bash\n🚀 Executing: {command}\n```")
    except Exception as e:
        logger.error(f"Error getting command from agent: {e}")
        await message.reply("⚠️ Error processing your request. Please try again.")
        return
        
    # Now submit the message to the brain for execution
    brain.submit_msg(message.content)
    
    # No need to wait since we're showing the command immediately

@bot.command(name="ping", help="Pings the bot.")
async def ping(ctx, *, arg=None):
    if (arg is None):
        await ctx.send("Pong!")
    else:
        await ctx.send(f"Pong! Your argument was {arg}")

# Add a shutdown command for administrative control
@bot.command(name="shutdown", help="Safely shut down the bot")
async def shutdown_command(ctx):
    if ctx.author.id not in ALLOWED_USER_IDS:
        await ctx.send("❌ You don't have permission to shut down the bot.")
        return
    
    global shutdown_in_progress
    if shutdown_in_progress:
        await ctx.send("⏳ Shutdown already in progress.")
        return
        
    shutdown_in_progress = True
    
    await ctx.send("🚨 **Shutting down the bot and cleaning up resources...**")
    logger.info(f"Shutdown initiated by user {ctx.author.name} (ID: {ctx.author.id})")
    
    # Call the async shutdown sequence
    await handle_shutdown()

# Start the bot, connecting it to the gateway
try:
    # Add this import at the top with other imports
    import threading
    bot.run(token)
except KeyboardInterrupt:
    # KeyboardInterrupt is handled by the signal handler
    logger.info("KeyboardInterrupt - exiting")
except Exception as e:
    logger.error(f"Error running bot: {e}")
    cleanup()
finally:
    # One final cleanup attempt in case the others failed
    try:
        cleanup()
    except:
        pass
