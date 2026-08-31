import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class Settings:
    def __init__(self):
        self.app_env: str = os.getenv("APP_ENV", "development").lower()
        
        raw_secret_key = os.getenv("APP_SECRET_KEY")
        if not raw_secret_key:
            if self.app_env == "production":
                raise ValueError("CRITICAL: APP_SECRET_KEY must be set when APP_ENV is production!")
            else:
                logger.warning(
                    "WARNING: APP_SECRET_KEY is not set in development mode. "
                    "Using insecure fallback secret key for development only."
                )
                self.app_secret_key: str = "dev-insecure-secret-key-change-in-production-32chars"
        else:
            if self.app_env == "production" and len(raw_secret_key) < 32:
                raise ValueError("CRITICAL: APP_SECRET_KEY must be at least 32 characters in production!")
            self.app_secret_key: str = raw_secret_key

        self.database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/yamasee.db")
        
        # Session settings
        raw_https_only = os.getenv("SESSION_HTTPS_ONLY", "false").lower()
        self.session_https_only: bool = raw_https_only in {"true", "1", "yes", "on"}
        
        if self.app_env == "production" and not self.session_https_only:
            raise ValueError("CRITICAL: SESSION_HTTPS_ONLY must be true when APP_ENV is production!")

        raw_max_age = os.getenv("SESSION_MAX_AGE_SECONDS", "604800")
        try:
            self.session_max_age_seconds: int = int(raw_max_age)
        except ValueError:
            self.session_max_age_seconds: int = 604800

        # Storage settings
        self.cache_dir: str = os.getenv("CACHE_DIR", "data/cache")
        self.history_dir: str = os.getenv("HISTORY_DIR", "analysis_history")
        
        raw_keep_media = os.getenv("KEEP_MEDIA_FILES", "false").lower()
        self.keep_media_files: bool = raw_keep_media in {"true", "1", "yes", "on"}

        # Job cleanup settings
        raw_ttl = os.getenv("JOB_TERMINAL_TTL_SECONDS", "3600")
        try:
            val_ttl = int(raw_ttl)
            self.job_terminal_ttl_seconds: int = val_ttl if val_ttl > 0 else 3600
        except ValueError:
            self.job_terminal_ttl_seconds: int = 3600

        raw_max_del = os.getenv("JOB_CLEANUP_MAX_DELETIONS", "50")
        try:
            val_del = int(raw_max_del)
            self.job_cleanup_max_deletions: int = val_del if val_del > 0 else 50
        except ValueError:
            self.job_cleanup_max_deletions: int = 50

        raw_max_scans = os.getenv("JOB_CLEANUP_MAX_SCANS", "200")
        try:
            val_scans = int(raw_max_scans)
            self.job_cleanup_max_scans: int = val_scans if val_scans > 0 else 200
        except ValueError:
            self.job_cleanup_max_scans: int = 200

        # Request Size Limit Settings (bytes)
        self.max_file_bytes: int = 2147483648 # 2 GB
        raw_max_upload = os.getenv("MAX_UPLOAD_BYTES", "2157969408") # Default 2 GB + 10 MiB multipart overhead
        try:
            val_upload = int(raw_max_upload)
            self.max_upload_bytes: int = val_upload if val_upload > 0 else 2157969408
        except ValueError:
            self.max_upload_bytes: int = 2157969408

        raw_max_json = os.getenv("MAX_JSON_BODY_BYTES", "10485760") # Default 10 MiB
        try:
            val_json = int(raw_max_json)
            self.max_json_body_bytes: int = val_json if val_json > 0 else 10485760
        except ValueError:
            self.max_json_body_bytes: int = 10485760

        raw_max_form = os.getenv("MAX_FORM_BODY_BYTES", "10485760") # Default 10 MiB
        try:
            val_form = int(raw_max_form)
            self.max_form_body_bytes: int = val_form if val_form > 0 else 10485760
        except ValueError:
            self.max_form_body_bytes: int = 10485760

        # Subprocess Timeout Settings (seconds)
        raw_ffmpeg_timeout = os.getenv("FFMPEG_TIMEOUT_SECONDS", "300")
        try:
            val_ffmpeg = int(raw_ffmpeg_timeout)
            self.ffmpeg_timeout_seconds: int = val_ffmpeg if val_ffmpeg > 0 else 300
        except ValueError:
            self.ffmpeg_timeout_seconds: int = 300

        raw_ffprobe_timeout = os.getenv("FFPROBE_TIMEOUT_SECONDS", "60")
        try:
            val_ffprobe = int(raw_ffprobe_timeout)
            self.ffprobe_timeout_seconds: int = val_ffprobe if val_ffprobe > 0 else 60
        except ValueError:
            self.ffprobe_timeout_seconds: int = 60

        # Phase 8 Performance & Reliability Settings
        raw_max_term = os.getenv("MAX_TERMINAL_JOBS_IN_MEMORY", "500")
        try:
            val_term = int(raw_max_term)
            self.max_terminal_jobs_in_memory: int = val_term if val_term > 0 else 500
        except ValueError:
            self.max_terminal_jobs_in_memory: int = 500

        raw_idem_ttl = os.getenv("IDEMPOTENCY_TTL_SECONDS", "300")
        try:
            val_idem = int(raw_idem_ttl)
            self.idempotency_ttl_seconds: int = val_idem if val_idem > 0 else 300
        except ValueError:
            self.idempotency_ttl_seconds: int = 300

        raw_idem_max = os.getenv("IDEMPOTENCY_MAX_ENTRIES", "10000")
        try:
            val_idem_max = int(raw_idem_max)
            self.idempotency_max_entries: int = val_idem_max if val_idem_max > 0 else 10000
        except ValueError:
            self.idempotency_max_entries: int = 10000

        raw_active_limit = os.getenv("ACTIVE_JOBS_LIMIT", "10")
        try:
            val_active = int(raw_active_limit)
            self.active_jobs_limit: int = val_active if val_active > 0 else 10
        except ValueError:
            self.active_jobs_limit: int = 10

        # API Keys
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")

settings = Settings()
