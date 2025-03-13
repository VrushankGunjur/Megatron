#!/bin/bash

docker build -t 153-proj . && docker run -e OPENAI_API_KEY=$OPENAI_API_KEY -e DISCORD_TOKEN=$DISCORD_TOKEN -e MISTRAL_API_KEY=$MISTRAL_API_KEY --rm -ti -v $(pwd)/logs:/app/logs 153-proj