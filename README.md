# Telegram video downloader bot

This bot uses `yt-dlp` and `ffmpeg` to download one video at a time per chat
and send it back through Telegram. It supports YouTube and TikTok links sent
as messages, plus any HTTPS source supported by yt-dlp through `/download`.

## Run locally

```sh
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN='your-token-from-botfather'
python yt_downloader_bot.py
```

Run the automated suite with:

```sh
TELEGRAM_BOT_TOKEN=test-token python -m unittest discover -s tests -v
```

`ffmpeg` must be installed and available on `PATH` for MP3 conversion and
separate video/audio streams. Current yt-dlp YouTube extraction also benefits
from the `yt-dlp[default]` extra and a JavaScript runtime. On macOS, install
Node.js with `brew install node`, then set `YTDLP_JS_RUNTIME=node` in `.env`.
The Docker image includes Node.js automatically.

Useful optional settings are:

- `TELEGRAM_MAX_UPLOAD_MB` (default `49`)
- `MAX_DOWNLOAD_MB` (default `2048`)
- `DOWNLOAD_WORKERS` (default `2`)
- `FRAGMENT_WORKERS` (default `4`)
- `HTTP_CHUNK_SIZE_MB` (default `10`, used automatically after a 403)
- `R2_UPLOAD_CONCURRENCY` (default `8`)
- `CALLBACK_STATE_TTL_SECONDS` (default `1800`)
- `YTDLP_COOKIES_FILE` (Netscape-format YouTube cookies, only when needed)
- `YTDLP_PROXY` (HTTP proxy, only when needed)
- `YTDLP_PLAYER_CLIENT` and `YTDLP_PO_TOKEN` (advanced YouTube access)

The hosted Telegram Bot API accepts bot uploads up to 50 MB. Increasing
`TELEGRAM_MAX_UPLOAD_MB` alone cannot change that server-side limit. For files
up to 2 GB, run Telegram's Local Bot API Server in `--local` mode and set:

```env
TELEGRAM_MAX_UPLOAD_MB=2000
TELEGRAM_API_BASE_URL=http://127.0.0.1:8081/bot
TELEGRAM_API_FILE_BASE_URL=http://127.0.0.1:8081/file/bot
```

The Local Bot API Server must be reachable from the bot process. Do not run
both the hosted and local API endpoints with the same bot at the same time;
stop the existing bot before switching endpoints.

## Recommended large-file delivery: Cloudflare R2

Set `DELIVERY_MODE=r2` and fill in the R2 values in `.env`. The bot will
download into temporary disk, upload the completed file to R2, and send the
phone an expiring HTTPS button. Telegram never receives the media itself.

Use an R2 API token with permission to read and write only the selected
bucket. The simplified configuration needs only the account ID, bucket name,
and one combined secret value:

```env
R2_ACCOUNT_ID=your-account-id
R2_BUCKET_NAME=your-bucket-name
R2_API_TOKEN=ACCESS_KEY_ID:SECRET_ACCESS_KEY
```

Cloudflare displays the API token as an Access Key ID and Secret Access Key;
put them together with one colon in `R2_API_TOKEN`. Do not send the secret
value in chat or commit it.

Configure an R2 lifecycle rule to delete objects under `downloads/` after a
short retention period (for example, one day); an expiring URL does not delete
the object automatically. `DELIVERY_MODE=auto` keeps Telegram delivery as a
fallback when R2 is not configured.

The bot deliberately rejects files above the configured upload limit instead
of splitting raw bytes, because arbitrary byte chunks are not valid media
parts. Ask the user to choose a lower quality or MP3 instead.

During processing, the bot reports download percentage, a progress bar,
transfer speed, and ETA. It also reports merging/conversion and Telegram
upload as separate stages. The Telegram upload stage has no byte-level
percentage because the Bot API does not expose a reliable upload callback.

## Deploy with Docker

```sh
docker build -t yt-downloader .
docker run --rm -e TELEGRAM_BOT_TOKEN='your-token' yt-downloader
```

For Fly.io, keep credentials out of `fly.toml` and set them as secrets:

```sh
fly secrets set \
  TELEGRAM_BOT_TOKEN='your-token' \
  DELIVERY_MODE='r2' \
  R2_ENDPOINT_URL='https://your-account-id.r2.cloudflarestorage.com' \
  R2_ACCESS_KEY_ID='your-access-key-id' \
  R2_SECRET_ACCESS_KEY='your-secret-access-key' \
  R2_BUCKET_NAME='your-bucket-name'
fly deploy
```

Never commit the bot token. If the old token was ever active, revoke it in
BotFather and issue a new one.

For restricted or bot-challenged videos, use a supported JavaScript runtime
first. Cookies should only be used for content your account is authorized to
access, and should never be committed or copied into a public deployment.
