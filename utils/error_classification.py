import subprocess
import json
import sqlite3
from typing import Union
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

# Error Categories
DOWNLOAD_ERROR = "DOWNLOAD_ERROR"
FFMPEG_ERROR = "FFMPEG_ERROR"
FFPROBE_ERROR = "FFPROBE_ERROR"
TRANSCRIPTION_ERROR = "TRANSCRIPTION_ERROR"
AI_PROVIDER_ERROR = "AI_PROVIDER_ERROR"
JSON_PARSE_ERROR = "JSON_PARSE_ERROR"
DATABASE_ERROR = "DATABASE_ERROR"
FILESYSTEM_ERROR = "FILESYSTEM_ERROR"
VALIDATION_ERROR = "VALIDATION_ERROR"
SECURITY_ERROR = "SECURITY_ERROR"
TIMEOUT_ERROR = "TIMEOUT_ERROR"
UNKNOWN_ERROR = "UNKNOWN_ERROR"

def classify_error(err: Union[Exception, str]) -> str:
    """Classifies exceptions or error strings into standard operational error categories."""
    if isinstance(err, subprocess.TimeoutExpired):
        return TIMEOUT_ERROR
    
    if isinstance(err, json.JSONDecodeError):
        return JSON_PARSE_ERROR
    
    if isinstance(err, ValueError) and "json" in str(err).lower():
        return JSON_PARSE_ERROR

    if isinstance(err, (SQLAlchemyError, sqlite3.Error)):
        return DATABASE_ERROR

    if isinstance(err, (OSError, IOError, PermissionError, FileNotFoundError)):
        return FILESYSTEM_ERROR

    if isinstance(err, HTTPException):
        if err.status_code in (401, 403):
            return SECURITY_ERROR
        if err.status_code in (400, 422, 413, 415, 429):
            return VALIDATION_ERROR

    err_str = str(err).lower()
    
    if "timeout" in err_str or "timed out" in err_str:
        return TIMEOUT_ERROR
    if "yt-dlp" in err_str or "download" in err_str or "video_download" in err_str:
        return DOWNLOAD_ERROR
    if "ffprobe" in err_str:
        return FFPROBE_ERROR
    if "ffmpeg" in err_str:
        return FFMPEG_ERROR
    if "whisper" in err_str or "transcrib" in err_str or "vad" in err_str:
        return TRANSCRIPTION_ERROR
    if "gemini" in err_str or "ai" in err_str or "model" in err_str or "google" in err_str:
        return AI_PROVIDER_ERROR
    if "json" in err_str:
        return JSON_PARSE_ERROR
    if "db" in err_str or "database" in err_str or "sql" in err_str:
        return DATABASE_ERROR
    if "permission" in err_str or "unauthorized" in err_str or "forbidden" in err_str:
        return SECURITY_ERROR
    if "validation" in err_str or "invalid" in err_str:
        return VALIDATION_ERROR
    if "file" in err_str or "path" in err_str:
        return FILESYSTEM_ERROR

    return UNKNOWN_ERROR
