# Downloader backend

The backend runs the Telegram media downloader and its protected admin API.
It supports video and audio downloads from YouTube, TikTok, Instagram,
Facebook, X, and LinkedIn, with Telegram and cloud-storage delivery options.

## Features

- Quality selection and MP3 conversion.
- Download progress updates in Telegram.
- Automatic delivery selection for large files.
- Temporary cloud download links with cleanup.
- PostgreSQL-backed activity tracking.
- Protected admin endpoints for activity management and bot messaging.

## Project structure

- `main.py` — stable application entry point.
- `bot/config/` — typed environment-backed settings grouped by concern.
- `bot/runtime/` — Telegram callback state and delivery models.
- `bot/queue/` — Celery broker configuration and application queue client.
- `bot/platforms/` — platform media formatting, URL security, and rate limits.
- `bot/services/` — yt-dlp and object-storage application services.
- `bot/telegram/` — reusable Telegram presentation and keyboard helpers.
- `bot/persistence/` — PostgreSQL activity, conversation, feedback, and job storage.
- `bot/integrations/` — R2 cleanup, Modal transcription, and cookie integrations.
- `bot/api/` — protected admin API.
- `bot/transcription_tasks.py` — Celery transcription worker task.
- `tests/` — backend test suite.
- `Dockerfile` — container deployment configuration.

## Local development

From this directory, install the dependencies and provide the runtime settings
through your local environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Run the backend tests with:

```sh
python -m unittest discover -s tests -v
```

The application requires a Telegram bot token and the services selected for
your deployment, such as PostgreSQL or cloud storage. Keep those values in
your hosting provider's secret configuration rather than in the repository.

## Speech-to-text queue and Modal worker

Speech-to-text jobs use a dedicated Celery worker and private Redis broker.
PostgreSQL stores the durable job record used by the admin panel. Create a
second Railway service from this repository and set its start command to:

```sh
celery -A bot.transcription_tasks worker --loglevel=INFO --concurrency=1 -Q transcription
```

The bot and worker services must share the same Redis, database, Telegram, R2,
and Modal variables. Only an opaque job ID is sent through Redis; media bytes
and signed URLs are not placed in the queue.

Deploy the Modal GPU function separately:

```sh
modal deploy backend/modal_transcriber.py
```

Required queue variables:

- `REDIS_URL` — private Redis connection URL provided by Railway.
- `TRANSCRIPTION_QUEUE_ENABLED=true`.

Queue protection variables include `TRANSCRIPTION_QUEUE_MAX_SIZE` (default
100), `TRANSCRIPTION_QUEUE_MAX_PER_USER` (default 3),
`TRANSCRIPTION_ESTIMATED_SECONDS` (default 300),
`TRANSCRIPTION_MAX_RETRIES` (default 2), and
`CELERY_VISIBILITY_TIMEOUT_SECONDS` (default six hours). Keep the Celery
worker at `--concurrency=1` and Modal at one GPU container while controlling
costs is the priority.

The bot calculates queue position from PostgreSQL and estimates wait time from
completed transcription durations. The bot and worker must use the same
`DATABASE_URL`. If the worker logs `event=transcription_job_missing`, verify
that both Railway services point to the same PostgreSQL database, not only the
same Redis instance.

The format chooser also provides a separate summarize action. Summary jobs
use the same queue, generate the transcript and summary in Modal, then send the
summary followed by the complete timestamped transcript file. Configure the
Modal summary model with `SUMMARY_MODEL`; the default is a small instruct model
selected for lower latency.
