# Use an official Python runtime as a parent image
FROM python:3.12

# Set the working directory in the container
WORKDIR /app

# Install sudo
# RUN apt-get update && apt-get install -y sudo nano vim
RUN apt-get update && apt-get install -y sudo

# Copy the current directory contents into the container at /app
COPY . .

ENV DISCORD_TOKEN="MTMzOTczNzAzMjE4MzkwNjM1OA.GRg4CM.7nct2O53xKfyBzlgpkTsUsofN0HpTE-GsmGNG4"
ENV OPENAI_API_KEY="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"
ENV PS1="sussybaka"

# Install any dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run the main function when the container starts
CMD ["python", "/app/src/bot.py"]

# we need to make sure that it can connect to discord bot from within the docker container