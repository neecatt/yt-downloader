# Telegram Media Downloader

A production-oriented Telegram bot for downloading media, extracting audio,
and transforming long-form content into high-value transcripts and summaries.

The project is designed around a simple user experience: users send a link,
choose what they need, and receive clear progress updates until the result is
ready.

## Product capabilities

- Video and MP3 downloads from major social platforms.
- Quality selection and media-format conversion.
- Progress updates for queued and active work.
- Large-file delivery through temporary cloud links.
- AI-powered speech transcription with automatic language detection.
- Multilingual transcription for English, Azerbaijani, and Russian content.
- Clean, timestamped transcripts that make long videos easy to search and
  revisit.
- AI summaries that turn lengthy content into a fast overview and actionable
  key takeaways.
- A dedicated summary flow that delivers the insight without forcing users to
  read the full transcript first.
- English, Azerbaijani, and Russian user-facing flows.
- Credit balances, referrals, and configurable usage limits.
- Feedback collection and operational activity tracking.

## Admin experience

The private admin dashboard gives a clear view of product usage without mixing
analytics with audit data:

- Usage dashboard with charts for downloads, AI usage, users, and referrals.
- Activity history with search, filters, and pagination.
- User management with credit and entitlement controls.
- Referral and credit performance views.
- Separate transaction and audit-log table.
- Broadcast and individual user messaging.
- Runtime product settings for launch experiments and abuse prevention.

## Engineering highlights

- Modular Telegram handlers, delivery workflows, background workers, and
  persistence services.
- Clear separation of concerns with bounded responsibilities across the
  transport, application, domain, and infrastructure layers.
- Dependency inversion around external providers so media extraction, object
  storage, AI inference, and messaging remain replaceable integrations.
- PostgreSQL-backed user accounts, activity, credit ledger, referrals, and
  job state.
- Explicit state transitions for queued, processing, completed, failed, and
  retrying work rather than relying on implicit control flow.
- Atomic credit reservations that remain safe across retries and duplicate
  worker deliveries.
- Idempotent command handling designed for at-least-once message delivery,
  including duplicate callbacks, retries, and concurrent requests.
- Retry-aware transcription jobs that remain visible to users instead of
  silently disappearing from the queue.
- Dedicated AI processing workflows for long-form audio and video, with queue
  progress, language detection, retry handling, and cost-aware limits.
- Idempotent referral rewards and durable transaction history.
- Configurable rate limits and global capacity protection.
- Temporary media links with cleanup after delivery.
- Protected admin API and server-side dashboard authentication.
- Defense-in-depth controls combining input validation, authorization, rate
  limiting, bounded resource usage, and auditable administrative actions.
- Automated unit, integration, type, build, and compile validation.

## Launch model

The initial launch keeps downloads free and uses credits for AI-heavy work.
Users receive starter credits and can earn more through successful referrals.
Premium payments remain disabled while usage, infrastructure cost, and feature
demand are measured. Product settings are intentionally configurable so the
launch can evolve without rewriting business logic.

## Current direction

The project prioritizes fast interactions, understandable feedback, reliable
background processing, and responsible usage controls. The architecture is
prepared for future subscription and payment experiments, while the current
release remains focused on validating real usage and operating costs.
