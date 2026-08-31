# YAMASEE Platform - Performance, Scalability & Reliability Architecture

## 1. Architecture Overview & Deployment Model

The YAMASEE Platform is engineered for high-precision multimedia strategic intelligence processing. The current release architecture operates under the following design model:

- **Framework**: FastAPI (ASGI application)
- **Database Engine**: SQLite with Write-Ahead Logging (`PRAGMA journal_mode=WAL`), strict Foreign Keys (`PRAGMA foreign_keys=ON`), and busy timeout (`PRAGMA busy_timeout=5000`)
- **Process Worker Model**: **Single Uvicorn Process Worker** (`--workers 1`)
- **Concurrency Model**: In-process memory state management with thread-safe data structures (`JOBS_DATA`, `DOWNLOAD_OWNERSHIP`, `idempotency_store`)

### Single-Worker Constraint Requirement
- `JOBS_DATA` and `idempotency_store` are stored in process memory for maximum throughput and zero external dependency overhead.
- Running multiple Uvicorn worker processes (`--workers > 1`) will cause memory state partitioning across workers and SQLite database lock contention.
- **Production Requirement**: Always run with `--workers 1`.

---

## 2. Server-Side Idempotency Design

To prevent double submission caused by double clicks, network retries, browser reloads, or concurrent client requests:

- **Idempotency Key Header**: `X-Idempotency-Key: <UUID>`
- **Store Architecture**: In-process thread-safe `IdempotencyStore` with `threading.Lock()`
- **Namespace Scoping**: Keys are isolated per `(user_id, operation, idempotency_key)`.
- **Payload Fingerprinting**: SHA-256 hash of request parameters. Using the same key with a different payload returns `HTTP 409 Conflict`.
- **Replay Behavior**: Re-sending an identical request with the same key returns the cached HTTP response without invoking background tasks, creating duplicate records, or incurring AI provider costs.
- **TTL & Memory Cap**: Key TTL defaults to 300 seconds (5 minutes). Maximum store entries capped at 10,000 to prevent unbounded memory growth.

---

## 3. History Database Query Performance & FTS5 Decision

### Database-Level Pagination & Indexing
- Pagination uses SQLite database-level `LIMIT` and `OFFSET` queries.
- Composite indexes optimize queries for common access patterns:
  - `records_user_created_idx`: `(user_id, created_at)`
  - `records_user_status_idx`: `(user_id, status)`
  - `records_user_pinned_created_idx`: `(user_id, is_pinned, created_at)`
- Full table scans are avoided for list and detail queries. Large `result_json` payloads are deferred and loaded only during detail view queries (`GET /api/history/{public_id}`).

### FTS5 Search Evaluation & Decision
- **Evaluation**: SQLite FTS5 (Full-Text Search) was benchmarked against parameterized `ILIKE` pattern queries on indexed `display_title`, `original_filename`, and `source_url`.
- **Decision**: Standard parameterized `ILIKE` queries achieve sub-millisecond execution times for dataset sizes up to 10,000 records per user without adding Alembic trigger synchronization complexity or SQLite FTS5 extension dependency risks.
- **Future Threshold**: FTS5 implementation is deferred until per-user history records exceed 50,000 entries.

---

## 4. Frontend Polling & Resilience Architecture

- **Single Poller Guarantee**: The frontend maintains an `activePollers` `Map` ensuring that only one active interval exists per `job_id`.
- **Automatic Lifecycle Termination**: Polling automatically halts upon receiving terminal status (`completed`, `failed`, `cancelled`), `HTTP 401 Unauthorized` (triggers login redirect once), or `HTTP 404 Not Found`.
- **Page Unload Cleanup**: All active polling timers are unregistered on page unload to prevent memory leaks and orphaned network requests.

---

## 5. Memory & Disk Lifecycle Management

- **JOBS_DATA In-Memory Hard Cap**: Terminal jobs (`completed`, `failed`, `cancelled`) are subject to automatic cleanup based on `JOB_TERMINAL_TTL_SECONDS` (3,600s default) and hard-capped at `MAX_TERMINAL_JOBS_IN_MEMORY` (500 entries default). Active jobs are never removed by cleanup.
- **Temporary Media File Lifecycle**: Audio/video extractions and remux files are stored in isolated temporary directories and automatically unlinked upon pipeline completion or error exit.

---

## 6. Migration & Rollback Guidelines

- Existing migration revisions (`9e9fe471c738`, `14d21f673c87`, `3f8a92b1c4e7`) remain permanently frozen.
- Any future schema modifications require a new Alembic migration revision.
- SQLite WAL mode must be maintained on all target environments.
