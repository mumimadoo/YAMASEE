"""
In-memory rate limiter for login failure protection.

Note: This in-memory implementation is designed for single-process / development environments.
For multi-worker or multi-process production deployments, this should be replaced with a shared store (e.g., Redis).
"""

import time
from typing import Callable

class LoginRateLimiter:
    def __init__(self, max_attempts: int = 50, window_seconds: int = 600):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, list[float]] = {}

    def _get_key(self, email: str, client_ip: str) -> str:
        norm_email = (email or "").strip().lower()
        norm_ip = (client_ip or "127.0.0.1").strip()
        return f"login_fail:{norm_email}:{norm_ip}"

    def _clean_expired(self, key: str, now: float) -> None:
        if key in self._failures:
            threshold = now - self.window_seconds
            valid_stamps = [t for t in self._failures[key] if t > threshold]
            if valid_stamps:
                self._failures[key] = valid_stamps
            else:
                del self._failures[key]

    def is_rate_limited(self, email: str, client_ip: str, get_time: Callable[[], float] | None = None) -> bool:
        now = get_time() if get_time else time.time()
        key = self._get_key(email, client_ip)
        self._clean_expired(key, now)
        stamps = self._failures.get(key, [])
        return len(stamps) >= self.max_attempts

    def record_failure(self, email: str, client_ip: str, get_time: Callable[[], float] | None = None) -> int:
        now = get_time() if get_time else time.time()
        key = self._get_key(email, client_ip)
        self._clean_expired(key, now)
        if key not in self._failures:
            self._failures[key] = []
        self._failures[key].append(now)
        return len(self._failures[key])

    def reset_failures(self, email: str, client_ip: str) -> None:
        key = self._get_key(email, client_ip)
        if key in self._failures:
            del self._failures[key]

    def clear_all(self) -> None:
        self._failures.clear()

login_rate_limiter = LoginRateLimiter()


class PasswordResetRateLimiter:
    def __init__(self, max_resets: int = 5, window_seconds: int = 3600):
        self.max_resets = max_resets
        self.window_seconds = window_seconds
        self._resets: dict[str, list[float]] = {}

    def _get_key(self, actor_id: int) -> str:
        return f"pwd_reset:{actor_id}"

    def _clean_expired(self, key: str, now: float) -> None:
        if key in self._resets:
            threshold = now - self.window_seconds
            valid_stamps = [t for t in self._resets[key] if t > threshold]
            if valid_stamps:
                self._resets[key] = valid_stamps
            else:
                del self._resets[key]

    def is_rate_limited(self, actor_id: int, now: float | None = None) -> bool:
        curr_now = now if now is not None else time.time()
        key = self._get_key(actor_id)
        self._clean_expired(key, curr_now)
        stamps = self._resets.get(key, [])
        return len(stamps) >= self.max_resets

    def record_reset(self, actor_id: int, now: float | None = None) -> None:
        curr_now = now if now is not None else time.time()
        key = self._get_key(actor_id)
        self._clean_expired(key, curr_now)
        if key not in self._resets:
            self._resets[key] = []
        self._resets[key].append(curr_now)

    def clear_all(self) -> None:
        self._resets.clear()

password_reset_rate_limiter = PasswordResetRateLimiter()
