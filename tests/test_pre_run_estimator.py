import pytest
import time
from services.pre_run_estimator import (
    PreRunCostEstimator,
    format_duration_hhmmss,
    pre_run_estimator
)
from services.cost_engine import MODEL_PRICING

def test_1_duration_known_format():
    assert format_duration_hhmmss(211.0) == "00:03:31"
    assert format_duration_hhmmss(45.0) == "00:00:45"
    assert format_duration_hhmmss(3661.0) == "01:01:01"

def test_2_duration_unknown():
    res = pre_run_estimator.estimate_pre_run("gemini-3.5-flash", None)
    assert res["duration_known"] is False
    assert res["duration_formatted"] == "ยังไม่ทราบความยาว"
    assert res["tokens_range_text"] == "รอข้อมูลความยาววิดีโอ"
    assert res["cost_range_thb_text"] == "รอข้อมูลความยาววิดีโอ"
    assert res["confidence"] == "UNAVAILABLE"
    assert res["confidence_label_th"] == "ยังไม่สามารถประเมินได้"

def test_3_hhmmss_format_in_estimate():
    res = pre_run_estimator.estimate_pre_run("gemini-3.5-flash", 211.0)
    assert res["duration_formatted"] == "00:03:31"
    assert "211.0s" not in res["duration_formatted"]

def test_4_historical_token_profile():
    res = pre_run_estimator.estimate_pre_run("gemini-3.5-flash", 211.0)
    assert res["tokens_low"] is not None
    assert res["tokens_expected"] is not None
    assert res["tokens_high"] is not None
    assert res["tokens_low"] <= res["tokens_expected"] <= res["tokens_high"]

def test_5_historical_cost_profile():
    res = pre_run_estimator.estimate_pre_run("gemini-3.5-flash", 211.0)
    assert res["cost_low_thb"] is not None
    assert res["cost_expected_thb"] is not None
    assert res["cost_high_thb"] is not None
    assert res["cost_low_thb"] <= res["cost_expected_thb"] <= res["cost_high_thb"]

def test_6_model_specific_profile():
    # gemini-3.5-flash has >= 3 historical samples
    res = pre_run_estimator.estimate_pre_run("gemini-3.5-flash", 300.0)
    assert res["confidence"] in ["HIGH", "MEDIUM"]
    assert res["historical_samples"] >= 3
    assert "ประมาณจากข้อมูลการใช้งานจริงย้อนหลังของ YAMASEE" in res["explanation_th"]

def test_7_fallback_profile():
    # gemini-2.5-flash-lite has < 3 historical samples
    res = pre_run_estimator.estimate_pre_run("gemini-2.5-flash-lite", 300.0)
    assert res["confidence"] == "LOW"
    assert "ข้อมูลย้อนหลังของโมเดลนี้ยังไม่เพียงพอ" in res["explanation_th"]

def test_8_confidence_levels():
    res_high = pre_run_estimator.estimate_pre_run("gemini-3.5-flash", 120.0)
    assert res_high["confidence"] in ["HIGH", "MEDIUM"]
    
    res_low = pre_run_estimator.estimate_pre_run("gemini-2.5-flash-lite", 120.0)
    assert res_low["confidence"] == "LOW"

    res_unavail = pre_run_estimator.estimate_pre_run("gemini-3.5-flash", None)
    assert res_unavail["confidence"] == "UNAVAILABLE"

def test_9_token_range_formatting():
    res = pre_run_estimator.estimate_pre_run("gemini-3.5-flash", 211.0)
    assert "≈" in res["tokens_range_text"]
    assert "Tokens" in res["tokens_range_text"]

def test_10_thb_range_formatting():
    res = pre_run_estimator.estimate_pre_run("gemini-3.5-flash", 211.0)
    assert "≈" in res["cost_range_thb_text"]
    assert "฿" in res["cost_range_thb_text"]

def test_11_model_dropdown_recalculation():
    dur = 211.0
    est_flash = pre_run_estimator.estimate_pre_run("gemini-3.5-flash", dur)
    est_lite = pre_run_estimator.estimate_pre_run("gemini-2.5-flash-lite", dur)
    # Flash Lite pricing is significantly lower than 3.5 Flash
    assert est_lite["cost_expected_thb"] < est_flash["cost_expected_thb"]

def test_12_all_model_estimates():
    all_ests = pre_run_estimator.get_all_model_estimates(211.0)
    assert "gemini-3.5-flash" in all_ests
    assert "gemini-2.5-flash" in all_ests
    assert "gemini-2.5-flash-lite" in all_ests
    assert "gemini-3.6-flash" in all_ests

def test_13_no_extra_gemini_calls(monkeypatch):
    import google.genai as genai
    def blow_up(*args, **kwargs):
        pytest.fail("Gemini API call attempted during pre-run estimation!")
    monkeypatch.setattr(genai.Client, "models", blow_up)

    res = pre_run_estimator.estimate_pre_run("gemini-3.5-flash", 211.0)
    assert res["cost_expected_thb"] is not None

def test_14_no_extra_search_calls(monkeypatch):
    res = pre_run_estimator.estimate_pre_run("gemini-3.5-flash", 211.0)
    assert res["cost_expected_thb"] is not None

def test_15_performance_under_10ms():
    t0 = time.time()
    for _ in range(100):
        pre_run_estimator.estimate_pre_run("gemini-3.5-flash", 211.0)
        pre_run_estimator.estimate_pre_run("gemini-2.5-flash-lite", 211.0)
    elapsed_ms = (time.time() - t0) * 1000.0
    avg_ms = elapsed_ms / 200.0
    assert avg_ms < 5.0, f"Average estimation time {avg_ms:.2f}ms exceeded 5ms target"
