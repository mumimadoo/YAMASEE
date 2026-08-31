import time
import hashlib
import threading
from typing import Dict, Any, Optional, Tuple

class IdempotencyStore:
    def __init__(self, ttl_seconds: int = 300, max_entries: int = 10000):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _make_store_key(self, user_id: int, operation: str, idempotency_key: str) -> str:
        return f"{user_id}:{operation}:{idempotency_key}"

    def _compute_payload_hash(self, payload_str: str) -> str:
        return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

    def _cleanup_expired_locked(self, now: float) -> None:
        expired_keys = [
            k for k, v in self._store.items()
            if v["expires_at"] <= now
        ]
        for k in expired_keys:
            del self._store[k]

        # Enforce max entries cap by removing oldest terminal entries
        if len(self._store) > self.max_entries:
            sorted_entries = sorted(self._store.items(), key=lambda x: x[1]["created_at"])
            overage = len(self._store) - self.max_entries
            for k, _ in sorted_entries[:overage]:
                del self._store[k]

    def check_or_reserve(
        self,
        user_id: int,
        operation: str,
        idempotency_key: str,
        payload_str: str
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Atomically checks or reserves an idempotency key.
        Returns tuple (status, data):
        - ("NEW", None): Key reserved cleanly for processing.
        - ("REPLAY", data): Key matches previous completed/processing request. Return saved response.
        - ("CONFLICT", None): Same key used with different payload.
        """
        now = time.time()
        store_key = self._make_store_key(user_id, operation, idempotency_key)
        payload_hash = self._compute_payload_hash(payload_str)

        with self._lock:
            self._cleanup_expired_locked(now)

            if store_key in self._store:
                entry = self._store[store_key]
                if entry["payload_hash"] != payload_hash:
                    return ("CONFLICT", None)
                return ("REPLAY", entry.get("response_data"))

            # Reserve new key
            self._store[store_key] = {
                "user_id": user_id,
                "operation": operation,
                "payload_hash": payload_hash,
                "response_data": None,
                "status": "processing",
                "created_at": now,
                "expires_at": now + self.ttl_seconds
            }
            return ("NEW", None)

    def record_response(
        self,
        user_id: int,
        operation: str,
        idempotency_key: str,
        response_data: Dict[str, Any]
    ) -> None:
        store_key = self._make_store_key(user_id, operation, idempotency_key)
        with self._lock:
            if store_key in self._store:
                self._store[store_key]["response_data"] = response_data
                self._store[store_key]["status"] = "completed"

    def release_key(self, user_id: int, operation: str, idempotency_key: str) -> None:
        store_key = self._make_store_key(user_id, operation, idempotency_key)
        with self._lock:
            self._store.pop(store_key, None)

    def clear_all(self) -> None:
        with self._lock:
            self._store.clear()

idempotency_store = IdempotencyStore(ttl_seconds=300, max_entries=10000)
