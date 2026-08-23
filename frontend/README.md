# Downloader admin dashboard

The frontend is a separate Next.js application for managing the downloader.
It provides a private view of bot activity and controlled messaging tools.

## Pages

- Activity — review download history and remove selected logs.
- Broadcast — send a message to recorded private bot contacts.
- Message user — send a message to a specific Telegram username.

## Project structure

- `app/` — pages and server-side API routes.
- `components/` — dashboard, navigation, login, and messaging interfaces.
- `lib/` — authentication, activity, and backend service helpers.

## Local development

```sh
npm install
npm run dev
```

Open `http://localhost:3000` after configuring the dashboard environment for
your local backend. Production deployments can run this directory as a
separate service from the backend.

The dashboard keeps backend credentials on the server and uses authenticated
sessions for browser access.
