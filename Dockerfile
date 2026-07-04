# Use the official telegram-bot-api image as the base (built on Alpine Linux)
FROM aiogram/telegram-bot-api:latest

# Install Python, pip, ffmpeg, and bash dependencies
RUN apk add --no-cache python3 py3-pip ffmpeg bash

WORKDIR /app

# Configure a virtual environment to safely install python packages
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Copy and install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -U yt-dlp

# Copy application scripts
COPY bot.py .
COPY entrypoint.sh .
COPY cookies.txt* .

# Fix script execution permissions and directory access for Hugging Face standard user
RUN chmod +x entrypoint.sh && chmod -R 777 /app

# Hugging Face strictly monitors port 7860
EXPOSE 7860

ENTRYPOINT ["/app/entrypoint.sh"]
