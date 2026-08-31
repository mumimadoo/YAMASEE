# Production Readiness & Deployment Safety Guide (YAMASEE)

## 1. Overview
This document specifies the deployment parameters, security controls, and operational guidelines required to run the YAMASEE AI Video Analysis Application safely in production.

---

## 2. Server & Environment Configuration
### Application Environment (`APP_ENV`)
- Set `APP_ENV=production` in the production `.env` file or process environment.
- Setting `APP_ENV=production` enforces `FastAPI(debug=False)` and enables strict secret key validation.

### Secret Key Security (`APP_SECRET_KEY`)
- Must be set to a secure, randomly generated string of at least 32 characters (e.g., generated via `openssl rand -hex 32`).
- Missing or short (< 32 chars) `APP_SECRET_KEY` in production mode causes the application to fail fast at startup (`ValueError`).

### Single Worker Requirement
- **Requirement**: Run Uvicorn with `--workers 1`.
- **Rationale**: The application uses SQLite in WAL mode and background tasks. Running multiple Uvicorn workers without an external database or process coordinator can cause database locking and state inconsistency.

---

## 3. Web Server & Reverse Proxy Setup (Nginx)
### Request Body Size Limit (HTTP 413)
- Application-level HTTP 413 request size enforcement is implemented via `RequestSizeLimitMiddleware` (configured via `MAX_UPLOAD_BYTES`, default 2 GB + 10 MiB overhead).
- Enforce max upload size (e.g. 2060 MB) at the Nginx reverse proxy level:
  ```nginx
  client_max_body_size 2060M;
  ```

### Security Headers & HTTPS
- Application includes basic security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`).
- HTTPS termination should be handled by Nginx or Cloudflare with `Strict-Transport-Security` enabled.

---

## 4. Database (SQLite) Production Parameters
- **Busy Timeout**: Configured to `5000` ms to handle temporary write locks.
- **Journal Mode**: Configured to `WAL` (Write-Ahead Logging) for concurrent read performance.
- **Foreign Keys**: Enforced on every connection (`PRAGMA foreign_keys=ON`).

---

## 5. Health Monitoring
- Endpoint: `GET /health`
- Response:
  - `200 OK`: Database connected (`{"status": "healthy", "database": "connected"}`)
  - `503 Service Unavailable`: Database unreachable (`{"status": "unhealthy", "database": "disconnected"}`)

---

## 6. Open Hardening Items for RC-3
- **ASGI Upload Size Middleware (HTTP 413)**
- **Strict Content-Type Validation Middleware (HTTP 415)**
- **Subprocess Execution Timeouts (ffmpeg/ffprobe)**
