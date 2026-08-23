# Downloader admin dashboard

This is a separate Next.js service for private bot-activity monitoring and
controlled bot messaging. It intentionally shows Telegram usernames/display
names and activity metadata, but never renders Telegram numeric user IDs.

Available pages are Activity (`/`), Broadcast (`/broadcast`), and Message user
(`/message`). The latter two use authenticated server-side proxy routes, so the
Telegram bot token and backend API token never reach the browser.

## Run locally

```bash
npm install
cp .env.example .env.local
# set ADMIN_DASHBOARD_TOKEN in .env.local
npm run dev
```

Open `http://localhost:3000`. To preview the UI without a bot API, set `DASHBOARD_DEMO=true`; demo mode is opt-in and clearly labelled.

For Railway, deploy `frontend` as its own service with the service root set to
`frontend`. Set `ADMIN_DASHBOARD_TOKEN`, `ADMIN_API_URL`, and
`ADMIN_API_TOKEN` as Railway Variables. The backend service should use
`backend` as its service root. Do not copy the backend `.env` into the
frontend service.

## Production variables

- `ADMIN_DASHBOARD_TOKEN`: long random secret used for the dashboard login.
- `ADMIN_SESSION_SECRET`: optional separate secret used to sign the HTTP-only session cookie.
- `ADMIN_API_URL`: server-only URL of the bot's activity API.
- `ADMIN_ACTIVITY_PATH`: optional API path, default `/admin/activity`.
- `ADMIN_API_TOKEN`: server-only bearer token for the activity API.

The backend exposes a protected PostgreSQL-backed activity API. The frontend
uses `GET /admin/activity` to load activity and `DELETE /admin/activity` to
remove explicitly selected event IDs. The dashboard requires confirmation
before deleting logs and never sends the backend token to the browser.

The frontend expects `GET /admin/activity` to return:

```json
{
  "events": [{
    "id": "event-id",
    "telegramUsername": "@name",
    "telegramDisplayName": "Name",
    "sourceUrl": "https://...",
    "title": "Video title",
    "platform": "youtube",
    "action": "download",
    "format": "1080p",
    "status": "completed",
    "delivery": "r2",
    "sizeBytes": 123,
    "durationMs": 1200,
    "error": null,
    "createdAt": "2026-08-22T12:00:00Z"
  }],
  "summary": { "total": 1, "completed": 1, "failed": 0, "activeUsers": 1, "totalBytes": 123 },
  "page": 1,
  "pageSize": 25,
  "total": 1
}
```

Do not put bot tokens, R2 secrets, database credentials, or admin API tokens in any `NEXT_PUBLIC_*` variable. The browser only talks to the authenticated Next.js routes.

The login endpoint applies a per-instance failed-attempt throttle and supports
an optional 30-day remembered-device session. Keep the
dashboard private behind Railway access controls or a private network where
possible; the dashboard token and backend API token must remain different,
long random secrets.
