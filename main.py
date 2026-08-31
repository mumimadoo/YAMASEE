import sys
import os
import io
import re
import json
import time
import shutil
import subprocess
import hashlib
import difflib
import uuid
import datetime
from typing import Optional, Dict, Set, Any
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, Depends, HTTPException, Request, status, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles

# 📦 แกนประมวลผลยุทธศาสตร์หลักตามสถาปัตยกรรม Modular
from schemas.analysis_schemas import AnalyticsMetrics
from engines.video_engine import VideoEngine
from engines.audio_engine import AudioEngine
from engines.transcript_engine import TranscriptEngine
from engines.ai_analysis_engine import AIAnalysisEngine
from utils.logger import (
    get_logger, request_id_ctx, job_id_ctx, user_id_ctx,
    component_ctx, stage_ctx
)
from utils.origin_checker import verify_same_origin
from utils.error_classification import classify_error
from utils.metrics import metrics
from utils.audit import record_audit_event
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import or_, and_, text
from sqlalchemy.orm import Session
from database import SessionLocal, get_db
from models.analysis_record import AnalysisRecord
from models.analysis_cache import AnalysisCache
from models.user import User
from dependencies.auth import require_current_user_api
from starlette.middleware.sessions import SessionMiddleware
from config import settings
from routers.auth import router as auth_router
from routers.pages import router as pages_router
from routers.history import router as history_router
from routers.admin import router as admin_router
from routers.notifications import router as notifications_router
from routers.comparison import router as comparison_router

from utils.request_size_limiter import RequestSizeLimitMiddleware
from utils.url_validator import is_safe_url
from utils.idempotency import idempotency_store
from utils.gemini_model_policy import (
    GeminiRateLimitedError,
    RATE_LIMITED_MESSAGE,
    validate_primary_model,
)
from services.pre_run_estimator import pre_run_estimator
from services.duration_service import resolve_url_duration_async, find_cached_duration

SERVER_START_TIME = time.time()

app = FastAPI(debug=False)

app.add_middleware(RequestSizeLimitMiddleware)

@app.middleware("http")
async def request_correlation_middleware(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID")
    if not req_id or not re.match(r"^[A-Za-z0-9\-_]{8,64}$", req_id):
        req_id = f"req_{uuid.uuid4().hex[:16]}"

    request_id_ctx.set(req_id)
    request.state.request_id = req_id

    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id

        if response.status_code == 413:
            metrics.inc("http_413_count")
        elif response.status_code == 415:
            metrics.inc("http_415_count")
        elif response.status_code == 429:
            metrics.inc("http_429_count")

        return response
    except Exception as exc:
        logger.error(f"Global unhandled exception on {request.url.path}: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "detail": "Internal Server Error",
                "message": str(exc)
            },
            headers={"X-Request-ID": req_id}
        )

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.app_secret_key,
    max_age=settings.session_max_age_seconds,
    same_site="lax",
    https_only=settings.session_https_only
)

app.include_router(auth_router)
app.include_router(pages_router)
app.include_router(history_router)
app.include_router(admin_router)
app.include_router(notifications_router)
app.include_router(comparison_router)

@app.on_event("startup")
def startup_event():
    """
    Startup recovery: detect database jobs left in queued/processing state
    and mark them as failed (interrupted by server restart).
    """
    logger.info("Running application startup checks...")
    db = SessionLocal()
    try:
        from utils.audit import record_audit_event
        stale_records = db.query(AnalysisRecord).filter(
            AnalysisRecord.status == "processing"
        ).all()
        
        for rec in stale_records:
            logger.warning(f"Startup recovery: job {rec.job_id} was left in status '{rec.status}'. Marking as failed (interrupted by server restart).")
            rec.status = "failed"
            rec.error_message = "interrupted: Job was interrupted by server restart"
            rec.updated_at = datetime.datetime.now(datetime.timezone.utc)
            # Log audit event for recovery
            record_audit_event("job_interrupted_recovered", user_id=rec.user_id, details={"job_id": rec.job_id, "previous_status": rec.status})
        
        db.commit()
    except Exception as e:
        logger.error(f"Startup recovery failed: {e}")
        db.rollback()
    finally:
        db.close()

logger = get_logger()

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global unhandled exception on {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "detail": "Internal Server Error",
            "message": str(exc)
        }
    )

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(CURRENT_DIR, "static")
TEMPLATES_DIR = os.path.join(CURRENT_DIR, "templates")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(os.path.join(STATIC_DIR, "Logo_boy.png"), media_type="image/png")

# Phase 17.3 safe media storage directories
DATA_DIR = os.path.join(CURRENT_DIR, "data")
MEDIA_DIR = os.path.join(DATA_DIR, "media")
MEDIA_YOUTUBE_DIR = os.path.join(MEDIA_DIR, "youtube")
MEDIA_TIKTOK_DIR = os.path.join(MEDIA_DIR, "tiktok")
MEDIA_LOCAL_DIR = os.path.join(MEDIA_DIR, "local")
CACHE_MEDIA_DIR = os.path.join(DATA_DIR, "cache", "media")

# Setup default cache dir under data/cache
CACHE_DIR = os.getenv("CACHE_DIR", "data/cache")
if not os.path.isabs(CACHE_DIR):
    CACHE_DIR = os.path.join(CURRENT_DIR, CACHE_DIR)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

HISTORY_DIR = os.path.join(CURRENT_DIR, "analysis_history")

# Ensure all directories exist
for d in [STATIC_DIR, CACHE_DIR, HISTORY_DIR, MEDIA_YOUTUBE_DIR, MEDIA_TIKTOK_DIR, MEDIA_LOCAL_DIR, CACHE_MEDIA_DIR]:
    if not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def get_media_path(unique_id: str, is_cache: bool = False, source_hash: str = None) -> str:
    if is_cache:
        filename = f"{unique_id}_audio_v2_{source_hash}.wav" if source_hash else f"{unique_id}.wav"
        return os.path.join(CACHE_MEDIA_DIR, filename)
    else:
        filename = f"{unique_id}.mp4"
        if unique_id.startswith("youtube_"):
            return os.path.join(MEDIA_YOUTUBE_DIR, filename)
        elif unique_id.startswith("tiktok_"):
            return os.path.join(MEDIA_TIKTOK_DIR, filename)
        else:
            return os.path.join(MEDIA_LOCAL_DIR, filename)

def resolve_media_path(unique_id: str) -> str:
    # 1. Check new paths
    new_path = get_media_path(unique_id)
    if os.path.exists(new_path):
        return new_path
    # 2. Check legacy static path
    legacy_path = os.path.join(STATIC_DIR, f"{unique_id}.mp4")
    if os.path.exists(legacy_path):
        return legacy_path
    # 3. Check legacy cache path
    legacy_cache_path = os.path.join(CACHE_DIR, f"{unique_id}.mp4")
    if os.path.exists(legacy_cache_path):
        return legacy_cache_path
    return new_path

def range_response(request: Request, file_path: str, content_type: str):
    file_size = os.path.getsize(file_path)
    range_header = request.headers.get("range")
    
    if not range_header:
        def iter_file():
            with open(file_path, "rb") as f:
                yield from f
        return StreamingResponse(
            iter_file(),
            media_type=content_type,
            headers={
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
            }
        )
        
    try:
        range_str = range_header.replace("bytes=", "").strip()
        parts = range_str.split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid range header")
        
    if start >= file_size or end >= file_size or start > end:
        return StreamingResponse(
            b"",
            status_code=416,
            headers={
                "Content-Range": f"bytes */{file_size}"
            }
        )
        
    chunk_size = end - start + 1
    
    def iter_range():
        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = chunk_size
            while remaining > 0:
                chunk = f.read(min(remaining, 64 * 1024))
                if not chunk:
                    break
                yield chunk
                remaining -= len(chunk)
                
    return StreamingResponse(
        iter_range(),
        status_code=206,
        media_type=content_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(chunk_size)
        }
    )

# Routes defined BEFORE StaticFiles mount to intercept /static/media requests
@app.get("/api/media/{unique_id}")
@app.get("/static/{unique_id}.mp4")
async def serve_media(unique_id: str, request: Request):
    if unique_id.endswith(".mp4"):
        unique_id = unique_id[:-4]
        
    # Prevent path traversal by strictly matching valid unique id format
    if not re.match(r"^[a-zA-Z0-9_\-]+$", unique_id):
        raise HTTPException(status_code=400, detail="Invalid media identifier")
        
    file_path = resolve_media_path(unique_id)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Media file not found")
        
    return range_response(request, file_path, "video/mp4")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/templates", StaticFiles(directory=TEMPLATES_DIR), name="templates")

def derive_media_type_display(mode: Optional[str] = None, url: Optional[str] = None, filename: Optional[str] = None) -> str:
    """
    Derives standardized, human-readable media display string for Admin dashboard.
    Does NOT invoke ffprobe or execute disk/external checks.
    """
    url_str = str(url or "").strip().lower()
    mode_str = str(mode or "").strip().lower()
    
    # 1. External URL Sources
    if "tiktok.com" in url_str or mode_str == "tiktok":
        return "TikTok"
    if "youtube.com" in url_str or "youtu.be" in url_str or mode_str == "youtube":
        return "YouTube"
    if url_str.startswith("http://") or url_str.startswith("https://"):
        return "URL"

    # 2. File Uploads
    if filename:
        ext = os.path.splitext(str(filename))[1].lower()
        if ext in [".mp4", ".mov", ".mkv", ".webm"]:
            return f"Video ({ext[1:].upper()})"
        if ext in [".mp3", ".wav", ".m4a", ".aac"]:
            return f"Audio ({ext[1:].upper()})"
        if ext.startswith("."):
            ext_name = ext[1:].upper()
            if ext_name in ["AVI", "FLV", "WMV", "M4V", "3GP"]:
                return f"Video ({ext_name})"
            if ext_name in ["FLAC", "OGG", "WMA", "AIFF"]:
                return f"Audio ({ext_name})"

    if mode_str == "mp4":
        return "Video (MP4)"
    if mode_str in ["file", "upload"]:
        return "Upload"

    return "UNKNOWN"

JOBS_DATA = {}
DOWNLOAD_OWNERSHIP: Dict[str, Set[int]] = {}

def record_timeline_stage(job_id: str, stage_name: str, status: str = "started"):
    """
    Records job stage timeline transitions.
    Stages: queued -> download -> extract -> transcribe -> analysis -> persist -> completed / failed
    """
    if job_id not in JOBS_DATA:
        return
    now = time.time()
    timeline = JOBS_DATA[job_id].setdefault("timeline", [])

    for entry in timeline:
        if entry.get("finished_at") is None:
            entry["finished_at"] = now
            entry["duration"] = round(now - entry["started_at"], 3)

    if stage_name not in ("completed", "failed") and status == "started":
        timeline.append({
            "stage": stage_name,
            "started_at": now,
            "finished_at": None,
            "duration": None
        })
    elif stage_name in ("completed", "failed"):
        JOBS_DATA[job_id]["terminal_at"] = now

    stage_ctx.set(stage_name)

def set_job_terminal_status(job_id: str, status: str, result: Optional[dict] = None, error: Optional[str] = None):
    """Safely updates job state to a terminal status ('completed', 'failed') setting terminal_at timestamp."""
    now = time.time()
    if job_id in JOBS_DATA:
        JOBS_DATA[job_id]["status"] = status
        JOBS_DATA[job_id]["terminal_at"] = now
        record_timeline_stage(job_id, status, "finished")
        if status == "completed":
            JOBS_DATA[job_id]["progress"] = 100
            JOBS_DATA[job_id]["completed_at"] = now
            if result is not None:
                JOBS_DATA[job_id]["result"] = result
        elif status == "failed":
            JOBS_DATA[job_id]["failed_at"] = now
            if error is not None:
                JOBS_DATA[job_id]["error"] = error

@app.get("/health")
async def health_check(db: Any = Depends(get_db)):
    """Application health check endpoint with WAL, migration, temp, and tool diagnostics."""
    db_ok = False
    wal_enabled = False
    migration_rev = "unknown"

    try:
        db.execute(text("SELECT 1"))
        db_ok = True

        try:
            wal_res = db.execute(text("PRAGMA journal_mode")).scalar()
            if wal_res and str(wal_res).lower() == "wal":
                wal_enabled = True
        except Exception:
            wal_enabled = False

        try:
            mig_res = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
            if mig_res:
                migration_rev = str(mig_res)
        except Exception:
            migration_rev = "unknown"

    except Exception as e:
        logger.error(f"Health check database failure: {e}", extra={"error_category": classify_error(e)})
        return JSONResponse(status_code=503, content={"status": "error", "database": "unavailable"})

    import tempfile
    temp_dir = tempfile.gettempdir()
    temp_ok = os.path.exists(temp_dir) and os.access(temp_dir, os.W_OK)

    ffmpeg_ok = bool(shutil.which("ffmpeg") or os.path.exists(os.path.join(CURRENT_DIR, "ffmpeg.exe")))
    ffprobe_ok = bool(shutil.which("ffprobe") or os.path.exists(os.path.join(CURRENT_DIR, "ffprobe.exe")))

    uptime = round(time.time() - SERVER_START_TIME, 2)

    return {
        "status": "ok",
        "database": "ok" if db_ok else "unavailable",
        "sqlite_wal": wal_enabled,
        "migration_revision": migration_rev,
        "temp_directory": "ok" if temp_ok else "error",
        "ffmpeg_availability": ffmpeg_ok,
        "ffprobe_availability": ffprobe_ok,
        "application_version": "1.0.0",
        "uptime_seconds": uptime
    }

@app.get("/diagnostics/runtime")
async def runtime_diagnostics():
    """Development-only endpoint for inspecting internal runtime state."""
    if settings.app_env.lower() != "development":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Diagnostics endpoint disabled in non-development environment."
        )

    active_count = sum(1 for j in JOBS_DATA.values() if j.get("status") in ("queued", "processing"))
    terminal_count = sum(1 for j in JOBS_DATA.values() if j.get("status") in ("completed", "failed"))

    config_summary = {
        "app_env": settings.app_env,
        "session_https_only": settings.session_https_only,
        "session_max_age_seconds": settings.session_max_age_seconds,
        "keep_media_files": settings.keep_media_files,
        "job_terminal_ttl_seconds": settings.job_terminal_ttl_seconds,
        "max_upload_bytes": settings.max_upload_bytes,
        "idempotency_ttl_seconds": settings.idempotency_ttl_seconds,
        "active_jobs_limit": settings.active_jobs_limit,
    }

    return {
        "environment": settings.app_env,
        "active_jobs_count": active_count,
        "terminal_jobs_count": terminal_count,
        "idempotency_entries_count": len(idempotency_store._store),
        "last_cleanup_timestamp": getattr(app.state, "last_cleanup_timestamp", None),
        "config_summary": config_summary,
        "jobs_summary": {
            k: {
                "status": v.get("status"),
                "progress": v.get("progress"),
                "created_at": v.get("created_at"),
                "terminal_at": v.get("terminal_at"),
                "request_id": v.get("request_id"),
                "timeline": v.get("timeline", [])
            }
            for k, v in list(JOBS_DATA.items())[:50]
        }
    }

@app.get("/version")
async def version_info(db: Any = Depends(get_db)):
    """Returns application, git, alembic, and runtime version details."""
    import sys
    git_rev = "unknown"
    try:
        res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=3)
        if res.returncode == 0 and res.stdout.strip():
            git_rev = res.stdout.strip()
    except Exception:
        git_rev = "unknown"

    alembic_rev = "unknown"
    try:
        alembic_rev = db.execute(text("SELECT version_num FROM alembic_version")).scalar() or "unknown"
    except Exception:
        alembic_rev = "unknown"

    return {
        "application_version": "1.0.0",
        "git_revision": str(git_rev),
        "alembic_revision": str(alembic_rev),
        "build_timestamp": datetime.datetime.fromtimestamp(SERVER_START_TIME, datetime.timezone.utc).isoformat(),
        "python_version": sys.version.split()[0]
    }

@app.get("/metrics")
@app.get("/diagnostics/metrics")
async def get_operational_metrics():
    """Returns current snapshot of in-memory operational metrics."""
    return metrics.snapshot()

def cleanup_expired_jobs(max_deletions: Optional[int] = None, max_scans: Optional[int] = None) -> int:
    """
    Safely purges completed/failed jobs from JOBS_DATA after settings.job_terminal_ttl_seconds.
    - Active ('queued', 'processing') jobs are NEVER removed regardless of age.
    - Terminal jobs ('completed', 'failed', 'cancelled') count TTL from terminal_at / completed_at / failed_at.
    - Missing or invalid terminal timestamp fails safe (job is NOT removed).
    - Bounded work: scans up to max_scans items, deletes up to max_deletions items per invocation.
    - Preserves database AnalysisRecord history.
    """
    ttl_limit = getattr(settings, "job_terminal_ttl_seconds", 3600)
    if ttl_limit <= 0:
        ttl_limit = 3600

    limit_del = max_deletions if max_deletions is not None else getattr(settings, "job_cleanup_max_deletions", 50)
    limit_scan = max_scans if max_scans is not None else getattr(settings, "job_cleanup_max_scans", 200)

    now = time.time()
    to_delete = []
    scanned = 0

    for j_id, j_info in list(JOBS_DATA.items()):
        if scanned >= limit_scan or len(to_delete) >= limit_del:
            break
        scanned += 1

        if not isinstance(j_info, dict):
            continue

        status = j_info.get("status")
        if status in ["queued", "processing"]:
            continue

        if status in ["completed", "failed", "cancelled"]:
            terminal_at = j_info.get("terminal_at") or j_info.get("completed_at") or j_info.get("failed_at")
            if terminal_at is None:
                continue
            try:
                term_ts = float(terminal_at)
                if (now - term_ts) > ttl_limit:
                    to_delete.append(j_id)
            except (ValueError, TypeError):
                continue

    for j_id in to_delete:
        JOBS_DATA.pop(j_id, None)

    return len(to_delete)

def get_owned_job_or_404(job_id: str, user_id: int) -> dict:
    """Retrieves a job dictionary from JOBS_DATA or database fallback if it belongs to user_id, else raises HTTP 404."""
    cleanup_expired_jobs()
    job = JOBS_DATA.get(job_id)
    if not job:
        db = SessionLocal()
        try:
            record = db.query(AnalysisRecord).filter(
                AnalysisRecord.job_id == job_id,
                AnalysisRecord.user_id == user_id
            ).first()
            if record:
                result = None
                if record.status == "completed":
                    media_key = record.cache.media_key if record.cache else record.job_id
                    history_file_path = os.path.join(HISTORY_DIR, f"{media_key}.json")
                    if os.path.exists(history_file_path):
                        with open(history_file_path, "r", encoding="utf-8") as h_file:
                            result = json.load(h_file)
                job = {
                    "status": record.status,
                    "progress": record.progress,
                    "result": result,
                    "user_id": record.user_id,
                    "created_at": record.created_at.timestamp() if record.created_at else time.time(),
                    "public_id": record.public_id,
                    "source_type": record.source_type,
                    "error_message": record.error_message,
                    "error": record.error_message
                }
        except Exception as db_ex:
            logger.error(f"Error querying job fallback in DB: {db_ex}")
        finally:
            db.close()
    else:
        # Prevent mutation of registry and normalize both error properties
        job = dict(job)
        if "error" in job and "error_message" not in job:
            job["error_message"] = job["error"]
        elif "error_message" in job and "error" not in job:
            job["error"] = job["error_message"]
        if "public_id" not in job:
            db = SessionLocal()
            try:
                rec = db.query(AnalysisRecord).filter(AnalysisRecord.job_id == job_id).first()
                if rec:
                    job["public_id"] = rec.public_id
            except Exception:
                pass
            finally:
                db.close()

    if not job or job.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

def verify_download_ownership(unique_id: str, user_id: int, db: Optional[Any] = None):
    """
    STRICTLY READ-ONLY verification of download ownership.
    NEVER assigns ownership on read/GET requests.
    Checks in-memory registry or database AnalysisRecord relation.
    Raises HTTP 404 Not Found if unique_id is not in registry/database for user_id.
    """
    allowed_users = DOWNLOAD_OWNERSHIP.get(unique_id)
    if allowed_users and user_id in allowed_users:
        return True

    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        rec = db.query(AnalysisRecord).filter(
            AnalysisRecord.user_id == user_id,
            or_(
                AnalysisRecord.public_id == unique_id,
                AnalysisRecord.job_id == unique_id
            )
        ).first()
        if rec:
            return True

        cache = db.query(AnalysisCache).filter(AnalysisCache.media_key == unique_id).first()
        if cache:
            rec_cache = db.query(AnalysisRecord).filter(
                AnalysisRecord.user_id == user_id,
                AnalysisRecord.cache_id == cache.id
            ).first()
            if rec_cache:
                return True
    finally:
        if close_db:
            db.close()

    raise HTTPException(status_code=404, detail="Resource not found")

video_engine = VideoEngine()
audio_engine = AudioEngine(cache_dir=CACHE_DIR)

def fetch_related_videos(keywords: list, count: int = 6) -> list:
    """ดึงวิดีโอแนะนำจาก YouTube จำนวน 4-7 คลิป โดยใช้คีย์เวิร์ดเด่นจากการวิเคราะห์"""
    if not keywords:
        return []
    
    # ดึง top keywords 2 ตัวแรกมาสร้างข้อความค้นหา (Search Query)
    search_query = " ".join([re.sub(r'[^a-zA-Z0-9ก-๙\s]', '', k) for k in keywords[:2]])
    logger.info(f"🔍 เริ่มต้นค้นหาสื่อวิดีโออ้างอิงและแนะนำระดับยุทธศาสตร์จาก YouTube ด้วยคำค้นหา: {search_query}")
    try:
        cmd = ["yt-dlp", "--js-runtimes", "node", "--flat-playlist", "--dump-single-json", "--playlist-items", f"1-{count}", f"ytsearch{count}:{search_query}"]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=settings.ffprobe_timeout_seconds)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            entries = data.get("entries", [])
            recommendations = []
            for entry in entries:
                if not entry:
                    continue
                v_id = entry.get("id")
                v_title = entry.get("title", "วิดีโอแนะนำ")
                v_url = entry.get("url") or f"https://www.youtube.com/watch?v={v_id}"
                # ใช้พิกัดภาพปกมาตรฐานสูงสุดของ YouTube
                v_thumb = f"https://img.youtube.com/vi/{v_id}/0.jpg"
                recommendations.append({
                    "title": v_title,
                    "url": v_url,
                    "thumbnail": v_thumb
                })
            return recommendations
    except Exception as e:
        logger.error(f"❌ ระบบไม่สามารถค้นหาสื่อวิดีโออ้างอิงได้: {e}")
    return []

# ----------------------------------------------------
# BACKGROUND PROCESSING PIPELINE (ขบวนการประมวลผลจริงแปรผันตามวิดีโอ)
# ----------------------------------------------------
from concurrent.futures import ThreadPoolExecutor
# Bounded local thread pool executor for processing jobs
MAX_CONCURRENT_JOBS = 2
job_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS, thread_name_prefix="job_worker")

class TaskCancelledException(Exception):
    pass

class TikTokDownloadError(Exception):
    pass

TIKTOK_DOWNLOAD_TIMEOUT_SECONDS = 180
TIKTOK_EDGE_COOKIE_TIMEOUT_SECONDS = 60

import threading
claim_lock = threading.Lock()

def claim_job_atomic(db: Session, job_id: str) -> bool:
    with claim_lock:
        record = db.query(AnalysisRecord).filter(AnalysisRecord.job_id == job_id).first()
        if record and record.status == "queued":
            record.status = "processing"
            record.progress = 5
            record.updated_at = datetime.datetime.now(datetime.timezone.utc)
            db.commit()
            return True
        return False

def update_job_status(job_id: str, next_status: str, progress: int, error: Optional[str] = None, result: Optional[Dict] = None):
    """Safely updates job state in memory and database, validating the state transition."""
    from services.analysis_history_service import validate_state_transition, InvalidStateTransitionException
    
    # Retrieve current status from memory first
    current_status = "queued"
    if job_id in JOBS_DATA:
        current_status = JOBS_DATA[job_id].get("status", "queued")
    else:
        # Fallback to database
        db = SessionLocal()
        try:
            record = db.query(AnalysisRecord).filter(AnalysisRecord.job_id == job_id).first()
            if record:
                current_status = record.status
        finally:
            db.close()

    try:
        validate_state_transition(current_status, next_status)
    except InvalidStateTransitionException as e:
        logger.warning(f"State transition validation rejected for job {job_id}: {e}")
        return False

    # 1. Update in-memory registry
    if job_id in JOBS_DATA:
        JOBS_DATA[job_id]["status"] = next_status
        JOBS_DATA[job_id]["progress"] = progress
        if error is not None:
            JOBS_DATA[job_id]["error"] = error
        if result is not None:
            JOBS_DATA[job_id]["result"] = result
        
        # Log terminal timestamps
        now = time.time()
        if next_status in ("completed", "failed", "cancelled"):
            JOBS_DATA[job_id]["terminal_at"] = now
            if next_status == "completed":
                JOBS_DATA[job_id]["completed_at"] = now
            elif next_status == "failed":
                JOBS_DATA[job_id]["failed_at"] = now
            elif next_status == "cancelled":
                JOBS_DATA[job_id]["cancelled_at"] = now

    # 2. Update database record
    db = SessionLocal()
    try:
        record = db.query(AnalysisRecord).filter(AnalysisRecord.job_id == job_id).first()
        if record:
            record.status = next_status
            record.progress = progress
            if error is not None:
                record.error_message = error
            if next_status == "completed":
                record.completed_at = datetime.datetime.now(datetime.timezone.utc)
            record.updated_at = datetime.datetime.now(datetime.timezone.utc)
            db.commit()

            # 🔔 Trigger notifications
            from services.notification_service import create_notification
            try:
                if next_status == "completed":
                    create_notification(
                        db=db,
                        user_id=record.user_id,
                        type="job_completed",
                        title="Analysis completed",
                        message="Your analysis is ready.",
                        related_job_id=job_id,
                        target_url="/history",
                        deduplication_key=f"job:{job_id}:completed"
                    )
                elif next_status == "failed":
                    error_msg = error or "Analysis failed"
                    create_notification(
                        db=db,
                        user_id=record.user_id,
                        type="job_failed",
                        title="Analysis failed",
                        message=error_msg[:100],
                        related_job_id=job_id,
                        target_url="/history",
                        deduplication_key=f"job:{job_id}:failed:{progress}"
                    )
                elif next_status == "cancelled":
                    create_notification(
                        db=db,
                        user_id=record.user_id,
                        type="job_cancelled",
                        title="Analysis cancelled",
                        message="The analysis job was cancelled.",
                        related_job_id=job_id,
                        target_url="/history",
                        deduplication_key=f"job:{job_id}:cancelled"
                    )
            except Exception as e:
                logger.error(f"Failed to create notification for job {job_id}: {e}")

    except Exception as ex:
        logger.error(f"Error updating database status for job {job_id}: {ex}")
        db.rollback()
    finally:
        db.close()
        
    return True

async def enterprise_processing_pipeline(job_id: str, mode: str, youtube_url: Optional[str], file_bytes: Optional[bytes], file_name: Optional[str], selected_model: Optional[str] = None):
    """Async wrapper that offloads job processing to a bounded thread executor to avoid event loop blocking."""
    import asyncio
    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        job_executor,
        enterprise_processing_pipeline_sync,
        job_id,
        mode,
        youtube_url,
        file_bytes,
        file_name,
        selected_model
    )

def check_cancellation_checkpoint(job_id: str, db_session: Session):
    if JOBS_DATA.get(job_id, {}).get("cancel_requested"):
        raise TaskCancelledException("Job was cancelled by user")
    rec = db_session.query(AnalysisRecord).filter(AnalysisRecord.job_id == job_id).first()
    if rec and rec.status == "cancelled":
        raise TaskCancelledException("Job was cancelled by user")

def normalize_tiktok_url(url: str) -> str:
    """Normalize TikTok URLs by stripping query parameters."""
    if "tiktok.com" in url.lower():
        return url.split("?")[0]
    return url


def _tiktok_download_command(url: str, output_path: str, *, browser_profile: Optional[str] = None) -> list[str]:
    """Build the bounded TikTok yt-dlp invocation."""
    command = [
        "yt-dlp", "--js-runtimes", "node", "-f", "bestvideo+bestaudio/best",
        "--merge-output-format", "mp4", "--ffmpeg-location", CURRENT_DIR,
    ]
    command.extend([url, "-o", output_path])
    return command


def validate_tiktok_downloaded_media(path: str) -> bool:
    """Require a non-empty video that ffprobe can inspect before entering the media pipeline."""
    try:
        if not os.path.isfile(path) or os.path.getsize(path) <= 0:
            return False
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", path],
            capture_output=True, text=True, timeout=settings.ffprobe_timeout_seconds, check=False,
        )
        if probe.returncode != 0:
            return False
        metadata = json.loads(probe.stdout or "{}")
        duration = float(metadata.get("format", {}).get("duration", 0) or 0)
        has_video = any(stream.get("codec_type") == "video" for stream in metadata.get("streams", []))
        return duration > 0 and has_video
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, json.JSONDecodeError):
        return False


def _validate_playwright_media_candidate(path: str) -> tuple[bool, bool]:
    """
    Validates the media file downloaded via Playwright.
    Returns (success, has_audio).
    """
    try:
        if not os.path.isfile(path) or os.path.getsize(path) <= 0:
            return False, False
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", path],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if probe.returncode != 0:
            return False, False
        metadata = json.loads(probe.stdout or "{}")
        duration = float(metadata.get("format", {}).get("duration", 0) or 0)
        has_video = any(stream.get("codec_type") == "video" for stream in metadata.get("streams", []))
        has_audio = any(stream.get("codec_type") == "audio" for stream in metadata.get("streams", []))
        return (duration > 0 and has_video), has_audio
    except Exception:
        return False, False


def validate_uploaded_media_ffprobe(path: str) -> tuple[bool, str]:
    """
    Validates uploaded media file with ffprobe to ensure container readability and stream integrity.
    Returns (is_valid, reason).
    """
    try:
        if not os.path.isfile(path):
            return False, "Uploaded file does not exist on disk"
        if os.path.getsize(path) <= 0:
            return False, "Uploaded file is empty (0 bytes)"

        ffprobe_bin = shutil.which("ffprobe") or (
            os.path.join(CURRENT_DIR, "ffprobe.exe")
            if os.path.exists(os.path.join(CURRENT_DIR, "ffprobe.exe"))
            else "ffprobe"
        )

        probe = subprocess.run(
            [ffprobe_bin, "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", path],
            capture_output=True, text=True, timeout=getattr(settings, "ffprobe_timeout_seconds", 60), check=False,
        )
        if probe.returncode != 0:
            err_msg = (probe.stderr or "").strip() or "Invalid or corrupted media container"
            return False, f"ffprobe rejected media container: {err_msg}"

        metadata = json.loads(probe.stdout or "{}")
        duration = float(metadata.get("format", {}).get("duration", 0) or 0)
        streams = metadata.get("streams", [])
        has_video = any(s.get("codec_type") == "video" for s in streams)
        has_audio = any(s.get("codec_type") == "audio" for s in streams)

        if not (has_video or has_audio):
            return False, "No valid audio or video stream found in file"

        if duration <= 0:
            return False, "Invalid or unreadable media duration (duration is 0 seconds)"

        return True, "OK"
    except Exception as e:
        return False, f"ffprobe validation error: {str(e)}"


def download_tiktok_with_fallbacks(url: str, output_path: str) -> None:
    """Run each TikTok download method once, in the approved order."""
    def attempt(command: list[str], timeout: int) -> tuple[bool, str]:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return False, ""
        return result.returncode == 0 and validate_tiktok_downloaded_media(output_path), result.stderr or result.stdout or ""

    logger.info("TikTok Download Attempt 1 (Standard): Running standard yt-dlp")
    normal_success, normal_error = attempt(_tiktok_download_command(url, output_path), TIKTOK_DOWNLOAD_TIMEOUT_SECONDS)
    if normal_success:
        logger.info("TikTok download succeeded on Attempt 1.")
        return

    # Check for extraction / webpage / challenge / block errors
    challenge_markers = ("unable to extract", "webpage", "access denied", "captcha", "challenge")
    if not any(marker in normal_error.lower() for marker in challenge_markers):
        # Even if normal_error doesn't contain markers, let's still fall back to Playwright to be robust
        pass

    # Playwright Headless Fallback
    import asyncio
    import threading
    import shutil
    
    async def _download_tiktok_playwright_async(url: str, output_path: str) -> bool:
        from playwright.async_api import async_playwright
        import tempfile
        
        logger.info("TikTok Download Attempt 2 (Playwright Headless): Starting browser fallback")
        
        success = False
        playwright_instance = None
        browser = None
        context = None
        
        try:
            playwright_instance = await async_playwright().start()
            browser = await playwright_instance.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 375, "height": 667},
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
                is_mobile=True,
                has_touch=True
            )
            
            page = await context.new_page()
            downloaded = asyncio.Event()
            
            async def handle_response(response):
                nonlocal success
                if downloaded.is_set():
                    return
                    
                res_url = response.url
                content_type = response.headers.get("content-type", "")
                
                is_media_candidate = False
                if "video/" in content_type:
                    is_media_candidate = True
                elif ".mp4" in res_url or "mime=video" in res_url:
                    is_media_candidate = True
                    
                if is_media_candidate:
                    clean_url = res_url.split("?")[0]
                    logger.info(f"TikTok Playwright media candidate detected: {clean_url}")
                    
                    temp_fd, temp_file_path = tempfile.mkstemp(suffix=".mp4")
                    os.close(temp_fd)
                    
                    try:
                        try:
                            body_bytes = await response.body()
                        except Exception as e_body:
                            logger.debug(f"Direct body read failed, trying request get with headers: {e_body}")
                            body_bytes = b""
                            try:
                                res_api = await context.request.get(res_url, headers=response.request.headers)
                                body_bytes = await res_api.body()
                            except Exception as e_get:
                                logger.warning(f"Fallback request get failed for {clean_url}: {e_get}")
                        
                        with open(temp_file_path, "wb") as f:
                            f.write(body_bytes)
                            
                        # Validate candidate file
                        valid_video, has_audio = _validate_playwright_media_candidate(temp_file_path)
                        logger.info(f"TikTok Playwright candidate validation: valid_video={valid_video}, has_audio={has_audio} for {clean_url}")
                        
                        if valid_video:
                            if has_audio:
                                logger.info("TikTok Playwright media validation PASS")
                                shutil.copy2(temp_file_path, output_path)
                                success = True
                                downloaded.set()
                            else:
                                logger.warning(f"TikTok Playwright media candidate lacks audio stream: {clean_url}")
                        else:
                            logger.warning(f"TikTok Playwright media candidate validation FAIL (invalid video): {clean_url}")
                    except Exception as e:
                        logger.debug(f"Failed processing candidate response: {e}")
                    finally:
                        try:
                            os.remove(temp_file_path)
                        except Exception:
                            pass
            
            page.on("response", lambda res: asyncio.create_task(handle_response(res)))
            
            await page.goto(url, timeout=30000, wait_until="load")
            
            try:
                await page.wait_for_selector("video", timeout=5000)
                await page.click("video")
            except Exception as e:
                logger.debug(f"Could not click video to play: {e}")
            
            try:
                await asyncio.wait_for(downloaded.wait(), timeout=45.0)
            except (TimeoutError, asyncio.TimeoutError):
                logger.warning("TikTok Playwright fallback timed out waiting for media download")
                
        except Exception as e:
            logger.error(f"Error during Playwright fallback execution: {e}", exc_info=True)
        finally:
            if context:
                try:
                    await context.close()
                except Exception:
                    pass
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            if playwright_instance:
                try:
                    await playwright_instance.stop()
                except Exception:
                    pass
                    
        if success:
            logger.info("TikTok Playwright fallback SUCCESS")
        return success

    playwright_success = False
    result_container = []
    exception_container = []
    
    def run_target():
        try:
            res = asyncio.run(_download_tiktok_playwright_async(url, output_path))
            result_container.append(res)
        except Exception as ex:
            exception_container.append(ex)
            
    t = threading.Thread(target=run_target)
    t.start()
    t.join()
    
    if exception_container:
        logger.error(f"Playwright fallback thread raised exception: {exception_container[0]}")
        raise TikTokDownloadError("TikTok download failed due to Playwright exception")
        
    if result_container and result_container[0]:
        return

    raise TikTokDownloadError("TikTok download failed after Playwright fallback")


def enterprise_processing_pipeline_sync(job_id: str, mode: str, youtube_url: Optional[str], file_bytes: Optional[bytes], file_name: Optional[str], selected_model: Optional[str] = None):
    pipeline_start_time = time.time()
    current_stage = "initializing"
    selected_model = validate_primary_model(selected_model)

    req_id = JOBS_DATA.get(job_id, {}).get("request_id") or "-"
    u_id = JOBS_DATA.get(job_id, {}).get("user_id")
    request_id_ctx.set(req_id)
    job_id_ctx.set(job_id)
    if u_id:
        user_id_ctx.set(u_id)
    component_ctx.set("pipeline")
    metrics.inc("jobs_running")

    # Temporary files isolated working directory
    job_work_dir = os.path.join(CACHE_DIR, job_id)
    os.makedirs(job_work_dir, exist_ok=True)
    temp_video_path = os.path.join(job_work_dir, "temp_video.mp4")
    temp_audio_path = os.path.join(job_work_dir, "temp_audio.wav")

    db = SessionLocal()
    try:
        # 1. Atomic Job Claiming
        if not claim_job_atomic(db, job_id):
            metrics.dec("jobs_running")
            logger.error(f"Worker claim failed: AnalysisRecord for job {job_id} does not exist or is not in 'queued' status in the database.")
            if job_id in JOBS_DATA:
                JOBS_DATA[job_id]["status"] = "failed"
                JOBS_DATA[job_id]["progress"] = 100
                JOBS_DATA[job_id]["error"] = "Worker claim failed: Job record not found or already claimed."
                JOBS_DATA[job_id]["terminal_at"] = time.time()
                JOBS_DATA[job_id]["failed_at"] = time.time()
                record_timeline_stage(job_id, "failed", "finished")
            return

        if job_id in JOBS_DATA:
            JOBS_DATA[job_id]["status"] = "processing"
            JOBS_DATA[job_id]["progress"] = 5
            from utils.telemetry import create_empty_token_usage
            JOBS_DATA[job_id]["token_usage"] = create_empty_token_usage()
            record_timeline_stage(job_id, "download", "started")

        logger.info(f"เริ่มต้นประมวลผลข้อมูลจริงเชิงลึกสำหรับ Job ID: {job_id}")

        check_cancellation_checkpoint(job_id, db)
        
        unique_id = f"media_{int(time.time())}"
        video_path = ""
        is_youtube = False
        real_url = ""

        # 🎯 1. [ขั้นตอนสแกนคัดกรองลิงก์ออนไลน์เก่า]: YouTube / TikTok ด้วย Video ID บนเว็บ
        if mode in ["youtube", "tiktok"] and youtube_url:
            is_youtube = True
            real_url = youtube_url
            unique_id = video_engine.extract_unique_video_id(youtube_url)
            
            history_file_path = os.path.join(HISTORY_DIR, f"{unique_id}.json")
            if os.path.exists(history_file_path):
                logger.info(f"🎯 เจอประวัติเก่าของลิงก์นี้! ({unique_id}) ดึงข้อมูลแดชบอร์ดขึ้นแสดงทันทีใน 1 วินาที...")
                with open(history_file_path, "r", encoding="utf-8") as h_file:
                    saved_result = json.load(h_file)
                
                # Persist Cache Reuse to Database
                from services.analysis_history_service import persist_cache_reuse_record
                try:
                    persist_cache_reuse_record(
                        db=db,
                        user_id=u_id,
                        media_key=unique_id,
                        source_type=mode,
                        result_json=saved_result,
                        job_id=job_id,
                        source_url=youtube_url,
                        original_filename=file_name,
                        model_used=selected_model or "gemini-2.5-flash",
                        duration_seconds=saved_result.get("duration_seconds")
                    )
                except Exception as persist_ex:
                    logger.error(f"Error persisting cache reuse for job {job_id}: {persist_ex}")

                JOBS_DATA[job_id]["result"] = saved_result
                JOBS_DATA[job_id]["status"] = "completed"
                JOBS_DATA[job_id]["progress"] = 100
                JOBS_DATA[job_id]["terminal_at"] = time.time()
                JOBS_DATA[job_id]["completed_at"] = time.time()
                record_timeline_stage(job_id, "completed", "finished")
                metrics.inc("cache_hits")
                metrics.dec("jobs_running")
                metrics.inc("jobs_completed")
                return

        metrics.inc("cache_misses")
        update_job_status(job_id, "processing", 10)

        # 2. จัดการข้อมูลแหล่งสื่ออินพุต (Video Processing Phase)
        current_stage = "video_download"
        check_cancellation_checkpoint(job_id, db)
        if is_youtube:
            video_path = os.path.join(CACHE_MEDIA_DIR, f"{unique_id}.mp4")
            logger.info(f"ดึงสัญญาณวิดีโอผ่านแพลตฟอร์ม: {unique_id}")
            if not os.path.exists(video_path):
                youtube_url_lower = youtube_url.lower()
                
                # แยกท่อสากลไม่ให้เอ๋อใส่กัน
                if "tiktok.com" in youtube_url_lower:
                    logger.info("📱 ระบบตรวจสอบพบสัญญาณลิงก์ TikTok กำลังสลับไปใช้ท่อดาวน์โหลด Playwright Fallback...")
                    download_tiktok_with_fallbacks(youtube_url, temp_video_path)
                else:
                    # 🎯 [ปลดล็อก 100% เลิกฟิกซ์ฟอร์แมต]: ปล่อยให้ระบบเลือกไฟล์ที่อิสระและผ่านด่านได้ง่ายที่สุด (เช่น webvtt / webm ที่ไม่ติด PO Token)
                    # จากนั้นใช้คำสั่ง --merge-output-format mp4 เพื่อให้ ffmpeg ประกอบร่างให้เป็น .mp4 สากลหน้าบ้านเอง
                    logger.info("📺 ระบบตรวจสอบพบสัญญาณลิงก์ YouTube กำลังเปิดใช้งานระบบท่อเปิดกว้างข้ามด่าน PO Token...")
                    cmd = (
                        f'yt-dlp --js-runtimes node -f "bestvideo+bestaudio/best" '
                        f'--merge-output-format mp4 '
                        f'--ffmpeg-location "{CURRENT_DIR}" '
                        f'--user-agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" '
                        f'--extractor-args "youtube:player_client=android,ios;skip=webpage" '
                        f'--no-check-certificates --geo-bypass '
                        f'"{youtube_url}" -o "{temp_video_path}"'
                    )
                    subprocess.run(cmd, shell=True, check=True)
                # Move to final cache destination atomically
                if os.path.exists(temp_video_path):
                    shutil.move(temp_video_path, video_path)
        else:
            # 🎯 [วิธีที่ 1]: คำนวณค่า SHA-256 จากเนื้อหาไฟล์จริง (เปลี่ยนชื่อไฟล์ แฮชก็ยังเท่าเดิม)
            if file_bytes and file_name:
                if isinstance(file_bytes, str):
                    # Check if the filename contains the hash already
                    base_name = os.path.basename(file_bytes)
                    if base_name.startswith("local_sha256_"):
                        # Extract hash from base_name: local_sha256_{hash}{ext}
                        parts = base_name.split("_")
                        if len(parts) >= 3:
                            file_hash_with_ext = parts[2]
                            file_hash = file_hash_with_ext.split(".")[0]
                        else:
                            file_hash = calculate_file_sha256_full(file_bytes)
                    else:
                        file_hash = calculate_file_sha256_full(file_bytes)
                else:
                    # Legacy fallback for bytes (tests)
                    file_hash = hashlib.sha256(file_bytes).hexdigest()
                
                unique_id = f"local_sha256_{file_hash[:16]}" # ใช้แฮช 16 หลักแรกเป็นไอดีถาวร
                
                # ตรวจสอบด่านแรก: ถ้าแฮชตรงกับประวัติเดิม ดึงข้อมูลเก่าขึ้นแสดงทันทีใน 1 วินาที (เร็วที่สุด)
                saved_result = None
                history_file_path = os.path.join(HISTORY_DIR, f"{unique_id}.json")
                if os.path.exists(history_file_path):
                    try:
                        with open(history_file_path, "r", encoding="utf-8") as h_file:
                            saved_result = json.load(h_file)
                    except Exception:
                        saved_result = None

                if not saved_result:
                    try:
                        cache_entry = db.query(AnalysisCache).filter(AnalysisCache.media_key == unique_id).first()
                        if cache_entry and cache_entry.result_json:
                            saved_result = cache_entry.result_json
                            if isinstance(saved_result, str):
                                saved_result = json.loads(saved_result)
                    except Exception:
                        saved_result = None

                if saved_result:
                    logger.info(f"🎯 [SHA-256 Match] เจอประวัติตรงกันจากสารบบไฟล์เนื้อหาเดิม! ({unique_id}) ดึงผลลัพธ์ขึ้นแสดงทันที...")
                    from services.analysis_history_service import persist_cache_reuse_record
                    try:
                        persist_cache_reuse_record(
                            db=db,
                            user_id=u_id,
                            media_key=unique_id,
                            source_type=mode,
                            result_json=saved_result,
                            job_id=job_id,
                            source_url=youtube_url,
                            original_filename=file_name,
                            model_used=selected_model or "gemini-2.5-flash",
                            duration_seconds=saved_result.get("duration_seconds")
                        )
                    except Exception as persist_ex:
                        logger.error(f"Error persisting cache reuse for job {job_id}: {persist_ex}")
                    
                    JOBS_DATA[job_id]["result"] = saved_result
                    JOBS_DATA[job_id]["status"] = "completed"
                    JOBS_DATA[job_id]["progress"] = 100
                    JOBS_DATA[job_id]["terminal_at"] = time.time()
                    JOBS_DATA[job_id]["completed_at"] = time.time()
                    return 

                # หากด่านแรกไม่เจอ -> ระบบจะบันทึกไฟล์และสกัดเสียงตามปกติก่อน
                video_path = os.path.join(CACHE_MEDIA_DIR, f"{unique_id}.mp4")
                if not os.path.exists(video_path):
                    if isinstance(file_bytes, str):
                        # Moving file from temp location to target CACHE_MEDIA_DIR
                        if os.path.exists(file_bytes):
                            shutil.move(file_bytes, video_path)
                    else:
                        # Legacy fallback for bytes (tests)
                        with open(temp_video_path, "wb") as f:
                            f.write(file_bytes)
                        shutil.move(temp_video_path, video_path)

        update_job_status(job_id, "processing", 30)
        
        # 🎯 [P0-1]: ประกาศ path นี้ทันทีเพื่อป้องกัน UnboundLocalError
        dest_static_video = get_media_path(unique_id)
        
        # 3. ขบวนการสกัดสัญญาณเสียง (Audio Extraction Phase)
        current_stage = "audio_extraction"
        check_cancellation_checkpoint(job_id, db)
        record_timeline_stage(job_id, "extract", "started")

        # 🎯 [P0-2]: helper for content hashing
        def calculate_file_sha256(path: str) -> str:
            digest = hashlib.sha256()
            with open(path, "rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
            return digest.hexdigest()[:16]

        # 🎯 [P0-1]: เลือก source หลัง remux (ตรวจสอบเงื่อนไขความถูกต้อง)
        if os.path.exists(dest_static_video) and os.path.getsize(dest_static_video) > 0:
            transcription_video_source = dest_static_video
        elif os.path.exists(video_path) and os.path.getsize(video_path) > 0:
            transcription_video_source = video_path
        else:
            raise FileNotFoundError(
                f"No valid video source found: video_path={video_path}, dest_static_video={dest_static_video}"
            )
        
        logger.info(f"Transcription source selected: {transcription_video_source}")
        
        # Generate & persist video thumbnail for AnalysisRecord
        try:
            from utils.thumbnail_service import generate_mp4_thumbnail, get_youtube_thumbnail_url
            rec_to_thumb = db_session.query(AnalysisRecord).filter(AnalysisRecord.job_id == job_id).first()
            if rec_to_thumb and not rec_to_thumb.thumbnail_url:
                t_url = None
                if is_youtube:
                    t_url = get_youtube_thumbnail_url(youtube_url)
                if not t_url:
                    t_url = generate_mp4_thumbnail(transcription_video_source, job_id, rec_to_thumb.duration_seconds)
                if t_url:
                    rec_to_thumb.thumbnail_url = t_url
                    db_session.commit()
        except Exception as th_err:
            logger.warning(f"Failed to generate thumbnail for job {job_id}: {th_err}")
        
        # 🎯 [P0-2]: สร้าง audio_path พร้อม source hash
        source_hash = calculate_file_sha256(transcription_video_source)
        audio_path = get_media_path(unique_id, is_cache=True, source_hash=source_hash)

        # 🎯 [P0-2]: ตรวจสอบ duration และลบแคชเก่าถ้าจำเป็น
        def get_duration(path):
            cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{path}"'
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            return float(res.stdout.strip()) if res.stdout.strip() else 0.0

        if os.path.exists(audio_path):
            if os.path.getsize(audio_path) == 0:
                os.remove(audio_path)
            else:
                source_dur = get_duration(transcription_video_source)
                audio_dur = get_duration(audio_path)
                if abs(source_dur - audio_dur) > 0.25:
                    logger.warning(f"Audio cache duration mismatch, regenerating: {source_dur} vs {audio_dur}")
                    os.remove(audio_path)

        if not os.path.exists(audio_path):
            logger.info(f"กำลังสกัดสัญญาณเสียงจากแหล่ง: {transcription_video_source}")
            
            source_dur = get_duration(transcription_video_source)
            
            cmd_audio = [
                "ffmpeg", "-y", "-i", transcription_video_source,
                "-vn", "-ac", "1", "-ar", "16000",
                "-c:a", "pcm_s16le", temp_audio_path
            ]
            result = subprocess.run(cmd_audio, capture_output=True)
            
            if result.returncode != 0:
                logger.error("🚨 สกัดเสียงล้มเหลว")
                update_job_status(job_id, "failed", 30, error="Audio extraction failed")
                return
                
            audio_dur = get_duration(temp_audio_path)
            
            diff = abs(source_dur - audio_dur)
            if diff > 1.0:
                logger.error(f"🚨 ERROR: Timebase drift too high: {diff}s")
                update_job_status(job_id, "failed", 30, error="Timebase drift exceeds threshold")
                return
            elif diff > 0.25:
                logger.warning(f"⚠️ WARNING: Timebase drift detected: {diff}s")
            
            # Rename to final cache path atomically
            if os.path.exists(temp_audio_path):
                shutil.move(temp_audio_path, audio_path)

        update_job_status(job_id, "processing", 50)

        # 4. ขบวนการปรับสตรีมภาพวิดีโอให้ขึ้นจอ (Web-Ready Remux แก้จอดำ)
        current_stage = "remuxing"
        check_cancellation_checkpoint(job_id, db)
        logger.info("กำลังเปิดระบบสแกนสัญญาณเสียงและสั่งหั่นก้อนข้อมูลส่งวิเคราะห์...")
        
        if os.path.exists(video_path) and not os.path.exists(dest_static_video):
            youtube_url_lower = (youtube_url or "").lower()
            
            temp_static_video = os.path.join(job_work_dir, "temp_static_video.mp4")
            # 🎯 ถ้าเป็นลิงก์ TikTok ให้ทำการแปลงภาพใหม่เป็น H.264 แบบติดสปีดแก้ปัญหาจอดำตามเดิม
            if "tiktok.com" in youtube_url_lower:
                logger.info("🎬 [TikTok Video Remux] บังคับแปลงรหัสภาพใหม่เป็น H.264 (libx264) สปีดเร่งด่วนเพื่อแก้ปัญหาจอดำ...")
                cmd_remux = (
                    f'ffmpeg -y -i "{video_path}" '
                    f'-c:v libx264 -preset ultrafast -pix_fmt yuv420p '
                    f'-c:a aac -b:a 128k -movflags +faststart "{temp_static_video}"'
                )
            # 📺 ถ้าเป็น YouTube หรือไฟล์อื่น ๆ (ซ่อมบั๊กเวลากับคำพูดไม่ตรงกัน)
            else:
                logger.info("🎬 [Standard Video Remux] จัดเรียงโครงสร้างวิดีโอพร้อมซิงค์แกนเวลาถาวร (Timebase Sync)...")
                # 🎯 [ปลดล็อกบั๊กเวลาเพี้ยน]: เพิ่มคำสั่ง -fflags +genpts ปลุกสร้างพิกัดเวลาใหม่ 
                # และพ่วง -async 1 / -vsync passthrough บังคับให้ท่อภาพและเสียงเกาะล็อกเวลาตรงกันเป๊ะ ไม่เหลื่อมหลุดแคช
                cmd_remux = (
                    f'ffmpeg -y -fflags +genpts -i "{video_path}" '
                    f'-c:v copy -c:a copy -async 1 -vsync passthrough '
                    f'-movflags +faststart "{temp_static_video}"'
                )
            
            remux_res = subprocess.run(cmd_remux, shell=True, capture_output=True)
            
            if remux_res.returncode != 0:
                logger.warning("⚠️ ไม่สามารถทำการ Remux ขั้นสูงได้ กำลังคัดลอกไฟล์แบบดิบ...")
                shutil.copy(video_path, dest_static_video)
            else:
                if os.path.exists(temp_static_video):
                    shutil.move(temp_static_video, dest_static_video)

        # สั่งให้ระบบถอดความคำพูดออกมาก่อนเพื่อนำค่าไปเทียบความคล้ายคลึง
        current_stage = "transcription"
        check_cancellation_checkpoint(job_id, db)
        record_timeline_stage(job_id, "transcribe", "started")
        t_trans_start = time.time()
        # Define progress callback and cancellation checker lambdas
        def progress_callback(batch_index: int, total_batches: int, attempt: int, completed_segs: int, total_segs: int, msg: str):
            progress_percent = 50 + int((batch_index / total_batches) * 25) # 50% to 75%
            if job_id in JOBS_DATA:
                JOBS_DATA[job_id]["stage"] = "transcription"
                JOBS_DATA[job_id]["current_batch"] = batch_index
                JOBS_DATA[job_id]["total_batches"] = total_batches
                JOBS_DATA[job_id]["current_attempt"] = attempt
                JOBS_DATA[job_id]["completed_segments"] = completed_segs
                JOBS_DATA[job_id]["total_segments"] = total_segs
                JOBS_DATA[job_id]["stage_message"] = msg
            try:
                update_job_status(job_id, "processing", progress_percent)
            except Exception:
                pass
                
        def cancel_check_fn():
            check_cancellation_checkpoint(job_id, db)

        transcript_engine = TranscriptEngine(preferred_model=selected_model)
        transcript_result = transcript_engine.transcribe_audio(
            audio_path, 
            cache_dir=job_work_dir,
            job_id=job_id,
            progress_callback=progress_callback,
            cancel_check_fn=cancel_check_fn
        )
        metrics.record_duration("transcription", time.time() - t_trans_start)
        if job_id in JOBS_DATA and hasattr(transcript_engine, 'token_telemetry'):
            from utils.telemetry import merge_token_usage
            merge_token_usage(JOBS_DATA[job_id]["token_usage"], transcript_engine.token_telemetry)
        real_timeline = transcript_result["timeline"]
        metadata = transcript_result["metadata"]

        JOBS_DATA[job_id]["warnings"] = []
        integrity = metadata.get("integrity_percent", 100.0)
        failed_chunks = metadata.get("failed_segment_ids", [])
        
        if integrity < 70:
            error_msg = f"🚨 ระบบถอดความล้มเหลวโดยสิ้นเชิง ({integrity}%): Failed chunks indexes: {failed_chunks}"
            logger.error(error_msg, extra={"error_category": "TRANSCRIPTION_ERROR"})
            update_job_status(job_id, "failed", 50, error=error_msg)
            return
        elif integrity < 100:
            warning_msg = f"⚠️ ระบบถอดความคำพูดไม่สมบูรณ์ ({integrity}%): Failed chunks indexes: {failed_chunks}"
            logger.warning(warning_msg)
            JOBS_DATA[job_id]["warnings"].append(warning_msg)

        formatted_text_lines = [f"{item['label']} - {item['text']}" for item in real_timeline if item.get("status") != "failed" and "text" in item]
        
        update_job_status(job_id, "processing", 75)

        # 🎯 [วิธีที่ 5 & 6]: เปรียบเทียบข้อความถอดความ (Transcript Similarity) เกิน 95% กับคลังข้อมูลเดิม
        current_full_text = "".join([item['text'] for item in real_timeline if item.get("status") != "failed" and "text" in item])
        duplicate_found_id = None
        
        for existing_file in os.listdir(HISTORY_DIR):
            if existing_file.endswith(".json") and existing_file.startswith("local_"):
                try:
                    with open(os.path.join(HISTORY_DIR, existing_file), "r", encoding="utf-8") as old_f:
                        old_data = json.load(old_f)
                        old_timeline = old_data.get("timeline", [])
                        old_full_text = "".join([item['text'] for item in old_timeline if item.get("status") != "failed" and "text" in item])
                        
                        # คำนวณหาค่าอัตราความคล้ายคลึงระหว่างข้อความเก่ากับข้อความใหม่
                        similarity_ratio = difflib.SequenceMatcher(None, current_full_text, old_full_text).ratio()
                        
                        if similarity_ratio >= 0.95:
                            duplicate_found_id = existing_file.replace(".json", "")
                            logger.info(f"💡 [Transcript Match] ตรวจพบข้อความเหมือนกัน {similarity_ratio*100:.2f}% กับไฟล์เก่าไอดี: {duplicate_found_id}")
                            break
                except Exception:
                    continue

        if duplicate_found_id:
            logger.info(f"🎯 ผูกฐานข้อมูลและดึงประวัติเก่าของไอดี {duplicate_found_id} ขึ้นแดชบอร์ดทันที...")
            with open(os.path.join(HISTORY_DIR, f"{duplicate_found_id}.json"), "r", encoding="utf-8") as h_file:
                saved_result = json.load(h_file)
            
            if os.path.exists(video_path): os.remove(video_path)
            if os.path.exists(audio_path): os.remove(audio_path)
            
            # Persist Cache Reuse to Database
            from services.analysis_history_service import persist_cache_reuse_record
            try:
                persist_cache_reuse_record(
                    db=db,
                    user_id=u_id,
                    media_key=duplicate_found_id,
                    source_type=mode,
                    result_json=saved_result,
                    job_id=job_id,
                    source_url=youtube_url,
                    original_filename=file_name,
                    model_used=selected_model or "gemini-2.5-flash",
                    duration_seconds=saved_result.get("duration_seconds")
                )
            except Exception as persist_ex:
                logger.error(f"Error persisting cache reuse for job {job_id}: {persist_ex}")

            JOBS_DATA[job_id]["result"] = saved_result
            JOBS_DATA[job_id]["status"] = "completed"
            JOBS_DATA[job_id]["progress"] = 100
            JOBS_DATA[job_id]["terminal_at"] = time.time()
            JOBS_DATA[job_id]["completed_at"] = time.time()
            record_timeline_stage(job_id, "completed", "finished")
            metrics.inc("cache_hits")
            metrics.dec("jobs_running")
            metrics.inc("jobs_completed")
            return

        # ----------------------------------------------------
        # 5. ส่งวิเคราะห์ชุดโครงสร้าง 8 โมดูลหลักแบบ Dynamic
        # ----------------------------------------------------
        current_stage = "ai_analysis"
        check_cancellation_checkpoint(job_id, db)
        record_timeline_stage(job_id, "analysis", "started")
        t_ai_start = time.time()
        logger.info("ส่งข้อมูลคำพูดจริงเข้าสู่กระบวนการวิเคราะห์ 8 โมดูลหลักยุทธศาสตร์...")
        
        strategic_prompt = (
            "คุณคือผู้เชี่ยวชาญด้านการวิเคราะห์สื่อระดับองค์กร\n\n"

            "หน้าที่ของคุณคือวิเคราะห์ข้อมูลจากข้อความถอดเสียงเท่านั้น\n\n"

            "กฎสำคัญ:\n"
            "1. ห้ามลบข้อความต้นฉบับ\n"
            "2. ห้ามย่อข้อความต้นฉบับ\n"
            "3. ห้ามสรุปข้อความต้นฉบับก่อนวิเคราะห์\n"
            "4. ห้ามเปลี่ยนความหมายของคำพูด\n"
            "5. ห้ามเติมข้อมูลที่ไม่มีอยู่ในคลิป\n"
            "6. ใช้ข้อมูลจากข้อความถอดเสียงจริงเท่านั้น\n"
            "7. หากพบคำสะกดผิด ให้ใช้ความหมายเดิมในการวิเคราะห์ แต่ห้ามแก้ไขข้อความต้นฉบับ\n"
            "9. หากคลิปยาวเกิน 10 นาที ต้องมีอย่างน้อย 4 หัวข้อหลัก (Chapters)\n"
            "10. หากคลิปยาวเกิน 20 นาที ต้องมีอย่างน้อย 6 หัวข้อหลัก (Chapters)\n"
            "11. แต่ละหัวข้อหลักต้องมีหัวข้อย่อย (sub_chapters) อย่างน้อย 2 รายการ\n"
            "12. ต้องใช้ข้อมูลจากข้อความถอดเสียงจริงเท่านั้น ห้ามสร้างข้อมูลเท็จ\n\n"

            "ภารกิจคือสร้างผลการวิเคราะห์จากข้อความเท่านั้น โดยข้อความต้นฉบับต้องถือเป็นข้อมูลอ้างอิงที่ห้ามเปลี่ยนแปลง\n\n"

            "ตอบกลับเฉพาะ JSON ตาม Schema ด้านล่าง\n"

            "{\n"
            "  \"summary\": [\"บทสรุปประเด็นหลักประโยคยาวที่ได้ใจความจากคลิปจริง 3-5 บรรทัด\"],\n"
            "  \"keyword_trending\": [{\"keyword\": \"คำสำคัญที่เจอในคลิป\", \"count\": จำนวนครั้งที่เจอ}],\n"
            "  \"sentiment_analysis\": [{\"time_range\": \"ช่วงเวลา\", \"sentiment\": \"อารมณ์\", \"trigger\": \"ปัจจัยกระตุ้น\", \"purpose\": \"เป้าหมายคำพูด\"}],\n"
            "  \"dominant_sentiment_summary\": \"บทสรุปภาพรวมบรรยากาศทางจิตวิทยาของคลิปนี้\",\n"
            "  \"video_chapters\": [{\"start_time_seconds\": วินาที, \"chapter_title\": \"ชื่อบทเรียนย่อยจากคลิปจริง\", \"sub_chapters\": [{\"start_time_seconds\": วินาที, \"sub_title\": \"หัวข้อย้อย\"}]}]\n"
            "}"
        )

        local_ai_engine = AIAnalysisEngine(api_key=GEMINI_API_KEY, preferred_model=selected_model)
        ai_analysis_raw = local_ai_engine.generate_analytics(strategic_prompt, formatted_text_lines)
        successful_model = local_ai_engine.successful_model
        metrics.record_duration("ai_analysis", time.time() - t_ai_start)
        if job_id in JOBS_DATA and hasattr(local_ai_engine, 'token_telemetry'):
            from utils.telemetry import merge_token_usage
            merge_token_usage(JOBS_DATA[job_id]["token_usage"], local_ai_engine.token_telemetry)
        
        if not ai_analysis_raw:
            logger.error("🚨 AI analysis returned empty response.")
            update_job_status(job_id, "failed", 75, error="AI Analysis engine failed")
            return
            
        ai_analysis_data = {}
        if isinstance(ai_analysis_raw, dict):
            ai_analysis_data = ai_analysis_raw
        elif isinstance(ai_analysis_raw, str):
            try:
                ai_analysis_data = json.loads(ai_analysis_raw)
            except Exception as e:
                logger.error(f"Error parsing AI Analysis response string: {e}")
                update_job_status(job_id, "failed", 75, error=f"AI Analysis parsing error: {e}")
                return

        # 6. คำนวณมาตรวัดเชิงสถิติ
        total_words = sum(len(item.get("text", "").split()) for item in real_timeline)
        total_sentences = sum(item.get("text", "").count(".") + item.get("text", "").count("?") + 1 for item in real_timeline)
        duration_mins = (real_timeline[-1]["end"] / 60.0) if real_timeline else 1.0
        wpm_calc = f"{int(total_words / duration_mins)} คำ/นาที"

        # 🎯 [Fallback Mechanism]: หาก AI ส่ง video_chapters น้อยกว่า 3 หรือว่าง ให้สร้าง fallback chapters จาก timeline จริง
        has_chapters = ai_analysis_data and ai_analysis_data.get("video_chapters") and len(ai_analysis_data.get("video_chapters")) >= 3
        
        if not has_chapters:
            logger.info("ℹ️ AI chapter ไม่เพียงพอ, กำลังรัน Fallback Chapter Generation...")
            interval = 240
            total_duration = real_timeline[-1]["end"] if real_timeline else 0
            fallback_chapters = []
            num_chapters = max(3, int(total_duration / interval) + 1)
            for i in range(num_chapters):
                start_time = i * interval
                chapter_text = [tl["text"] for tl in real_timeline if tl.get("status") != "failed" and "text" in tl and start_time <= tl["start"] < (i + 1) * interval]
                chapter_title = f"ส่วนที่ {i+1}: " + (chapter_text[0][:30] + "..." if chapter_text and len(chapter_text[0]) > 30 else (chapter_text[0] if chapter_text else "เนื้อหาช่วงนี้"))
                sub_chapters = []
                if len(chapter_text) > 1:
                    sub_chapters.append({"sub_title": chapter_text[1][:30] + "...", "start_time_seconds": start_time + 60})
                fallback_chapters.append({"start_time_seconds": start_time, "chapter_title": chapter_title, "sub_chapters": sub_chapters})
            ai_analysis_data["video_chapters"] = fallback_chapters

        # 🎯 [แก้บั๊กพิกัดเวลาเพี้ยนถาวร]: บังคับดึงพิกัดเวลาจาก Speech-to-Text ซิงค์ลงระบบบทเรียน
        synced_chapters = []
        if ai_analysis_data and ai_analysis_data.get("video_chapters"):
            for idx, ai_ch in enumerate(ai_analysis_data["video_chapters"]):
                matched_time = 0
                matched_label = "00:00"
                
                ch_title = ai_ch.get("chapter_title", "")
                clean_ch_title = re.sub(r'[^a-zA-Z0-9ก-๙]', '', ch_title)
                
                best_ratio = 0
                # ค้นหาข้อความคู่ขนาน
                for tl in real_timeline:
                    if tl.get("status") == "failed" or "text" not in tl:
                        continue
                    clean_tl_text = re.sub(r'[^a-zA-Z0-9ก-๙]', '', tl["text"])
                    ratio = difflib.SequenceMatcher(None, clean_ch_title, clean_tl_text).ratio()
                    if ratio > best_ratio:
                        best_ratio = ratio
                        matched_time = tl["start"]
                        matched_label = tl["label"]
                
                # 🛠️ [กลไกดักจับความแม่นยำด่านสุดท้าย]: ถ้าเป็นบทเรียนช่องแรก บังคับเซ็ตแกนเวลาเริ่มพูดที่ 1 วินาที (00:01) เสมอ
                if idx == 0:
                    matched_time = real_timeline[0]["start"] if real_timeline else 1
                    m, s = divmod(int(matched_time), 60)
                    h, m = divmod(m, 60)
                    matched_label = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
                elif best_ratio < 0.2:
                    ai_start = ai_ch.get("start_time_seconds", 0)
                    matched_time = max(1, ai_start - 6) if ai_start > 0 else 1
                    m, s = divmod(int(matched_time), 60)
                    h, m = divmod(m, 60)
                    matched_label = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

                # จัดการสารบัญย่อย (Sub Chapters)
                synced_subs = []
                for s_idx, sub in enumerate(ai_ch.get("sub_chapters", [])):
                    sub_time = sub.get("start_time_seconds", 0)
                    sub_label = sub.get("time_range_label", "00:00")
                    sub_title = sub.get("sub_title", "")
                    clean_sub_title = re.sub(r'[^a-zA-Z0-9ก-๙]', '', sub_title)
                    
                    sub_best_ratio = 0
                    for tl in real_timeline:
                        if tl.get("status") == "failed" or "text" not in tl:
                            continue
                        clean_tl_text = re.sub(r'[^a-zA-Z0-9ก-๙]', '', tl["text"])
                        s_ratio = difflib.SequenceMatcher(None, clean_sub_title, clean_tl_text).ratio()
                        if s_ratio > sub_best_ratio:
                            sub_best_ratio = s_ratio
                            sub_time = tl["start"]
                            m, s = divmod(int(sub_time), 60)
                            sub_label = f"{m:02d}:{s:02d}"
                    
                    if s_idx == 0 and idx == 0:
                        sub_time = matched_time
                        sub_label = matched_label
                    elif sub_best_ratio < 0.2 and sub_time > 0:
                        sub_time = max(1, sub_time - 5)
                        m, s = divmod(int(sub_time), 60)
                        sub_label = f"{m:02d}:{s:02d}"
                            
                    synced_subs.append({
                        "start_time_seconds": float(sub_time),
                        "time_range_label": sub_label,
                        "sub_title": sub_title
                    })

                synced_chapters.append({
                    "start_time_seconds": float(matched_time),
                    "time_range_label": matched_label,
                    "chapter_title": ch_title,
                    "sub_chapters": synced_subs
                })
        else:
            m, s = divmod(int(1), 60)
            synced_chapters = [{"start_time_seconds": 1, "time_range_label": f"{m:02d}:{s:02d}", "chapter_title": "บทเรียนหลักจากคลิปวิดีโอต้นฉบับ", "sub_chapters": []}]

        real_url_lower = real_url.lower()
        is_output_youtube = is_youtube
        if "tiktok.com" in real_url_lower:
            is_output_youtube = False

        # 📊 คำนวณขนาดไฟล์ที่ประมวลผลจริง และเวลาที่ใช้ในการประมวลผลทั้งหมด
        file_size_label = "วิเคราะห์จากระบบคลาวด์"
        target_file_for_size = dest_static_video if os.path.exists(dest_static_video) else video_path
        if os.path.exists(target_file_for_size):
            size_bytes = os.path.getsize(target_file_for_size)
            size_mb = size_bytes / (1024 * 1024)
            file_size_label = f"{size_mb:.2f} MB"

        # Normalize timeline for frontend compatibility
        normalized_timeline = []
        for item in real_timeline:
            normalized_item = item.copy()
            # Ensure start and end are strictly numeric floats
            normalized_item["start"] = float(item["start"])
            normalized_item["end"] = float(item["end"])
            # Mapping label to time for backward compatibility
            normalized_item["time"] = item["label"] 
            normalized_timeline.append(normalized_item)

        elapsed_seconds = time.time() - pipeline_start_time
        h = int(elapsed_seconds // 3600)
        m = int((elapsed_seconds % 3600) // 60)
        s = int(elapsed_seconds % 60)
        if h > 0:
            analysis_time_label = f"{h:02d}:{m:02d}:{s:02d}"
        else:
            analysis_time_label = f"{m:02d}:{s:02d}"

        # ดึงคำสำคัญและทำการสืบค้นวิดีโอแนะนำเชิงลึก (4-7 คลิป)
        trending_keywords = [item.get("keyword", "") for item in ai_analysis_data.get("keyword_trending", [])]
        recommended_cards = fetch_related_videos(trending_keywords, count=6)
        
        # หากไม่เจอ ให้ดีดกลับไปใช้ตัวต้นฉบับสำรองเป็น default
        if not recommended_cards:
            recommended_cards = [
                {"title": f"วิเคราะห์เจาะลึก: {unique_id}", "url": real_url if is_output_youtube else "#", "thumbnail": f"https://img.youtube.com/vi/{unique_id}/0.jpg" if is_output_youtube else "/static/Logo_boy.png"}
            ]

        final_result = {
            "is_youtube": is_output_youtube,
            "real_youtube_url": real_url,
            "video_url": f"/api/media/{unique_id}",
            "model_used": successful_model,
            "timeline": normalized_timeline, 
            "summary": ai_analysis_data.get("summary", ["วิเคราะห์โครงสร้างเนื้อหาสำเร็จ"]),
            "file_size_label": file_size_label,
            "analysis_time": analysis_time_label,
            "telemetry": {
                "duration": f"{real_timeline[-1]['label'] if real_timeline else '00:00'} นาที",
                "words": f"{total_words} คำ",
                "sentences": f"{total_sentences} ประโยค",
                "wpm": wpm_calc,
                "topics": ai_analysis_data.get("summary", [""])[0][:20] if ai_analysis_data.get("summary") else "General Analysis"
            },
            "keywords_chart": ai_analysis_data.get("keyword_trending", []),
            "sentiment_table": ai_analysis_data.get("sentiment_analysis", []),
            "dominant_sentiment": ai_analysis_data.get("dominant_sentiment_summary", "ประเมินภาพรวมความเรียบร้อยสำเร็จ"),
            "recommendations": recommended_cards,
            "video_counters": synced_chapters,
            "video_chapters": synced_chapters
        }

        # Apply normalization layer
        from utils.normalization import normalize_analysis_result
        final_result = normalize_analysis_result(final_result)

        # 💾 บันทึกผลลงคลังถาวร
        current_stage = "saving_results"
        record_timeline_stage(job_id, "persist", "started")
        if not os.path.exists(HISTORY_DIR): 
            os.makedirs(HISTORY_DIR)
            
        history_file_path = os.path.join(HISTORY_DIR, f"{unique_id}.json")
        with open(history_file_path, "w", encoding="utf-8") as h_file:
            json.dump(final_result, h_file, ensure_ascii=False, indent=4)
            
        logger.info(f"💾 ระบบทำการบันทึกประวัติสำเร็จ รหัสอ้างอิง: {unique_id}")

        # Persist completed analysis to Database using service
        from services.analysis_history_service import persist_completed_analysis
        try:
            completed_rec = persist_completed_analysis(
                db=db,
                user_id=u_id,
                job_id=job_id,
                media_key=unique_id,
                source_type=mode,
                result_json=final_result,
                source_url=youtube_url,
                original_filename=file_name,
                model_used=successful_model,
                duration_seconds=final_result.get("duration_seconds"),
                processing_seconds=elapsed_seconds,
                token_usage=JOBS_DATA.get(job_id, {}).get("token_usage")
            )
            if completed_rec and hasattr(completed_rec, "public_id"):
                JOBS_DATA[job_id]["public_id"] = completed_rec.public_id
        except Exception as persist_ex:
            logger.error(f"Error persisting completed job {job_id} to DB: {persist_ex}")

        JOBS_DATA[job_id]["result"] = final_result
        JOBS_DATA[job_id]["status"] = "completed"
        JOBS_DATA[job_id]["progress"] = 100
        JOBS_DATA[job_id]["terminal_at"] = time.time()
        JOBS_DATA[job_id]["completed_at"] = time.time()
        record_timeline_stage(job_id, "completed", "finished")
        metrics.dec("jobs_running")
        metrics.inc("jobs_completed")
        metrics.record_duration("processing", time.time() - pipeline_start_time)
        logger.info(f"✅ สำเร็จเสร็จสิ้น! นำส่งข้อมูลเข้าระบบสำเร็จ")

    except TaskCancelledException as ce:
        logger.info(f"Job {job_id} cancelled cooperatively at stage: {current_stage}")
        update_job_status(job_id, "cancelled", 100, error="Job was cancelled by user")
        metrics.dec("jobs_running")
        metrics.inc("jobs_failed")
    except TikTokDownloadError as e:
        logger.error(f"TikTok download failed for job {job_id}.")
        record_timeline_stage(job_id, "failed", "finished")
        metrics.dec("jobs_running")
        metrics.inc("jobs_failed")
        last_progress = 0
        if job_id in JOBS_DATA:
            last_progress = JOBS_DATA[job_id].get("progress", 0)
        if last_progress >= 100:
            last_progress = 99
        friendly_error = (
            "ไม่สามารถดาวน์โหลดวิดีโอจาก TikTok ได้ในขณะนี้\n"
            "TikTok อาจจำกัดหรือเปลี่ยนรูปแบบการเข้าถึงวิดีโอ\n"
            "กรุณาลองใหม่อีกครั้ง หรืออัปโหลดไฟล์ MP4 โดยตรง"
        )
        update_job_status(job_id, "failed", last_progress, error=friendly_error)
    except GeminiRateLimitedError as rate_error:
        logger.warning(
            f"Pipeline rate limited | job={job_id} | stage={current_stage} | metadata={rate_error.safe_metadata()}"
        )
        record_timeline_stage(job_id, "failed", "finished")
        metrics.dec("jobs_running")
        metrics.inc("jobs_failed")
        if job_id in JOBS_DATA:
            JOBS_DATA[job_id]["failure_reason"] = "RATE_LIMITED"
            JOBS_DATA[job_id]["rate_limit"] = rate_error.safe_metadata()
        update_job_status(job_id, "failed", 100, error=RATE_LIMITED_MESSAGE)
    except Exception as e:
        error_type = type(e).__name__
        error_detail = str(e).strip() or repr(e)
        err_cat = classify_error(e)
        logger.exception(
            f"Pipeline failed | job={job_id} | stage={current_stage} "
            f"| category={err_cat} | type={error_type} | detail={error_detail}",
            extra={"error_category": err_cat}
        )
        record_timeline_stage(job_id, "failed", "finished")
        metrics.dec("jobs_running")
        metrics.inc("jobs_failed")
        update_job_status(job_id, "failed", 100, error=f"{current_stage}: {error_type}: {error_detail}")
    finally:
        # Persist partial telemetry if job failed or was cancelled and has recorded API requests
        try:
            if job_id in JOBS_DATA:
                status_now = JOBS_DATA[job_id].get("status")
                if status_now in ("failed", "cancelled"):
                    tok_u = JOBS_DATA[job_id].get("token_usage")
                    if tok_u and tok_u.get("job_total", {}).get("requests", 0) > 0:
                        from services.analysis_history_service import record_run_history
                        record_run_history(
                            db=db,
                            user_id=u_id,
                            source_type=mode if 'mode' in locals() else "unknown",
                            result_json={"timeline": real_timeline if 'real_timeline' in locals() else []},
                            source_url=youtube_url if 'youtube_url' in locals() else None,
                            original_filename=file_name if 'file_name' in locals() else None,
                            model_used=selected_model if 'selected_model' in locals() else "gemini-2.5-flash",
                            job_id=job_id,
                            processing_seconds=time.time() - pipeline_start_time,
                            token_usage=tok_u
                        )
                        db.commit()
        except Exception as fail_tok_ex:
            logger.warning(f"Safely caught partial telemetry persistence error: {fail_tok_ex}")

        # Cleanup the entire isolated job work directory safely
        try:
            if os.path.exists(job_work_dir):
                job_status = JOBS_DATA.get(job_id, {}).get("status")
                has_checkpoints = os.path.exists(os.path.join(job_work_dir, "checkpoints"))
                if job_status == "completed" or not has_checkpoints:
                    shutil.rmtree(job_work_dir, ignore_errors=True)
                else:
                    # Clean only disposable files, preserve checkpoints
                    for item in os.listdir(job_work_dir):
                        item_path = os.path.join(job_work_dir, item)
                        if item == "checkpoints":
                            continue
                        if os.path.isdir(item_path):
                            shutil.rmtree(item_path, ignore_errors=True)
                        else:
                            try: os.remove(item_path)
                            except Exception: pass
        except Exception as clean_ex:
            logger.error(f"Error cleaning up work directory {job_work_dir}: {clean_ex}")
        db.close()

# ----------------------------------------------------
# API ENDPOINTS
# ----------------------------------------------------

# 🎯 Route ดักตรวจประวัติเก่าด่วน และคำนวณราคาประเมิน Token
@app.post("/pre_check_cache")
async def handle_pre_check_cache(
    request: Request,
    mode: str = Form(...),
    youtube_url: Optional[str] = Form(None),
    file_name: Optional[str] = Form(None),
    file_size_bytes: Optional[int] = Form(None),
    duration_seconds: Optional[float] = Form(None),
    model: Optional[str] = Form(None),
    current_user: User = Depends(require_current_user_api)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    if mode == "youtube" and youtube_url and "tiktok.com" in youtube_url.lower():
        mode = "tiktok"

    unique_id = ""
    if mode in ["youtube", "tiktok"] and youtube_url:
        unique_id = video_engine.extract_unique_video_id(youtube_url)
    elif mode in ["mp4", "file"] and file_name and file_size_bytes:
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', file_name)
        for existing_file in os.listdir(HISTORY_DIR):
            if clean_name in existing_file:
                unique_id = existing_file.replace(".json", "")
                break
        if not unique_id:
            unique_id = f"local_sha256_preview_{clean_name}"

    history_file_path = os.path.join(HISTORY_DIR, f"{unique_id}.json")
    if os.path.exists(history_file_path):
        with open(history_file_path, "r", encoding="utf-8") as h_file:
            saved_result = json.load(h_file)
        if unique_id:
            DOWNLOAD_OWNERSHIP.setdefault(unique_id, set()).add(current_user.id)

        pub_id = None
        disp_title = saved_result.get("video_title") or saved_result.get("title")
        duration_sec = saved_result.get("duration_seconds")
        db_s = SessionLocal()
        try:
            cache_obj = db_s.query(AnalysisCache).filter(AnalysisCache.media_key == unique_id).first()
            if cache_obj:
                rec_obj = db_s.query(AnalysisRecord).filter(AnalysisRecord.cache_id == cache_obj.id, AnalysisRecord.user_id == current_user.id).first()
                if not rec_obj:
                    rec_obj = db_s.query(AnalysisRecord).filter(AnalysisRecord.cache_id == cache_obj.id).first()
                if rec_obj:
                    pub_id = rec_obj.public_id
                    disp_title = rec_obj.display_title or disp_title
                    duration_sec = rec_obj.duration_seconds or duration_sec
        except Exception:
            pass
        finally:
            db_s.close()

        reanalyze_estimates = pre_run_estimator.get_all_model_estimates(duration_sec)

        return {
            "cache_exists": True,
            "result_data": saved_result,
            "public_id": pub_id,
            "display_title": disp_title,
            "duration_seconds": duration_sec,
            "source_type": mode,
            "reanalyze_estimates": reanalyze_estimates,
        }

    resolved_seconds = None
    if duration_seconds is not None and float(duration_seconds) > 0:
        resolved_seconds = float(duration_seconds)

    selected_model = model or "gemini-3.5-flash"
    selected_estimate = pre_run_estimator.estimate_pre_run(selected_model, resolved_seconds, source_type=mode)
    all_estimates = pre_run_estimator.get_all_model_estimates(resolved_seconds, source_type=mode)

    return {
        "cache_exists": False,
        "duration_seconds": resolved_seconds,
        "duration_formatted": selected_estimate["duration_formatted"],
        "duration_label": selected_estimate["duration_formatted"],
        "selected_model": selected_model,
        "estimate": selected_estimate,
        "all_estimates": all_estimates,
        "eligible_runs_count": pre_run_estimator.eligible_historical_runs_count,
        "estimated_tokens": selected_estimate["tokens_expected"],
        "estimated_cost_baht": selected_estimate["cost_expected_thb"],
    }

@app.api_route("/api/pre_run_estimate", methods=["GET", "POST"])
async def get_pre_run_estimate_api(
    request: Request,
    model: Optional[str] = Form(None),
    duration_seconds: Optional[float] = Form(None),
    source_type: Optional[str] = Form(None),
    query_model: Optional[str] = Query(None, alias="model"),
    query_duration: Optional[float] = Query(None, alias="duration_seconds"),
    query_source: Optional[str] = Query(None, alias="source_type")
):
    target_model = model or query_model or "gemini-3.5-flash"
    dur_sec = duration_seconds if duration_seconds is not None else query_duration
    st_type = source_type or query_source

    if (dur_sec is None or not st_type) and request.headers.get("content-type", "").startswith("application/json"):
        try:
            body_data = await request.json()
            target_model = body_data.get("model") or target_model
            dur_sec = body_data.get("duration_seconds") if dur_sec is None else dur_sec
            st_type = body_data.get("source_type") or st_type
        except Exception:
            pass

    selected_est = pre_run_estimator.estimate_pre_run(target_model, dur_sec, source_type=st_type)
    all_ests = pre_run_estimator.get_all_model_estimates(dur_sec, source_type=st_type)
    return {
        "status": "success",
        "selected_model": target_model,
        "duration_seconds": dur_sec,
        "estimate": selected_est,
        "all_estimates": all_ests,
        "eligible_runs_count": pre_run_estimator.eligible_historical_runs_count,
    }

@app.api_route("/api/resolve_duration", methods=["GET", "POST"])
async def resolve_duration_api(
    request: Request,
    url: Optional[str] = Form(None),
    youtube_url: Optional[str] = Form(None),
    source_type: Optional[str] = Form("youtube"),
    model: Optional[str] = Form("gemini-3.5-flash"),
    query_url: Optional[str] = Query(None, alias="url"),
    query_model: Optional[str] = Query(None, alias="model"),
    query_source: Optional[str] = Query(None, alias="source_type"),
    current_user: User = Depends(require_current_user_api)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    target_url = youtube_url or url or query_url
    target_model = model or query_model or "gemini-3.5-flash"
    st_type = source_type or query_source or "youtube"

    if not target_url and request.headers.get("content-type", "").startswith("application/json"):
        try:
            body_data = await request.json()
            target_url = body_data.get("youtube_url") or body_data.get("url")
            target_model = body_data.get("model") or target_model
            st_type = body_data.get("source_type") or st_type
        except Exception:
            pass

    if not target_url or not target_url.strip():
        selected_est = pre_run_estimator.estimate_pre_run(target_model, None, source_type=st_type)
        all_ests = pre_run_estimator.get_all_model_estimates(None, source_type=st_type)
        return {
            "status": "failed",
            "reason": "Missing URL",
            "duration_seconds": None,
            "estimate": selected_est,
            "all_estimates": all_ests,
        }

    clean_url = target_url.strip()

    logger.info(f"[PRE-RUN API] incoming URL: {clean_url}")
    logger.info(f"[PRE-RUN API] source type: {st_type}")
    logger.info(f"[PRE-RUN API] python executable: {sys.executable}")

    from services.duration_service import resolve_media_metadata
    meta_res = await resolve_media_metadata(
        url=clean_url,
        source_type=st_type,
        timeout_seconds=14.0
    )

    resolved_dur = meta_res.get("duration_seconds")
    clean_url = meta_res.get("normalized_url") or clean_url
    logger.info(f"[PRE-RUN API] duration resolved: {resolved_dur}")

    selected_estimate = pre_run_estimator.estimate_pre_run(target_model, resolved_dur, source_type=st_type)
    all_estimates = pre_run_estimator.get_all_model_estimates(resolved_dur, source_type=st_type)

    return {
        "status": "success" if (resolved_dur and resolved_dur > 0) else "failed",
        "url": clean_url,
        "duration_seconds": resolved_dur,
        "duration_formatted": selected_estimate["duration_formatted"],
        "selected_model": target_model,
        "estimate": selected_estimate,
        "all_estimates": all_estimates,
        "eligible_runs_count": pre_run_estimator.eligible_historical_runs_count,
    }

@app.post("/process")
@app.post("/submit_analysis")
async def handle_analysis_submission(
    request: Request,
    background_tasks: BackgroundTasks,
    mediaMode: Optional[str] = Form(None),
    mode: Optional[str] = Form(None),
    youtubeUrl: Optional[str] = Form(None),
    youtube_url: Optional[str] = Form(None),
    localFile: Optional[UploadFile] = File(None),
    file: Optional[UploadFile] = File(None),
    model: Optional[str] = Form(None),
    current_user: User = Depends(require_current_user_api)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    final_mode = mediaMode if mediaMode else mode
    final_url = youtubeUrl if youtubeUrl else youtube_url
    final_file = localFile if localFile else file
    selected_model = validate_primary_model(model)

    if final_mode == "youtube" and final_url and "tiktok.com" in final_url.lower():
        final_mode = "tiktok"

    # Fix 1: Initialize all source-dependent variables before any conditional branch
    file_name = None
    if final_mode in ["mp4", "file"] and final_file:
        file_name = final_file.filename

    cleanup_expired_jobs()
    job_id = f"job_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    display_title = file_name or final_url or f"Media Analysis {job_id}"

    idempotency_key = request.headers.get("X-Idempotency-Key") or request.headers.get("idempotency_key")
    payload_fingerprint = f"{final_mode}:{final_url or (file_name if file_name else '')}:{selected_model}"
    
    if idempotency_key:
        idem_status, saved_res = idempotency_store.check_or_reserve(current_user.id, "submit", idempotency_key, payload_fingerprint)
        if idem_status == "CONFLICT":
            return JSONResponse(content={"detail": "Idempotency key conflict: Same key used with different payload"}, status_code=409)
        if idem_status == "REPLAY":
            return JSONResponse(content=saved_res or {"job_id": "replay", "queued": True})

    if not final_mode:
        if idempotency_key: idempotency_store.release_key(current_user.id, "submit", idempotency_key)
        return JSONResponse(content={"error": "Missing mode parameter"}, status_code=400)

    # 1. Early URL destination safety check for URL mode
    if final_mode in ["youtube", "tiktok"]:
        if not final_url:
            if idempotency_key: idempotency_store.release_key(current_user.id, "submit", idempotency_key)
            return JSONResponse(content={"error": "Missing youtube_url parameter"}, status_code=400)
        if not is_safe_url(final_url):
            if idempotency_key: idempotency_store.release_key(current_user.id, "submit", idempotency_key)
            return JSONResponse(content={"detail": "Invalid or unsafe URL destination"}, status_code=400)

    # 2. Early file type validation (HTTP 415) & empty check for file mode
    ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".mp3", ".wav", ".m4a", ".aac"}
    ALLOWED_MIME_TYPES = {
        "video/mp4", "video/webm", "video/quicktime", "video/x-msvideo", "video/x-matroska",
        "audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/aac", "audio/ogg", "audio/flac",
        "application/octet-stream"
    }

    MAX_UPLOAD_SIZE = 5 * 1024 * 1024 * 1024  # 5 GB limit

    content_length_header = request.headers.get("Content-Length")
    if content_length_header:
        try:
            cl_bytes = int(content_length_header)
            if cl_bytes > MAX_UPLOAD_SIZE:
                if idempotency_key: idempotency_store.release_key(current_user.id, "submit", idempotency_key)
                return JSONResponse(
                    content={"detail": "Payload Too Large: File size exceeds maximum allowed limit of 5 GB"},
                    status_code=413
                )
        except (ValueError, TypeError):
            pass

    if final_mode in ["mp4", "file"]:
        if not final_file or not final_file.filename:
            if idempotency_key: idempotency_store.release_key(current_user.id, "submit", idempotency_key)
            return JSONResponse(content={"error": "Empty file upload"}, status_code=400)
        
        file_name = final_file.filename
        ext = os.path.splitext(file_name)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            if idempotency_key: idempotency_store.release_key(current_user.id, "submit", idempotency_key)
            return JSONResponse(
                content={"detail": f"Unsupported Media Type: Extension '{ext}' is not allowed"},
                status_code=415,
                headers={"X-Content-Type-Options": "nosniff", "X-Frame-Options": "SAMEORIGIN", "Referrer-Policy": "strict-origin-when-cross-origin"}
            )
        
        if final_file.content_type and final_file.content_type.lower() not in ALLOWED_MIME_TYPES:
            if idempotency_key: idempotency_store.release_key(current_user.id, "submit", idempotency_key)
            return JSONResponse(
                content={"detail": f"Unsupported Media Type: Content-Type '{final_file.content_type}' is not allowed"},
                status_code=415,
                headers={"X-Content-Type-Options": "nosniff", "X-Frame-Options": "SAMEORIGIN", "Referrer-Policy": "strict-origin-when-cross-origin"}
            )

        header = await final_file.read(64)
        await final_file.seek(0)
        if len(header) == 0:
            if idempotency_key: idempotency_store.release_key(current_user.id, "submit", idempotency_key)
            return JSONResponse(content={"error": "Uploaded file is empty (0 bytes)"}, status_code=400)
        if (
            header.startswith(b"MZ") or 
            header.startswith(b"\x7fELF") or 
            header.startswith(b"PK\x03\x04") or
            header.startswith(b"Rar!") or
            header.startswith(b"7z\xbc\xaf") or
            header.startswith(b"%PDF") or
            header.startswith(b"\xd0\xcf\x11\xe0")
        ):
            if idempotency_key: idempotency_store.release_key(current_user.id, "submit", idempotency_key)
            return JSONResponse(
                content={"detail": "Unsupported Media Type: Executable, document, or archive signature detected"},
                status_code=415,
                headers={"X-Content-Type-Options": "nosniff", "X-Frame-Options": "SAMEORIGIN", "Referrer-Policy": "strict-origin-when-cross-origin"}
            )

    req_id = getattr(request.state, "request_id", None)
    
    # Fix 2 & 3: Create AnalysisRecord and commit database transaction. Rollback, log traceback and return non-2xx on failure.
    from services.analysis_history_service import sanitize_display_title
    clean_title = sanitize_display_title(display_title, f"Analysis {job_id[:12]}")
    
    from utils.thumbnail_service import get_youtube_thumbnail_url
    init_thumb = get_youtube_thumbnail_url(final_url or "") if final_mode == "youtube" else None

    db_session = SessionLocal()
    db_committed = False
    try:
        db_record = AnalysisRecord(
            user_id=current_user.id,
            job_id=job_id,
            display_title=clean_title,
            source_type=final_mode,
            source_url=final_url,
            original_filename=file_name,
            thumbnail_url=init_thumb,
            status="queued",
            progress=0,
            model_used=selected_model,
            created_at=datetime.datetime.now(datetime.timezone.utc),
            updated_at=datetime.datetime.now(datetime.timezone.utc)
        )
        db_session.add(db_record)
        db_session.commit()
        db_committed = True
    except Exception as db_ex:
        db_session.rollback()
        logger.exception(f"Error creating queued job record in DB for job_id {job_id}: {db_ex}")
        if idempotency_key:
            idempotency_store.release_key(current_user.id, "submit", idempotency_key)
        return JSONResponse(
            content={"detail": "Failed to persist analysis job record to database. Please try again later."},
            status_code=500
        )
    finally:
        db_session.close()

    # Confirm persisted record exists in DB
    db_check = SessionLocal()
    try:
        persisted = db_check.query(AnalysisRecord).filter(AnalysisRecord.job_id == job_id).first()
        if not persisted:
            raise Exception("Persisted record not found in database post-commit check")
    except Exception as check_ex:
        logger.exception(f"Database check post-commit failed for job_id {job_id}: {check_ex}")
        if idempotency_key:
            idempotency_store.release_key(current_user.id, "submit", idempotency_key)
        try:
            db_check.query(AnalysisRecord).filter(AnalysisRecord.job_id == job_id).delete()
            db_check.commit()
        except Exception:
            pass
        return JSONResponse(
            content={"detail": "Failed to verify database persistence for the analysis job."},
            status_code=500
        )
    finally:
        db_check.close()

    # 2. Update JOBS_DATA in memory
    JOBS_DATA[job_id] = {
        "status": "queued",
        "progress": 0,
        "result": None,
        "user_id": current_user.id,
        "created_at": time.time(),
        "request_id": req_id,
        "mode": final_mode,
        "url": final_url,
        "filename": file_name,
        "selected_model": selected_model,
        "source_type": derive_media_type_display(final_mode, final_url, file_name)
    }
    
    try:
        record_timeline_stage(job_id, "queued", "started")
        record_audit_event("analysis_submission", user_id=current_user.id, details={"job_id": job_id, "mode": final_mode})
        logger.info(f"ลงทะเบียนคำขอผ่าน Route รหัสงาน: {job_id}")

        if final_mode in ["youtube", "tiktok"] and final_url:
            u_id = video_engine.extract_unique_video_id(final_url)
            if u_id:
                DOWNLOAD_OWNERSHIP.setdefault(u_id, set()).add(current_user.id)

        file_bytes = None
        if final_mode in ["mp4", "file"] and final_file:
            # Stream the upload file to disk chunk-by-chunk to keep memory usage low
            job_work_dir = os.path.join(CACHE_DIR, job_id)
            os.makedirs(job_work_dir, exist_ok=True)
            temp_upload_path = os.path.join(job_work_dir, "upload_raw.tmp")
            hasher = hashlib.sha256()
            total_bytes_written = 0
            try:
                with open(temp_upload_path, "wb") as buffer:
                    while True:
                        chunk = await final_file.read(1024 * 1024) # 1 MB chunk
                        if not chunk:
                            break
                        total_bytes_written += len(chunk)
                        if total_bytes_written > MAX_UPLOAD_SIZE:
                            buffer.close()
                            if os.path.exists(temp_upload_path):
                                try: os.remove(temp_upload_path)
                                except Exception: pass
                            if os.path.exists(job_work_dir):
                                try: shutil.rmtree(job_work_dir)
                                except Exception: pass
                            try:
                                db_del = SessionLocal()
                                db_del.query(AnalysisRecord).filter(AnalysisRecord.job_id == job_id).delete()
                                db_del.commit()
                                db_del.close()
                            except Exception: pass
                            JOBS_DATA.pop(job_id, None)
                            if idempotency_key: idempotency_store.release_key(current_user.id, "submit", idempotency_key)
                            return JSONResponse(
                                content={"detail": "Payload Too Large: File size exceeds maximum allowed limit of 5 GB"},
                                status_code=413
                            )
                        hasher.update(chunk)
                        buffer.write(chunk)
                
                # Compute SHA-256 digest
                file_hash = hasher.hexdigest()
                
                # Preserve the original extension
                ext = os.path.splitext(file_name)[1].lower() if file_name else ".mp4"
                if ext not in ALLOWED_EXTENSIONS:
                    ext = ".mp4"
                
                # Generate local media identifier in the form: local_sha256_<digest><ext>
                temp_video_path = os.path.join(job_work_dir, f"local_sha256_{file_hash}{ext}")
                
                # Path Traversal Check: ensure final resolved path is strictly within CACHE_DIR
                real_temp_video = os.path.realpath(temp_video_path)
                real_cache_dir = os.path.realpath(CACHE_DIR)
                if not real_temp_video.startswith(real_cache_dir):
                    if os.path.exists(temp_upload_path):
                        try: os.remove(temp_upload_path)
                        except Exception: pass
                    if os.path.exists(job_work_dir):
                        try: shutil.rmtree(job_work_dir)
                        except Exception: pass
                    try:
                        db_del = SessionLocal()
                        db_del.query(AnalysisRecord).filter(AnalysisRecord.job_id == job_id).delete()
                        db_del.commit()
                        db_del.close()
                    except Exception: pass
                    JOBS_DATA.pop(job_id, None)
                    if idempotency_key: idempotency_store.release_key(current_user.id, "submit", idempotency_key)
                    return JSONResponse(content={"detail": "Invalid path destination: Path traversal rejected"}, status_code=400)

                # Move file atomically
                if os.path.exists(temp_upload_path):
                    shutil.move(temp_upload_path, temp_video_path)

                # Validate media content with ffprobe before enqueuing pipeline
                is_valid_media, ffprobe_reason = validate_uploaded_media_ffprobe(temp_video_path)
                if not is_valid_media:
                    if os.path.exists(temp_video_path):
                        try: os.remove(temp_video_path)
                        except Exception: pass
                    if os.path.exists(job_work_dir):
                        try: shutil.rmtree(job_work_dir)
                        except Exception: pass
                    try:
                        db_del = SessionLocal()
                        db_del.query(AnalysisRecord).filter(AnalysisRecord.job_id == job_id).delete()
                        db_del.commit()
                        db_del.close()
                    except Exception: pass
                    JOBS_DATA.pop(job_id, None)
                    if idempotency_key: idempotency_store.release_key(current_user.id, "submit", idempotency_key)
                    return JSONResponse(
                        content={"detail": f"Unsupported Media Type: {ffprobe_reason}"},
                        status_code=415
                    )
                
                file_bytes = temp_video_path
            except Exception as stream_ex:
                if isinstance(stream_ex, HTTPException):
                    raise stream_ex
                # Clean up partial files if upload fails
                if os.path.exists(temp_upload_path):
                    try: os.remove(temp_upload_path)
                    except Exception: pass
                if os.path.exists(job_work_dir):
                    try: shutil.rmtree(job_work_dir)
                    except Exception: pass
                raise stream_ex

        background_tasks.add_task(
            enterprise_processing_pipeline, 
            job_id, 
            final_mode, 
            final_url, 
            file_bytes, 
            file_name,
            selected_model
        )
    except Exception as pipeline_ex:
        logger.exception(f"Error submitting background task for job_id {job_id}: {pipeline_ex}")
        
        # Mark the job failed truthfully in-memory
        JOBS_DATA[job_id] = {
            "status": "failed",
            "progress": 100,
            "error": f"Upload or initialization failed: {pipeline_ex}",
            "terminal_at": time.time(),
            "failed_at": time.time(),
            "user_id": current_user.id,
            "created_at": time.time(),
            "request_id": req_id,
            "mode": final_mode,
            "url": final_url,
            "filename": file_name,
            "source_type": derive_media_type_display(final_mode, final_url, file_name)
        }
        
        # Mark the job failed truthfully in DB
        db_cleanup = SessionLocal()
        try:
            db_rec = db_cleanup.query(AnalysisRecord).filter(AnalysisRecord.job_id == job_id).first()
            if db_rec:
                db_rec.status = "failed"
                db_rec.updated_at = datetime.datetime.now(datetime.timezone.utc)
                db_cleanup.commit()
        except Exception as clean_ex:
            logger.error(f"Error marking database record as failed after submit failure: {clean_ex}")
        finally:
            db_cleanup.close()
            
        if idempotency_key:
            idempotency_store.release_key(current_user.id, "submit", idempotency_key)
            
        return JSONResponse(
            content={"detail": "Failed to initialize and start the background analysis task.", "error": str(pipeline_ex)},
            status_code=500
        )

    resp_data = {"job_id": job_id, "queued": True}
    if idempotency_key:
        idempotency_store.record_response(current_user.id, "submit", idempotency_key, resp_data)

    return JSONResponse(content=resp_data)

@app.get("/job_status/{job_id}")
async def check_job_status(job_id: str, current_user: User = Depends(require_current_user_api)):
    job = get_owned_job_or_404(job_id, current_user.id)
    return JSONResponse(content=job)

@app.post("/translate_timeline")
async def handle_pivot_translation(
    request: Request,
    target_lang: str = Form(...),
    transcript_text: str = Form(...),
    current_user: User = Depends(require_current_user_api)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    prompt = f"แปลข้อความในลิสต์นี้เป็นภาษา {target_lang} โดยคงรักษาโครงสร้างเวลาเดิมไว้อย่างเคร่งครัด"
    text_array = transcript_text.split("\n")
    # instantiate locally to avoid global ai_engine
    local_ai_engine = AIAnalysisEngine(api_key=GEMINI_API_KEY)
    translation_result = local_ai_engine.generate_analytics(prompt, text_array)
    if translation_result:
        return JSONResponse(content={ "translated_lines": translation_result if isinstance(translation_result, list) else [] })
    return JSONResponse(content={"error": "ระบบแปลภาษาขัดข้อง"}, status_code=500)

# ----------------------------------------------------
# DOWNLOAD REPORT ENDPOINTS (โมดูลที่ 9: ดาวน์โหลดผลลัพธ์)
# ----------------------------------------------------
@app.get("/download/txt/{unique_id}")
async def download_txt_report(
    unique_id: str,
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db)
):
    verify_download_ownership(unique_id, current_user.id, db=db)
    record_audit_event("download", user_id=current_user.id, details={"record_id": unique_id, "format": "txt"})
    history_file_path = os.path.join(HISTORY_DIR, f"{unique_id}.json")
    if not os.path.exists(history_file_path):
        rec = db.query(AnalysisRecord).filter(
            AnalysisRecord.public_id == unique_id,
            AnalysisRecord.user_id == current_user.id
        ).first()
        if rec and rec.cache_id:
            cache = db.query(AnalysisCache).filter(AnalysisCache.id == rec.cache_id).first()
            if cache and cache.media_key:
                alt_path = os.path.join(HISTORY_DIR, f"{cache.media_key}.json")
                if os.path.exists(alt_path):
                    history_file_path = alt_path

    if not os.path.exists(history_file_path):
        return HTMLResponse(content="<h3>❌ ไม่พบข้อมูลประวัติการประมวลผลสำหรับรหัสอ้างอิงนี้</h3>", status_code=404)
        
    try:
        with open(history_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        from utils.normalization import normalize_analysis_result
        data = normalize_analysis_result(data)
            
        timeline = data.get("timeline", [])
        real_url = data.get("real_youtube_url", "Local File Upload")
        duration = data.get("telemetry", {}).get("duration", "ไม่ทราบความยาว")
        
        # ประกอบไฟล์ข้อความตามมาตรฐานของผู้ใช้
        txt_content = []
        txt_content.append("==========================================================")
        txt_content.append("           YAMASEE MULTIMEDIA PLATFORM REPORT")
        txt_content.append(f" แหล่งอ้างอิงมีเดีย: {real_url}")
        txt_content.append(f" ความยาววิดีโอ: {duration}")
        txt_content.append(f" วันที่ดาวน์โหลดเอกสาร: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        txt_content.append("==========================================================\n")
        
        from utils.normalization import extract_segment_timestamps, format_time_range

        for item in timeline:
            start, end = extract_segment_timestamps(item)
            if start is not None or end is not None:
                label = format_time_range(start, end)
            else:
                lbl = item.get("label", "") or item.get("time", "") or item.get("timestamp", "")
                label = str(lbl).replace("[", "").replace("]", "")
                if "speaker" in label.lower():
                    label = ""
            
            if label:
                txt_content.append(f"[{label}] {item.get('text', '')}")
            else:
                txt_content.append(f"{item.get('text', '')}")
            
        final_txt = "\n".join(txt_content)
        
        return Response(
            content=final_txt,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=yamasee_transcript_{unique_id}.txt"}
        )
    except Exception as e:
        logger.error(f"เกิดข้อผิดพลาดในการสร้างไฟล์ .txt: {e}")
        return JSONResponse(content={"error": f"ระบบประมวลผลข้อความขัดข้อง: {e}"}, status_code=500)


@app.get("/download/pdf/{unique_id}")
async def download_pdf_report(
    unique_id: str,
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db)
):
    verify_download_ownership(unique_id, current_user.id, db=db)
    record_audit_event("download", user_id=current_user.id, details={"record_id": unique_id, "format": "pdf"})
    history_file_path = os.path.join(HISTORY_DIR, f"{unique_id}.json")
    if not os.path.exists(history_file_path):
        rec = db.query(AnalysisRecord).filter(
            AnalysisRecord.public_id == unique_id,
            AnalysisRecord.user_id == current_user.id
        ).first()
        if rec and rec.cache_id:
            cache = db.query(AnalysisCache).filter(AnalysisCache.id == rec.cache_id).first()
            if cache and cache.media_key:
                alt_path = os.path.join(HISTORY_DIR, f"{cache.media_key}.json")
                if os.path.exists(alt_path):
                    history_file_path = alt_path

    if not os.path.exists(history_file_path):
        return HTMLResponse(content="<h3>❌ ไม่พบข้อมูลประวัติการประมวลผลสำหรับรหัสอ้างอิงนี้</h3>", status_code=404)
        
    try:
        with open(history_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        from utils.normalization import normalize_analysis_result
        data = normalize_analysis_result(data)
            
        timeline = data.get("timeline", [])
        real_url = data.get("real_youtube_url", "Local File Upload")
        duration = data.get("telemetry", {}).get("duration", "ไม่ทราบความยาว")
        summary_sentences = data.get("summary", ["วิเคราะห์ข้อมูลสมบูรณ์"])
        
        # ค้นหาและลงทะเบียนฟอนต์ภาษาไทยของ Windows (Tahoma) เพื่อสยบบั๊กตัวอักษรสระไทยเพี้ยน
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        
        font_name = 'Helvetica'
        font_name_bold = 'Helvetica-Bold'
        
        try:
            pdfmetrics.registerFont(TTFont('Tahoma', 'C:\\Windows\\Fonts\\tahoma.ttf'))
            pdfmetrics.registerFont(TTFont('Tahoma-Bold', 'C:\\Windows\\Fonts\\tahomabd.ttf'))
            font_name = 'Tahoma'
            font_name_bold = 'Tahoma-Bold'
            logger.info("🎯 ลงทะเบียนฟอนต์ภาษาไทย Tahoma บน Windows สำเร็จเรียบร้อยสำหรับ PDF")
        except Exception as font_err:
            logger.warning(f"⚠️ ไม่สามารถดึงฟอนต์ Tahoma ได้ ระบบจะรันฟอนต์มาตรฐานแทน: {font_err}")
            
        # สร้างบัฟเฟอร์หน่วยความจำชั่วคราวเพื่อตอบกลับเป็นไบต์สตรีมทันที
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, 
            pagesize=A4, 
            rightMargin=36, leftMargin=36, 
            topMargin=36, bottomMargin=36
        )
        
        story = []
        styles = getSampleStyleSheet()
        
        # สร้าง Custom Styles สำหรับ Tahoma ภาษาไทย
        title_style = ParagraphStyle(
            'ThaiTitle',
            parent=styles['Heading1'],
            fontName=font_name_bold,
            fontSize=18,
            leading=22,
            textColor=colors.HexColor('#2563EB'),
            alignment=1, # กึ่งกลาง
            spaceAfter=15
        )
        
        section_style = ParagraphStyle(
            'ThaiSection',
            parent=styles['Heading2'],
            fontName=font_name_bold,
            fontSize=13,
            leading=16,
            textColor=colors.HexColor('#FF9A00'),
            spaceBefore=15,
            spaceAfter=10,
            borderPadding=4
        )
        
        body_style = ParagraphStyle(
            'ThaiBody',
            parent=styles['Normal'],
            fontName=font_name,
            fontSize=10,
            leading=15,
            textColor=colors.HexColor('#334155'),
            spaceAfter=6
        )
        
        meta_label_style = ParagraphStyle(
            'ThaiMetaLabel',
            fontName=font_name_bold,
            fontSize=9,
            leading=12,
            textColor=colors.HexColor('#475569')
        )
        
        meta_val_style = ParagraphStyle(
            'ThaiMetaVal',
            fontName=font_name,
            fontSize=9,
            leading=12,
            textColor=colors.HexColor('#0F172A')
        )
        
        # 1. หัวเรื่องหลักรายงานเชิงสถิติพรีเมียม
        story.append(Paragraph("YAMASEE TRANSCRIPT EXECUTIVE REPORT", title_style))
        story.append(Spacer(1, 10))
        
        # 2. ตารางตารางข้อมูลรายละเอียด (Metadata Table)
        meta_data = [
            [Paragraph("<b>แหล่งที่มาของสื่อ (Media Source):</b>", meta_label_style), Paragraph(real_url, meta_val_style)],
            [Paragraph("<b>ความยาวของคลิปวิดีโอ:</b>", meta_label_style), Paragraph(duration, meta_val_style)],
            [Paragraph("<b>รหัสอ้างอิงระบบ (Reference ID):</b>", meta_label_style), Paragraph(unique_id, meta_val_style)],
            [Paragraph("<b>วันที่สกัดข้อมูลยุทธศาสตร์:</b>", meta_label_style), Paragraph(time.strftime('%Y-%m-%d %H:%M:%S'), meta_val_style)]
        ]
        
        meta_table = Table(meta_data, colWidths=[150, 370])
        meta_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#E2E8F0')),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#F1F5F9')),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('LEFTPADDING', (0,0), (-1,-1), 12),
            ('RIGHTPADDING', (0,0), (-1,-1), 12),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        
        story.append(meta_table)
        story.append(Spacer(1, 15))
        
        # 3. บทสรุปยุทธศาสตร์ (Executive Summary)
        story.append(Paragraph("💡 บทสรุปวิเคราะห์เนื้อหายุทธศาสตร์ (Executive Summary)", section_style))
        summary_text = " ".join(summary_sentences)
        story.append(Paragraph(summary_text, body_style))
        story.append(Spacer(1, 15))
        
        # 4. ส่วนตารางหลัก (Transcription Timeline Table)
        story.append(Paragraph("📊 รายการตารางเวลาถอดความคำพูด (Detailed Transcription Timeline)", section_style))
        
        # กำหนดหน้าตาสไตล์ตารางรายงาน
        table_style = TableStyle([
            ('BACKGROUND', (0, 0), (1, 0), colors.HexColor('#1E293B')),
            ('TEXTCOLOR', (0, 0), (1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#CBD5E1')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ])
        
        table_header_time_style = ParagraphStyle(
            'HeaderTime',
            fontName=font_name_bold,
            fontSize=10,
            leading=12,
            textColor=colors.white
        )
        
        table_header_text_style = ParagraphStyle(
            'HeaderText',
            fontName=font_name_bold,
            fontSize=10,
            leading=12,
            textColor=colors.white
        )
        
        table_body_time_style = ParagraphStyle(
            'BodyTime',
            fontName=font_name_bold,
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor('#2563EB')
        )
        
        table_body_text_style = ParagraphStyle(
            'BodyText',
            fontName=font_name,
            fontSize=9.5,
            leading=14,
            textColor=colors.HexColor('#1E293B')
        )
        
        table_rows = [
            [Paragraph("เวลา (Timestamp)", table_header_time_style), Paragraph("ข้อความถอดความคำพูด (Transcription Timeline)", table_header_text_style)]
        ]
        
        from utils.normalization import extract_segment_timestamps, format_time_range

        # วนลูปข้อมูล timeline เพื่อสร้างคอลัมน์ของตาราง
        for row in timeline:
            start, end = extract_segment_timestamps(row)
            if start is not None or end is not None:
                lbl = format_time_range(start, end)
            else:
                lbl = row.get("label", "") or row.get("time", "") or row.get("timestamp", "")
                lbl = str(lbl).replace("[", "").replace("]", "")
                if "speaker" in lbl.lower():
                    lbl = ""
            txt = row.get("text", "")
            table_rows.append([
                Paragraph(lbl, table_body_time_style),
                Paragraph(txt, table_body_text_style)
            ])
            
        # สร้างวัตถอร์ตารางและกำหนดความกว้างคอลัมน์ (เวลา 90pt, ข้อความ 430pt)
        trans_table = Table(table_rows, colWidths=[90, 430], repeatRows=1)
        trans_table.setStyle(table_style)
        
        story.append(trans_table)
        
        # ประกอบโครงร่างลงเอกสาร PDF
        doc.build(story)
        
        # ส่งข้อมูลคืนเป็นไบต์ไฟล์กลับไปยังเบราว์เซอร์เพื่อให้ผู้ใช้บันทึก
        buffer.seek(0)
        return StreamingResponse(
            buffer, 
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=yamasee_report_{unique_id}.pdf"}
        )
    except Exception as e:
        logger.error(f"เกิดข้อผิดพลาดในการสร้างรายงาน PDF: {e}")
        return HTMLResponse(content=f"<h3>❌ ระบบไม่สามารถประมวลผลสร้างรายงาน PDF ได้: {e}</h3>", status_code=500)

if __name__ == "__main__":
    import uvicorn
    logger.info("กำลังสตาร์ทระบบ YAMASEE Transcript Real Platform Systems...")
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)
