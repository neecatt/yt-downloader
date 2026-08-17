FROM python:3.12-slim

# Install ffmpeg (required by yt-dlp for audio/video processing)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg nodejs tini && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY yt_downloader_bot.py ./

# Do not run the bot as root, and flush logs immediately for deployment output.
RUN useradd --create-home --uid 10001 appuser && \
    chown -R appuser:appuser /app
USER appuser
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    YTDLP_JS_RUNTIME=node

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "yt_downloader_bot.py"]
