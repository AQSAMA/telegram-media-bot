#!/bin/bash
set -euo pipefail

: "${BOT_TOKEN:?BOT_TOKEN is required}"
: "${TELEGRAM_API_ID:?TELEGRAM_API_ID is required for the local Telegram Bot API server}"
: "${TELEGRAM_API_HASH:?TELEGRAM_API_HASH is required for the local Telegram Bot API server}"

# Start the local Telegram Bot API server in the background on Hugging Face's public port.
telegram-bot-api \
  --local \
  --http-port=7860 \
  --dir=/app/telegram-bot-api-data \
  --temp-dir=/app/telegram-bot-api-temp \
  --api-id="$TELEGRAM_API_ID" \
  --api-hash="$TELEGRAM_API_HASH" &
api_pid=$!

cleanup() {
  kill "$api_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Wait for the local Bot API HTTP endpoint instead of sleeping a fixed amount of time.
for _ in {1..30}; do
  if python3 - <<'PY' >/dev/null 2>&1
import urllib.request
urllib.request.urlopen('http://127.0.0.1:7860/', timeout=1)
PY
  then
    break
  fi
  sleep 1
done

exec python3 bot.py
