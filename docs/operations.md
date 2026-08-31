# Operational & Observability Documentation — YAMASEE Platform

## 1. Overview & Operational Architecture

The YAMASEE platform is designed as a single-worker Python/FastAPI enterprise video and audio strategic analysis application backed by SQLite (WAL mode) and local filesystem storage.

### Core Stack
- **Framework**: FastAPI (Single-worker deployment model)
- **Database**: SQLite with Write-Ahead Logging (`journal_mode=WAL`) & SQLAlchemy ORM
- **Task Processing**: Process-in-memory `JOBS_DATA` registry & FastAPI `BackgroundTasks`
- **Subprocess Utilities**: `yt-dlp`, `ffmpeg`, `ffprobe`
- **AI Analytics**: Gemini Multi-Model Dynamic Loop Engine & Faster-Whisper

---

## 2. Structured Logging

All operational log messages use standard Python `logging` with structured JSON output via `StructuredFormatter`.

### Log Structure
Every log entry contains the following standard fields:
- `timestamp`: ISO 8601 UTC timestamp.
- `level`: Log level (`INFO`, `WARNING`, `ERROR`, `DEBUG`, `CRITICAL`).
- `request_id`: Request correlation ID flow.
- `job_id`: Background job identifier (or `-` if N/A).
- `user_id`: Authenticated user ID (or `-` if unauthenticated).
- `component`: Subsystem identifier (`api`, `pipeline`, `auth`, `history`, `audit_trail`).
- `stage`: Current processing pipeline stage (`queued`, `download`, `extract`, `transcribe`, `analysis`, `persist`, `completed`, `failed`).
- `message`: Sanitized log text.
- `error_category`: Operational error category (when logging exceptions).

### Redaction Policy
Log sanitization automatically redacts sensitive data before writing to stdout or `logs/app.log`:
- Session secrets & `APP_SECRET_KEY`
- API keys (`GEMINI_API_KEY`, Bearer tokens)
- User credentials & passwords
- Raw AI prompts & full speech transcripts
- Authorization headers & cookie values

---

## 3. Request Correlation (`X-Request-ID`)

Every incoming HTTP request is assigned a unique Request ID.
- If the client supplies a valid `X-Request-ID` header (alphanumeric/hyphens, length 8-64), it is preserved.
- Otherwise, a server-side UUID (`req_<hex>`) is generated.
- The `X-Request-ID` header is attached to all HTTP responses.
- The Request ID is propagated via ContextVars (`request_id_ctx`) across background processing tasks, history queries, retry execution, and log lines.

---

## 4. Health Diagnostics Endpoint (`/health`)

- **Method**: `GET /health`
- **Access**: Public / Load Balancer health checks
- **Response Format**:
```json
{
  "status": "ok",
  "database": "ok",
  "sqlite_wal": true,
  "migration_revision": "003_add_analysis_records",
  "temp_directory": "ok",
  "ffmpeg_availability": true,
  "ffprobe_availability": true,
  "application_version": "1.0.0",
  "uptime_seconds": 3600.25
}
```

---

## 5. Runtime Diagnostics Endpoint (`/diagnostics/runtime`)

- **Method**: `GET /diagnostics/runtime`
- **Access**: Development Environment Only (`APP_ENV=development`). In production, returns `403 Forbidden`.
- **Response Format**:
```json
{
  "environment": "development",
  "active_jobs_count": 2,
  "terminal_jobs_count": 45,
  "idempotency_entries_count": 12,
  "last_cleanup_timestamp": 1789001234.5,
  "config_summary": {
    "app_env": "development",
    "session_https_only": false,
    "session_max_age_seconds": 604800,
    "job_terminal_ttl_seconds": 3600,
    "max_upload_bytes": 524288000
  },
  "jobs_summary": { ... }
}
```

---

## 6. Version Endpoint (`/version`)

- **Method**: `GET /version`
- **Access**: Public
- **Response Format**:
```json
{
  "application_version": "1.0.0",
  "git_revision": "a1b2c3d",
  "alembic_revision": "003_add_analysis_records",
  "build_timestamp": "2026-07-20T17:55:00Z",
  "python_version": "3.14.5"
}
```

---

## 7. Operational Metrics (`/metrics` & `/diagnostics/metrics`)

- **Method**: `GET /metrics`
- **Access**: Monitoring / Operational Scrape
- **Monitored Counters & Gauges**:
  - `jobs_running`: Active jobs currently queued or processing.
  - `jobs_completed`: Total successfully completed jobs.
  - `jobs_failed`: Total failed jobs.
  - `retry_count`: Number of job retries executed.
  - `cache_hits`: Analysis cache hit count.
  - `cache_misses`: Analysis cache miss count.
  - `http_413_count`: 413 Payload Too Large responses.
  - `http_415_count`: 415 Unsupported Media Type responses.
  - `http_429_count`: 429 Rate Limit responses.
  - Averages: `avg_processing_time_seconds`, `avg_download_time_seconds`, `avg_transcription_time_seconds`, `avg_ai_analysis_time_seconds`.

---

## 8. Audit Trail Policy

Security and business events are logged to the structured log (`component="audit_trail"`) and kept in a bounded in-memory buffer (`MAX_AUDIT_LOGS = 1000`).

### Audited Events
- `login`: User login attempt & success.
- `logout`: User session termination.
- `analysis_submission`: New video/audio submission.
- `retry`: Analysis retry execution.
- `rename`: History record display title modification.
- `pin`: Record pin/unpin status toggle.
- `delete`: History record deletion.
- `download`: TXT/PDF report generation & export.

### Excluded Audit Payload
Prompts, raw transcripts, result JSON blobs, secret keys, passwords, and tokens are strictly excluded from audit payloads.

---

## 9. Error Classification

Errors are classified into standard categories:
- `DOWNLOAD_ERROR`: Media download or `yt-dlp` failures.
- `FFMPEG_ERROR`: Media remuxing, audio conversion, or timebase issues.
- `FFPROBE_ERROR`: Media metadata probe failures.
- `TRANSCRIPTION_ERROR`: Speech-to-Text Whisper/VAD failures.
- `AI_PROVIDER_ERROR`: Gemini model API or output generation failures.
- `JSON_PARSE_ERROR`: Structural JSON decoding errors.
- `DATABASE_ERROR`: SQLite database or SQLAlchemy query errors.
- `FILESYSTEM_ERROR`: Storage, permission, or missing file errors.
- `VALIDATION_ERROR`: Input parameters, file type, or size validation errors.
- `SECURITY_ERROR`: Authentication, CSRF/same-origin, or ownership access violations.
- `TIMEOUT_ERROR`: Subprocess or network call timeouts.

---

## 10. Operational Limitations & Known Residual Risks

1. **Process-Local Idempotency**:
   - Idempotency reservations are stored in worker memory. In multi-worker or restarted environments, idempotency keys do not sync across instances.
2. **Single-Worker Deployment**:
   - The application relies on single-worker execution for `JOBS_DATA` in-memory state consistency.
3. **Cross-User Cache Stampede for Uncached Sources**:
   - Concurrent requests for identical uncached video URLs by different users will initiate parallel downloads before cache registration completes.

---

## 11. Troubleshooting & Recovery Steps

### High Memory Usage / Stuck Background Tasks
- Check `/diagnostics/runtime` for active jobs count.
- If background tasks hang due to subprocess timeouts, inspect `logs/app.log` for `TIMEOUT_ERROR` or `FFMPEG_ERROR`.
- Restart the service instance. In-memory `JOBS_DATA` will clear, while persisted history records in SQLite & `analysis_history/` remain intact.

### Database Lock / WAL Recovery
- If SQLite database becomes locked, verify WAL mode status via `/health`.
- If database file is corrupted, run `alembic upgrade head` to re-apply schema on a clean database file.

### Disk Storage Exhaustion
- Inspect `cache/` directory size.
- If `KEEP_MEDIA_FILES=false`, temporary media files are automatically removed upon processing completion. Run manual purge of `cache/*.mp4` and `cache/*.wav` if necessary.
