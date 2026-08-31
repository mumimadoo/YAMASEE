import hashlib
import json
import logging
import math
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import or_

from models.analysis_record import AnalysisRecord
from models.analysis_cache import AnalysisCache
from models.video_comparison import VideoComparison, utc_now
from utils.normalization import normalize_analysis_result
from utils.thumbnail_service import get_record_thumbnail_url
from schemas.comparison import (
    ComparisonVideoSnapshot,
    ComparisonTranscriptSegment,
    EvidenceReference,
    EvidenceVerificationStatus,
)

logger = logging.getLogger("yamasee.comparison_service")

# Default comparison schema version
DEFAULT_SCHEMA_VERSION = "1.1"

class ComparisonAuthorizationError(Exception):
    """Raised when user attempts to access analysis record they do not own."""
    pass

class ComparisonIneligibleError(Exception):
    """Raised when analysis record is not completed or lacks valid transcript."""
    pass

def create_comparison_identity(analysis_id_a: str, analysis_id_b: str) -> Dict[str, str]:
    """
    Computes a deterministic canonical pair identity for cache matching,
    while preserving the user's explicit display ordering.
    """
    ids = [analysis_id_a.strip(), analysis_id_b.strip()]
    ids_sorted = sorted(ids)
    canonical_pair_key = f"{ids_sorted[0]}:{ids_sorted[1]}"

    return {
        "canonical_pair_key": canonical_pair_key,
        "display_order_a": analysis_id_a.strip(),
        "display_order_b": analysis_id_b.strip(),
    }

def get_candidate_videos(
    db: Session,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None
) -> Dict[str, Any]:
    """
    Returns a paginated list of eligible completed analysis records for user_id.
    Filters strictly by ownership, completed status, cache existence, and transcript availability.
    """
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 20
    elif page_size > 50:
        page_size = 50

    base_query = db.query(AnalysisRecord).filter(
        AnalysisRecord.user_id == user_id,
        AnalysisRecord.status == "completed",
        AnalysisRecord.cache_id.isnot(None)
    )

    if search:
        clean_search = search.strip()[:200]
        if clean_search:
            base_query = base_query.filter(
                or_(
                    AnalysisRecord.display_title.ilike(f"%{clean_search}%"),
                    AnalysisRecord.original_filename.ilike(f"%{clean_search}%"),
                    AnalysisRecord.source_url.ilike(f"%{clean_search}%")
                )
            )

    records = base_query.order_by(AnalysisRecord.completed_at.desc(), AnalysisRecord.id.desc()).all()

    candidates = []
    for rec in records:
        # Verify cache has non-empty transcript segments
        cache = db.query(AnalysisCache).filter(AnalysisCache.id == rec.cache_id).first()
        if not cache or not cache.result_json:
            continue

        result_data = cache.result_json
        if isinstance(result_data, str):
            try:
                result_data = json.loads(result_data)
            except Exception:
                continue

        normalized_data = normalize_analysis_result(result_data)
        timeline = normalized_data.get("timeline", [])

        # Filter valid speech segments
        valid_segments = [
            seg for seg in timeline
            if isinstance(seg, dict) and seg.get("status") != "failed" and str(seg.get("text", "")).strip()
        ]

        if not valid_segments:
            continue

        thumb_url = get_record_thumbnail_url(rec)
        if not rec.thumbnail_url and thumb_url and thumb_url != "/static/Logo_boy.png":
            try:
                rec.thumbnail_url = thumb_url
                db.flush()
            except Exception:
                pass

        candidates.append({
            "public_id": rec.public_id,
            "analysis_id": rec.public_id,
            "display_title": rec.display_title,
            "source_type": rec.source_type,
            "source_url": rec.source_url,
            "duration_seconds": rec.duration_seconds,
            "thumbnail_url": thumb_url,
            "completed_at": rec.completed_at.isoformat() if rec.completed_at else None,
            "segment_count": len(valid_segments)
        })

    total = len(candidates)
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    offset = (page - 1) * page_size
    paged_items = candidates[offset : offset + page_size]

    return {
        "items": paged_items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1,
    }

def build_video_snapshot(
    db: Session,
    user_id: int,
    public_id: str
) -> ComparisonVideoSnapshot:
    """
    Normalizes existing analysis data into a stable ComparisonVideoSnapshot.
    Enforces authorization isolation and rejects incomplete or invalid records.
    Failed transcript segments are excluded and timestamps/segment IDs are strictly preserved.
    """
    record = db.query(AnalysisRecord).filter(AnalysisRecord.public_id == public_id).first()
    if not record:
        raise ComparisonAuthorizationError(f"Analysis record '{public_id}' not found.")

    if record.user_id != user_id:
        # Multi-tenant isolation: do not leak existence across users
        raise ComparisonAuthorizationError(f"Analysis record '{public_id}' not found.")

    if record.status != "completed":
        raise ComparisonIneligibleError(
            f"Analysis record '{public_id}' is not completed (status: {record.status})."
        )

    if not record.cache_id:
        raise ComparisonIneligibleError(f"Analysis record '{public_id}' has no associated analysis cache.")

    cache = db.query(AnalysisCache).filter(AnalysisCache.id == record.cache_id).first()
    if not cache or not cache.result_json:
        raise ComparisonIneligibleError(f"Analysis cache for '{public_id}' is missing or empty.")

    raw_result = cache.result_json
    if isinstance(raw_result, str):
        try:
            raw_result = json.loads(raw_result)
        except Exception as e:
            raise ComparisonIneligibleError(f"Invalid JSON in cache for '{public_id}': {e}") from e

    normalized_data = normalize_analysis_result(raw_result)
    timeline = normalized_data.get("timeline", [])

    transcript_segments: List[ComparisonTranscriptSegment] = []
    for idx, seg in enumerate(timeline):
        if not isinstance(seg, dict):
            continue
        # Exclude failed transcript segments
        if seg.get("status") == "failed":
            continue

        raw_text = str(seg.get("text", "")).strip()
        if not raw_text:
            continue

        seg_id = seg.get("id") or seg.get("segment_id") or (idx + 1)
        try:
            seg_id = int(seg_id)
        except (ValueError, TypeError):
            seg_id = idx + 1

        start_val = float(seg.get("start", 0.0))
        end_val = float(seg.get("end", start_val))
        label_val = str(seg.get("label", seg.get("time", f"[{start_val:.2f}]")))
        speaker_val = str(seg.get("speaker")) if seg.get("speaker") else None

        transcript_segments.append(
            ComparisonTranscriptSegment(
                segment_id=seg_id,
                start=start_val,
                end=end_val,
                label=label_val,
                text=raw_text,
                speaker=speaker_val,
            )
        )

    if not transcript_segments:
        raise ComparisonIneligibleError(f"Analysis record '{public_id}' contains no valid speech segments.")

    existing_analysis = {
        "summary": normalized_data.get("summary", []),
        "topics": normalized_data.get("telemetry", {}).get("topics", "General Analysis"),
        "keywords": normalized_data.get("keywords_chart", []),
        "sentiment_table": normalized_data.get("sentiment_table", []),
        "dominant_sentiment": normalized_data.get("dominant_sentiment") or normalized_data.get("current_emotion", ""),
        "chapters": normalized_data.get("video_chapters", []),
    }

    title = record.display_title or record.original_filename or record.source_url or f"Video {public_id[:8]}"
    duration = record.duration_seconds or cache.duration_seconds or 0.0
    analyzed_at = (record.completed_at or record.created_at or utc_now()).isoformat()

    # Compute lightweight input fingerprint for snapshot
    fp_str = (
        f"{record.public_id}:{analyzed_at}:{duration}:{len(transcript_segments)}:"
        f"{hashlib.sha256(''.join(s.text for s in transcript_segments).encode('utf-8')).hexdigest()[:16]}"
    )
    fingerprint = hashlib.sha256(fp_str.encode("utf-8")).hexdigest()

    return ComparisonVideoSnapshot(
        analysis_id=record.public_id,
        job_id=record.job_id,
        source_type=record.source_type,
        source_url=record.source_url,
        title=title,
        duration_seconds=float(duration),
        thumbnail=record.thumbnail_url,
        analyzed_at=analyzed_at,
        model_used=record.model_used or cache.model_used,
        transcript=transcript_segments,
        existing_analysis=existing_analysis,
        fingerprint=fingerprint,
    )

def compute_comparison_fingerprint(
    snapshot_a: ComparisonVideoSnapshot,
    snapshot_b: ComparisonVideoSnapshot
) -> str:
    """
    Computes a combined input fingerprint from two snapshots for cache staleness validation.
    Order-independent for canonical pair hashing.
    """
    pair_fingerprints = sorted([snapshot_a.fingerprint, snapshot_b.fingerprint])
    combined_str = f"{pair_fingerprints[0]}:{pair_fingerprints[1]}"
    return hashlib.sha256(combined_str.encode("utf-8")).hexdigest()

def validate_evidence(
    evidence: Dict[str, Any] | EvidenceReference,
    snapshot_a: ComparisonVideoSnapshot,
    snapshot_b: ComparisonVideoSnapshot
) -> Dict[str, Any]:
    """
    Validates an AI evidence reference against authoritative transcript segments in the snapshots.
    Evidence must point back to real transcript segments.
    Returns status: VERIFIED, PARTIALLY_VERIFIED, or UNVERIFIED.
    """
    if isinstance(evidence, dict):
        video = str(evidence.get("video", "")).upper()
        seg_id = evidence.get("segment_id")
        start = evidence.get("start")
        end = evidence.get("end")
        timestamp = evidence.get("timestamp", "")
    else:
        video = evidence.video.upper()
        seg_id = evidence.segment_id
        start = evidence.start
        end = evidence.end
        timestamp = evidence.timestamp

    if video not in {"A", "B"}:
        return {
            "status": EvidenceVerificationStatus.UNVERIFIED.value,
            "resolved_text": None,
            "reason": f"Invalid video target identifier '{video}' (must be 'A' or 'B')."
        }

    target_snapshot = snapshot_a if video == "A" else snapshot_b
    segments = target_snapshot.transcript

    if seg_id is None and start is None:
        return {
            "status": EvidenceVerificationStatus.UNVERIFIED.value,
            "resolved_text": None,
            "reason": "Missing both segment_id and start timestamp."
        }

    # 1. Attempt exact segment_id resolution
    found_by_id = None
    if seg_id is not None:
        for seg in segments:
            if seg.segment_id == seg_id:
                found_by_id = seg
                break

    if found_by_id:
        # Check timestamp alignment if start/end provided
        if start is not None and end is not None:
            if abs(found_by_id.start - float(start)) <= 3.0 and abs(found_by_id.end - float(end)) <= 3.0:
                return {
                    "status": EvidenceVerificationStatus.VERIFIED.value,
                    "resolved_text": found_by_id.text,
                    "segment": found_by_id.model_dump(),
                    "reason": "Exact match on segment_id and timestamps."
                }
            else:
                return {
                    "status": EvidenceVerificationStatus.PARTIALLY_VERIFIED.value,
                    "resolved_text": found_by_id.text,
                    "segment": found_by_id.model_dump(),
                    "reason": "Matching segment_id found, but timestamps slightly differ."
                }
        return {
            "status": EvidenceVerificationStatus.VERIFIED.value,
            "resolved_text": found_by_id.text,
            "segment": found_by_id.model_dump(),
            "reason": "Exact match on segment_id."
        }

    # 2. Attempt fallback timestamp resolution
    if start is not None:
        start_flt = float(start)
        for seg in segments:
            if abs(seg.start - start_flt) <= 2.0:
                return {
                    "status": EvidenceVerificationStatus.PARTIALLY_VERIFIED.value,
                    "resolved_text": seg.text,
                    "segment": seg.model_dump(),
                    "reason": f"Segment ID {seg_id} not found, but resolved by timestamp range within tolerance."
                }

    return {
        "status": EvidenceVerificationStatus.UNVERIFIED.value,
        "resolved_text": None,
        "reason": f"Evidence segment {seg_id} could not be resolved in Video {video} transcript."
    }

def find_cached_comparison(
    db: Session,
    user_id: int,
    analysis_id_a: str,
    analysis_id_b: str,
    input_fingerprint: str,
    schema_version: str = DEFAULT_SCHEMA_VERSION
) -> Optional[VideoComparison]:
    """
    Searches for an existing cached comparison for canonical pair (A+B or B+A).
    Returns cached entry if fingerprint matches. Returns None if stale or not found.
    """
    identity = create_comparison_identity(analysis_id_a, analysis_id_b)
    canonical_key = identity["canonical_pair_key"]

    cached = (
        db.query(VideoComparison)
        .filter(
            VideoComparison.user_id == user_id,
            VideoComparison.canonical_pair_key == canonical_key,
            VideoComparison.schema_version == schema_version,
            VideoComparison.status == "completed"
        )
        .order_by(VideoComparison.updated_at.desc())
        .first()
    )

    if not cached:
        return None

    # Check input fingerprint for cache staleness
    if cached.input_fingerprint != input_fingerprint:
        logger.info(
            f"Cached comparison {cached.public_id} is stale (input fingerprint changed). Skipping cache hit."
        )
        return None

    return cached

def persist_comparison(
    db: Session,
    user_id: int,
    analysis_id_a: str,
    analysis_id_b: str,
    comparison_result: Dict[str, Any],
    input_fingerprint: str,
    schema_version: str = DEFAULT_SCHEMA_VERSION,
    status: str = "completed",
    error_message: Optional[str] = None,
    processing_seconds: Optional[float] = None,
    api_calls: int = 0,
    token_usage: Optional[Dict[str, Any]] = None,
    model_used: Optional[str] = None,
) -> VideoComparison:
    """
    Persists or updates a VideoComparison record for user_id.
    Maintains canonical pair identity while storing user's display order.
    """
    identity = create_comparison_identity(analysis_id_a, analysis_id_b)
    canonical_key = identity["canonical_pair_key"]

    existing = (
        db.query(VideoComparison)
        .filter(
            VideoComparison.user_id == user_id,
            VideoComparison.canonical_pair_key == canonical_key,
            VideoComparison.schema_version == schema_version
        )
        .first()
    )

    if existing:
        existing.display_order_a = identity["display_order_a"]
        existing.display_order_b = identity["display_order_b"]
        existing.input_fingerprint = input_fingerprint
        existing.status = status
        existing.result_json = comparison_result
        existing.error_message = error_message
        existing.processing_seconds = processing_seconds
        existing.api_calls = api_calls
        existing.token_usage = token_usage
        if model_used:
            existing.model_used = model_used
        existing.updated_at = utc_now()
        db.flush()
        db.commit()
        db.refresh(existing)
        return existing

    comp = VideoComparison(
        user_id=user_id,
        canonical_pair_key=canonical_key,
        analysis_id_a=identity["display_order_a"],
        analysis_id_b=identity["display_order_b"],
        display_order_a=identity["display_order_a"],
        display_order_b=identity["display_order_b"],
        input_fingerprint=input_fingerprint,
        schema_version=schema_version,
        status=status,
        result_json=comparison_result,
        error_message=error_message,
        model_used=model_used,
        processing_seconds=processing_seconds,
        api_calls=api_calls,
        token_usage=token_usage,
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    db.add(comp)
    db.flush()
    db.commit()
    db.refresh(comp)
    return comp

def get_comparison(
    db: Session,
    user_id: int,
    comparison_public_id: str
) -> Optional[VideoComparison]:
    """
    Retrieves a VideoComparison by public_id owned by user_id.
    """
    return (
        db.query(VideoComparison)
        .filter(
            VideoComparison.public_id == comparison_public_id,
            VideoComparison.user_id == user_id
        )
        .first()
    )

def prepare_phase2_input_builder(
    snapshot_a: ComparisonVideoSnapshot,
    snapshot_b: ComparisonVideoSnapshot
) -> Dict[str, Any]:
    """
    Prepares the context payload for Phase 2 comparison engine.
    Calculates character sizes, estimates tokens, and checks context limits.
    DOES NOT INVOKE GEMINI.
    """
    text_a = f"VIDEO A: {snapshot_a.title}\n" + "\n".join(
        f"[{s.label}] {s.text}" for s in snapshot_a.transcript
    )
    text_b = f"VIDEO B: {snapshot_b.title}\n" + "\n".join(
        f"[{s.label}] {s.text}" for s in snapshot_b.transcript
    )

    char_a = len(text_a)
    char_b = len(text_b)
    combined_chars = char_a + char_b

    # Approximate token ratio (~3.5 chars per token for Thai/English mixed text)
    est_tokens = math.ceil(combined_chars / 3.5)

    # Gemini Flash models have 1,000,000+ token context window (~3,500,000 characters)
    gemini_context_safe = combined_chars < 3_000_000

    prompt_instructions = (
        "Instructions: Compare Video A and Video B based strictly on their transcripts and analysis outputs. "
        "Return structured JSON matching the 9 required comparison sections (01-09) and reference real segment IDs for all evidence claims."
    )

    return {
        "snapshot_a_char_count": char_a,
        "snapshot_b_char_count": char_b,
        "combined_char_count": combined_chars,
        "estimated_transcript_tokens": est_tokens,
        "gemini_context_safe": gemini_context_safe,
        "prompt_preview": f"--- CONTEXT VIDEO A ({char_a} chars) ---\n{text_a[:200]}...\n\n--- CONTEXT VIDEO B ({char_b} chars) ---\n{text_b[:200]}...\n\n--- INSTRUCTIONS ---\n{prompt_instructions}",
    }

def list_user_comparisons(
    db: Session,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """
    Returns a paginated list of video comparisons created by user_id.
    Strictly isolated per user. Resolves Video A/B titles and thumbnails.
    """
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 20
    elif page_size > 50:
        page_size = 50

    base_query = db.query(VideoComparison).filter(VideoComparison.user_id == user_id)
    total = base_query.count()
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    offset = (page - 1) * page_size

    records = (
        base_query.order_by(VideoComparison.created_at.desc(), VideoComparison.id.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    items = []
    for comp in records:
        rec_a = db.query(AnalysisRecord).filter(AnalysisRecord.public_id == comp.display_order_a).first()
        rec_b = db.query(AnalysisRecord).filter(AnalysisRecord.public_id == comp.display_order_b).first()

        video_a_meta = {
            "analysis_id": comp.display_order_a,
            "title": rec_a.display_title if rec_a else f"Video A ({comp.display_order_a[:8]})",
            "thumbnail_url": rec_a.thumbnail_url if rec_a else "/static/Logo_boy.png",
            "source_type": rec_a.source_type if rec_a else "unknown",
        }

        video_b_meta = {
            "analysis_id": comp.display_order_b,
            "title": rec_b.display_title if rec_b else f"Video B ({comp.display_order_b[:8]})",
            "thumbnail_url": rec_b.thumbnail_url if rec_b else "/static/Logo_boy.png",
            "source_type": rec_b.source_type if rec_b else "unknown",
        }

        total_tokens = 0
        if comp.token_usage:
            if isinstance(comp.token_usage, dict):
                total_tokens = (
                    comp.token_usage.get("comparison", {}).get("total_tokens")
                    or comp.token_usage.get("total_tokens")
                    or comp.token_usage.get("total")
                    or 0
                )
            elif isinstance(comp.token_usage, int):
                total_tokens = comp.token_usage

        items.append({
            "public_id": comp.public_id,
            "canonical_pair_key": comp.canonical_pair_key,
            "display_order_a": comp.display_order_a,
            "display_order_b": comp.display_order_b,
            "status": comp.status,
            "model_used": comp.model_used or "gemini-2.5-flash",
            "processing_seconds": comp.processing_seconds or 0.0,
            "api_calls": comp.api_calls,
            "token_usage": comp.token_usage,
            "total_tokens": total_tokens,
            "cached": comp.api_calls == 0,
            "created_at": comp.created_at.isoformat() if comp.created_at else None,
            "updated_at": comp.updated_at.isoformat() if comp.updated_at else None,
            "video_a": video_a_meta,
            "video_b": video_b_meta,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1,
    }

