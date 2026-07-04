---
title: TeleBotDown
emoji: 💻
colorFrom: purple
colorTo: indigo
sdk: docker
pinned: false
license: gpl-3.0
---

# TeleBotDown

A Telegram media downloader bot for public YouTube, Instagram, TikTok, Reddit, X/Twitter, Facebook, generic `yt-dlp` supported pages, and direct file links.

The container runs a local Telegram Bot API server and the Python bot in the same process tree. Local Bot API mode is required for large uploads that exceed the normal cloud Bot API limits.

## Required environment variables

| Variable | Purpose |
| --- | --- |
| `BOT_TOKEN` | Telegram bot token from BotFather. |
| `TELEGRAM_API_ID` | Telegram API ID from <https://my.telegram.org>. |
| `TELEGRAM_API_HASH` | Telegram API hash from <https://my.telegram.org>. |

## Optional environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `BOT_API_URL` | `http://127.0.0.1:7860/bot` | Local Telegram Bot API base URL. |
| `BOT_API_FILE_URL` | `http://127.0.0.1:7860/file/bot` | Local Telegram Bot API file URL. |
| `DOWNLOAD_DIR` | `/app/downloads` | Temporary download folder. |
| `MAX_FILE_SIZE` | `2147483648` | Maximum accepted file size in bytes. |
| `CONCURRENCY` | `2` | Number of simultaneous user downloads. |
| `COOKIES_FILE` | `/app/cookies.txt` | Optional Netscape cookies file for sites that require login cookies. |
| `YTDLP_FRAGMENTS` | `6` | Number of concurrent fragments for segmented downloads. |
| `YTDLP_TIMEOUT` | `3600` | Seconds to wait for new `yt-dlp` output before timing out. |

## Docker Compose

```bash
cp .env.example .env  # if you create one locally
# Fill BOT_TOKEN, TELEGRAM_API_ID, and TELEGRAM_API_HASH in .env
docker compose up --build
```

## Notes

- Use cookies only from accounts you own and only where allowed by a site's terms.
- Telegram and the local Bot API server still enforce their own limits; `MAX_FILE_SIZE` prevents wasting disk and bandwidth on files that cannot be uploaded.
- Some platforms block datacenter IPs, require cookies, or change extractors often. Keeping `yt-dlp` current is important.
