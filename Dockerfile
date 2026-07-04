FROM python:3.12-slim

# Install system dependencies including FFmpeg for merging audio/video
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Always pull the absolute latest yt-dlp to bypass platform changes
RUN pip install --no-cache-dir -U yt-dlp

COPY bot.py .

CMD ["python", "-u", "bot.py"]
