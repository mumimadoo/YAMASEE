import time
import threading
from typing import Optional, Dict, Any, List
from utils.logger import get_logger, component_ctx

logger = get_logger("audit_trail")

# In-memory bounded audit log buffer (max 1000 items)
MAX_AUDIT_LOGS = 1000
_audit_logs_buffer: List[Dict[str, Any]] = []
_audit_lock = threading.Lock()

FORBIDDEN_AUDIT_KEYS = {
    "prompt", "transcript", "result_json", "secret", "password", 
    "api_key", "token", "cookie", "authorization", "confirm_password"
}

def _sanitize_audit_details(details: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = {}
    for key, value in details.items():
        key_lower = str(key).lower()
        if key_lower in FORBIDDEN_AUDIT_KEYS or any(f in key_lower for f in ("secret", "password", "prompt", "transcript", "token")):
            continue
        sanitized[key] = value
    return sanitized

def record_audit_event(event_type: str, user_id: Optional[int] = None, details: Optional[Dict[str, Any]] = None):
    """
    Records an operational audit trail event.
    Guarantees no sensitive data (passwords, raw prompts, full transcripts, secrets) is recorded.
    """
    clean_details = _sanitize_audit_details(details) if details else {}
    
    event_entry = {
        "event_type": event_type,
        "user_id": user_id if user_id is not None else "-",
        "timestamp": time.time(),
        "details": clean_details
    }

    with _audit_lock:
        _audit_logs_buffer.append(event_entry)
        if len(_audit_logs_buffer) > MAX_AUDIT_LOGS:
            _audit_logs_buffer.pop(0)

    # Log to structured log file/stream under component="audit_trail"
    logger.info(
        f"AUDIT_EVENT: {event_type} for user_id={user_id}",
        extra={
            "component": "audit_trail",
            "stage": "audit",
            "user_id": user_id,
            "details": clean_details
        }
    )

def get_audit_trail_snapshot(limit: int = 100) -> List[Dict[str, Any]]:
    with _audit_lock:
        return list(_audit_logs_buffer[-limit:])
