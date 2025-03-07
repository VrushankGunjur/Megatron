from mistralai import Mistral as _Mistral
# from mistralai.models.chat_completion import ChatMessage
import os
from dspy import LM
from typing import Any
import json

class Mistral(LM):

    def __init__(self, model, api_key, **kwargs):
        self.model = model
        self.api_key = api_key
        # self.endpoint = endpoint 
        self.client = _Mistral(api_key=api_key)
        self.kwargs = {
            "temperature": 0.0,
            "max_tokens": 150,
            "top_p": 1,
            "frequency_penalty": 0,
            "presence_penalty": 0,
            "n": 1,
            **kwargs,
        }
        self.history: list[dict[str, Any]] = []
        self.provider = "openai"

    def basic_request(self, prompt: str, messages, **kwargs):
        chat_response = self.client.chat.complete(
            model=self.model,
            messages=messages + [
                {"role": "user", "content": prompt}
            ],
            **kwargs
        )
        response_dict = json.loads(chat_response.model_dump_json())

        self.history.append({
            "prompt": prompt,
            "response": response_dict, #{"choices": chat_response.choices[0].message.content},
            "kwargs": kwargs,
        })

        return chat_response

    def __call__(self, prompt=None, messages=None, only_completed=True, return_sorted=False, **kwargs):
        response = self.basic_request(prompt=prompt, messages=messages, **kwargs)
        completions = [response.choices[0].message.content] 
        return completions

    def _get_choice_text(self, choice: dict[str, Any]) -> str:
        
        return choice["message"]["content"]