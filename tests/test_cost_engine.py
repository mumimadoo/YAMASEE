import pytest
from decimal import Decimal
from services.cost_engine import (
    MODEL_PRICING,
    QUALITY_FULL,
    QUALITY_PARTIAL,
    QUALITY_UNAVAILABLE,
    calculate_single_model_cost,
    calculate_run_cost,
    resolve_model_name,
)

def test_1_input_cost():
    # Model: gemini-2.5-flash -> input rate = $0.30 / 1M
    # 1,000,000 input tokens = $0.30
    res = calculate_single_model_cost("gemini-2.5-flash", prompt_tokens=1_000_000, candidates_tokens=0)
    assert abs(res["cost_input_usd"] - 0.30) < 1e-6

def test_2_candidate_output_cost():
    # Model: gemini-2.5-flash -> output rate = $2.50 / 1M
    # 1,000,000 candidate tokens = $2.50
    res = calculate_single_model_cost("gemini-2.5-flash", prompt_tokens=0, candidates_tokens=1_000_000)
    assert abs(res["cost_output_usd"] - 2.50) < 1e-6

def test_3_thinking_token_cost():
    # Thinking tokens must be added to candidate tokens for output pricing
    # 500,000 candidates + 500,000 thoughts = 1,000,000 output tokens = $2.50
    res = calculate_single_model_cost("gemini-2.5-flash", prompt_tokens=0, candidates_tokens=500_000, thoughts_tokens=500_000)
    assert abs(res["cost_output_usd"] - 2.50) < 1e-6

def test_4_cached_token_cost():
    # Model: gemini-2.5-flash -> cached rate = $0.075 / 1M
    # 1,000,000 prompt tokens, 400,000 cached tokens
    # Non-cached prompt = 600,000 -> 600,000 * 0.30/1M = $0.18
    # Cached = 400,000 * 0.075/1M = $0.03
    res = calculate_single_model_cost("gemini-2.5-flash", prompt_tokens=1_000_000, candidates_tokens=0, cached_tokens=400_000)
    assert abs(res["cost_input_usd"] - 0.18) < 1e-6
    assert abs(res["cost_cached_usd"] - 0.03) < 1e-6

def test_5_modality_specific_rates():
    # Model: gemini-2.5-flash -> audio input rate = $1.00 / 1M, text input = $0.30 / 1M
    # 1,000,000 prompt tokens, 500,000 audio tokens
    # Audio input = 500,000 * 1.00/1M = $0.50
    # Text input = 500,000 * 0.30/1M = $0.15
    # Total input = $0.65
    res = calculate_single_model_cost("gemini-2.5-flash", prompt_tokens=1_000_000, candidates_tokens=0, prompt_audio_tokens=500_000)
    assert abs(res["cost_input_usd"] - 0.65) < 1e-6

def test_6_partial_telemetry():
    # Telemetry without models map but with job_total fallback
    tu = {
        "job_total": {
            "requests": 5,
            "prompt_tokens": 10000,
            "candidates_tokens": 2000,
            "cached_tokens": 0,
            "thoughts_tokens": 1000,
            "total_tokens": 13000
        }
    }
    res = calculate_run_cost(tu, model_used="gemini-2.5-flash")
    assert res["estimation_quality"] == QUALITY_FULL  # known pricing model used
    assert res["quality_label_th"] == "ประมาณการจากข้อมูล Token ที่บันทึกครบ"

def test_7_unavailable_telemetry():
    res = calculate_run_cost(None)
    assert res["estimation_quality"] == QUALITY_UNAVAILABLE
    assert res["quality_label_th"] == "ไม่มีข้อมูลเพียงพอสำหรับประมาณค่าใช้จ่าย"

def test_8_unknown_not_zero():
    # Missing telemetry must return display_thb = "ไม่มีข้อมูล" or "—", NOT "฿0.00"
    res = calculate_run_cost(None)
    assert res["display_thb"] == "ไม่มีข้อมูล"
    assert res["estimated_cost_usd"] is None
    assert res["estimated_cost_thb"] is None

def test_9_usd_total():
    tu = {
        "models": {
            "gemini-2.5-flash": {
                "requests": 1,
                "prompt_tokens": 1_000_000,
                "candidates_tokens": 1_000_000,
                "cached_tokens": 0,
                "thoughts_tokens": 0
            }
        }
    }
    # input = 0.30, output = 2.50 -> USD total = 2.80
    res = calculate_run_cost(tu)
    assert abs(res["estimated_cost_usd"] - 2.80) < 1e-6

def test_10_thb_conversion():
    tu = {
        "models": {
            "gemini-2.5-flash": {
                "requests": 1,
                "prompt_tokens": 1_000_000,
                "candidates_tokens": 1_000_000,
                "cached_tokens": 0,
                "thoughts_tokens": 0
            }
        }
    }
    # USD total = 2.80, fx_rate = 35.0 -> THB = 98.0
    res = calculate_run_cost(tu, fx_rate=35.0)
    assert abs(res["estimated_cost_thb"] - 98.0) < 1e-4

def test_11_pricing_snapshot():
    res = calculate_run_cost({"job_total": {"total_tokens": 100}}, model_used="gemini-2.5-flash")
    assert res["pricing_version"] == "v1"
    assert res["pricing_date"] == "2026-08-22"

def test_12_fx_snapshot():
    res = calculate_run_cost({"job_total": {"total_tokens": 100}}, model_used="gemini-2.5-flash", fx_rate=36.5)
    assert res["fx_currency"] == "USD_THB"
    assert res["fx_rate"] == 36.5

def test_13_multi_call_aggregation():
    tu = {
        "models": {
            "gemini-2.5-flash": {
                "requests": 10,
                "prompt_tokens": 100_000,
                "candidates_tokens": 20_000,
                "cached_tokens": 0,
                "thoughts_tokens": 5_000
            }
        }
    }
    res = calculate_run_cost(tu)
    assert res["api_calls"] == 10
    assert res["total_tokens"] == 125_000

def test_14_multi_model_aggregation():
    tu = {
        "models": {
            "gemini-2.5-flash": {
                "requests": 1,
                "prompt_tokens": 1_000_000,
                "candidates_tokens": 0,
                "cached_tokens": 0,
                "thoughts_tokens": 0
            },
            "gemini-3.5-flash": {
                "requests": 1,
                "prompt_tokens": 1_000_000,
                "candidates_tokens": 0,
                "cached_tokens": 0,
                "thoughts_tokens": 0
            }
        }
    }
    # gemini-2.5-flash input = 0.30, gemini-3.5-flash input = 1.50 -> USD = 1.80
    res = calculate_run_cost(tu)
    assert res["is_multi_model"] is True
    assert abs(res["estimated_cost_usd"] - 1.80) < 1e-6

def test_15_failover_accounting():
    # Primary model failed after consuming tokens, failover model succeeded
    tu = {
        "models": {
            "gemini-3.5-flash": {
                "requests": 1,
                "prompt_tokens": 10_000,
                "candidates_tokens": 0,
                "cached_tokens": 0,
                "thoughts_tokens": 0
            },
            "gemini-2.5-flash-lite": {
                "requests": 2,
                "prompt_tokens": 10_000,
                "candidates_tokens": 5_000,
                "cached_tokens": 0,
                "thoughts_tokens": 0
            }
        }
    }
    # 3.5-flash: 10,000 * 1.50 / 1M = $0.015
    # 2.5-flash-lite: input = 10,000 * 0.10 / 1M = $0.001, output = 5,000 * 0.40 / 1M = $0.002
    # Total = 0.015 + 0.001 + 0.002 = $0.018
    res = calculate_run_cost(tu)
    assert abs(res["estimated_cost_usd"] - 0.018) < 1e-6

def test_16_cost_per_minute():
    tu = {
        "models": {
            "gemini-2.5-flash": {
                "requests": 1,
                "prompt_tokens": 1_000_000,
                "candidates_tokens": 0
            }
        }
    }
    # Total USD = 0.30 * 35 = 10.50 THB. Duration = 120s (2 mins) -> 10.50 / 2 = 5.25 THB/min
    res = calculate_run_cost(tu, video_duration=120.0, fx_rate=35.0)
    assert abs(res["cost_per_video_minute_thb"] - 5.25) < 1e-4

def test_17_tokens_per_minute():
    tu = {
        "models": {
            "gemini-2.5-flash": {
                "requests": 1,
                "prompt_tokens": 120_000,
                "candidates_tokens": 0
            }
        }
    }
    # Total tokens = 120,000. Duration = 120s (2 mins) -> 60,000 tokens/min
    res = calculate_run_cost(tu, video_duration=120.0)
    assert abs(res["tokens_per_video_minute"] - 60000.0) < 1e-4

def test_18_zero_missing_duration():
    tu = {"job_total": {"total_tokens": 1000, "requests": 1}}
    res_zero = calculate_run_cost(tu, video_duration=0.0)
    assert res_zero["cost_per_video_minute_thb"] is None
    assert res_zero["tokens_per_video_minute"] is None

    res_none = calculate_run_cost(tu, video_duration=None)
    assert res_none["cost_per_video_minute_thb"] is None
    assert res_none["tokens_per_video_minute"] is None

def test_19_historical_compatibility():
    # Historical record with old structure or missing model map
    tu = {
        "job_total": {
            "requests": 3,
            "prompt_tokens": 5000,
            "candidates_tokens": 1000,
            "cached_tokens": 0,
            "thoughts_tokens": 0,
            "total_tokens": 6000
        }
    }
    res = calculate_run_cost(tu, model_used="gemini-2.5-flash")
    assert res["total_tokens"] == 6000
    assert res["estimated_cost_thb"] is not None

def test_20_csv_export():
    from routers.admin import export_run_history_csv
    assert callable(export_run_history_csv)

def test_21_no_extra_gemini_calls(monkeypatch):
    import google.genai as genai
    def blow_up(*args, **kwargs):
        pytest.fail("Gemini API call made during cost calculation!")
    monkeypatch.setattr(genai.Client, "models", blow_up)
    
    tu = {"job_total": {"prompt_tokens": 100, "candidates_tokens": 50}}
    res = calculate_run_cost(tu, model_used="gemini-2.5-flash")
    assert res["estimated_cost_usd"] is not None

def test_22_no_extra_search_calls(monkeypatch):
    tu = {"external_research": {"search_queries_count": 2}, "job_total": {"prompt_tokens": 100}}
    res = calculate_run_cost(tu, model_used="gemini-2.5-flash")
    assert res["cost_grounding_usd"] == round(2 * 0.014, 6)
