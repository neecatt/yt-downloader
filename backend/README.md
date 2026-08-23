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

- `main.py` — application entry point and Telegram handlers.
- `bot/` — storage, security, media, cookies, limits, and admin API modules.
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
