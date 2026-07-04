#!/bin/bash
set -euo pipefail

: "${BOT_TOKEN:?BOT_TOKEN is required}"
: "${TELEGRAM_API_ID:?TELEGRAM_API_ID is required for the local Telegram Bot API server}"
: "${TELEGRAM_API_HASH:?TELEGRAM_API_HASH is required for the local Telegram Bot API server}"

BOT_API_HOST="127.0.0.1"
BOT_API_PORT="7860"
BOT_API_URL="http://${BOT_API_HOST}:${BOT_API_PORT}/"
BOT_API_DATA_DIR="/app/telegram-bot-api-data"
BOT_API_TEMP_DIR="/app/telegram-bot-api-temp"
DOWNLOAD_DIR="/app/downloads"

mkdir -p "$BOT_API_DATA_DIR" "$BOT_API_TEMP_DIR" "$DOWNLOAD_DIR"

telegram-bot-api \
  --local \
  --http-ip-address="$BOT_API_HOST" \
  --http-port="$BOT_API_PORT" \
  --dir="$BOT_API_DATA_DIR" \
  --temp-dir="$BOT_API_TEMP_DIR" \
  --api-id="$TELEGRAM_API_ID" \
  --api-hash="$TELEGRAM_API_HASH" &
api_pid=$!

cleanup() {
  kill "$api_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

bot_api_ready() {
  python3 -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=1).close()' "$BOT_API_URL" >/dev/null 2>&1
}

ready=0
for _ in $(seq 1 30); do
  if ! kill -0 "$api_pid" 2>/dev/null; then
    echo "telegram-bot-api exited before becoming ready" >&2
    exit 1
  fi

  if bot_api_ready; then
    ready=1
    break
  fi
  sleep 1
done

if [ "$ready" -ne 1 ] || ! kill -0 "$api_pid" 2>/dev/null; then
  echo "telegram-bot-api did not become ready on ${BOT_API_URL} within 30 seconds" >&2
  exit 1
fi

exec python3 bot.py
