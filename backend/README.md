# Downloader backend

The backend powers the Telegram bot, media-processing workflows, AI
transcription and summarization jobs, cloud delivery, and protected admin API.

## Responsibilities

- Accept and validate links from supported media platforms.
- Coordinate downloads, format conversion, and delivery.
- Report progress and recover gracefully from temporary failures.
- Queue transcription and summarization work for background processing.
- Detect source language and produce readable, timestamped transcripts.
- Convert long-form content into concise summaries with clear overviews and key
  takeaways.
- Track users, activity, jobs, credits, referrals, and feedback.
- Enforce per-user and global capacity limits.
- Provide authenticated data and management endpoints for the dashboard.

## Design principles

The backend follows separation of concerns and dependency inversion: Telegram
presentation, application workflows, domain rules, and infrastructure
providers remain independently testable. External systems such as media
extractors, object storage, AI inference, and messaging are treated as
replaceable adapters rather than being woven through business logic.

Expensive work runs outside the request path, while PostgreSQL keeps important
user and job state durable across retries and deployments. Job processing uses
explicit state transitions so queue behavior is observable and recoverable.

Credit reservations, referral rewards, and worker callbacks are designed to be
atomic and idempotent. The system tolerates at-least-once delivery semantics:
failed work releases reserved resources, successful delivery settles the
operation, and duplicate callbacks do not create duplicate charges or rewards.

## Reliability and safety

- Retry-aware background jobs with visible queue state.
- Dedicated AI processing with progress feedback, language detection, and
  resilient retry handling.
- Durable audit history for credit and entitlement changes.
- Protected admin operations with validation and authorization.
- Defense-in-depth security through validation, authorization, rate limiting,
  bounded resource usage, and audit trails.
- Temporary cloud links for large results with cleanup.
- Abuse controls for user, queue, and global capacity.
- Structured operational logging for important product events.
- Test coverage for normal flows, retries, concurrency, and failure paths.
