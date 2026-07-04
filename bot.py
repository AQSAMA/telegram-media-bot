import asyncio
import logging
import os
import shutil
from pathlib import Path
from urllib.parse import urlparse

import aiofiles
import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

BOT_TOKEN        = os.environ["BOT_TOKEN"]
# Point strictly to localhost on port 7860 where the local server co-exists
BOT_API_URL      = os.environ.get("BOT_API_URL", "http://127.0.0.1:7860/bot")
BOT_API_FILE_URL = os.environ.get("BOT_API_FILE_URL", "http://127.0.0.1:7860/file/bot")

DOWNLOAD_DIR = Path("/app/downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Limit concurrent operations to save container resources
CONCURRENCY = int(os.environ.get("CONCURRENCY", "3"))
sem = asyncio.Semaphore(CONCURRENCY)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("media-bot")

MEDIA_EXTS = {
    "photo": {".jpg", ".jpeg", ".png", ".webp"},
    "video": {".mp4", ".mkv", ".mov", ".webm", ".avi"},
    "audio": {".mp3", ".m4a", ".ogg", ".wav", ".flac", ".opus"},
}

async def cmd_start(update: Update, _):
    await update.message.reply_text(
        "👋 *Media Downloader Bot*\n\n"
        "Send me a link from Instagram, TikTok, YouTube, X, Reddit, Facebook... "
        "or a direct file URL. I will fetch it and send it back to you "
        "(supports up to 2 GB).",
        parse_mode="Markdown",
    )

def looks_like_direct_file(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for cat in MEDIA_EXTS.values() for ext in cat)

async def fetch_direct(url: str, dest: Path):
    """Fast async streaming for direct URLs bypassing yt-dlp overhead."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(600.0)) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            async with aiofiles.open(dest, "wb") as f:
                async for chunk in response.aiter_bytes(1 << 20):  # 1 MiB chunks
                    await f.write(chunk)

async def fetch_with_ytdlp(url: str, dest_dir: Path) -> list[Path]:
    """Executes yt-dlp in a managed subprocess with multi-threading optimized commands."""
    out_template = str(dest_dir / "%(title).200B.%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--no-playlist",
        "--no-progress",
        "--no-mtime",
        "--concurrent-fragments", "4",  # Parallel fragment downloads for speed
        "--retries", "5",
        "--embed-metadata",
        "--embed-thumbnail",
        "--merge-output-format", "mp4",
        "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--output", out_template,
    ]

    # Automatically check and inject cookies if available
    cookies_file = Path("/app/cookies.txt")
    if cookies_file.exists() and cookies_file.stat().st_size > 0:
        cmd.extend(["--cookies", str(cookies_file)])
        log.info("Using exported cookies for extraction.")

    cmd.append(url)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode(errors="replace").strip()[:1500])

    return [p for p in dest_dir.iterdir() if p.is_file()]

def classify(path: Path):
    ext = path.suffix.lower()
    for kind, exts in MEDIA_EXTS.items():
        if ext in exts:
            return kind
    return "document"

async def send_file(update: Update, path: Path):
    kind = classify(path)
    caption = path.name
    with path.open("rb") as fh:
        if kind == "photo":
            await update.message.reply_photo(photo=fh, caption=caption)
        elif kind == "video":
            await update.message.reply_video(video=fh, caption=caption, supports_streaming=True)
        elif kind == "audio":
            await update.message.reply_audio(audio=fh, caption=caption)
        else:
            await update.message.reply_document(document=fh, caption=caption)

async def handle_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    user = update.message.from_user
    log.info("User %s requested URL: %s", user.id, url)

    status = await update.message.reply_text("⏳ Downloading... Please wait.")

    async with sem:
        tmp_dir = DOWNLOAD_DIR / f"{update.update_id}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            # Keeps the interactive "uploading document" continuous during high latency
            ping_task = asyncio.create_task(_keep_pinging(update))

            try:
                if looks_like_direct_file(url):
                    name = Path(urlparse(url).path).name or "file"
                    dest = tmp_dir / name
                    await fetch_direct(url, dest)
                    files = [dest]
                else:
                    files = await fetch_with_ytdlp(url, tmp_dir)
            finally:
                ping_task.cancel()

            if not files:
                await status.edit_text("⚠️ No downloadable media found.")
                return

            await status.edit_text(f"📤 Uploading {len(files)} file(s) to Telegram...")
            await update.message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)

            for f in files:
                await send_file(update, f)

            await status.delete()
        except Exception as e:
            log.exception("Task failed.")
            await status.edit_text(f"❌ Error: {e}"[:4000])
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

async def _keep_pinging(update: Update):
    """Refreshes Telegram status action every 4 seconds for huge transfers."""
    try:
        while True:
            await update.message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass

def build_app() -> Application:
    return (
        Application.builder()
        .token(BOT_TOKEN)
        .base_url(BOT_API_URL)
        .base_file_url(BOT_API_FILE_URL)
        .local_mode(True)  # Activates Local Server Mode for 2 GB files
        .read_timeout(600)
        .write_timeout(600)
        .connect_timeout(60)
        .pool_timeout(60)
        .build()
    )

def main():
    app = build_app()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    log.info("Bot infrastructure successfully initialized.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
