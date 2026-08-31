import re
import json
import logging
import math
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any, Tuple, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from models.analysis_cache import AnalysisCache
from models.analysis_record import AnalysisRecord, utc_now
from models.user import User
from models.analysis_run_history import AnalysisRunHistory

logger = logging.getLogger("yamasee.analysis_history_service")

class InvalidStateTransitionException(Exception):
    pass

def validate_state_transition(current_status: str, next_status: str):
    """
    Validates state transitions for analysis records / jobs.
    Allowed transitions:
      - queued -> processing
      - queued -> cancelled
      - processing -> completed
      - processing -> failed
      - processing -> cancelled
      - failed -> queued (only via explicit retry)
      - cancelled -> queued (only via explicit retry)
    """
    if current_status == next_status:
        return
        
    allowed = {
        "queued": {"processing", "cancelled"},
        "processing": {"completed", "failed", "cancelled"},
        "completed": set(), # terminal
        "failed": {"queued"},
        "cancelled": {"queued"}
    }
    
    if next_status not in allowed.get(current_status, set()):
        raise InvalidStateTransitionException(f"Invalid transition from '{current_status}' to '{next_status}'")

def sanitize_display_title(raw_title: Optional[str], default_title: str = "Analysis Report") -> str:
    if not raw_title or not raw_title.strip():
        return default_title
    cleaned = raw_title.strip()
    return cleaned[:255]

def get_or_create_analysis_cache(
    db: Session,
    media_key: str,
    source_type: str,
    result_json: dict[str, Any],
    source_url: Optional[str] = None,
    original_filename: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    model_used: Optional[str] = None,
) -> AnalysisCache:
    """
    Retrieves an existing AnalysisCache by media_key or creates a new one.
    Updates last_accessed_at timestamp on match.
    Idempotent and handles concurrent insertion race conditions via IntegrityError rollback.
    """
    cache = db.query(AnalysisCache).filter(AnalysisCache.media_key == media_key).first()
    if cache:
        cache.last_accessed_at = utc_now()
        db.flush()
        return cache

    new_cache = AnalysisCache(
        media_key=media_key,
        source_type=source_type,
        source_url=source_url,
        original_filename=original_filename,
        duration_seconds=duration_seconds,
        model_used=model_used,
        result_json=result_json,
        created_at=utc_now(),
        updated_at=utc_now(),
        last_accessed_at=utc_now(),
    )
    try:
        db.add(new_cache)
        db.flush()
        return new_cache
    except IntegrityError:
        db.rollback()
        cache = db.query(AnalysisCache).filter(AnalysisCache.media_key == media_key).first()
        if cache:
            cache.last_accessed_at = utc_now()
            db.flush()
            return cache
        raise

def create_or_get_analysis_record(
    db: Session,
    user_id: int,
    cache_id: Optional[int],
    job_id: Optional[str],
    display_title: str,
    source_type: str,
    source_url: Optional[str] = None,
    original_filename: Optional[str] = None,
    model_used: Optional[str] = None,
    status: str = "completed",
    duration_seconds: Optional[float] = None,
    processing_seconds: Optional[float] = None,
    error_message: Optional[str] = None,
) -> AnalysisRecord:
    """
    Creates an AnalysisRecord for user_id associated with cache_id.
    Prevents duplicate entries if job_id already exists.
    Updates existing record if it already exists in queued/processing state.
    Validates user exists and is active.
    Handles concurrent insertion race conditions via IntegrityError rollback then re-query.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError(f"Persistence skipped: User ID {user_id} does not exist in database.")
    if not user.is_active:
        raise ValueError(f"Persistence skipped: User ID {user_id} is disabled.")

    if job_id:
        existing = (
            db.query(AnalysisRecord)
            .filter(AnalysisRecord.job_id == job_id)
            .first()
        )
        if existing:
            if existing.user_id != user_id:
                raise ValueError(
                    f"Job ID {job_id} already belongs to user_id {existing.user_id}, cannot create record for user_id {user_id}"
                )
            
            # If the existing record is already completed, do not overwrite it with stale processing data
            if existing.status == "completed" and status != "completed":
                return existing
                
            existing.status = status
            existing.progress = 100 if status == "completed" else (existing.progress or 0)
            if cache_id is not None:
                existing.cache_id = cache_id
            if display_title:
                existing.display_title = sanitize_display_title(display_title, f"Analysis {media_key_short(job_id)}")
            if source_url is not None:
                existing.source_url = source_url
            if original_filename is not None:
                existing.original_filename = original_filename
            if model_used is not None:
                existing.model_used = model_used
            if duration_seconds is not None:
                existing.duration_seconds = duration_seconds
            if processing_seconds is not None:
                existing.processing_seconds = processing_seconds
            if error_message is not None:
                existing.error_message = error_message
                
            existing.updated_at = utc_now()
            if status == "completed":
                existing.completed_at = utc_now()
                existing.progress = 100
            db.flush()
            return existing

    clean_title = sanitize_display_title(display_title, f"Analysis {media_key_short(job_id)}")

    record = AnalysisRecord(
        user_id=user_id,
        cache_id=cache_id,
        job_id=job_id,
        display_title=clean_title,
        source_type=source_type,
        source_url=source_url,
        original_filename=original_filename,
        duration_seconds=duration_seconds,
        status=status,
        progress=100 if status == "completed" else 0,
        model_used=model_used,
        processing_seconds=processing_seconds,
        error_message=error_message,
        created_at=utc_now(),
        updated_at=utc_now(),
        completed_at=utc_now() if status == "completed" else None,
    )
    try:
        db.add(record)
        db.flush()
        return record
    except IntegrityError as ie:
        db.rollback()
        if job_id:
            existing = (
                db.query(AnalysisRecord)
                .filter(AnalysisRecord.job_id == job_id)
                .first()
            )
            if existing:
                if existing.user_id != user_id:
                    raise IntegrityError(
                        f"Job ID {job_id} already belongs to user_id {existing.user_id}, cannot create record for user_id {user_id}",
                        params=None,
                        orig=None
                    )
                # Apply update to the rollback-retrieved existing record
                if not (existing.status == "completed" and status != "completed"):
                    existing.status = status
                    existing.progress = 100 if status == "completed" else (existing.progress or 0)
                    if cache_id is not None:
                        existing.cache_id = cache_id
                    if display_title:
                        existing.display_title = sanitize_display_title(display_title, f"Analysis {media_key_short(job_id)}")
                    if source_url is not None:
                        existing.source_url = source_url
                    if original_filename is not None:
                        existing.original_filename = original_filename
                    if model_used is not None:
                        existing.model_used = model_used
                    if duration_seconds is not None:
                        existing.duration_seconds = duration_seconds
                    if processing_seconds is not None:
                        existing.processing_seconds = processing_seconds
                    if error_message is not None:
                        existing.error_message = error_message
                    existing.updated_at = utc_now()
                    if status == "completed":
                        existing.completed_at = utc_now()
                        existing.progress = 100
                    db.flush()
                return existing
        raise ie

def media_key_short(val: Optional[str]) -> str:
    if not val:
        return "Report"
    return val[-8:]

from services.cost_engine import calculate_run_cost, PRICING_VERSION

def calculate_estimated_cost_v1(video_duration: float, model_used: str, token_usage: Optional[dict] = None) -> Decimal:
    """Delegates to centralized Cost Engine."""
    cost_res = calculate_run_cost(
        token_usage=token_usage,
        model_used=model_used,
        video_duration=video_duration
    )
    return cost_res["estimated_cost_decimal"]

def record_run_history(
    db: Session,
    user_id: int,
    source_type: str,
    result_json: dict[str, Any],
    source_url: Optional[str] = None,
    original_filename: Optional[str] = None,
    model_used: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    processing_seconds: Optional[float] = None,
    job_id: Optional[str] = None,
    api_calls: int = 0,
    estimated_cost: Optional[Decimal] = None,
    estimated_cost_version: str = PRICING_VERSION,
    token_usage: Optional[dict] = None,
) -> Optional[AnalysisRunHistory]:
    try:
        # Derive api_calls if 0 but token_usage exists
        if api_calls == 0 and token_usage and isinstance(token_usage, dict):
            job_tot = token_usage.get("job_total", {})
            if isinstance(job_tot, dict) and "requests" in job_tot:
                api_calls = int(job_tot.get("requests", 0) or 0)

        proc_time = float(processing_seconds or 0.0)
        if proc_time <= 0.0 and job_id:
            try:
                rec = db.query(AnalysisRecord).filter_by(job_id=job_id).first()
                if rec and rec.completed_at and rec.created_at:
                    proc_time = float((rec.completed_at - rec.created_at).total_seconds())
            except Exception:
                pass

        # Calculate duration in seconds
        timeline = result_json.get("timeline", [])
        dur_sec = duration_seconds or result_json.get("duration_seconds")
        if not dur_sec and timeline:
            try:
                dur_sec = float(timeline[-1].get("end", 0.0))
            except Exception:
                dur_sec = 0.0
        dur_sec = float(dur_sec or 0.0)

        model = model_used or result_json.get("model_used") or "gemini-2.5-flash"

        # Calculate estimated cost if not provided using Cost Engine
        if estimated_cost is None:
            cost_res = calculate_run_cost(
                token_usage=token_usage,
                model_used=model,
                video_duration=dur_sec
            )
            estimated_cost = cost_res["estimated_cost_decimal"]
            estimated_cost_version = cost_res["pricing_version"]

        if job_id:
            existing = db.query(AnalysisRunHistory).filter_by(job_id=job_id).first()
            if existing:
                if token_usage is not None:
                    existing.token_usage = token_usage
                    # Recalculate cost when token_usage is updated
                    cost_res = calculate_run_cost(
                        token_usage=token_usage,
                        model_used=model,
                        video_duration=dur_sec
                    )
                    existing.estimated_cost = cost_res["estimated_cost_decimal"]
                    existing.estimated_cost_version = cost_res["pricing_version"]
                if api_calls > 0:
                    existing.api_calls = api_calls
                if proc_time > 0 and (existing.processing_time is None or existing.processing_time <= 0):
                    existing.processing_time = proc_time
                db.flush()
                logger.info(f"AnalysisRunHistory for job_id {job_id} already exists. Updated telemetry and cost.")
                return existing

        # Calculate words from timeline
        total_words = sum(len(item.get("text", "").split()) for item in timeline)
        
        # Calculate words per minute
        duration_mins = (dur_sec / 60.0) if dur_sec > 0 else 1.0
        words_per_minute = float(total_words / duration_mins)
        
        url_or_filename = source_url or original_filename or "Unknown"
        
        run_history = AnalysisRunHistory(
            user_id=user_id,
            source_type=source_type,
            url_or_filename=url_or_filename,
            model_used=SaCleanModelName(model),
            video_duration=dur_sec,
            processing_time=proc_time,
            total_words=total_words,
            words_per_minute=words_per_minute,
            date_time=utc_now(),
            job_id=job_id,
            api_calls=api_calls,
            estimated_cost=estimated_cost,
            estimated_cost_version=estimated_cost_version,
            token_usage=token_usage
        )
        db.add(run_history)
        db.flush()
        return run_history
    except Exception as ex:
        logger.error(f"Failed to record analysis run history: {ex}")
        return None

def SaCleanModelName(name: str) -> str:
    """Cleans or normalizes the model name for display."""
    if not name:
        return "gemini-2.5-flash"
    return name.replace("Gemini Multi-Model Dynamic Loop Engine", "Gemini Multi-Model")

def persist_completed_analysis(
    db: Session,
    user_id: int,
    job_id: str,
    media_key: str,
    source_type: str,
    result_json: dict[str, Any],
    source_url: Optional[str] = None,
    original_filename: Optional[str] = None,
    model_used: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    processing_seconds: Optional[float] = None,
    api_calls: int = 0,
    token_usage: Optional[dict] = None,
) -> Tuple[AnalysisCache, AnalysisRecord]:
    """
    Persists a completed analysis job by creating/updating AnalysisCache and creating AnalysisRecord for user_id.
    Performs atomic transaction commit.
    """
    title = original_filename or source_url or f"Media Analysis ({media_key})"

    cache = get_or_create_analysis_cache(
        db=db,
        media_key=media_key,
        source_type=source_type,
        result_json=result_json,
        source_url=source_url,
        original_filename=original_filename,
        duration_seconds=duration_seconds,
        model_used=model_used,
    )

    record = create_or_get_analysis_record(
        db=db,
        user_id=user_id,
        cache_id=cache.id,
        job_id=job_id,
        display_title=title,
        source_type=source_type,
        source_url=source_url,
        original_filename=original_filename,
        model_used=model_used,
        status="completed",
        duration_seconds=duration_seconds,
        processing_seconds=processing_seconds,
    )

    # Record analysis run history metrics (do not store transcript text)
    record_run_history(
        db=db,
        user_id=user_id,
        source_type=source_type,
        result_json=result_json,
        source_url=source_url,
        original_filename=original_filename,
        model_used=model_used,
        duration_seconds=duration_seconds,
        processing_seconds=processing_seconds,
        job_id=job_id,
        api_calls=api_calls,
        token_usage=token_usage,
    )

    db.commit()
    return cache, record

def persist_cache_reuse_record(
    db: Session,
    user_id: int,
    media_key: str,
    source_type: str,
    result_json: dict[str, Any],
    job_id: Optional[str] = None,
    source_url: Optional[str] = None,
    original_filename: Optional[str] = None,
    model_used: Optional[str] = None,
    duration_seconds: Optional[float] = None,
) -> Tuple[AnalysisCache, AnalysisRecord]:
    """
    Creates an AnalysisRecord for requesting user_id when reusing an existing global AnalysisCache.
    Does NOT alter existing AnalysisRecords or job ownership of previous users.
    """
    cache = get_or_create_analysis_cache(
        db=db,
        media_key=media_key,
        source_type=source_type,
        result_json=result_json,
        source_url=source_url,
        original_filename=original_filename,
        duration_seconds=duration_seconds,
        model_used=model_used,
    )

    if job_id:
        existing = (
            db.query(AnalysisRecord)
            .filter(AnalysisRecord.job_id == job_id)
            .first()
        )
        if existing:
            existing.status = "completed"
            existing.progress = 100
            existing.cache_id = cache.id
            existing.completed_at = utc_now()
            existing.updated_at = utc_now()
            db.flush()
            
            # Record run history on reuse
            record_run_history(
                db=db,
                user_id=user_id,
                source_type=source_type,
                result_json=result_json,
                source_url=source_url,
                original_filename=original_filename,
                model_used=model_used,
                duration_seconds=duration_seconds,
                processing_seconds=0.0,
                job_id=job_id,
                api_calls=0
            )
            
            db.commit()
            return cache, existing
    else:
        existing = (
            db.query(AnalysisRecord)
            .filter(AnalysisRecord.user_id == user_id, AnalysisRecord.cache_id == cache.id)
            .order_by(AnalysisRecord.created_at.desc())
            .first()
        )
        if existing:
            # Reusing from cache without a job ID (immediate return on duplicate request)
            # Create a history entry as it represents a successful request served instantly
            record_run_history(
                db=db,
                user_id=user_id,
                source_type=source_type,
                result_json=result_json,
                source_url=source_url,
                original_filename=original_filename,
                model_used=model_used,
                duration_seconds=duration_seconds,
                processing_seconds=0.0,
                job_id=None,
                api_calls=0
            )
            db.commit()
            return cache, existing

    title = original_filename or source_url or f"Media Analysis ({media_key})"
    record = create_or_get_analysis_record(
        db=db,
        user_id=user_id,
        cache_id=cache.id,
        job_id=job_id,
        display_title=title,
        source_type=source_type,
        source_url=source_url,
        original_filename=original_filename,
        model_used=model_used,
        status="completed",
        duration_seconds=duration_seconds,
        processing_seconds=0.0,
    )

    # Record analysis run history metrics (do not store transcript text)
    record_run_history(
        db=db,
        user_id=user_id,
        source_type=source_type,
        result_json=result_json,
        source_url=source_url,
        original_filename=original_filename,
        model_used=model_used,
        duration_seconds=duration_seconds,
        processing_seconds=0.0,
        job_id=job_id,
        api_calls=0
    )

    db.commit()
    return cache, record
