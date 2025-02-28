import threading
import time
import queue
from shell import InteractiveShell
import discord
import asyncio



class Brain:
    global brain_online
    def __init__(self, channel):
        self.channel = channel
        self.discord_loop = None

        self.chat_state = queue.Queue()
        self.shell_state = queue.Queue()
        
        self.incoming_msg_buffer = queue.Queue()        # thread safe
        self.shell_out_buffer = queue.Queue()           # thread safe

        self.shell = InteractiveShell()
        self.shell.set_output_callback(self._drain_shell)
        self.shell.start()

        # start a thread on brain_main
        self.mthread = threading.Thread(target=self._brain_main)
        self.mthread.start()

        

    def _drain_shell(self, line: str):
        self.shell_out_buffer.put(line)
        
        print(line)
        # loop = self.discord_loop()
        if self.discord_loop is not None and self.discord_loop.is_running():
            asyncio.run_coroutine_threadsafe(self._send_discord_msg(line), self.discord_loop)

    def __del__(self):
        self.mthread.join()
        self.shell.stop()

    def submit_msg(self, msg: str):
        # this should only be called externally
        print(f"submitting msg: {msg}")
        self.incoming_msg_buffer.put(msg)

    def _brain_main(self):
        while True:
            time.sleep(1)
            print("Hello from Brain")

            # check if there is a message in the incoming_msg_buffer
            if not self.incoming_msg_buffer.empty():
                msg = self.incoming_msg_buffer.get()
                print(f"sending {msg} to shell")
                self.shell.execute_command(msg)     # this shouldn't block

            # check if there is a new message in the shell_out_buffer
            ...

    async def _send_discord_msg(self, msg: str):
        await self.channel.send(msg)