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
        
        # # Check if user already has an active GUI thread
        # if ctx.author.id in gui_threads:
        #     thread = gui_threads[ctx.author.id]
        #     # Verify the thread still exists and is accessible
        #     try:
        #         await thread.fetch()
        #         await ctx.send(f"You already have a control panel open in thread: {thread.mention}")
        #         return
        #     except discord.NotFound:
        #         # Thread was deleted or can't be found, remove from tracking
        #         if ctx.author.id in gui_shells:
        #             shell_to_close = gui_shells.pop(ctx.author.id)
        #             shell_to_close.stop()
        #         if ctx.author.id in gui_threads:
        #             del gui_threads[ctx.author.id]
        
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
        panel = ContainerControlPanel(bot.brain, ctx, thread, dedicated_shell, active_sessions, gui_threads)
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

    # Find if message is in any GUI thread
    thread_id = message.channel.id
    thread_owner = None
    for user_id, thread in gui_threads.items():
        if thread.id == thread_id:
            thread_owner = user_id
            break
    
    # Check for kill command in GUI threads
    if thread_owner is not None and message.content.lower() == "!kill":
        # Verify the sender is the thread owner or has admin permissions
        if message.author.id == thread_owner or message.author.guild_permissions.administrator:
            await message.add_reaction("⏳")
            
            # Clean up shell resources
            if thread_owner in gui_shells:
                try:
                    shell_to_close = gui_shells.pop(thread_owner)
                    shell_to_close.stop()
                    await message.channel.send("💤 **GUI session terminated**")
                    
                    # Also clean up any active sessions for this user
                    if thread_owner in active_sessions:
                        del active_sessions[thread_owner]
                    
                    # Remove thread from tracking
                    if thread_owner in gui_threads:
                        del gui_threads[thread_owner]

                    try:
                        await message.remove_reaction("⏳", bot.user)
                    except:
                        pass

                    await message.add_reaction("✅")
                    return True
                except Exception as e:
                    try:
                        await message.remove_reaction("⏳", bot.user)
                    except:
                        pass
                    await message.channel.send(f"❌ **Error terminating session:** {str(e)}")
                    await message.add_reaction("❌")
                    return True
            else:
                await message.channel.send("ℹ️ No active shell found to terminate")
                return True
        else:
            await message.reply("⛔ **Access denied**: Only the thread creator or an administrator can terminate this session.")
            return True
    
    # If this is a GUI thread but the message author isn't the owner, prevent interaction
    if thread_owner is not None and message.author.id != thread_owner:
        # Only respond if they're trying to use a command
        if message.content and not message.content.startswith(bot.command_prefix):
            await message.reply("⛔ **Access denied**: Only the user who created this GUI session can interact with it.")
        return True  # Message was handled (blocked)

    # Check if this is in a terminal session thread or a file upload
    if message.author.id in active_sessions: #and not message.content.startswith(bot.command_prefix):
        session = active_sessions[message.author.id]
        
        # Terminal session handler
        if session["type"] == "pure_terminal" and session["thread_id"] == message.channel.id:
            # Check for exit command
            if message.content.lower() == "exit":
                await message.channel.send("💤 **Terminal session ended**")
                del active_sessions[message.author.id]
                return True
            
            await message.add_reaction("⏳")
            
            # Get shell and execute command
            shell = session["shell"]
            command = message.content
            shell_output_buffer = queue.Queue()
            original_callback = shell.callback
            
            try:
                
                # Execute command with typing indicator
                async with message.channel.typing():
                    shell.set_output_callback(lambda line: shell_output_buffer.put(line))
                    shell.execute_command(command, wait_for_prompt=False)
                    
                    await asyncio.sleep(1.5)
                    
                    output_lines = []
                    while not shell_output_buffer.empty():
                        output_lines.append(shell_output_buffer.get())
                    
                    output_text = "\n".join(output_lines)
                    output_text = output_text.replace("SHELL_READY", "")
                    has_error = "[ERROR]" in output_text
                    
                    if output_text.strip():
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
                    
                    # Add success/error reaction
                    if has_error:
                        await message.add_reaction("❌")
                    else:
                        await message.add_reaction("✅")
            
            except Exception as e:
                await message.reply(f"❌ **Error executing command:**\n```\n{str(e)}\n```")
                await message.add_reaction("❌")
            finally:
                # Always restore original callback
                shell.set_output_callback(original_callback)
                try:
                    await message.remove_reaction("⏳", bot.user)
                except:
                    pass
                
            return True  
            
        # File upload handler
        elif session["type"] == "file_upload" and message.attachments:
            # Add thread verification
            if "thread_id" in session and session["thread_id"] != message.channel.id:
                # Message is in the wrong thread, ignore it
                return False
            
            await message.add_reaction("⏳")
            
            attachment = message.attachments[0]

            processing_msg = await message.reply(
                f"⏳ **Processing upload:** `{attachment.filename}`\n"
                "> Downloading file..."
            )
            
            async with message.channel.typing():
                try:
                    # Download the attachment
                    await processing_msg.edit(content=f"⏳ **Processing upload:** `{attachment.filename}`\n> Downloading file... ({attachment.size/1024:.1f} KB)")
                    file_data = await attachment.read()
                    
                    # Get the dedicated shell for this session if available, otherwise use the bot's shell
                    shell = None
                    if message.author.id in gui_shells:
                        shell = gui_shells[message.author.id]
                    else:
                        shell = bot.brain.shell
                    
                    # Create a temporary file
                    await processing_msg.edit(content=f"⏳ **Processing upload:** `{attachment.filename}`\n> Preparing file for container...")
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
                        await processing_msg.edit(content=f"⏳ **Processing upload:** `{attachment.filename}`\n> Checking target directory...")
                        shell.execute_command(f"mkdir -p '{target_dir}'")
                        await asyncio.sleep(0.5)
                        
                        # Clear queue
                        while not output_queue.empty():
                            output_queue.get()
                        
                        # Copy from temp to container
                        await processing_msg.edit(content=f"⏳ **Processing upload:** `{attachment.filename}`\n> Copying to container...")
                        target_path = os.path.join(target_dir, attachment.filename)
                        copy_cmd = f"cp '{temp_path}' '{target_path}'"
                        shell.execute_command(copy_cmd)
                        
                        # Wait for command to finish
                        await asyncio.sleep(1)
                        
                        # Clear queue
                        while not output_queue.empty():
                            output_queue.get()
                            
                        # Verify file was copied successfully
                        await processing_msg.edit(content=f"⏳ **Processing upload:** `{attachment.filename}`\n> Verifying file...")
                        shell.execute_command(f"[ -f '{target_path}' ] && echo 'SUCCESS' || echo 'FAILED'")
                        await asyncio.sleep(0.5)
                        
                        verify_output = []
                        while not output_queue.empty():
                            verify_output.append(output_queue.get())
                        
                        if any('SUCCESS' in line for line in verify_output):
                            # Success! File was uploaded successfully
                            await processing_msg.edit(content=f"✅ **Upload complete:** `{attachment.filename}`\n> File saved to `{target_path}`")
                            await message.add_reaction("✅")
                            
                            # Get the thread if available
                            if "thread_id" in session:
                                thread = bot.get_channel(session["thread_id"])
                                if thread and thread.id != message.channel.id:  # Don't duplicate if we're already in the thread
                                    await thread.send(f"✅ File `{attachment.filename}` uploaded to container at `{target_path}`")
                        else:
                            # Failed to verify file
                            await processing_msg.edit(content=f"❌ **Upload failed:** `{attachment.filename}`\n> Could not verify file in container.")
                            await message.add_reaction("❌")
                        
                    except Exception as e:
                        await processing_msg.edit(content=f"❌ **Upload error:** `{attachment.filename}`\n> {str(e)}")
                        await message.add_reaction("❌")
                        
                    finally:
                        shell.set_output_callback(original_callback)
                        # Clean up the session
                        del active_sessions[message.author.id]
                        
                        # Clean up temp file
                        try:
                            os.remove(temp_path)
                        except:
                            pass
                        
                except Exception as e:
                    await processing_msg.edit(content=f"❌ **Upload failed:** `{attachment.filename}`\n> {str(e)}")
                    await message.add_reaction("❌")
                    
                    # Clean up the session
                    del active_sessions[message.author.id]
            
            try:
                # Remove processing indicator after we're done
                await message.remove_reaction("⏳", bot.user)
            except:
                pass
                
            return True  # Message was handled

    return False  # Message was not handled by GUI