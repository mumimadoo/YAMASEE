"""
YAMASEE — Estimated Cost Engine V1
Centralized pricing registry and cost estimation engine for Gemini AI calls.

IMPORTANT DEFINITION:
This module calculates "Estimated Cost — ค่าใช้จ่ายโดยประมาณ".
This is NOT "Actual Billing Cost" charged by Google.
"""

from decimal import Decimal, ROUND_HALF_UP
import math
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger("yamasee.cost_engine")

# ---------------------------------------------------------------------------
# Official Pricing Source & Registry (Rates per 1,000,000 tokens / per query USD)
# Source: Official Google Gemini API Pricing (Google AI Studio / Vertex AI)
# Verified Date: 2026-08-22
# ---------------------------------------------------------------------------
OFFICIAL_PRICING_DATE = "2026-08-22"
PRICING_VERSION = "v1"
DEFAULT_FX_RATE_USD_THB = 35.0

MODEL_PRICING: Dict[str, Dict[str, float]] = {
    "gemini-2.5-flash": {
        "input_per_1m": 0.30,
        "input_audio_per_1m": 1.00,
        "cached_input_per_1m": 0.075,
        "output_per_1m": 2.50,  # includes thinking tokens
    },
    "gemini-2.5-flash-lite": {
        "input_per_1m": 0.10,
        "input_audio_per_1m": 0.30,
        "cached_input_per_1m": 0.025,
        "output_per_1m": 0.40,  # includes thinking tokens
    },
    "gemini-3.5-flash": {
        "input_per_1m": 1.50,
        "input_audio_per_1m": 1.50,
        "cached_input_per_1m": 0.375,
        "output_per_1m": 9.00,  # includes thinking tokens
    },
    "gemini-3-flash": {
        "input_per_1m": 1.50,
        "input_audio_per_1m": 1.50,
        "cached_input_per_1m": 0.375,
        "output_per_1m": 9.00,  # includes thinking tokens
    },
    "gemini-3.5-flash-lite": {
        "input_per_1m": 0.30,
        "input_audio_per_1m": 0.30,
        "cached_input_per_1m": 0.075,
        "output_per_1m": 2.50,  # includes thinking tokens
    },
    "gemini-3.1-flash-lite": {
        "input_per_1m": 0.25,
        "input_audio_per_1m": 0.25,
        "cached_input_per_1m": 0.0625,
        "output_per_1m": 1.50,  # includes thinking tokens
    },
    "gemini-3.6-flash": {
        "input_per_1m": 1.50,
        "input_audio_per_1m": 1.50,
        "cached_input_per_1m": 0.375,
        "output_per_1m": 7.50,  # includes thinking tokens
    },
    "gemini-1.5-flash": {
        "input_per_1m": 0.075,
        "input_audio_per_1m": 0.075,
        "cached_input_per_1m": 0.01875,
        "output_per_1m": 0.30,
    },
    "gemini-1.5-pro": {
        "input_per_1m": 1.25,
        "input_audio_per_1m": 1.25,
        "cached_input_per_1m": 0.3125,
        "output_per_1m": 5.00,
    },
}

# Grounding Search Cost per query in USD ($14 per 1,000 queries = $0.014 / query)
GROUNDING_SEARCH_COST_PER_QUERY_USD = 0.014

# Estimation Quality Enum Values
QUALITY_FULL = "FULL"
QUALITY_PARTIAL = "PARTIAL"
QUALITY_UNAVAILABLE = "UNAVAILABLE"

# Thai User-facing Quality Labels
QUALITY_LABEL_TH = {
    QUALITY_FULL: "ประมาณการจากข้อมูล Token ที่บันทึกครบ",
    QUALITY_PARTIAL: "ประมาณการจากข้อมูล Token ที่มีอยู่บางส่วน",
    QUALITY_UNAVAILABLE: "ไม่มีข้อมูลเพียงพอสำหรับประมาณค่าใช้จ่าย",
}

ESTIMATED_COST_TOOLTIP_TH = (
    "ค่าใช้จ่ายโดยประมาณ คำนวณจาก Token usage, โมเดล และอัตราราคาที่บันทึกไว้ ณ เวลาที่ประมวลผล "
    "ไม่ใช่ยอดเรียกเก็บจริงจากผู้ให้บริการ"
)


def resolve_model_name(raw_name: Optional[str]) -> Optional[str]:
    """
    Normalizes raw model strings (e.g. 'models/gemini-2.5-flash-001' or '1. Gemini 3.5 Flash') to registry keys.
    """
    if not raw_name:
        return None
    import re
    clean = raw_name.strip().lower()
    if clean.startswith("models/"):
        clean = clean[7:]
    
    clean = re.sub(r'^\d+[\.\s]*', '', clean).strip()
    clean = clean.replace(" ", "-")
    
    if clean in MODEL_PRICING:
        return clean
    
    # Substring / Prefix match
    for m_key in MODEL_PRICING:
        if m_key in clean or clean in m_key:
            return m_key
            
    return clean


def calculate_single_model_cost(
    model_name: str,
    prompt_tokens: int,
    candidates_tokens: int,
    cached_tokens: int = 0,
    thoughts_tokens: int = 0,
    prompt_audio_tokens: int = 0,
) -> Dict[str, Any]:
    """
    Calculates cost components for a specific model's token consumption.
    """
    resolved_model = resolve_model_name(model_name)
    rates = MODEL_PRICING.get(resolved_model) if resolved_model else None
    
    p_tok = max(0, int(prompt_tokens or 0))
    c_tok = max(0, int(candidates_tokens or 0))
    ca_tok = max(0, int(cached_tokens or 0))
    th_tok = max(0, int(thoughts_tokens or 0))
    aud_tok = max(0, int(prompt_audio_tokens or 0))
    tot_tok = p_tok + c_tok + ca_tok + th_tok

    if not rates:
        return {
            "model_name": model_name,
            "resolved_model": resolved_model or model_name,
            "known_pricing": False,
            "rates_used": None,
            "cost_input_usd": 0.0,
            "cost_cached_usd": 0.0,
            "cost_output_usd": 0.0,
            "cost_total_usd": 0.0,
            "prompt_tokens": p_tok,
            "candidates_tokens": c_tok,
            "cached_tokens": ca_tok,
            "thoughts_tokens": th_tok,
            "total_tokens": tot_tok,
        }

    # Non-cached prompt tokens
    non_cached_prompt = max(0, p_tok - ca_tok)

    # Modality breakdown if prompt audio tokens present
    if aud_tok > 0:
        audio_in = min(non_cached_prompt, aud_tok)
        text_in = max(0, non_cached_prompt - audio_in)
        cost_input = (
            (audio_in * rates.get("input_audio_per_1m", rates["input_per_1m"])) / 1_000_000.0 +
            (text_in * rates["input_per_1m"]) / 1_000_000.0
        )
    else:
        cost_input = (non_cached_prompt * rates["input_per_1m"]) / 1_000_000.0

    cost_cached = (ca_tok * rates.get("cached_input_per_1m", 0.0)) / 1_000_000.0

    # Billable output = candidates_tokens + thoughts_tokens
    billable_output = c_tok + th_tok
    cost_output = (billable_output * rates["output_per_1m"]) / 1_000_000.0

    cost_total = cost_input + cost_cached + cost_output

    return {
        "model_name": model_name,
        "resolved_model": resolved_model,
        "known_pricing": True,
        "rates_used": rates,
        "cost_input_usd": cost_input,
        "cost_cached_usd": cost_cached,
        "cost_output_usd": cost_output,
        "cost_total_usd": cost_total,
        "prompt_tokens": p_tok,
        "candidates_tokens": c_tok,
        "cached_tokens": ca_tok,
        "thoughts_tokens": th_tok,
        "total_tokens": tot_tok,
    }


def calculate_run_cost(
    token_usage: Optional[Dict[str, Any]],
    model_used: Optional[str] = None,
    video_duration: Optional[float] = None,
    fx_rate: float = DEFAULT_FX_RATE_USD_THB,
    search_queries_count: int = 0,
) -> Dict[str, Any]:
    """
    Computes complete Estimated Cost for an analysis Run.
    Handles multi-model calls, failover attribution, cached/thinking tokens, FX conversion,
    grounding search costs, and cost/tokens per video minute.
    """
    fx = float(fx_rate or DEFAULT_FX_RATE_USD_THB)

    # 1. Inspect token_usage
    if not token_usage or not isinstance(token_usage, dict):
        # Missing telemetry -> UNAVAILABLE
        return {
            "estimation_quality": QUALITY_UNAVAILABLE,
            "quality_label_th": QUALITY_LABEL_TH[QUALITY_UNAVAILABLE],
            "display_thb": "ไม่มีข้อมูล",
            "display_usd": None,
            "estimated_cost_usd": None,
            "estimated_cost_thb": None,
            "estimated_cost_decimal": None,
            "cost_input_usd": 0.0,
            "cost_cached_usd": 0.0,
            "cost_output_usd": 0.0,
            "cost_grounding_usd": 0.0,
            "prompt_tokens": 0,
            "candidates_tokens": 0,
            "cached_tokens": 0,
            "thoughts_tokens": 0,
            "total_tokens": 0,
            "api_calls": 0,
            "models_breakdown": {},
            "pricing_version": PRICING_VERSION,
            "pricing_date": OFFICIAL_PRICING_DATE,
            "fx_currency": "USD_THB",
            "fx_rate": fx,
            "fx_rate_date": OFFICIAL_PRICING_DATE,
            "cost_per_video_minute_thb": None,
            "tokens_per_video_minute": None,
            "disclaimer_th": ESTIMATED_COST_TOOLTIP_TH,
        }

    # Extract search grounding queries if present in stage telemetry or explicit arg
    g_queries = search_queries_count
    if g_queries <= 0 and "external_research" in token_usage and isinstance(token_usage["external_research"], dict):
        ext = token_usage["external_research"]
        g_queries = int(ext.get("search_queries_count", 0) or 0)
        if g_queries <= 0 and isinstance(ext.get("search_queries"), list):
            g_queries = len(ext["search_queries"])
        if g_queries <= 0 and int(ext.get("requests", 0) or 0) > 0:
            g_queries = int(ext.get("requests", 0) or 0)

    cost_grounding_usd = max(0, g_queries) * GROUNDING_SEARCH_COST_PER_QUERY_USD

    models_map = token_usage.get("models")
    job_total = token_usage.get("job_total", {})

    models_breakdown: Dict[str, Any] = {}
    cost_input_usd = 0.0
    cost_cached_usd = 0.0
    cost_output_usd = 0.0

    total_p_tokens = 0
    total_c_tokens = 0
    total_ca_tokens = 0
    total_th_tokens = 0
    total_t_tokens = 0
    total_api_calls = 0

    has_unknown_pricing = False
    is_multi_model = False

    if models_map and isinstance(models_map, dict) and len(models_map) > 0:
        is_multi_model = len(models_map) > 1
        for m_name, m_data in models_map.items():
            if not isinstance(m_data, dict):
                continue
            
            req = int(m_data.get("requests", 0) or 0)
            p_tok = int(m_data.get("prompt_tokens", 0) or 0)
            c_tok = int(m_data.get("candidates_tokens", 0) or 0)
            ca_tok = int(m_data.get("cached_tokens", 0) or 0)
            th_tok = int(m_data.get("thoughts_tokens", 0) or 0)
            aud_tok = int(m_data.get("prompt_audio_tokens", 0) or 0)

            m_cost = calculate_single_model_cost(
                model_name=m_name,
                prompt_tokens=p_tok,
                candidates_tokens=c_tok,
                cached_tokens=ca_tok,
                thoughts_tokens=th_tok,
                prompt_audio_tokens=aud_tok,
            )

            if not m_cost["known_pricing"]:
                has_unknown_pricing = True

            cost_input_usd += m_cost["cost_input_usd"]
            cost_cached_usd += m_cost["cost_cached_usd"]
            cost_output_usd += m_cost["cost_output_usd"]

            total_p_tokens += p_tok
            total_c_tokens += c_tok
            total_ca_tokens += ca_tok
            total_th_tokens += th_tok
            total_t_tokens += m_cost["total_tokens"]
            total_api_calls += req

            models_breakdown[m_name] = m_cost

        quality = QUALITY_PARTIAL if has_unknown_pricing else QUALITY_FULL
    elif job_total and isinstance(job_total, dict):
        fallback_model = model_used or "gemini-2.5-flash"
        req = int(job_total.get("requests", 0) or 0)
        p_tok = int(job_total.get("prompt_tokens", 0) or 0)
        c_tok = int(job_total.get("candidates_tokens", 0) or 0)
        ca_tok = int(job_total.get("cached_tokens", 0) or 0)
        th_tok = int(job_total.get("thoughts_tokens", 0) or 0)
        aud_tok = int(job_total.get("prompt_audio_tokens", 0) or 0)
        tot_tok = int(job_total.get("total_tokens", 0) or (p_tok + c_tok + ca_tok + th_tok))

        if tot_tok > 0 or req > 0:
            m_cost = calculate_single_model_cost(
                model_name=fallback_model,
                prompt_tokens=p_tok,
                candidates_tokens=c_tok,
                cached_tokens=ca_tok,
                thoughts_tokens=th_tok,
                prompt_audio_tokens=aud_tok,
            )

            cost_input_usd = m_cost["cost_input_usd"]
            cost_cached_usd = m_cost["cost_cached_usd"]
            cost_output_usd = m_cost["cost_output_usd"]

            total_p_tokens = p_tok
            total_c_tokens = c_tok
            total_ca_tokens = ca_tok
            total_th_tokens = th_tok
            total_t_tokens = m_cost["total_tokens"]
            total_api_calls = req

            models_breakdown[fallback_model] = m_cost
            quality = QUALITY_PARTIAL if not m_cost["known_pricing"] else QUALITY_FULL
        else:
            return {
                "estimation_quality": QUALITY_UNAVAILABLE,
                "quality_label_th": QUALITY_LABEL_TH[QUALITY_UNAVAILABLE],
                "display_thb": "ไม่มีข้อมูล",
                "display_usd": None,
                "estimated_cost_usd": None,
                "estimated_cost_thb": None,
                "estimated_cost_decimal": None,
                "cost_input_usd": 0.0,
                "cost_cached_usd": 0.0,
                "cost_output_usd": 0.0,
                "cost_grounding_usd": 0.0,
                "prompt_tokens": 0,
                "candidates_tokens": 0,
                "cached_tokens": 0,
                "thoughts_tokens": 0,
                "total_tokens": 0,
                "api_calls": 0,
                "models_breakdown": {},
                "pricing_version": PRICING_VERSION,
                "pricing_date": OFFICIAL_PRICING_DATE,
                "fx_currency": "USD_THB",
                "fx_rate": fx,
                "fx_rate_date": OFFICIAL_PRICING_DATE,
                "cost_per_video_minute_thb": None,
                "tokens_per_video_minute": None,
                "disclaimer_th": ESTIMATED_COST_TOOLTIP_TH,
            }
    else:
        # 0 tokens recorded -> UNAVAILABLE
        return {
            "estimation_quality": QUALITY_UNAVAILABLE,
            "quality_label_th": QUALITY_LABEL_TH[QUALITY_UNAVAILABLE],
            "display_thb": "ไม่มีข้อมูล",
            "display_usd": None,
            "estimated_cost_usd": None,
            "estimated_cost_thb": None,
            "estimated_cost_decimal": None,
            "cost_input_usd": 0.0,
            "cost_cached_usd": 0.0,
            "cost_output_usd": 0.0,
            "cost_grounding_usd": 0.0,
            "prompt_tokens": 0,
            "candidates_tokens": 0,
            "cached_tokens": 0,
            "thoughts_tokens": 0,
            "total_tokens": 0,
            "api_calls": 0,
            "models_breakdown": {},
            "pricing_version": PRICING_VERSION,
            "pricing_date": OFFICIAL_PRICING_DATE,
            "fx_currency": "USD_THB",
            "fx_rate": fx,
            "fx_rate_date": OFFICIAL_PRICING_DATE,
            "cost_per_video_minute_thb": None,
            "tokens_per_video_minute": None,
            "disclaimer_th": ESTIMATED_COST_TOOLTIP_TH,
        }

    total_usd = cost_input_usd + cost_cached_usd + cost_output_usd + cost_grounding_usd
    total_thb = total_usd * fx

    # Decimal representation for DB persistence
    thb_decimal = Decimal(str(total_thb)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    # Cost per video minute & tokens per video minute
    dur_sec = float(video_duration or 0.0)
    cost_per_min_thb = None
    tokens_per_min = None
    if dur_sec > 0.0:
        dur_mins = dur_sec / 60.0
        cost_per_min_thb = round(total_thb / dur_mins, 4)
        tokens_per_min = round(total_t_tokens / dur_mins, 2)

    display_thb = f"≈ ฿{total_thb:.2f}"
    display_usd = f"${total_usd:.4f}"

    # Extract stage breakdown if present in token_usage
    stages_breakdown = {}
    for st_name in ["transcription", "analysis", "comparison", "external_research"]:
        if st_name in token_usage and isinstance(token_usage[st_name], dict):
            stages_breakdown[st_name] = token_usage[st_name]

    return {
        "estimation_quality": quality,
        "quality_label_th": QUALITY_LABEL_TH[quality],
        "display_thb": display_thb,
        "display_usd": display_usd,
        "estimated_cost_usd": round(total_usd, 6),
        "estimated_cost_thb": round(total_thb, 4),
        "estimated_cost_decimal": thb_decimal,
        "cost_input_usd": round(cost_input_usd, 6),
        "cost_cached_usd": round(cost_cached_usd, 6),
        "cost_output_usd": round(cost_output_usd, 6),
        "cost_grounding_usd": round(cost_grounding_usd, 6),
        "prompt_tokens": total_p_tokens,
        "candidates_tokens": total_c_tokens,
        "cached_tokens": total_ca_tokens,
        "thoughts_tokens": total_th_tokens,
        "total_tokens": total_t_tokens,
        "api_calls": total_api_calls,
        "is_multi_model": is_multi_model,
        "models_breakdown": models_breakdown,
        "stages_breakdown": stages_breakdown,
        "pricing_version": PRICING_VERSION,
        "pricing_date": OFFICIAL_PRICING_DATE,
        "fx_currency": "USD_THB",
        "fx_rate": fx,
        "fx_rate_date": OFFICIAL_PRICING_DATE,
        "video_duration_seconds": dur_sec,
        "cost_per_video_minute_thb": cost_per_min_thb,
        "tokens_per_video_minute": tokens_per_min,
        "disclaimer_th": ESTIMATED_COST_TOOLTIP_TH,
    }


def recalculate_historical_run_costs(db: Any) -> Dict[str, int]:
    """
    Recalculates Estimated Cost for historical AnalysisRunHistory records.
    - Updates records with token_usage using current Cost Engine formula.
    - Preserves records without token_usage as UNAVAILABLE (estimated_cost = None).
    """
    from models.analysis_run_history import AnalysisRunHistory

    runs = db.query(AnalysisRunHistory).all()
    updated = 0
    skipped_unavailable = 0

    for r in runs:
        cost_res = calculate_run_cost(
            token_usage=r.token_usage,
            model_used=r.model_used,
            video_duration=r.video_duration,
        )
        if cost_res["estimation_quality"] != QUALITY_UNAVAILABLE:
            r.estimated_cost = cost_res["estimated_cost_decimal"]
            r.estimated_cost_version = PRICING_VERSION
            updated += 1
        else:
            r.estimated_cost = None
            r.estimated_cost_version = PRICING_VERSION
            skipped_unavailable += 1

    db.commit()
    logger.info(f"Recalculated historical costs: updated {updated} runs, skipped {skipped_unavailable} unavailable runs.")
    return {"updated": updated, "skipped_unavailable": skipped_unavailable}

