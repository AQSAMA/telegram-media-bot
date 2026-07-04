#!/bin/bash
set -euo pipefail

: "${BOT_TOKEN:?BOT_TOKEN is required}"
: "${TELEGRAM_API_ID:?TELEGRAM_API_ID is required for the local Telegram Bot API server}"
: "${TELEGRAM_API_HASH:?TELEGRAM_API_HASH is required for the local Telegram Bot API server}"

# Ensure telegram-bot-api storage paths exist before passing them to --dir/--temp-dir.
# The server resolves these paths at startup and exits if either directory is absent.
mkdir -p /app/telegram-bot-api-data /app/telegram-bot-api-temp

# Start the local Telegram Bot API server in the background for co-located bot use.
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

# Wait for the local Bot API HTTP endpoint and fail fast if it never becomes reachable.
ready=0
for _ in {1..30}; do
  if ! kill -0 "$api_pid" 2>/dev/null; then
    echo "telegram-bot-api exited before becoming ready" >&2
    exit 1
  fi

  if python3 - <<'PY' >/dev/null 2>&1
import socket
with socket.create_connection(('127.0.0.1', 7860), timeout=1):
    pass
PY
  then
    ready=1
    break
  fi
  sleep 1
done

if [ "$ready" -ne 1 ] || ! kill -0 "$api_pid" 2>/dev/null; then
  echo "telegram-bot-api did not become ready on http://127.0.0.1:7860 within 30 seconds" >&2
  exit 1
fi

exec python3 bot.py
