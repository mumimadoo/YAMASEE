"""
YAMASEE — Asynchronous Duration Resolver Service
Fetches media duration metadata asynchronously for new/cache-miss URLs without blocking the FastAPI event loop.

Rules:
- Metadata only (no video/audio download).
- Non-blocking (runs yt-dlp in asyncio.to_thread).
- Timeout protection (8-10 seconds).
- 0 Gemini calls, 0 Search calls.
"""

import asyncio
import subprocess
import re
import os
import logging
import json
from typing import Optional, Dict, Any
from database import SessionLocal
from models.analysis_cache import AnalysisCache
from models.analysis_record import AnalysisRecord
from engines.video_engine import VideoEngine
from services.pre_run_estimator import pre_run_estimator

logger = logging.getLogger("yamasee.duration_service")
HISTORY_DIR = "analysis_history"
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_MEDIA_DIR = os.path.join(PROJECT_DIR, "data", "cache", "media")


def find_cached_duration(url_or_filename: str, source_type: str = "youtube") -> Optional[float]:
    """
    Checks if video duration already exists in AnalysisCache, AnalysisRecord, or local history files.
    Fast & synchronous DB/file check (0 yt-dlp calls).
    """
    if not url_or_filename:
        return None

    unique_id = VideoEngine.extract_unique_video_id(url_or_filename)

    # 1. Check persisted AnalysisRecord and AnalysisCache metadata.
    db = SessionLocal()
    try:
        rec_obj = (
            db.query(AnalysisRecord)
            .filter(
                AnalysisRecord.source_url == url_or_filename,
                AnalysisRecord.duration_seconds.isnot(None),
                AnalysisRecord.duration_seconds > 0,
            )
            .order_by(AnalysisRecord.id.desc())
            .first()
        )
        if not rec_obj and unique_id.startswith("youtube_"):
            video_id = unique_id.removeprefix("youtube_")
            rec_obj = (
                db.query(AnalysisRecord)
                .filter(
                    AnalysisRecord.source_url.contains(video_id),
                    AnalysisRecord.duration_seconds.isnot(None),
                    AnalysisRecord.duration_seconds > 0,
                )
                .order_by(AnalysisRecord.id.desc())
                .first()
            )
        if rec_obj:
            return float(rec_obj.duration_seconds)

        cache_obj = db.query(AnalysisCache).filter(AnalysisCache.media_key == unique_id).first()
        if cache_obj and cache_obj.duration_seconds and float(cache_obj.duration_seconds) > 0:
            return float(cache_obj.duration_seconds)

        if cache_obj:
            rec_obj = db.query(AnalysisRecord).filter(AnalysisRecord.cache_id == cache_obj.id).first()
            if rec_obj and rec_obj.duration_seconds and float(rec_obj.duration_seconds) > 0:
                return float(rec_obj.duration_seconds)
    except Exception as e:
        logger.warning(f"DB duration lookup error: {e}")
    finally:
        db.close()

    # 2. Check the existing analysis history payload.
    history_file_path = os.path.join(PROJECT_DIR, HISTORY_DIR, f"{unique_id}.json")
    if os.path.exists(history_file_path):
        try:
            with open(history_file_path, "r", encoding="utf-8") as h_file:
                saved_result = json.load(h_file)
                dur = saved_result.get("duration_seconds") or saved_result.get("duration")
                if dur and float(dur) > 0:
                    return float(dur)
        except Exception:
            pass

    # 3. Probe only an already-present local media cache; never download for duration.
    cached_media_path = os.path.join(CACHE_MEDIA_DIR, f"{unique_id}.mp4")
    if os.path.isfile(cached_media_path):
        import shutil
        ffprobe_bin = os.path.join(PROJECT_DIR, "ffprobe.exe")
        if not os.path.isfile(ffprobe_bin):
            ffprobe_bin = shutil.which("ffprobe")
        if ffprobe_bin:
            try:
                probe = subprocess.run(
                    [ffprobe_bin, "-v", "error", "-show_entries", "format=duration", "-of", "json", cached_media_path],
                    capture_output=True, text=True, timeout=5, check=False,
                )
                if probe.returncode == 0:
                    duration = float(json.loads(probe.stdout or "{}").get("format", {}).get("duration", 0) or 0)
                    if duration > 0:
                        return duration
            except (OSError, subprocess.SubprocessError, ValueError, TypeError, json.JSONDecodeError):
                pass

    return None


def _yt_dlp_fetch_duration_sync(url: str, timeout_seconds: float = 12.0) -> Optional[float]:
    """
    Executes one bounded yt-dlp metadata-only duration fetch.
    Intended to be called via asyncio.to_thread.
    """
    import shutil

    ytdlp_bin = shutil.which("yt-dlp") or os.path.join(PROJECT_DIR, "yt-dlp.exe")
    if os.path.isfile(ytdlp_bin):
        cmd = [ytdlp_bin]
    else:
        import sys
        cmd = [sys.executable, "-m", "yt_dlp"]

    socket_timeout = max(3, min(8, int(timeout_seconds) - 1))
    cmd.extend([
        "--no-warnings",
        "--no-playlist",
        "--skip-download",
        "--socket-timeout", str(socket_timeout),
        "--extractor-args", "youtube:player_client=android_vr",
        "--print", "%(duration)s",
        url
    ])
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds
        )
        if res.returncode == 0:
            out_str = res.stdout.strip()
            lines = [l.strip() for l in out_str.split("\n") if l.strip()]
            for l in reversed(lines):
                try:
                    dur_val = float(l)
                    if dur_val > 0:
                        return dur_val
                except ValueError:
                    continue
        logger.warning(f"yt-dlp duration fetch non-zero exit code for {url}: {res.stderr}")
    except subprocess.TimeoutExpired:
        logger.warning(f"yt-dlp duration fetch timed out after {timeout_seconds}s for {url}")
    except Exception as e:
        logger.error(f"yt-dlp duration fetch error for {url}: {e}")

    return None


def normalize_tiktok_url(url: str) -> str:
    """Normalize TikTok URLs by stripping query parameters."""
    if url and "tiktok.com" in url.lower():
        return url.split("?")[0]
    return url


async def resolve_media_metadata(
    url: str,
    source_type: str = "youtube",
    timeout_seconds: float = 14.0
) -> Dict[str, Any]:
    """
    ONE SOURCE OF TRUTH: Resolves media metadata (duration_seconds, normalized_url, source_type)
    asynchronously without blocking the FastAPI event loop.
    """
    if not url or not url.strip():
        return {
            "status": "failed",
            "reason": "Missing URL",
            "normalized_url": "",
            "source_type": source_type,
            "duration_seconds": None
        }

    clean_url = url.strip()
    st_type = source_type or "youtube"
    if "tiktok.com" in clean_url.lower():
        st_type = "tiktok"
        clean_url = normalize_tiktok_url(clean_url)

    # 1. Fast Cache/Database Lookup
    cached_dur = find_cached_duration(clean_url, st_type)
    if cached_dur is not None and cached_dur > 0:
        logger.info(f"Media metadata cache hit for {clean_url}: {cached_dur}s")
        return {
            "status": "success",
            "normalized_url": clean_url,
            "source_type": st_type,
            "duration_seconds": cached_dur
        }

    # 2. Async yt-dlp Metadata Lookup
    dur = None
    try:
        dur = await asyncio.wait_for(
            asyncio.to_thread(_yt_dlp_fetch_duration_sync, clean_url, max(5.0, timeout_seconds - 1.0)),
            timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        logger.warning(f"Metadata resolution timed out for {clean_url}")
    except Exception as e:
        logger.error(f"Metadata resolution error for {clean_url}: {e}")

    if dur and dur > 0:
        logger.info(f"Media metadata resolved for {clean_url}: {dur}s")
        return {
            "status": "success",
            "normalized_url": clean_url,
            "source_type": st_type,
            "duration_seconds": dur
        }

    # A persisted record or local cache may have completed during the external lookup.
    fallback_dur = find_cached_duration(clean_url, st_type)
    if fallback_dur is not None and fallback_dur > 0:
        return {
            "status": "success",
            "normalized_url": clean_url,
            "source_type": st_type,
            "duration_seconds": fallback_dur
        }

    return {
        "status": "failed",
        "reason": "ไม่สามารถตรวจสอบความยาวสื่อได้ในขณะนี้",
        "normalized_url": clean_url,
        "source_type": st_type,
        "duration_seconds": None
    }


async def resolve_url_duration_async(
    url: str,
    source_type: str = "youtube",
    timeout_seconds: float = 14.0
) -> Optional[float]:
    """
    Backwards-compatible wrapper delegating to resolve_media_metadata.
    """
    res = await resolve_media_metadata(url, source_type, timeout_seconds)
    return res.get("duration_seconds")
