import math
import json
import logging
import time
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import or_

from models.analysis_record import AnalysisRecord
from models.analysis_cache import AnalysisCache
from models.analysis_run_history import AnalysisRunHistory
from services.cost_engine import calculate_run_cost
from utils.url_validator import is_safe_url
from utils.thumbnail_service import get_record_thumbnail_url

logger = logging.getLogger("yamasee.history_query_service")

def list_user_history(
    db: Session,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
    status: Optional[str] = None,
    source_type: Optional[str] = None,
    sort: str = "newest",
    pinned: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Returns a paginated list of AnalysisRecord metadata for user_id with search, filter, sort, and pin support.
    Filters strictly by user_id. Excludes result_json and internal paths.
    """
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 12
    elif page_size > 50:
        page_size = 50

    base_query = db.query(AnalysisRecord).filter(AnalysisRecord.user_id == user_id)

    if search:
        search_clean = search.strip()[:200]
        if search_clean:
            base_query = base_query.filter(
                or_(
                    AnalysisRecord.display_title.ilike(f"%{search_clean}%"),
                    AnalysisRecord.original_filename.ilike(f"%{search_clean}%"),
                    AnalysisRecord.source_url.ilike(f"%{search_clean}%")
                )
            )

    if status and status.lower() in {"queued", "processing", "completed", "failed", "cancelled"}:
        base_query = base_query.filter(AnalysisRecord.status == status.lower())

    if source_type and source_type.lower() != "all" and source_type.strip() != "":
        st_lower = source_type.lower().strip()
        if st_lower == "youtube":
            base_query = base_query.filter(AnalysisRecord.source_type == "youtube")
        elif st_lower == "tiktok":
            base_query = base_query.filter(AnalysisRecord.source_type.in_(["tiktok", "tiktok_url", "external_tiktok"]))
        elif st_lower == "upload":
            base_query = base_query.filter(AnalysisRecord.source_type.in_(["upload", "mp4", "file"]))
        else:
            base_query = base_query.filter(AnalysisRecord.source_type == st_lower)

    if pinned is not None:
        base_query = base_query.filter(AnalysisRecord.is_pinned == (1 if pinned else 0))

    # Sorting options
    if sort == "oldest":
        order_clause = [AnalysisRecord.is_pinned.desc(), AnalysisRecord.created_at.asc(), AnalysisRecord.id.asc()]
    elif sort == "title_asc":
        order_clause = [AnalysisRecord.is_pinned.desc(), AnalysisRecord.display_title.asc()]
    elif sort == "title_desc":
        order_clause = [AnalysisRecord.is_pinned.desc(), AnalysisRecord.display_title.desc()]
    else:
        # Default: newest (is_pinned DESC, created_at DESC, id DESC)
        order_clause = [AnalysisRecord.is_pinned.desc(), AnalysisRecord.created_at.desc(), AnalysisRecord.id.desc()]

    total = base_query.count()
    total_pages = math.ceil(total / page_size) if total > 0 else 0

    offset = (page - 1) * page_size
    records = (
        base_query
        .order_by(*order_clause)
        .offset(offset)
        .limit(page_size)
        .all()
    )

    # Batch query AnalysisRunHistory for job_ids
    job_ids = [r.job_id for r in records if r.job_id]
    run_hist_map = {}
    if job_ids:
        run_hist_records = db.query(AnalysisRunHistory).filter(AnalysisRunHistory.job_id.in_(job_ids)).all()
        run_hist_map = {rh.job_id: rh for rh in run_hist_records}

    items = []
    for rec in records:
        run_hist = run_hist_map.get(rec.job_id) if rec.job_id else None
        cost_data = calculate_run_cost(
            token_usage=run_hist.token_usage if run_hist else None,
            model_used=rec.model_used,
            video_duration=rec.duration_seconds
        )
        thumb_url = get_record_thumbnail_url(rec)
        if not rec.thumbnail_url and thumb_url and thumb_url != "/static/Logo_boy.png":
            try:
                rec.thumbnail_url = thumb_url
                db.flush()
            except Exception:
                pass

        items.append({
            "public_id": rec.public_id,
            "display_title": rec.display_title,
            "source_type": rec.source_type,
            "source_url": rec.source_url,
            "original_filename": rec.original_filename,
            "thumbnail_url": thumb_url,
            "duration_seconds": rec.duration_seconds,
            "status": rec.status,
            "progress": rec.progress,
            "model_used": rec.model_used,
            "is_pinned": getattr(rec, "is_pinned", False),
            "can_retry": rec.status in {"failed", "cancelled"} and rec.source_type in {"youtube", "tiktok", "tiktok_url", "external_tiktok"},
            "created_at": rec.created_at.isoformat() if rec.created_at else None,
            "completed_at": rec.completed_at.isoformat() if rec.completed_at else None,
            "processing_seconds": rec.processing_seconds,
            "download_available": rec.status == "completed",
            "has_cache": rec.cache_id is not None,
            "estimated_cost_thb": cost_data["estimated_cost_thb"],
            "estimated_cost_usd": cost_data["estimated_cost_usd"],
            "display_thb": cost_data["display_thb"],
            "display_usd": cost_data["display_usd"],
            "estimation_quality": cost_data["estimation_quality"],
            "quality_label_th": cost_data["quality_label_th"],
            "disclaimer_th": cost_data["disclaimer_th"],
        })

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": total,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1,
        },
        "filters": {
            "search": search or "",
            "status": status,
            "source_type": source_type,
            "sort": sort,
            "pinned": pinned
        }
    }

def build_analysis_detail(db: Session, record: AnalysisRecord) -> Dict[str, Any]:
    """
    Builds full detailed dict from AnalysisRecord (including 9 modules result_data).
    """
    result_data = None
    cache_media_key = None
    if record.cache_id:
        cache = db.query(AnalysisCache).filter(AnalysisCache.id == record.cache_id).first()
        if cache and cache.result_json:
            if isinstance(cache.result_json, str):
                try:
                    result_data = json.loads(cache.result_json)
                except Exception as e:
                    logger.error(f"Error parsing cache.result_json for record {record.public_id}: {e}")
                    result_data = None
            else:
                result_data = cache.result_json
            
            if result_data:
                from utils.normalization import normalize_analysis_result
                result_data = normalize_analysis_result(result_data)
            cache_media_key = cache.media_key

    download_unique_id = cache_media_key or record.job_id or record.public_id

    run_hist = db.query(AnalysisRunHistory).filter(AnalysisRunHistory.job_id == record.job_id).first() if record.job_id else None
    cost_data = calculate_run_cost(
        token_usage=run_hist.token_usage if run_hist else None,
        model_used=record.model_used,
        video_duration=record.duration_seconds
    )

    return {
        "public_id": record.public_id,
        "display_title": record.display_title,
        "source_type": record.source_type,
        "source_url": record.source_url,
        "original_filename": record.original_filename,
        "thumbnail_url": record.thumbnail_url,
        "duration_seconds": record.duration_seconds,
        "status": record.status,
        "progress": record.progress,
        "model_used": record.model_used,
        "is_pinned": getattr(record, "is_pinned", False),
        "can_retry": record.status in {"failed", "cancelled"} and record.source_type in {"youtube", "tiktok", "tiktok_url", "external_tiktok"},
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        "processing_seconds": record.processing_seconds,
        "download_unique_id": download_unique_id,
        "download_available": record.status == "completed",
        "result_data": result_data,
        "estimated_cost_thb": cost_data["estimated_cost_thb"],
        "estimated_cost_usd": cost_data["estimated_cost_usd"],
        "display_thb": cost_data["display_thb"],
        "display_usd": cost_data["display_usd"],
        "estimation_quality": cost_data["estimation_quality"],
        "quality_label_th": cost_data["quality_label_th"],
        "disclaimer_th": cost_data["disclaimer_th"],
        "cost_breakdown": cost_data,
    }

def get_user_history_detail(
    db: Session,
    user_id: int,
    public_id: str
) -> Optional[Dict[str, Any]]:
    """
    Retrieves full detail (including 9 modules result_data) of AnalysisRecord for user_id and public_id.
    Returns None if record does not exist or belongs to another user.
    """
    record = (
        db.query(AnalysisRecord)
        .filter(AnalysisRecord.public_id == public_id, AnalysisRecord.user_id == user_id)
        .first()
    )
    if not record:
        return None
    return build_analysis_detail(db, record)

def rename_user_history_record(
    db: Session,
    user_id: int,
    public_id: str,
    new_title: str
) -> Optional[Dict[str, Any]]:
    """
    Renames the display_title of AnalysisRecord owned by user_id.
    Returns updated dict if success, None if record not found or not owned.
    """
    clean_title = new_title.strip()
    if not clean_title or len(clean_title) > 200:
        raise ValueError("Display title must be between 1 and 200 characters long")

    record = (
        db.query(AnalysisRecord)
        .filter(AnalysisRecord.public_id == public_id, AnalysisRecord.user_id == user_id)
        .first()
    )
    if not record:
        return None

    record.display_title = clean_title
    db.commit()
    db.refresh(record)

    return {
        "public_id": record.public_id,
        "display_title": record.display_title,
        "is_pinned": getattr(record, "is_pinned", False),
        "updated_at": record.updated_at.isoformat() if record.updated_at else None
    }

def set_user_history_pin(
    db: Session,
    user_id: int,
    public_id: str,
    is_pinned: bool
) -> Optional[Dict[str, Any]]:
    """
    Pins or unpins AnalysisRecord owned by user_id.
    """
    record = (
        db.query(AnalysisRecord)
        .filter(AnalysisRecord.public_id == public_id, AnalysisRecord.user_id == user_id)
        .first()
    )
    if not record:
        return None

    record.is_pinned = is_pinned
    db.commit()
    db.refresh(record)

    return {
        "public_id": record.public_id,
        "display_title": record.display_title,
        "is_pinned": record.is_pinned,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None
    }

def get_active_user_jobs(
    db: Session,
    user_id: int
) -> List[Dict[str, Any]]:
    """
    Returns currently active (queued/processing) AnalysisRecord jobs for user_id.
    Excludes terminal (completed/failed/cancelled) jobs.
    """
    active_records = (
        db.query(AnalysisRecord)
        .filter(
            AnalysisRecord.user_id == user_id,
            AnalysisRecord.status.in_(["queued", "processing"])
        )
        .order_by(AnalysisRecord.created_at.desc())
        .limit(10)
        .all()
    )

    jobs = []
    for rec in active_records:
        jobs.append({
            "job_id": rec.job_id or rec.public_id,
            "public_id": rec.public_id,
            "display_title": rec.display_title,
            "source_type": rec.source_type,
            "status": rec.status,
            "progress": rec.progress,
            "created_at": rec.created_at.isoformat() if rec.created_at else None,
            "can_retry": False
        })
    return jobs

def delete_user_history_record(
    db: Session,
    user_id: int,
    public_id: str
) -> bool:
    """
    Deletes AnalysisRecord owned by user_id identified by public_id.
    Does NOT delete AnalysisCache or User records.
    Returns True if deleted, False if record not found or owned by another user.
    """
    record = (
        db.query(AnalysisRecord)
        .filter(AnalysisRecord.public_id == public_id, AnalysisRecord.user_id == user_id)
        .first()
    )
    if not record:
        return False

    db.delete(record)
    db.commit()
    return True
