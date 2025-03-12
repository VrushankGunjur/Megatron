import discord
import asyncio
import queue
import os
from shell import InteractiveShell

from .ContainerControlPanel import ContainerControlPanel


# Dictionary to track active sessions and GUI threads
active_sessions = {}
gui_threads = {}        # Map user IDs to their active GUI threads
gui_shells = {}         # Map user IDs to their dedicated shell instances
MAX_HISTORY = 20        # Maximum commands to remember

# Enhance the ContainerControlPanel with better visual organization
# Update other view classes to accept and use thread parameter
# Modify the setup function to support concurrent sessions

def setup(bot):
    # Track GUI thread cleanup status to avoid duplicate handlers
    bot._gui_cleanup_registered = False
    bot.handle_gui_messages = handle_gui_messages
    
    @bot.command(name="gui", help="Open a container control panel")
    async def gui_command(ctx):
        # if ctx.author.id not in bot.allowed_user_ids:
        #     await ctx.send("⛔ You don't have permission to use this command.")
        #     return
        
        # Check if user already has an active GUI thread
        if ctx.author.id in gui_threads:
            thread = gui_threads[ctx.author.id]
            # Verify the thread still exists and is accessible
            try:
                await thread.fetch()
                await ctx.send(f"You already have a control panel open in thread: {thread.mention}")
                return
            except discord.NotFound:
                # Thread was deleted or can't be found, remove from tracking
                if ctx.author.id in gui_shells:
                    shell_to_close = gui_shells.pop(ctx.author.id)
                    shell_to_close.stop()
                if ctx.author.id in gui_threads:
                    del gui_threads[ctx.author.id]
        
        # Create a thread for the GUI session
        thread = await ctx.message.create_thread(
            name=f"GUI Session - {ctx.author.display_name}",
            auto_archive_duration=60  # Minutes until auto-archive
        )
        
        # Create a dedicated shell instance for this GUI session
        dedicated_shell = InteractiveShell()
        dedicated_shell.set_output_callback(lambda line: print(f"[GUI Shell {thread.id}] {line}"))
        dedicated_shell.start()
        
        # Store references to the thread and shell
        gui_threads[ctx.author.id] = thread
        gui_shells[ctx.author.id] = dedicated_shell
        
        # Create and send the control panel in the thread with the dedicated shell
        panel = ContainerControlPanel(bot.brain, ctx, thread, dedicated_shell, active_sessions)
        await panel._send_welcome_message() 
        await thread.send("## 🎛️ **Container Control Panel**", view=panel)
        
        # Register the cleanup handler only once
        if not bot._gui_cleanup_registered:
            @bot.event
            async def on_thread_update(before, after):
                # Check if this is one of our GUI threads and it just got archived
                if not before.archived and after.archived:
                    # Check all registered GUI threads
                    for user_id, registered_thread in list(gui_threads.items()):
                        if after.id == registered_thread.id:
                            # Clean up this thread's resources
                            if user_id in gui_shells:
                                shell_to_close = gui_shells.pop(user_id)
                                shell_to_close.stop()
                                print(f"[GUI] Cleaned up shell for thread {after.id}")
                            # Remove from thread tracking
                            if user_id in gui_threads:
                                del gui_threads[user_id]
                                print(f"[GUI] Removed thread {after.id} from tracking")
                            
                            # Clean up any active sessions
                            for session_user_id, session in list(active_sessions.items()):
                                if session.get("thread_id") == after.id:
                                    del active_sessions[session_user_id]
                                    print(f"[GUI] Cleaned up session for user {session_user_id}")
                
                # Also check active_brains from the bot module
                if hasattr(bot, "active_brains") and after.id in bot.active_brains and not before.archived and after.archived:
                    # Clean up the brain when the thread is archived
                    brain_to_close = bot.active_brains.pop(after.id)
                    del brain_to_close  # This will trigger __del__ which cleans up resources
            
            # Mark that we've registered the cleanup handler
            bot._gui_cleanup_registered = True
        
        # Notify in original channel
        await ctx.send(f"Control panel opened in thread: {thread.mention}")

async def handle_gui_messages(bot, message):
    """Process messages related to GUI functionality like terminal sessions and file uploads"""

    if message.content.startswith(bot.command_prefix):
        print("RAN AGENT IN THE WRONG PLACE")
        return True

    # Check if this is in a terminal session thread or a file upload
    if message.author.id in active_sessions and not message.content.startswith(bot.command_prefix):
        session = active_sessions[message.author.id]
        
        # Terminal session handler
        if session["type"] == "pure_terminal" and session["thread_id"] == message.channel.id:
            # Special command handling
            if message.content.lower() == "exit":
                await message.channel.send("💤 **Terminal session ended**")
                # Remove from active sessions but keep shell alive
                del active_sessions[message.author.id]
                return True  # Message was handled
                
            # Execute the command directly on the shell
            shell = session["shell"]
            command = message.content
            
            # Add typing indicator to show processing
            async with message.channel.typing():
                output_queue = queue.Queue()
                original_callback = shell.callback
                
                try:
                    # Set callback to capture output directly
                    shell.set_output_callback(lambda line: output_queue.put(line))
                    
                    # Execute command without any brain processing
                    shell.execute_command(command)
                    
                    # Wait for command to finish
                    await asyncio.sleep(1.5)
                    
                    # Collect raw output
                    output_lines = []
                    while not output_queue.empty():
                        output_lines.append(output_queue.get())
                        
                    # Format output for terminal-like display
                    output_text = "\n".join(output_lines)
                    if "SHELL_READY" in output_text:
                        output_text = output_text.replace("SHELL_READY", "")
                    
                    # Send output as a reply to the command
                    if output_text.strip():
                        # Split large outputs
                        if len(output_text) > 1900:
                            chunks = [output_text[i:i+1900] for i in range(0, len(output_text), 1900)]
                            for i, chunk in enumerate(chunks):
                                if i == 0:
                                    await message.reply(f"```\n{chunk}\n```")
                                else:
                                    await message.channel.send(f"```\n{chunk}\n```")
                        else:
                            await message.reply(f"```\n{output_text}\n```")
                    else:
                        await message.reply("✅ Command executed with no output")
                    
                    # Add command to history for convenience
                    # if command not in command_history:
                    #     command_history.insert(0, command)
                    #     if len(command_history) > MAX_HISTORY:
                    #         command_history.pop()
                            
                except Exception as e:
                    await message.reply(f"❌ **Error executing command:**\n```\n{str(e)}\n```")
                finally:
                    shell.set_output_callback(original_callback)
            return True  # Message was handled
            
        # File upload handler
        elif session["type"] == "file_upload" and message.attachments:
            # Add thread verification
            if "thread_id" in session and session["thread_id"] != message.channel.id:
                # Message is in the wrong thread, ignore it
                return False
            
            attachment = message.attachments[0]
            
            # Download the attachment
            file_data = await attachment.read()
            
            # Get the dedicated shell for this session if available, otherwise use the bot's shell
            shell = None
            if message.author.id in gui_shells:
                shell = gui_shells[message.author.id]
            else:
                shell = bot.brain.shell
            
            # Create a temporary file
            temp_path = f"/tmp/{attachment.filename}"
            
            # Get the target directory from the session
            target_dir = session.get("target_dir", "/app")
            
            with open(temp_path, "wb") as f:
                f.write(file_data)
                
            # Now use shell to move it to the container
            output_queue = queue.Queue()
            original_callback = shell.callback
            
            try:
                shell.set_output_callback(lambda line: output_queue.put(line))
                
                # Make sure target directory exists
                shell.execute_command(f"mkdir -p '{target_dir}'")
                await asyncio.sleep(0.5)
                
                # Clear queue
                while not output_queue.empty():
                    output_queue.get()
                
                # Copy from temp to container
                target_path = os.path.join(target_dir, attachment.filename)
                copy_cmd = f"cp '{temp_path}' '{target_path}'"
                shell.execute_command(copy_cmd)
                
                # Wait for command to finish
                await asyncio.sleep(1)
                
                # Clear queue
                while not output_queue.empty():
                    output_queue.get()
                    
                # Get the thread if available
                if "thread_id" in session:
                    thread = bot.get_channel(session["thread_id"])
                    if thread:
                        await thread.send(f"✅ File `{attachment.filename}` uploaded to container at `{target_path}`")
                    else:
                        await message.channel.send(f"✅ File `{attachment.filename}` uploaded to container at `{target_path}`")
                else:
                    await message.channel.send(f"✅ File `{attachment.filename}` uploaded to container at `{target_path}`")
                
            except Exception as e:
                await message.channel.send(f"❌ Error uploading file: {str(e)}")
            finally:
                shell.set_output_callback(original_callback)
                # Clean up the session
                del active_sessions[message.author.id]
                
                # Clean up temp file
                try:
                    os.remove(temp_path)
                except:
                    pass
                    
            return True  # Message was handled

    return False  # Message was not handled by GUI