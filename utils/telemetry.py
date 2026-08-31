import logging
from typing import Any, Optional, Dict

logger = logging.getLogger("yamasee.telemetry")

def create_empty_token_usage() -> Dict[str, Any]:
    """Returns a fresh, empty token usage schema dictionary."""
    return {
        "transcription": {
            "requests": 0,
            "prompt_tokens": 0,
            "candidates_tokens": 0,
            "cached_tokens": 0,
            "thoughts_tokens": 0,
            "total_tokens": 0,
        },
        "analysis": {
            "requests": 0,
            "prompt_tokens": 0,
            "candidates_tokens": 0,
            "cached_tokens": 0,
            "thoughts_tokens": 0,
            "total_tokens": 0,
        },
        "job_total": {
            "requests": 0,
            "prompt_tokens": 0,
            "candidates_tokens": 0,
            "cached_tokens": 0,
            "thoughts_tokens": 0,
            "total_tokens": 0,
        },
        "models": {}
    }

def add_response_telemetry(
    token_usage_dict: Optional[Dict[str, Any]],
    stage: str,
    model_name: Optional[str],
    response: Any
) -> None:
    """
    Safely extracts usage_metadata from a Gemini generate_content response
    and aggregates token counts into token_usage_dict.
    Guaranteed NEVER to raise an exception or break pipeline execution.
    """
    if not isinstance(token_usage_dict, dict):
        return

    try:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            # Response was returned, so API call succeeded, but no usage_metadata provided.
            p_tokens = 0
            c_tokens = 0
            ca_tokens = 0
            th_tokens = 0
            t_tokens = 0
        else:
            p_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
            c_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
            ca_tokens = int(getattr(usage, "cached_content_token_count", 0) or 0)
            th_tokens = int(getattr(usage, "thoughts_token_count", 0) or 0)

            total_from_api = getattr(usage, "total_token_count", None)
            if total_from_api is not None:
                t_tokens = int(total_from_api)
            else:
                t_tokens = p_tokens + c_tokens + ca_tokens + th_tokens

        req_delta = 1

        def _update(s_dict: dict):
            s_dict["requests"] = int(s_dict.get("requests", 0) or 0) + req_delta
            s_dict["prompt_tokens"] = int(s_dict.get("prompt_tokens", 0) or 0) + p_tokens
            s_dict["candidates_tokens"] = int(s_dict.get("candidates_tokens", 0) or 0) + c_tokens
            s_dict["cached_tokens"] = int(s_dict.get("cached_tokens", 0) or 0) + ca_tokens
            s_dict["thoughts_tokens"] = int(s_dict.get("thoughts_tokens", 0) or 0) + th_tokens
            s_dict["total_tokens"] = int(s_dict.get("total_tokens", 0) or 0) + t_tokens

        # 1. Update stage (e.g. "transcription" or "analysis")
        if stage and stage in token_usage_dict:
            _update(token_usage_dict[stage])

        # 2. Update job_total
        if "job_total" in token_usage_dict:
            _update(token_usage_dict["job_total"])

        # 3. Update per-model dynamic map
        clean_model = model_name or "unknown-model"
        models_map = token_usage_dict.setdefault("models", {})
        if clean_model not in models_map:
            models_map[clean_model] = {
                "requests": 0,
                "prompt_tokens": 0,
                "candidates_tokens": 0,
                "cached_tokens": 0,
                "thoughts_tokens": 0,
                "total_tokens": 0,
            }
        _update(models_map[clean_model])

    except Exception as ex:
        logger.warning(f"Safely caught telemetry error: {ex}")

def merge_token_usage(target: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merges source token_usage into target token_usage in place.
    """
    if not target:
        target = create_empty_token_usage()
    if not source or not isinstance(source, dict):
        return target

    try:
        for key in ["transcription", "analysis", "job_total"]:
            if key in source and isinstance(source[key], dict) and key in target:
                for field in ["requests", "prompt_tokens", "candidates_tokens", "cached_tokens", "thoughts_tokens", "total_tokens"]:
                    target[key][field] = int(target[key].get(field, 0) or 0) + int(source[key].get(field, 0) or 0)

        if "models" in source and isinstance(source["models"], dict):
            target_models = target.setdefault("models", {})
            for m_name, m_data in source["models"].items():
                if not isinstance(m_data, dict):
                    continue
                if m_name not in target_models:
                    target_models[m_name] = {
                        "requests": 0,
                        "prompt_tokens": 0,
                        "candidates_tokens": 0,
                        "cached_tokens": 0,
                        "thoughts_tokens": 0,
                        "total_tokens": 0,
                    }
                for field in ["requests", "prompt_tokens", "candidates_tokens", "cached_tokens", "thoughts_tokens", "total_tokens"]:
                    target_models[m_name][field] = int(target_models[m_name].get(field, 0) or 0) + int(m_data.get(field, 0) or 0)
    except Exception as ex:
        logger.warning(f"Failed to merge token usage cleanly: {ex}")

    return target
