# Telegram bounded ingestion security

This control set is mandatory before Telegram file handling can be considered production-ready.

## Runtime posture

Production remains fail-closed:

```env
TELEGRAM_BOT_ENABLED=false
TELEGRAM_BOT_PRODUCTION_READY=false
TELEGRAM_ALLOW_GROUP_CHATS=false
```

The bounded ingestion stage does not authorize enabling the bot. Secret-store, SSRF/egress, and remaining deployment controls must still be completed.

## Pre-download validation

Every document or photo must provide all of the following in the Telegram message before it can enter the queue:

- an authorized Telegram user/chat binding;
- current `upload_documents` and `create_entries` permissions;
- a valid Telegram `file_id`;
- a sanitized `.pdf`, `.png`, `.jpg`, `.jpeg`, or `.webp` filename;
- a positive declared `file_size` no greater than `MAX_UPLOAD_SIZE_MB`;
- a message timestamp within `TELEGRAM_MESSAGE_MAX_AGE_SECONDS`.

The worker calls `getFile` and requires a second positive file size equal to the message size. A missing or changed size fails closed before download.

## Telegram URL and path rules

The application constructs file URLs itself. It never accepts a URL from an update.

- scheme must be HTTPS;
- final hostname after redirects must be exactly `api.telegram.org`;
- API paths must begin with `/bot`;
- file paths must begin with `/file/bot` after local construction;
- Telegram's returned `file_path` must be a relative POSIX path;
- absolute paths, `..`, backslashes, encoded percent sequences, duplicate separators, query strings, and external hosts are rejected.

Tokens and full download URLs must never be logged.

## Bounded streaming

Downloads use a random destination name beneath `storage/telegram_uploads` and a random `.part` file.

- response `Content-Length`, when present, must equal the expected Telegram size;
- each chunk is counted before writing;
- streaming stops immediately when the declared or global maximum is crossed;
- the temporary file is flushed and `fsync` is called;
- only an exact-size download is atomically renamed to the final file;
- temporary and destination files are removed on every failure;
- directory and file permissions are restricted where the operating system supports them.

After download and before OCR, the file is scanned by ClamAV and validated against its declared content type, PDF limits, and image limits.

## Fixed worker queue

No upload creates a new thread. The polling thread submits jobs to one bounded `queue.Queue` served by a fixed number of workers.

Default production limits:

```env
TELEGRAM_INGESTION_WORKERS=2
TELEGRAM_INGESTION_QUEUE_SIZE=20
TELEGRAM_MAX_PENDING_PER_ACTOR=1
TELEGRAM_MAX_PENDING_PER_ORGANIZATION=5
TELEGRAM_UPLOAD_RATE_LIMIT=5
TELEGRAM_UPLOAD_RATE_WINDOW_SECONDS=60
TELEGRAM_INGESTION_JOB_TTL_SECONDS=300
TELEGRAM_DOWNLOAD_TIMEOUT_SECONDS=30
TELEGRAM_DOWNLOAD_CHUNK_SIZE_BYTES=65536
TELEGRAM_API_RESPONSE_MAX_BYTES=1048576
```

A job that waits longer than its TTL is discarded without download or parsing. Worker exceptions always release actor and organization counters. Shutdown drains queued jobs and audits the discard.

## Cleanup

- failed or rejected ingestion removes local temporary/final files in `finally`;
- a successfully delivered approval retains its file only until a terminal approval state;
- overdue approvals are changed from `pending` to `expired` by periodic cleanup and their retained files are deleted;
- stale `.part` files are removed by maintenance;
- runtime stop and emergency disable clear queued ingestion and revoke outstanding approvals.

## Administrative status

`GET /api/v1/telegram/runtime-status` exposes only secret-free queue information:

- queue depth and capacity;
- configured and live worker counts;
- active actor and organization counts;
- pending durable approval count.

## Required CI gates

CI must fail if:

- `urlretrieve` returns to `telegram_bot.py`;
- a document thread targets `process_document`;
- direct Telegram document processing or download becomes callable;
- fixed queue, stream byte ceiling, malware scan, content validation, actor/organization limits, rate limits, TTL, atomic rename, or `fsync` controls disappear;
- Compose contains out-of-range ingestion limits.

The dedicated test suite is `backend/tests/test_telegram_ingestion_security.py`.
