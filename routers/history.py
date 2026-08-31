from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status, BackgroundTasks
from sqlalchemy.orm import Session

from database import get_db
from models.user import User
from dependencies.auth import require_current_user_api
from utils.origin_checker import verify_same_origin
from utils.url_validator import is_safe_url
from services.history_query_service import (
    list_user_history,
    get_user_history_detail,
    build_analysis_detail,
    delete_user_history_record,
    rename_user_history_record,
    set_user_history_pin,
    get_active_user_jobs,
)

router = APIRouter(tags=["history"])

class RenameHistoryRequest(BaseModel):
    display_title: str = Field(..., min_length=1, max_length=200)

class PinHistoryRequest(BaseModel):
    is_pinned: bool

@router.get("/api/history", status_code=status.HTTP_200_OK)
@router.get("/api/history/", status_code=status.HTTP_200_OK)
async def get_history_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    source_type: Optional[str] = Query(None),
    sort: str = Query("newest"),
    pinned: Optional[bool] = Query(None),
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db),
):
    """
    Returns a paginated, searchable, filterable, and sortable list of analysis records owned by the current user.
    """
    result = list_user_history(
        db=db,
        user_id=current_user.id,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
        source_type=source_type,
        sort=sort,
        pinned=pinned
    )
    return result

@router.get("/api/jobs/active", status_code=status.HTTP_200_OK)
async def get_active_jobs_list(
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db),
):
    """
    Returns active (queued/processing) jobs for the current user.
    """
    return get_active_user_jobs(db=db, user_id=current_user.id)

@router.get("/api/history/{public_id}", status_code=status.HTTP_200_OK)
async def get_history_detail(
    public_id: str,
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db),
):
    """
    Returns detailed analysis information for a specific record owned by current user.
    """
    detail = get_user_history_detail(db=db, user_id=current_user.id, public_id=public_id)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="History record not found")
    return detail

@router.get("/api/analyses/{analysis_id}", status_code=status.HTTP_200_OK)
async def get_analysis_for_restoration(
    analysis_id: str,
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db),
):
    """
    Returns detailed completed analysis record by canonical analysis_id for restoration.
    Rejects unauthorized access, nonexistent records, or incomplete/failed records.
    """
    import re
    import logging
    from models.analysis_record import AnalysisRecord

    logger = logging.getLogger("yamasee.restore")
    logger.info(f"[RESTORE API] requested public_id: {analysis_id}")
    logger.info(f"[RESTORE API] authenticated user id: {current_user.id}")

    # 1. Validate identifier format
    if not analysis_id or not re.match(r"^[a-zA-Z0-9\-]{36}$", analysis_id):
        logger.info("[RESTORE API] response status: 400 - Invalid analysis identifier format")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid analysis identifier format."
        )

    # 2. Query record
    record = db.query(AnalysisRecord).filter(AnalysisRecord.public_id == analysis_id).first()

    # 3. Reject nonexistent
    if not record:
        logger.info("[RESTORE API] record found: no")
        logger.info("[RESTORE API] response status: 404 - Analysis record not found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis record not found"
        )

    logger.info("[RESTORE API] record found: yes")
    logger.info(f"[RESTORE API] record owner id: {record.user_id}")
    logger.info(f"[RESTORE API] record status: {record.status}")

    # 4. Check ownership and role authorization policy
    user_role = getattr(current_user, "role", "user")
    is_admin_flag = getattr(current_user, "is_admin", False)
    is_privileged = is_admin_flag or user_role in ("admin", "owner")

    if record.user_id != current_user.id and not is_privileged:
        logger.info("[RESTORE API] response status: 404 - Unauthorized access (not leaking existence)")
        # Do not leak record existence across users. Return 404.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis record not found"
        )

    # 5. Reject incomplete or failed records
    if record.status != "completed":
        logger.info(f"[RESTORE API] response status: 409 - Record status is {record.status}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Analysis is not ready for restoration (status: {record.status})"
        )

    # 6. Return build_analysis_detail
    detail = build_analysis_detail(db, record)
    payload_keys = list(detail.keys())
    if detail.get("result_data"):
        payload_keys += [f"result_data.{k}" for k in detail["result_data"].keys()]
    
    logger.info(f"[RESTORE API] normalized payload keys: {', '.join(payload_keys)}")
    logger.info("[RESTORE API] response status: 200")
    return detail

from utils.audit import record_audit_event
from utils.metrics import metrics

@router.patch("/api/history/{public_id}", status_code=status.HTTP_200_OK)
async def rename_history_item(
    public_id: str,
    req: RenameHistoryRequest,
    request: Request,
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db),
):
    """
    Renames display_title of an analysis record owned by the current user.
    """
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    try:
        updated = rename_user_history_record(
            db=db,
            user_id=current_user.id,
            public_id=public_id,
            new_title=req.display_title
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="History record not found")

    record_audit_event("rename", user_id=current_user.id, details={"record_id": public_id})
    return updated

@router.patch("/api/history/{public_id}/pin", status_code=status.HTTP_200_OK)
async def pin_history_item(
    public_id: str,
    req: PinHistoryRequest,
    request: Request,
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db),
):
    """
    Pins or unpins an analysis record owned by the current user.
    """
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    updated = set_user_history_pin(
        db=db,
        user_id=current_user.id,
        public_id=public_id,
        is_pinned=req.is_pinned
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="History record not found")

    record_audit_event("pin", user_id=current_user.id, details={"record_id": public_id, "is_pinned": req.is_pinned})
    return updated

@router.post("/api/history/{public_id}/retry", status_code=status.HTTP_200_OK)
async def retry_failed_history_item(
    public_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db),
):
    """
    Safely retries a failed/cancelled URL analysis record owned by the current user.
    """
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    from utils.idempotency import idempotency_store
    idempotency_key = request.headers.get("X-Idempotency-Key") or request.headers.get("idempotency_key")
    if idempotency_key:
        idem_status, saved_res = idempotency_store.check_or_reserve(current_user.id, "retry", idempotency_key, f"retry:{public_id}")
        if idem_status == "CONFLICT":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key conflict: Same key used with different payload")
        if idem_status == "REPLAY":
            return saved_res or {"job_id": "replay", "queued": True, "message": "Retry job successfully queued"}

    # Fetch database record directly
    from models.analysis_record import AnalysisRecord
    from services.analysis_history_service import validate_state_transition, InvalidStateTransitionException
    
    record = db.query(AnalysisRecord).filter(
        AnalysisRecord.public_id == public_id,
        AnalysisRecord.user_id == current_user.id
    ).first()
    if not record:
        if idempotency_key: idempotency_store.release_key(current_user.id, "retry", idempotency_key)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="History record not found")

    # Validate state transition: only failed/cancelled jobs can be retried
    try:
        validate_state_transition(record.status, "queued")
    except InvalidStateTransitionException:
        if idempotency_key: idempotency_store.release_key(current_user.id, "retry", idempotency_key)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job cannot be retried. Current status is '{record.status}'. Only failed or cancelled URL analyses are retriable."
        )

    source_url = record.source_url
    if not source_url or not is_safe_url(source_url):
        if idempotency_key: idempotency_store.release_key(current_user.id, "retry", idempotency_key)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Source URL is invalid or unsafe for retry.")

    import time
    import datetime
    from main import JOBS_DATA, enterprise_processing_pipeline, cleanup_expired_jobs

    cleanup_expired_jobs()
    job_id = f"job_retry_{int(time.time())}"
    
    req_id = getattr(request.state, "request_id", None)
    JOBS_DATA[job_id] = {
        "status": "queued",
        "progress": 0,
        "result": None,
        "user_id": current_user.id,
        "created_at": time.time(),
        "request_id": req_id
    }

    # Reset record status to queued in DB
    record.status = "queued"
    record.progress = 0
    record.job_id = job_id
    record.error_message = None
    record.completed_at = None
    record.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()

    from utils.metrics import metrics
    from utils.audit import record_audit_event
    metrics.inc("retry_count")
    record_audit_event("job_retry_requested", user_id=current_user.id, details={"record_id": public_id, "job_id": job_id})
    record_audit_event("retry", user_id=current_user.id, details={"record_id": public_id, "job_id": job_id})

    background_tasks.add_task(
        enterprise_processing_pipeline,
        job_id,
        record.source_type or "youtube",
        source_url,
        None,
        None,
        record.model_used or "gemini-2.5-flash"
    )

    resp = {"job_id": job_id, "queued": True, "message": "Retry job successfully queued"}
    if idempotency_key:
        idempotency_store.record_response(current_user.id, "retry", idempotency_key, resp)
    return resp

@router.post("/api/jobs/{job_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_active_job(
    job_id: str,
    request: Request,
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db),
):
    """
    Cancels an active (queued/processing) job owned by the current user.
    """
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    from models.analysis_record import AnalysisRecord
    from services.analysis_history_service import validate_state_transition, InvalidStateTransitionException
    import datetime
    from main import JOBS_DATA

    record = db.query(AnalysisRecord).filter(
        AnalysisRecord.job_id == job_id
    ).first()
    
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    # Ownership check
    if record.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this job")

    # Validate state transition: only active jobs can be cancelled
    try:
        validate_state_transition(record.status, "cancelled")
    except InvalidStateTransitionException:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel job in '{record.status}' status."
        )

    # Set cancel flags
    if job_id in JOBS_DATA:
        JOBS_DATA[job_id]["cancel_requested"] = True
        JOBS_DATA[job_id]["status"] = "cancelled"

    record.status = "cancelled"
    record.error_message = "Job was cancelled by user"
    record.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()

    # 🔔 Trigger job_cancelled notification
    from services.notification_service import create_notification
    try:
        create_notification(
            db=db,
            user_id=current_user.id,
            type="job_cancelled",
            title="Analysis cancelled",
            message="The analysis job was cancelled.",
            related_job_id=job_id,
            target_url="/history",
            deduplication_key=f"job:{job_id}:cancelled"
        )
    except Exception as e:
        logger.error(f"Failed to create notification for job {job_id}: {e}")

    from utils.audit import record_audit_event
    record_audit_event("job_cancel_requested", user_id=current_user.id, details={"job_id": job_id})
    record_audit_event("job_cancelled", user_id=current_user.id, details={"job_id": job_id})

    return {"message": "Job cancellation request sent successfully", "job_id": job_id}

@router.delete("/api/history/{public_id}", status_code=status.HTTP_200_OK)
async def delete_history_item(
    public_id: str,
    request: Request,
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db),
):
    """
    Deletes an analysis record owned by the current user.
    """
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    success = delete_user_history_record(db=db, user_id=current_user.id, public_id=public_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="History record not found")

    record_audit_event("delete", user_id=current_user.id, details={"record_id": public_id})
    return {"success": True, "deleted_public_id": public_id}
