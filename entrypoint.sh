#!/bin/bash

# Start the local Telegram Bot API server in the background on port 7860
telegram-bot-api --local --http-port=7860 --api-id="$TELEGRAM_API_ID" --api-hash="$TELEGRAM_API_HASH" &

# Allow server startup latency synchronization
sleep 3

# Execute the main Python process
exec python3 bot.py
