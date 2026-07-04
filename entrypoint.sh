#!/bin/bash

# Create data directories with appropriate permissions
mkdir -p /app/tg-data /app/downloads

# 1. Start the local Telegram Bot API server in the background
telegram-bot-api \
  --api-id="${TELEGRAM_API_ID}" \
  --api-hash="${TELEGRAM_API_HASH}" \
  --local \
  --dir=/app/tg-data &

# 2. Start a dummy HTTP server on port 7860 to satisfy Hugging Face health checks
python3 -m http.server 7860 &

# 3. Start the main Python Telegram Bot (Keep this in the foreground)
exec python3 -u bot.py
