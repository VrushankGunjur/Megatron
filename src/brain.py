import threading
import time
import queue
from shell import InteractiveShell
import discord
import asyncio
from agent import MistralAgent


import logging


class Brain:

    def __init__(self):
        self.logger = logging.getLogger("brain")

        self.channel = None
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
        self.agent = MistralAgent()

        

    def _drain_shell(self, line: str):
        self.shell_out_buffer.put(line)
        
        self.logger.info(line)
        # loop = self.discord_loop()
        if self.discord_loop is not None and self.discord_loop.is_running():
            self.logger.info("Trying to send discord msg back..")
            asyncio.run_coroutine_threadsafe(self._send_discord_msg(line), self.discord_loop)

    def __del__(self):
        self.mthread.join()
        self.shell.stop()

    def submit_msg(self, msg: str):
        # this should only be called externally
        self.logger.info(f"submitting msg: {msg}")
        self.incoming_msg_buffer.put(msg)

    def _brain_main(self):
        while True:
            time.sleep(1)
            self.logger.info("Hello from Brain")

            # check if there is a message in the incoming_msg_buffer
            if not self.incoming_msg_buffer.empty():
                msg = self.incoming_msg_buffer.get()

                self.logger.info(f"Calling agent on {msg}")
                completion = self.agent.run(msg)


                # if 'rm' in completion:
                #     continue

                # self._drain_shell(completion)

                self.logger.info(f"sending \"{completion}\" to shell")
                
                self.shell.execute_command(completion)     # this shouldn't block

            # check if there is a new message in the shell_out_buffer



    async def _send_discord_msg(self, msg: str):
        self.logger.info("Channel:", self.channel)
        self.logger.info("Event loop:", self.discord_loop)
        self.logger.info(f"sending \"{msg}\" to discord")
        await self.channel.send(msg)