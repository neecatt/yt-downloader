# Telegram media downloader

A Telegram bot for downloading video and audio from popular social platforms,
with a separate admin dashboard for activity and messaging management.

## Highlights

- YouTube, TikTok, Instagram, and Facebook downloads.
- Video quality selection and MP3 output.
- Progress updates while media is being processed.
- Telegram delivery for smaller files and cloud links for larger files.
- Automatic cleanup of temporary cloud files.
- Private admin dashboard with activity review and bot messaging pages.

## Repository layout

```text
backend/   Telegram bot, admin API, storage integration, and tests
frontend/  Next.js admin dashboard
```

## Development

Run the backend and frontend independently from their respective directories.
Each directory contains a short README with its local development commands.

Keep deployment credentials and service configuration in the hosting
environment. They should not be committed to the repository.
