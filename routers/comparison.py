from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from database import get_db
from models.analysis_record import AnalysisRecord
from models.user import User
from models.video_comparison import VideoComparison
from dependencies.auth import require_current_user_api
from utils.origin_checker import verify_same_origin
from schemas.comparison import (
    CandidateVideosResponse,
    ComparisonVideoSnapshot,
    EvidenceValidationRequest,
    Phase2InputPreparationResponse,
    ComparisonRequest,
    ComparisonPreRunEstimateRequest,
)
from services.pre_run_estimator import pre_run_estimator
from services.duration_service import find_cached_duration
from services.comparison_service import (
    get_candidate_videos,
    build_video_snapshot,
    create_comparison_identity,
    compute_comparison_fingerprint,
    validate_evidence,
    find_cached_comparison,
    persist_comparison,
    get_comparison,
    list_user_comparisons,
    prepare_phase2_input_builder,
    ComparisonAuthorizationError,
    ComparisonIneligibleError,
)
from engines.comparison_engine import (
    ComparisonEngine,
    ComparisonEngineError,
    ComparisonEngineQuotaError,
    remap_comparison_orientation,
)
from engines.external_research_engine import ExternalResearchEngine
from utils.gemini_model_policy import RATE_LIMITED_MESSAGE, validate_primary_model

router = APIRouter(prefix="/api/comparison", tags=["video-comparison"])

def summarize_evidence_counts(result_json: Dict[str, Any]) -> Dict[str, int]:
    """Helper to aggregate evidence verification counts in a comparison result."""
    counts = {"VERIFIED": 0, "PARTIALLY_VERIFIED": 0, "UNVERIFIED": 0}
    if not result_json or not isinstance(result_json, dict):
        return counts

    def _count(ev: Optional[Dict[str, Any]]):
        if ev and isinstance(ev, dict) and "verification_status" in ev:
            st = str(ev["verification_status"]).upper()
            if st in counts:
                counts[st] += 1
            else:
                counts["UNVERIFIED"] += 1

    for section in ["shared_topics", "key_differences", "viewpoint_relationships", "evidence_timeline"]:
        for item in result_json.get(section, []):
            if isinstance(item, dict):
                _count(item.get("evidence_a"))
                _count(item.get("evidence_b"))

    unique = result_json.get("unique_topics", {})
    if isinstance(unique, dict):
        for item in unique.get("video_a", []):
            if isinstance(item, dict):
                _count(item.get("evidence"))
        for item in unique.get("video_b", []):
            if isinstance(item, dict):
                _count(item.get("evidence"))

    return counts

@router.get("/candidates", response_model=CandidateVideosResponse, status_code=status.HTTP_200_OK)
async def list_comparison_candidates(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    search: Optional[str] = Query(None),
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db),
):
    """
    Returns a paginated list of analysis records owned by current user that are eligible for video comparison.
    Eligible records must be completed and contain at least one valid speech transcript segment.
    """
    res = get_candidate_videos(
        db=db,
        user_id=current_user.id,
        page=page,
        page_size=page_size,
        search=search
    )
    return res

@router.get("/snapshots/{analysis_id}", response_model=ComparisonVideoSnapshot, status_code=status.HTTP_200_OK)
async def get_video_snapshot(
    analysis_id: str,
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db),
):
    """
    Builds and returns canonical ComparisonVideoSnapshot for an analysis record owned by current user.
    Enforces authorization isolation (returns 404 for nonexistent/unauthorized records).
    """
    try:
        snapshot = build_video_snapshot(db=db, user_id=current_user.id, public_id=analysis_id)
        return snapshot
    except ComparisonAuthorizationError:
        # Do not leak existence across users
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis record not found"
        )
    except ComparisonIneligibleError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )

@router.post("/validate-evidence", status_code=status.HTTP_200_OK)
async def validate_evidence_endpoint(
    req: EvidenceValidationRequest,
    current_user: User = Depends(require_current_user_api),
):
    """
    Validates an evidence reference object against provided Video A/B snapshots.
    Returns VERIFIED, PARTIALLY_VERIFIED, or UNVERIFIED with resolved transcript text.
    """
    result = validate_evidence(req.evidence, req.snapshot_a, req.snapshot_b)
    return result

@router.post("/prepare-input", response_model=Phase2InputPreparationResponse, status_code=status.HTTP_200_OK)
async def prepare_phase2_input_endpoint(
    req: ComparisonRequest,
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db),
):
    """
    Dry-run input builder for Phase 2 comparison engine.
    Calculates combined character size, estimated tokens, and Gemini context limit safety.
    DOES NOT INVOKE GEMINI.
    """
    if req.analysis_id_a.strip() == req.analysis_id_b.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Video A and Video B cannot be the same analysis record."
        )

    try:
        snap_a = build_video_snapshot(db=db, user_id=current_user.id, public_id=req.analysis_id_a)
        snap_b = build_video_snapshot(db=db, user_id=current_user.id, public_id=req.analysis_id_b)
    except ComparisonAuthorizationError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="One or both analysis records not found")
    except ComparisonIneligibleError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    prep = prepare_phase2_input_builder(snap_a, snap_b)
    return prep

@router.get("/cache", status_code=status.HTTP_200_OK)
async def check_comparison_cache(
    analysis_id_a: str = Query(...),
    analysis_id_b: str = Query(...),
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db),
):
    """
    Checks if a cached comparison result exists for canonical pair (A+B or B+A).
    Validates input fingerprint for staleness. Returns cached result if valid.
    """
    if analysis_id_a.strip() == analysis_id_b.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Video A and Video B cannot be the same analysis record."
        )

    try:
        snap_a = build_video_snapshot(db=db, user_id=current_user.id, public_id=analysis_id_a)
        snap_b = build_video_snapshot(db=db, user_id=current_user.id, public_id=analysis_id_b)
    except ComparisonAuthorizationError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis record not found")
    except ComparisonIneligibleError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    fp = compute_comparison_fingerprint(snap_a, snap_b)
    cached = find_cached_comparison(
        db=db,
        user_id=current_user.id,
        analysis_id_a=analysis_id_a,
        analysis_id_b=analysis_id_b,
        input_fingerprint=fp
    )

    if not cached:
        return {"cached": False, "comparison": None}

    # Handle orientation remapping if stored orientation differs from requested
    res_json = cached.result_json
    if cached.display_order_a != analysis_id_a.strip():
        res_json = remap_comparison_orientation(res_json)

    return {
        "cached": True,
        "comparison": {
            "public_id": cached.public_id,
            "canonical_pair_key": cached.canonical_pair_key,
            "display_order_a": analysis_id_a.strip(),
            "display_order_b": analysis_id_b.strip(),
            "status": cached.status,
            "schema_version": cached.schema_version,
            "result_json": res_json,
            "created_at": cached.created_at.isoformat() if cached.created_at else None,
            "updated_at": cached.updated_at.isoformat() if cached.updated_at else None,
        }
    }

@router.post("/compare", status_code=status.HTTP_200_OK)
async def perform_video_comparison(
    req: ComparisonRequest,
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db),
):
    """
    Executes or retrieves Video Comparison between Video A and Video B.
    Checks completed cache first (0 AI calls on hit, orientation remapped if needed).
    Runs Gemini comparative engine on cache miss (1 AI call on happy path).
    Verifies all evidence claims against authoritative transcripts and persists result.
    """
    id_a = req.analysis_id_a.strip()
    id_b = req.analysis_id_b.strip()

    if id_a == id_b:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Video A and Video B cannot be the same analysis record."
        )

    # 1. Build snapshots and verify authorization
    try:
        snap_a = build_video_snapshot(db=db, user_id=current_user.id, public_id=id_a)
        snap_b = build_video_snapshot(db=db, user_id=current_user.id, public_id=id_b)
    except ComparisonAuthorizationError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or both analysis records not found."
        )
    except ComparisonIneligibleError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )

    # 2. Compute canonical pair identity and fingerprint
    fp = compute_comparison_fingerprint(snap_a, snap_b)

    # 3. Check existing completed cache
    cached = find_cached_comparison(
        db=db,
        user_id=current_user.id,
        analysis_id_a=id_a,
        analysis_id_b=id_b,
        input_fingerprint=fp
    )

    if cached and cached.result_json:
        final_res = cached.result_json
        # Check display orientation remapping
        if cached.display_order_a != id_a:
            final_res = remap_comparison_orientation(final_res)

        ev_summary = summarize_evidence_counts(final_res)

        return {
            "comparison_id": cached.public_id,
            "comparison_public_id": cached.public_id,
            "cached": True,
            "video_a": {
                "analysis_id": snap_a.analysis_id,
                "title": snap_a.title,
                "source_type": snap_a.source_type,
                "duration_seconds": snap_a.duration_seconds,
            },
            "video_b": {
                "analysis_id": snap_b.analysis_id,
                "title": snap_b.title,
                "source_type": snap_b.source_type,
                "duration_seconds": snap_b.duration_seconds,
            },
            "result": final_res,
            "evidence_summary": ev_summary,
            "processing_seconds": cached.processing_seconds or 0.0,
            "api_calls": 0,
            "token_usage": cached.token_usage or {},
            "model_used": cached.model_used or "cached",
        }

    # 4. Cache miss: Execute AI Comparison Engine
    try:
        selected_comparison_model = validate_primary_model(
            req.comparison_model,
            default="gemini-2.5-flash",
        )
        engine = ComparisonEngine(preferred_model=selected_comparison_model)
        result_dict, token_telemetry, model_used, proc_seconds = engine.run_comparison(snap_a, snap_b)
    except ComparisonEngineQuotaError as q_err:
        # Save failed comparison safely without destroying original video records
        persist_comparison(
            db=db,
            user_id=current_user.id,
            analysis_id_a=id_a,
            analysis_id_b=id_b,
            comparison_result={},
            input_fingerprint=fp,
            status="failed",
            error_message=str(q_err),
            processing_seconds=0.0,
            api_calls=0,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"RATE_LIMITED: {RATE_LIMITED_MESSAGE}"
        )
    except Exception as ai_err:
        persist_comparison(
            db=db,
            user_id=current_user.id,
            analysis_id_a=id_a,
            analysis_id_b=id_b,
            comparison_result={},
            input_fingerprint=fp,
            status="failed",
            error_message=str(ai_err),
            processing_seconds=0.0,
            api_calls=1,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Video comparison processing failed: {ai_err}"
        )

    ev_summary = summarize_evidence_counts(result_dict)

    # 5. Persist completed comparison
    saved = persist_comparison(
        db=db,
        user_id=current_user.id,
        analysis_id_a=id_a,
        analysis_id_b=id_b,
        comparison_result=result_dict,
        input_fingerprint=fp,
        status="completed",
        processing_seconds=proc_seconds,
        api_calls=1,
        token_usage=token_telemetry,
        model_used=model_used,
    )

    return {
        "comparison_id": saved.public_id,
        "comparison_public_id": saved.public_id,
        "cached": False,
        "video_a": {
            "analysis_id": snap_a.analysis_id,
            "title": snap_a.title,
            "source_type": snap_a.source_type,
            "duration_seconds": snap_a.duration_seconds,
        },
        "video_b": {
            "analysis_id": snap_b.analysis_id,
            "title": snap_b.title,
            "source_type": snap_b.source_type,
            "duration_seconds": snap_b.duration_seconds,
        },
        "result": result_dict,
        "evidence_summary": ev_summary,
        "processing_seconds": proc_seconds,
        "api_calls": 1,
        "token_usage": token_telemetry,
        "model_used": model_used,
    }

@router.get("/history", status_code=status.HTTP_200_OK)
async def list_comparison_history_endpoint(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db),
):
    """
    Returns paginated list of video comparisons created by current user.
    Maintains strict user isolation.
    """
    res = list_user_comparisons(
        db=db,
        user_id=current_user.id,
        page=page,
        page_size=page_size
    )
    return res

@router.get("/{public_id}", status_code=status.HTTP_200_OK)
async def get_comparison_detail(
    public_id: str,
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db),
):
    """
    Retrieves detailed comparison record by public_id.
    Privileged users (admin/owner) can view any comparison.
    Normal users can only view comparison records they own.
    Returns 0 extra Gemini calls and 0 extra Tokens.
    """
    user_role = getattr(current_user, "role", "user")
    is_admin_flag = getattr(current_user, "is_admin", False)
    is_privileged = is_admin_flag or user_role in ("admin", "owner")

    if is_privileged:
        comp = db.query(VideoComparison).filter(VideoComparison.public_id == public_id).first()
    else:
        comp = get_comparison(db=db, user_id=current_user.id, comparison_public_id=public_id)

    if not comp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comparison record not found")

    snap_a_dict = None
    snap_b_dict = None
    title_a = "Video A"
    title_b = "Video B"

    rec_a = db.query(AnalysisRecord).filter(AnalysisRecord.public_id == comp.display_order_a).first() if comp.display_order_a else None
    rec_b = db.query(AnalysisRecord).filter(AnalysisRecord.public_id == comp.display_order_b).first() if comp.display_order_b else None

    if rec_a:
        try:
            user_id_a = rec_a.user_id or comp.user_id
            snap_a = build_video_snapshot(db=db, user_id=user_id_a, public_id=rec_a.public_id)
            snap_a_dict = snap_a.model_dump()
            title_a = snap_a.title
        except Exception:
            pass

    if not snap_a_dict and comp.display_order_a:
        snap_a_dict = {
            "analysis_id": comp.display_order_a,
            "public_id": comp.display_order_a,
            "title": (rec_a.display_title or rec_a.original_filename) if rec_a else "Video A",
            "display_title": (rec_a.display_title or rec_a.original_filename) if rec_a else "Video A",
            "source_type": (rec_a.source_type if rec_a else "mp4"),
            "duration_seconds": (rec_a.duration_seconds if rec_a and rec_a.duration_seconds else 0),
            "analyzed_at": (rec_a.created_at.isoformat() if rec_a and rec_a.created_at else (comp.created_at.isoformat() if comp.created_at else None)),
            "thumbnail_url": (getattr(rec_a, "thumbnail_url", None) if rec_a else "/static/Logo_boy.png") or "/static/Logo_boy.png"
        }
        title_a = snap_a_dict["title"]

    if rec_b:
        try:
            user_id_b = rec_b.user_id or comp.user_id
            snap_b = build_video_snapshot(db=db, user_id=user_id_b, public_id=rec_b.public_id)
            snap_b_dict = snap_b.model_dump()
            title_b = snap_b.title
        except Exception:
            pass

    if not snap_b_dict and comp.display_order_b:
        snap_b_dict = {
            "analysis_id": comp.display_order_b,
            "public_id": comp.display_order_b,
            "title": (rec_b.display_title or rec_b.original_filename) if rec_b else "Video B",
            "display_title": (rec_b.display_title or rec_b.original_filename) if rec_b else "Video B",
            "source_type": (rec_b.source_type if rec_b else "mp4"),
            "duration_seconds": (rec_b.duration_seconds if rec_b and rec_b.duration_seconds else 0),
            "analyzed_at": (rec_b.created_at.isoformat() if rec_b and rec_b.created_at else (comp.created_at.isoformat() if comp.created_at else None)),
            "thumbnail_url": (getattr(rec_b, "thumbnail_url", None) if rec_b else "/static/Logo_boy.png") or "/static/Logo_boy.png"
        }
        title_b = snap_b_dict["title"]

    res_json = comp.result_json or {}
    ev_summary = summarize_evidence_counts(res_json)

    return {
        "public_id": comp.public_id,
        "comparison_public_id": comp.public_id,
        "canonical_pair_key": comp.canonical_pair_key,
        "display_order_a": comp.display_order_a,
        "display_order_b": comp.display_order_b,
        "status": comp.status,
        "schema_version": comp.schema_version,
        "result": res_json,
        "result_json": res_json,
        "evidence_summary": ev_summary,
        "error_message": comp.error_message,
        "processing_seconds": comp.processing_seconds or 0.0,
        "api_calls": comp.api_calls,
        "token_usage": comp.token_usage or {},
        "model_used": comp.model_used or "gemini-2.5-flash",
        "created_at": comp.created_at.isoformat() if comp.created_at else None,
        "updated_at": comp.updated_at.isoformat() if comp.updated_at else None,
        "cached": True,
        "video_a_snapshot": snap_a_dict,
        "video_b_snapshot": snap_b_dict,
        "video_a": {
            "analysis_id": comp.display_order_a,
            "title": title_a,
            "source_type": snap_a_dict.get("source_type", "mp4") if snap_a_dict else "mp4",
            "duration_seconds": snap_a_dict.get("duration_seconds", 0) if snap_a_dict else 0,
        },
        "video_b": {
            "analysis_id": comp.display_order_b,
            "title": title_b,
            "source_type": snap_b_dict.get("source_type", "mp4") if snap_b_dict else "mp4",
            "duration_seconds": snap_b_dict.get("duration_seconds", 0) if snap_b_dict else 0,
        },
        "external_research": res_json.get("external_research") if isinstance(res_json, dict) else None
    }

@router.delete("/{public_id}", status_code=status.HTTP_200_OK)
async def delete_comparison(
    public_id: str,
    request: Request,
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db),
):
    """Delete only the authorized saved comparison record, never its source analyses."""
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    comp = db.query(VideoComparison).filter(VideoComparison.public_id == public_id).first()
    if not comp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comparison record not found")

    user_role = getattr(current_user, "role", "user")
    is_privileged = getattr(current_user, "is_admin", False) or user_role in ("admin", "owner")
    if not is_privileged and comp.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete this comparison")

    db.delete(comp)
    db.commit()
    return {"success": True, "public_id": public_id}

@router.post("/{public_id}/external-research", status_code=status.HTTP_200_OK)
async def get_or_refresh_external_research(
    public_id: str,
    refresh: bool = Query(False),
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db),
):
    """
    Executes or returns cached External Research POC for comparison public_id.
    - If refresh is False and cache exists: Returns cache (0 Gemini calls, 0 Search calls).
    - If refresh is True (explicit user action) or cache miss: Executes External Research POC flow and updates cache.
    """
    user_role = getattr(current_user, "role", "user")
    is_admin_flag = getattr(current_user, "is_admin", False)
    is_privileged = is_admin_flag or user_role in ("admin", "owner")

    if is_privileged:
        comp = db.query(VideoComparison).filter(VideoComparison.public_id == public_id).first()
    else:
        comp = get_comparison(db=db, user_id=current_user.id, comparison_public_id=public_id)

    if not comp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comparison record not found")

    res_json = comp.result_json or {}
    if not isinstance(res_json, dict):
        res_json = {}

    existing_ext = res_json.get("external_research")
    if not refresh and existing_ext and isinstance(existing_ext, dict):
        return {
            "cached": True,
            "public_id": public_id,
            "external_research": existing_ext
        }

    # Execute POC Research flow
    title_a = "Video A"
    title_b = "Video B"
    try:
        snap_a = build_video_snapshot(db=db, user_id=comp.user_id, public_id=comp.display_order_a)
        title_a = snap_a.title
    except Exception:
        pass
    try:
        snap_b = build_video_snapshot(db=db, user_id=comp.user_id, public_id=comp.display_order_b)
        title_b = snap_b.title
    except Exception:
        pass

    engine = ExternalResearchEngine()
    ext_result = engine.run_research(res_json, title_a=title_a, title_b=title_b)

    # Cache result back inside VideoComparison.result_json["external_research"]
    res_json["external_research"] = ext_result
    comp.result_json = res_json
    db.commit()

    return {
        "cached": False,
        "public_id": public_id,
        "external_research": ext_result
    }


@router.post("/pre-run-estimate", status_code=status.HTTP_200_OK)
async def pre_run_estimate_endpoint(
    req: ComparisonPreRunEstimateRequest,
    current_user: User = Depends(require_current_user_api),
    db: Session = Depends(get_db),
):
    """
    Computes Pre-run cost and resource usage estimate for Video Comparison setup workspace.
    Determines single-video analysis states (NEW vs HISTORY/CACHE REUSE), comparison engine cost,
    and checks exact comparison cache hit.
    0 Gemini API calls, 0 Search calls.
    """
    def _resolve_side(side_input):
        side_dict = side_input.model_dump() if side_input else {}
        st = (side_dict.get("state") or "UNRESOLVED").upper()
        dur = side_dict.get("duration_seconds")
        aid = side_dict.get("analysis_id")
        url = side_dict.get("url")

        # If analysis_id is provided, look up duration from DB snapshot if dur is missing
        if aid and (dur is None or dur <= 0):
            try:
                snap = build_video_snapshot(db=db, user_id=current_user.id, public_id=aid)
                if snap and snap.duration_seconds > 0:
                    dur = float(snap.duration_seconds)
                    side_dict["duration_seconds"] = dur
                if st in ("UNRESOLVED", "WAITING", "READY"):
                    st = "HISTORY_REUSE"
                    side_dict["state"] = st
            except Exception:
                pass

        # If url is provided and duration is missing, try fast cached duration lookup
        if (dur is None or dur <= 0) and url:
            cached_dur = find_cached_duration(url)
            if cached_dur and cached_dur > 0:
                dur = cached_dur
                side_dict["duration_seconds"] = dur

        return side_dict

    side_a = _resolve_side(req.video_a)
    side_b = _resolve_side(req.video_b)

    # Check exact comparison cache hit if both IDs are known
    exact_cached = req.exact_comparison_cached or False
    aid_a = side_a.get("analysis_id")
    aid_b = side_b.get("analysis_id")

    if not exact_cached and aid_a and aid_b and aid_a != aid_b:
        try:
            snap_a = build_video_snapshot(db=db, user_id=current_user.id, public_id=aid_a)
            snap_b = build_video_snapshot(db=db, user_id=current_user.id, public_id=aid_b)
            fp = compute_comparison_fingerprint(snap_a, snap_b)
            cached_comp = find_cached_comparison(
                db=db,
                user_id=current_user.id,
                analysis_id_a=aid_a,
                analysis_id_b=aid_b,
                input_fingerprint=fp
            )
            if cached_comp and cached_comp.status == "completed":
                exact_cached = True
        except Exception:
            pass

    est = pre_run_estimator.estimate_comparison_pre_run(
        video_a_data=side_a,
        video_b_data=side_b,
        comparison_model=req.comparison_model or "gemini-2.5-flash",
        exact_comparison_cached=exact_cached
    )

    return est
