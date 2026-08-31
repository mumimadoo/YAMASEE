import sys
import os
import json
import logging
import datetime
import re
from contextvars import ContextVar
from typing import Optional, Any, Dict

request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
job_id_ctx: ContextVar[Optional[str]] = ContextVar("job_id", default=None)
user_id_ctx: ContextVar[Optional[int]] = ContextVar("user_id", default=None)
component_ctx: ContextVar[Optional[str]] = ContextVar("component", default="app")
stage_ctx: ContextVar[Optional[str]] = ContextVar("stage", default="general")

SENSITIVE_PATTERNS = [
    (re.compile(r'(api[_-]?key|secret|password|authorization|cookie|session)=([^\s&",]+)', re.IGNORECASE), r'\1=***REDACTED***'),
    (re.compile(r'(Bearer\s+)[A-Za-z0-9\-\._~\+\/]+=*', re.IGNORECASE), r'\1***REDACTED***'),
    (re.compile(r'("?(?:api[_-]?key|secret|password|authorization|cookie|session|app_secret_key)"?\s*:\s*)"([^"]+)"', re.IGNORECASE), r'\1"***REDACTED***"'),
]

def sanitize_message(msg: str) -> str:
    if not isinstance(msg, str):
        msg = str(msg)
    for pattern, replacement in SENSITIVE_PATTERNS:
        msg = pattern.sub(replacement, msg)
    return msg

class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        req_id = getattr(record, "request_id", None) or request_id_ctx.get() or "-"
        j_id = getattr(record, "job_id", None) or job_id_ctx.get() or "-"
        u_id = getattr(record, "user_id", None) or user_id_ctx.get() or "-"
        comp = getattr(record, "component", None) or component_ctx.get() or "app"
        stg = getattr(record, "stage", None) or stage_ctx.get() or "general"

        msg = record.getMessage()
        sanitized_msg = sanitize_message(msg)

        log_data: Dict[str, Any] = {
            "timestamp": datetime.datetime.fromtimestamp(record.created, datetime.timezone.utc).isoformat(),
            "level": record.levelname,
            "request_id": str(req_id),
            "job_id": str(j_id),
            "user_id": u_id if u_id is not None else "-",
            "component": comp,
            "stage": stg,
            "message": sanitized_msg,
        }

        if hasattr(record, "error_category"):
            log_data["error_category"] = record.error_category

        return json.dumps(log_data, ensure_ascii=False)

def setup_logger():
    os.makedirs("logs", exist_ok=True)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Avoid duplicate handlers if setup is called multiple times
    if not any(isinstance(h.formatter, StructuredFormatter) for h in root_logger.handlers):
        formatter = StructuredFormatter()
        
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        file_handler = logging.FileHandler("logs/app.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

setup_logger()

logger = logging.getLogger("yamasee")

def get_logger(name: Optional[str] = None) -> logging.Logger:
    if name:
        return logging.getLogger(name)
    return logger