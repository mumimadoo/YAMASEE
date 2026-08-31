import os
import re
import shutil
import subprocess
import logging
from typing import Optional

logger = logging.getLogger("yamasee.thumbnail_service")

THUMBNAILS_DIR = os.path.join(os.getcwd(), "static", "thumbnails")

def ensure_thumbnails_dir():
    os.makedirs(THUMBNAILS_DIR, exist_ok=True)

def extract_youtube_video_id(url_or_id: str) -> Optional[str]:
    if not url_or_id:
        return None
    match = re.search(r'(youtu\.be\/|v\/|u\/\w\/|embed\/|watch\?v=|\&v=)([^#\&\?]*)', url_or_id)
    if match and len(match.group(2)) == 11:
        return match.group(2)
    clean = url_or_id.strip()
    if len(clean) == 11 and re.match(r'^[a-zA-Z0-9_-]{11}$', clean):
        return clean
    return None

def get_youtube_thumbnail_url(url_or_id: str) -> Optional[str]:
    vid = extract_youtube_video_id(url_or_id)
    if vid:
        return f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
    return None

def generate_mp4_thumbnail(video_path: str, job_id_or_hash: str, duration_seconds: Optional[float] = None) -> Optional[str]:
    """
    Generates a single-frame thumbnail (480px width JPEG) for a local video file using FFmpeg.
    Returns static URL path (e.g. '/static/thumbnails/<clean_id>.jpg') or None.
    """
    if not video_path or not os.path.isfile(video_path) or os.path.getsize(video_path) == 0:
        return None

    try:
        ensure_thumbnails_dir()
        safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', job_id_or_hash)
        thumb_filename = f"{safe_id}.jpg"
        thumb_filepath = os.path.join(THUMBNAILS_DIR, thumb_filename)

        if os.path.exists(thumb_filepath) and os.path.getsize(thumb_filepath) > 0:
            return f"/static/thumbnails/{thumb_filename}"

        seek_pos = 1.0
        if duration_seconds and float(duration_seconds) > 2.0:
            seek_pos = round(float(duration_seconds) * 0.10, 2)

        ffmpeg_bin = shutil.which("ffmpeg") or os.path.join(os.getcwd(), "ffmpeg.exe")
        cmd = [
            ffmpeg_bin, "-y",
            "-ss", str(seek_pos),
            "-i", video_path,
            "-vframes", "1",
            "-vf", "scale=480:-1",
            "-q:v", "3",
            thumb_filepath
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and os.path.exists(thumb_filepath) and os.path.getsize(thumb_filepath) > 0:
            return f"/static/thumbnails/{thumb_filename}"
    except Exception as e:
        logger.warning(f"FFmpeg thumbnail generation error for {video_path}: {e}")

    return None

def find_local_media_file(job_id_or_url: str, original_filename: Optional[str] = None) -> Optional[str]:
    """Locates existing video file on local disk if available."""
    safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', job_id_or_url)
    
    candidate_paths = [
        os.path.join(os.getcwd(), "static", f"{safe_id}.mp4"),
        os.path.join(os.getcwd(), "temp_jobs", safe_id, "temp_video.mp4"),
        os.path.join(os.getcwd(), "temp_jobs", safe_id, "video.mp4"),
    ]
    if original_filename:
        candidate_paths.append(os.path.join(os.getcwd(), "temp_jobs", safe_id, original_filename))
        candidate_paths.append(os.path.join(os.getcwd(), "static", original_filename))

    for path in candidate_paths:
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return path
    return None

def get_record_thumbnail_url(rec) -> str:
    """
    Guarantees a valid thumbnail URL for any AnalysisRecord.
    0 network calls, 0 Gemini calls, instant O(1) resolution.
    """
    if getattr(rec, "thumbnail_url", None) and rec.thumbnail_url.strip():
        return rec.thumbnail_url.strip()

    source_type = (getattr(rec, "source_type", "") or "").lower()
    source_url = getattr(rec, "source_url", "") or ""
    job_id = getattr(rec, "job_id", "") or str(getattr(rec, "public_id", ""))

    # 1. YouTube instant resolution
    if source_type == "youtube" or "youtube.com" in source_url or "youtu.be" in source_url:
        yt_thumb = get_youtube_thumbnail_url(source_url) or get_youtube_thumbnail_url(job_id)
        if yt_thumb:
            return yt_thumb

    # 2. Check if local generated thumbnail file already exists
    safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', job_id)
    local_thumb_file = os.path.join(THUMBNAILS_DIR, f"{safe_id}.jpg")
    if os.path.exists(local_thumb_file) and os.path.getsize(local_thumb_file) > 0:
        return f"/static/thumbnails/{safe_id}.jpg"

    # 3. Check if local MP4 / media file exists and generate thumbnail on the fly
    local_media = find_local_media_file(job_id, getattr(rec, "original_filename", None))
    if local_media:
        gen = generate_mp4_thumbnail(local_media, safe_id, getattr(rec, "duration_seconds", None))
        if gen:
            return gen

    # 4. Fallback placeholder
    return "/static/Logo_boy.png"
