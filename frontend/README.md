# Admin dashboard

The admin dashboard is a private operational interface for understanding and
managing the Telegram downloader.

## Dashboard areas

- Usage: visual trends for downloads, AI processing, users, and referrals.
- Activity: searchable and paginated bot activity.
- Users: account balances, referral status, AI usage, and access controls.
- Credits: earned, spent, reserved, and available credits.
- Transactions: a separate searchable audit-log table.
- Broadcast: controlled communication with bot users.
- Settings: runtime controls for launch limits and product experiments.

## Interface principles

The dashboard separates visual trends from dense transaction records so each
screen remains easy to scan. Sensitive backend credentials stay server-side,
and manual account changes require an audit reason.
