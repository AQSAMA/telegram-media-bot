import asyncio
import contextlib
import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

import aiofiles
import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.error import BadRequest, NetworkError, TimedOut
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN")
BOT_API_URL = os.environ.get("BOT_API_URL", "http://127.0.0.1:7860/bot")
BOT_API_FILE_URL = os.environ.get("BOT_API_FILE_URL", "http://127.0.0.1:7860/file/bot")

DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", "/app/downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE", str(2 * 1024 * 1024 * 1024)))
CONCURRENCY = int(os.environ.get("CONCURRENCY", "2"))
DIRECT_TIMEOUT = float(os.environ.get("DIRECT_TIMEOUT", "1800"))
YTDLP_TIMEOUT = int(os.environ.get("YTDLP_TIMEOUT", "3600"))
sem = asyncio.Semaphore(CONCURRENCY)

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
log = logging.getLogger("media-bot")

MEDIA_EXTS = {
    "photo": {".jpg", ".jpeg", ".png", ".webp"},
    "video": {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"},
    "audio": {".mp3", ".m4a", ".ogg", ".wav", ".flac", ".opus"},
}
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
DIRECT_FILE_EXTS = set().union(*MEDIA_EXTS.values()) | {
    ".7z", ".apk", ".bin", ".csv", ".doc", ".docx", ".epub", ".exe",
    ".gz", ".iso", ".json", ".pdf", ".ppt", ".pptx", ".rar", ".tar",
    ".txt", ".xls", ".xlsx", ".zip",
}


def human_size(num: int | None) -> str:
    if num is None:
        return "unknown size"
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{num} B"


def extract_url(text: str) -> str | None:
    match = URL_RE.search(text or "")
    return match.group(0).rstrip(").,;!?'\"") if match else None


def safe_filename(name: str, fallback: str = "download") -> str:
    name = unquote(name).strip().replace("\x00", "")
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name or fallback)[:180]


def looks_like_direct_file(url: str) -> bool:
    path = urlparse(url).path.lower()
    return Path(path).suffix in DIRECT_FILE_EXTS


async def cmd_start(update: Update, _):
    await update.effective_message.reply_text(
        "👋 *Media Downloader Bot*\n\n"
        "Send a public link from YouTube, Instagram, TikTok, Reddit, X, Facebook, "
        "or a direct file URL. I will download it and send it back on Telegram.\n\n"
        "Large files work best when the local Telegram Bot API is configured with "
        "TELEGRAM_API_ID and TELEGRAM_API_HASH.",
        parse_mode="Markdown",
    )


async def edit_status(message, text: str):
    try:
        await message.edit_text(text[:4000])
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


async def fetch_direct(url: str, dest: Path, status) -> Path:
    headers = {"User-Agent": "Mozilla/5.0 telegram-media-bot/1.0"}
    timeout = httpx.Timeout(DIRECT_TIMEOUT, connect=60.0)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout, headers=headers) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0) or None
            if total and total > MAX_FILE_SIZE:
                raise RuntimeError(f"File is {human_size(total)}, larger than the {human_size(MAX_FILE_SIZE)} limit.")

            cd_name = response.headers.get("content-disposition", "")
            filename = dest.name
            if "filename=" in cd_name:
                filename = cd_name.split("filename=", 1)[1].strip('"; ')
                dest = dest.with_name(safe_filename(filename, dest.name))

            downloaded = 0
            last_update = 0.0
            async with aiofiles.open(dest, "wb") as f:
                async for chunk in response.aiter_bytes(1 << 20):
                    downloaded += len(chunk)
                    if downloaded > MAX_FILE_SIZE:
                        raise RuntimeError(f"Download exceeded the {human_size(MAX_FILE_SIZE)} limit.")
                    await f.write(chunk)
                    if time.monotonic() - last_update > 8:
                        last_update = time.monotonic()
                        await edit_status(status, f"⏳ Downloading direct file... {human_size(downloaded)} / {human_size(total)}")
    return dest


async def fetch_with_ytdlp(url: str, dest_dir: Path, status) -> list[Path]:
    out_template = str(dest_dir / "%(title).180B [%(id)s].%(ext)s")
    cmd = [
        "yt-dlp", "--no-warnings", "--no-playlist", "--newline", "--no-mtime",
        "--concurrent-fragments", os.environ.get("YTDLP_FRAGMENTS", "6"),
        "--retries", "8", "--fragment-retries", "8", "--socket-timeout", "30",
        "--merge-output-format", "mp4", "--max-filesize", str(MAX_FILE_SIZE),
        "--format", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[ext=mp4]/b",
        "--output", out_template,
    ]
    cookies_file = Path(os.environ.get("COOKIES_FILE", "/app/cookies.txt"))
    if cookies_file.exists() and cookies_file.stat().st_size > 0:
        cmd.extend(["--cookies", str(cookies_file)])
    cmd.append(url)

    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    output: list[str] = []
    last_update = 0.0
    try:
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=YTDLP_TIMEOUT)
            if not line:
                break
            text = line.decode(errors="replace").strip()
            output.append(text)
            if len(output) > 80:
                output.pop(0)
            if time.monotonic() - last_update > 6 and text:
                last_update = time.monotonic()
                await edit_status(status, f"⏳ yt-dlp: {text[-250:]}")
        rc = await proc.wait()
    except asyncio.TimeoutError as exc:
        proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()
        raise RuntimeError("Download timed out while waiting for yt-dlp output.") from exc

    if rc != 0:
        raise RuntimeError("yt-dlp failed:\n" + "\n".join(output[-12:]))
    files = [p for p in dest_dir.iterdir() if p.is_file() and p.stat().st_size > 0]
    too_large = [p.name for p in files if p.stat().st_size > MAX_FILE_SIZE]
    if too_large:
        raise RuntimeError(f"Downloaded file is larger than {human_size(MAX_FILE_SIZE)}: {too_large[0]}")
    return files


def classify(path: Path):
    ext = path.suffix.lower()
    for kind, exts in MEDIA_EXTS.items():
        if ext in exts:
            return kind
    return "document"


async def send_file(update: Update, path: Path):
    kind = classify(path)
    caption = path.name[:1024]
    try:
        with path.open("rb") as fh:
            if kind == "photo" and path.stat().st_size <= 10 * 1024 * 1024:
                await update.message.reply_photo(photo=fh, caption=caption)
            elif kind == "video":
                await update.message.reply_video(video=fh, caption=caption, supports_streaming=True, read_timeout=1800, write_timeout=1800)
            elif kind == "audio":
                await update.message.reply_audio(audio=fh, caption=caption, read_timeout=1800, write_timeout=1800)
            else:
                await update.message.reply_document(document=fh, caption=caption, read_timeout=1800, write_timeout=1800)
    except (TimedOut, NetworkError) as exc:
        raise RuntimeError(f"Telegram upload failed for {path.name}: {exc}") from exc


async def handle_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    url = extract_url(update.message.text)
    if not url:
        await update.message.reply_text("Please send a valid http:// or https:// link.")
        return
    user = update.message.from_user
    log.info("User %s requested URL: %s", user.id if user else "unknown", url)
    status = await update.message.reply_text("⏳ Queued. I will download your file shortly...")

    async with sem:
        tmp_dir = DOWNLOAD_DIR / f"{update.update_id}-{uuid.uuid4().hex[:8]}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        ping_task = asyncio.create_task(_keep_pinging(update))
        try:
            await edit_status(status, "⏳ Downloading... Please wait.")
            if looks_like_direct_file(url):
                name = safe_filename(Path(urlparse(url).path).name, "download.bin")
                files = [await fetch_direct(url, tmp_dir / name, status)]
            else:
                files = await fetch_with_ytdlp(url, tmp_dir, status)
            if not files:
                await edit_status(status, "⚠️ No downloadable media found.")
                return
            await edit_status(status, f"📤 Uploading {len(files)} file(s) to Telegram...")
            for f in sorted(files, key=lambda p: p.stat().st_size, reverse=True):
                await update.message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
                await send_file(update, f)
            await status.delete()
        except Exception as e:
            log.exception("Task failed")
            await edit_status(status, f"❌ Error: {e}")
        finally:
            ping_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ping_task
            shutil.rmtree(tmp_dir, ignore_errors=True)


async def _keep_pinging(update: Update):
    try:
        while True:
            await update.message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass
    except Exception:
        log.exception("Telegram chat action ping task stopped unexpectedly")


def build_app() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is required")
    return (
        Application.builder().token(BOT_TOKEN).base_url(BOT_API_URL).base_file_url(BOT_API_FILE_URL)
        .local_mode(True).read_timeout(1800).write_timeout(1800).connect_timeout(60).pool_timeout(60).build()
    )


def main():
    app = build_app()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    log.info("Bot initialized with downloads=%s, max_file_size=%s, concurrency=%s", DOWNLOAD_DIR, human_size(MAX_FILE_SIZE), CONCURRENCY)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
