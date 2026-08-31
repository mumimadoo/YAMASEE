import pytest
from services.pre_run_estimator import PreRunCostEstimator

def test_case_a_tiktok_with_duration_uses_duration_estimate():
    estimator = PreRunCostEstimator()
    # When duration is available, duration-based path is used
    res = estimator.estimate_pre_run("gemini-3.5-flash", duration_seconds=120.0, source_type="tiktok")
    assert res["duration_known"] is True
    assert res["duration_seconds"] == 120.0
    assert "≈" in res["tokens_range_text"]
    assert "≈ ฿" in res["cost_range_thb_text"]
    assert res.get("is_historical_fallback") is not True

def test_case_b_tiktok_without_duration_model_specific_fallback():
    estimator = PreRunCostEstimator()
    # When duration is None and source_type is TikTok
    res = estimator.estimate_pre_run("gemini-3.5-flash", duration_seconds=None, source_type="tiktok")
    assert res["duration_known"] is False
    assert res["duration_formatted"] == "ยังไม่ทราบก่อนประมวลผล"
    assert res["is_historical_fallback"] is True
    assert res["fallback_available"] is True
    assert res["fallback_level"] == "MODEL_SPECIFIC"
    assert "ประมาณจากงาน TikTok ที่ระบบเคยประมวลผลด้วยโมเดลนี้" in res["explanation_th"]
    assert res["historical_samples"] >= 5
    assert "Tokens" in res["tokens_range_text"]
    assert "฿" in res["cost_range_thb_text"]

def test_case_c_tiktok_without_duration_global_fallback():
    estimator = PreRunCostEstimator()
    # Simulate a model with < 5 samples but global TikTok >= 5
    estimator.tiktok_profiles["gemini-uncommon-model"] = {"sample_count": 2}
    res = estimator.estimate_pre_run("gemini-uncommon-model", duration_seconds=None, source_type="tiktok")
    assert res["duration_known"] is False
    assert res["is_historical_fallback"] is True
    assert res["fallback_available"] is True
    assert res["fallback_level"] == "GLOBAL_TIKTOK"
    assert "ประมาณจากงาน TikTok ที่ระบบเคยประมวลผล" in res["explanation_th"]

def test_case_d_tiktok_insufficient_history_fallback_unavailable():
    estimator = PreRunCostEstimator()
    # Temporarily override tiktok_global_profile and tiktok_profiles to simulate < 5 samples
    orig_global = estimator.tiktok_global_profile
    orig_profiles = estimator.tiktok_profiles
    try:
        estimator.tiktok_global_profile = {"sample_count": 2}
        estimator.tiktok_profiles = {}
        res = estimator.estimate_pre_run("gemini-3.5-flash", duration_seconds=None, source_type="tiktok")
        assert res["duration_known"] is False
        assert res["is_historical_fallback"] is True
        assert res["fallback_available"] is False
        assert res["fallback_level"] == "UNAVAILABLE"
        assert res["tokens_range_text"] == "ยังไม่สามารถประมาณได้"
        assert res["cost_range_thb_text"] == "ยังไม่สามารถประมาณได้"
    finally:
        estimator.tiktok_global_profile = orig_global
        estimator.tiktok_profiles = orig_profiles

def test_case_e_model_switch_recalculates_fallback():
    estimator = PreRunCostEstimator()
    res_flash = estimator.estimate_pre_run("gemini-3.5-flash", duration_seconds=None, source_type="tiktok")
    res_lite = estimator.estimate_pre_run("gemini-2.5-flash-lite", duration_seconds=None, source_type="tiktok")
    
    assert res_flash["is_historical_fallback"] is True
    assert res_lite["is_historical_fallback"] is True
    assert res_flash["model_name"] == "gemini-3.5-flash"
    assert res_lite["model_name"] == "gemini-2.5-flash-lite"
    # Flash and Flash-Lite costs should reflect model pricing differences
    assert res_flash["cost_expected_thb"] != res_lite["cost_expected_thb"]

def test_case_f_youtube_unaffected():
    estimator = PreRunCostEstimator()
    # YouTube without duration remains standard waiting
    res_yt = estimator.estimate_pre_run("gemini-3.5-flash", duration_seconds=None, source_type="youtube")
    assert res_yt["duration_known"] is False
    assert res_yt["tokens_range_text"] == "รอข้อมูลความยาววิดีโอ"
    assert res_yt.get("is_historical_fallback") is not True

def test_case_g_mp4_unaffected():
    estimator = PreRunCostEstimator()
    # MP4 without duration remains standard waiting
    res_mp4 = estimator.estimate_pre_run("gemini-3.5-flash", duration_seconds=None, source_type="mp4")
    assert res_mp4["duration_known"] is False
    assert res_mp4["tokens_range_text"] == "รอข้อมูลความยาววิดีโอ"
    assert res_mp4.get("is_historical_fallback") is not True
