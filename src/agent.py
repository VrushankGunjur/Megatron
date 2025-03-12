import os
# from mistralai import Mistral
from openai import OpenAI 
import discord
import asyncio

OPENAI_MODEL = "gpt-4o"
SYSTEM_PROMPT = "Your task is to translate english to bash commands. Respond in a single bash command that can be run directly in the shell, don't use any formatting and respond in plaintext"


class MistralAgent:
    def __init__(self):
        # MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
        # self.client = Mistral(api_key=MISTRAL_API_KEY)
        OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # Update env variable
        self.client = OpenAI(api_key=OPENAI_API_KEY)

    async def run_async(self, message: discord.Message):
        # The simplest form of an agent
        # Send the message's content to Mistral's API and return Mistral's response

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message.content},
        ]

        response = await self.client.chat.complete_async(
            model=MISTRAL_MODEL,
            messages=messages,
        )

        return response.choices[0].message.content

    def run(self, message: str):
        # The simplest form of an agent
        # Send the message's content to Mistral's API and return Mistral's response

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ]

        response = self.client.chat.complete(
            model=MISTRAL_MODEL,
            messages=messages,
        )

        return response.choices[0].message.content