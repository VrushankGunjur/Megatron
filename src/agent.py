import os
import time
import random
from mistralai import Mistral
import discord
import asyncio
import logging

logger = logging.getLogger(__name__)

MISTRAL_MODEL = "mistral-large-latest"
SYSTEM_PROMPT = "Your task is to translate english to bash commands. Respond in a single bash command that can be run directly in the shell, don't use any formatting and respond in plaintext"

# Rate limiting constants
MAX_RETRIES = 5
BASE_RETRY_DELAY = 1  # seconds
MAX_RETRY_DELAY = 30  # seconds


class MistralAgent:
    def __init__(self):
        MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
        self.client = Mistral(api_key=MISTRAL_API_KEY)

    async def run_async(self, message: discord.Message):
        """Async version of the run method with rate limit handling"""
        retry_count = 0
        delay = BASE_RETRY_DELAY

        while retry_count <= MAX_RETRIES:
            try:
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": message.content},
                ]

                response = await self.client.chat.complete_async(
                    model=MISTRAL_MODEL,
                    messages=messages,
                )

                return response.choices[0].message.content

            except MistralAPIError as e:
                # Check if it's a rate limit error
                if "rate limit" in str(e).lower() or "too many requests" in str(e).lower() or e.status_code == 429:
                    retry_count += 1
                    if retry_count > MAX_RETRIES:
                        logger.error(f"Rate limit exceeded after {MAX_RETRIES} retries: {e}")
                        return f"echo 'Rate limit exceeded. Please try again later. Error: {e}'"
                    
                    # Calculate exponential backoff with jitter
                    jitter = random.uniform(0, 0.5) * delay
                    wait_time = min(delay + jitter, MAX_RETRY_DELAY)
                    
                    logger.warning(f"Rate limit hit. Retrying in {wait_time:.2f}s (attempt {retry_count}/{MAX_RETRIES})")
                    await asyncio.sleep(wait_time)
                    
                    # Exponential backoff
                    delay = min(delay * 2, MAX_RETRY_DELAY)
                else:
                    # For other API errors, log and return an error message
                    logger.error(f"Mistral API error: {e}")
                    return f"echo 'Error calling Mistral API: {e}'"
            except Exception as e:
                logger.error(f"Unexpected error calling Mistral API: {e}")
                return f"echo 'Unexpected error: {e}'"

    def run(self, message: str):
        """Synchronous version of run with rate limit handling"""
        retry_count = 0
        delay = BASE_RETRY_DELAY

        while retry_count <= MAX_RETRIES:
            try:
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ]

                response = self.client.chat.complete(
                    model=MISTRAL_MODEL,
                    messages=messages,
                )

                return response.choices[0].message.content

            except MistralAPIError as e:
                # Check if it's a rate limit error
                if "rate limit" in str(e).lower() or "too many requests" in str(e).lower() or getattr(e, 'status_code', 0) == 429:
                    retry_count += 1
                    if retry_count > MAX_RETRIES:
                        logger.error(f"Rate limit exceeded after {MAX_RETRIES} retries: {e}")
                        return f"echo 'Rate limit exceeded. Please try again later. Error: {e}'"
                    
                    # Calculate exponential backoff with jitter
                    jitter = random.uniform(0, 0.5) * delay
                    wait_time = min(delay + jitter, MAX_RETRY_DELAY)
                    
                    logger.warning(f"Rate limit hit. Retrying in {wait_time:.2f}s (attempt {retry_count}/{MAX_RETRIES})")
                    time.sleep(wait_time)
                    
                    # Exponential backoff
                    delay = min(delay * 2, MAX_RETRY_DELAY)
                else:
                    # For other API errors, log and return an error message
                    logger.error(f"Mistral API error: {e}")
                    return f"echo 'Error calling Mistral API: {e}'"
            except Exception as e:
                logger.error(f"Unexpected error calling Mistral API: {e}")
                return f"echo 'Unexpected error: {e}'"