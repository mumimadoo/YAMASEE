import email.utils
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.genai import errors as genai_errors


DEFAULT_PRIMARY_MODEL = "gemini-3.5-flash"
USER_SELECTABLE_MODELS = frozenset({
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
})
RESERVE_MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.6-flash",
)
MODEL_CHAINS = {
    "gemini-3.5-flash": (
        "gemini-3.5-flash",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        *RESERVE_MODELS,
    ),
    "gemini-2.5-flash": (
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-3.5-flash",
        *RESERVE_MODELS,
    ),
    "gemini-2.5-flash-lite": (
        "gemini-2.5-flash-lite",
        "gemini-3.5-flash",
        "gemini-2.5-flash",
        *RESERVE_MODELS,
    ),
}

RATE_LIMITED_MESSAGE = "ระบบ AI มีคำขอเกินขีดจำกัดชั่วคราว กรุณาลองใหม่ภายหลัง"
MAX_RETRY_AFTER_SECONDS = 60.0


def validate_primary_model(model: Optional[str], default: str = DEFAULT_PRIMARY_MODEL) -> str:
    normalized = (model or "").strip().lower()
    return normalized if normalized in USER_SELECTABLE_MODELS else default


def build_model_chain(model: Optional[str], default: str = DEFAULT_PRIMARY_MODEL) -> List[str]:
    primary = validate_primary_model(model, default=default)
    return list(MODEL_CHAINS[primary])


def is_rate_limit_error(error: Exception) -> bool:
    if isinstance(error, genai_errors.APIError):
        return getattr(error, "code", None) == 429 or str(getattr(error, "status", "")).upper() == "RESOURCE_EXHAUSTED"
    return False


def classify_gemini_error(error: Exception) -> str:
    """Classify runtime failures without treating an unavailable model as rate limited."""
    if is_rate_limit_error(error):
        return "RATE_LIMITED"

    code = getattr(error, "code", None)
    status_name = str(getattr(error, "status", "")).upper()
    text = " ".join(
        str(value).lower()
        for value in (
            error,
            getattr(error, "message", None),
            getattr(error, "details", None),
        )
        if value is not None
    )
    model_not_found_markers = (
        "model not found",
        "unsupported for generatecontent",
        "unsupported model",
        "not supported for generatecontent",
    )
    if str(code) == "404" or "NOT_FOUND" in status_name or any(marker in text for marker in model_not_found_markers):
        return "MODEL_NOT_FOUND"

    if code in (401, 403) or status_name in ("UNAUTHENTICATED", "PERMISSION_DENIED") or any(
        marker in text for marker in ("invalid api key", "unauthorized", "authentication", "permission denied")
    ):
        return "AUTH_ERROR"

    if isinstance(error, (ConnectionError, TimeoutError)) or any(
        marker in text for marker in ("connection error", "network error", "timed out", "timeout")
    ):
        return "NETWORK_ERROR"
    return "OTHER"


def is_model_not_found_error(error: Exception) -> bool:
    return classify_gemini_error(error) == "MODEL_NOT_FOUND"


def is_hard_quota_error(error: Exception) -> bool:
    if not is_rate_limit_error(error):
        return False
    text = " ".join(
        str(value).lower()
        for value in (getattr(error, "message", None), getattr(error, "details", None))
        if value is not None
    )
    hard_quota_markers = (
        "generaterequestsperdayperprojectpermodel",
        "per day",
        "daily limit",
        "daily quota",
        "daily_quota",
        "quota exceeded for the day",
    )
    return any(marker in text for marker in hard_quota_markers)


def get_retry_after_seconds(error: Exception, max_seconds: float = MAX_RETRY_AFTER_SECONDS) -> Optional[float]:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    raw_value = headers.get("Retry-After") or headers.get("retry-after")
    if raw_value is None:
        return None
    try:
        seconds = float(str(raw_value).strip())
    except (TypeError, ValueError):
        try:
            retry_at = email.utils.parsedate_to_datetime(str(raw_value).strip())
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    if seconds < 0:
        return None
    return min(seconds, max_seconds)


def get_rate_limit_wait(error: Exception, attempt_index: int) -> tuple[float, str]:
    retry_after = get_retry_after_seconds(error)
    if retry_after is not None:
        return retry_after, "Retry-After"
    base_seconds = 2.0 * (2 ** attempt_index)
    return base_seconds + random.uniform(0.0, 0.25), "backoff"


class GeminiRateLimitedError(Exception):
    def __init__(
        self,
        *,
        selected_model: str,
        final_model: str,
        attempted_models: List[str],
        attempt_count: int,
        quota_type: str,
    ):
        super().__init__(RATE_LIMITED_MESSAGE)
        self.reason = "RATE_LIMITED"
        self.selected_model = selected_model
        self.final_model = final_model
        self.attempted_models = list(attempted_models)
        self.attempt_count = attempt_count
        self.quota_type = quota_type

    def safe_metadata(self) -> Dict[str, Any]:
        return {
            "reason": self.reason,
            "selected_model": self.selected_model,
            "final_model": self.final_model,
            "attempted_models": list(self.attempted_models),
            "attempt_count": self.attempt_count,
            "quota_type": self.quota_type,
        }


def run_with_model_fallback(
    call_model,
    *,
    selected_model: Optional[str],
    logger,
    sleep_fn=None,
    max_attempts: int = 5,
):
    primary = validate_primary_model(selected_model)
    sleep_fn = sleep_fn or time.sleep
    chain = build_model_chain(primary)
    attempted_models: List[str] = []
    total_attempts = 0
    last_quota_type = "temporary"
    last_error = None

    for model_index, model_name in enumerate(chain):
        attempted_models.append(model_name)
        if model_name in RESERVE_MODELS:
            logger.info(f"MODEL_RESERVE\nmodel={model_name}")

        model_rate_limited = False
        for attempt_index in range(max_attempts):
            total_attempts += 1
            logger.info(f"MODEL_ATTEMPT\nmodel={model_name}\nattempt={attempt_index + 1}/{max_attempts}")
            try:
                return call_model(model_name), model_name
            except Exception as error:
                last_error = error
                if is_model_not_found_error(error):
                    logger.warning(
                        f"MODEL_UNAVAILABLE\nmodel={model_name}\nreason=MODEL_NOT_FOUND\naction=FAILOVER"
                    )
                    break
                if not is_rate_limit_error(error):
                    raise

                model_rate_limited = True
                if is_hard_quota_error(error):
                    last_quota_type = "hard_daily"
                    break

                last_quota_type = "temporary"
                if attempt_index == max_attempts - 1:
                    break

                wait_seconds, wait_source = get_rate_limit_wait(error, attempt_index)
                logger.warning(
                    f"RATE_LIMIT\nmodel={model_name}\nattempt={attempt_index + 1}/{max_attempts}"
                    f"\nwait={wait_seconds:.3f}\nsource={wait_source}"
                )
                sleep_fn(wait_seconds)

        if model_rate_limited and model_index + 1 < len(chain):
            logger.warning(
                f"MODEL_FAILOVER\nfrom={model_name}\nto={chain[model_index + 1]}\nreason=RATE_LIMITED"
            )

    if last_error is not None and not is_rate_limit_error(last_error):
        raise last_error

    raise GeminiRateLimitedError(
        selected_model=primary,
        final_model=chain[-1],
        attempted_models=attempted_models,
        attempt_count=total_attempts,
        quota_type=last_quota_type,
    )
