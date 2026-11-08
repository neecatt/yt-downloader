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

## YouTube access checks

The bgutil container and the Python plugin installed in the bot and transcription
workers must use the same version. This repository pins the plugin to `2.0.2`;
deploy `brainicism/bgutil-ytdlp-pot-provider:2.0.2` alongside it. Rebuild the bot
and workers after updating `requirements.txt`. Updating only the provider to
`2.x` leaves the old `1.x` plugin unable to request tokens.

Set `YTDLP_POT_PROVIDER_URL` in both bot and worker services to the provider's
private HTTP address on port `4416`. Keep the provider accessible only inside
the deployment network. Leave `YTDLP_PLAYER_CLIENT` blank to try `mweb`, `tv`,
and `web_safari`; forcing only `mweb` can fail a login check before requesting
any token. Explicit client overrides are preserved.

When a provider URL is configured, the bot sets `youtube:fetch_pot=always`.
yt-dlp's default `auto` policy can skip player tokens for clients it considers
not to require them. YouTube can then reject the player request before yt-dlp
reaches GVS token generation. `always` requests tokens automatically for those
contexts too, while retaining the provider's caching and renewal. This setting
is shared by analysis, downloads, and transcription workers.

The bot logs sanitized provider warnings (including version mismatches and
connection errors). `event=ytdlp_po_token_requested` means the HTTP provider
flow was reached; it does not confirm token generation succeeded. See the
provider logs for generation failures. These diagnostics apply to metadata
analysis and downloads, including transcription downloads.

A PO token does not resolve every server IP or account restriction, and bgutil
does not renew Google account cookies. If sign-in is still required, first
check whether the provider was reached and successfully generated a token.
If it did, compare the same configuration from another network to investigate
server IP restrictions before changing credentials. Account cookies, when
needed, must follow
[yt-dlp's YouTube cookie instructions](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies).
Base64 cookies take precedence over `YTDLP_COOKIES_FILE`. An unexpired cookie
file can still contain a revoked or rotated session. Never commit cookie
exports or paste their contents into logs.

See also [bgutil's verification guide](https://github.com/Brainicism/bgutil-ytdlp-pot-provider#verification).
