import pytest
from services.pre_run_estimator import pre_run_estimator
from schemas.comparison import ComparisonPreRunEstimateRequest, ComparisonSideStateInput

def test_case_1_new_youtube_and_new_youtube():
    """CASE 1: A new YouTube + B new YouTube -> both analysis estimates + comparison estimate."""
    video_a = {"state": "NEW_ANALYSIS_REQUIRED", "duration_seconds": 120.0, "selected_model": "gemini-3.5-flash"}
    video_b = {"state": "NEW_ANALYSIS_REQUIRED", "duration_seconds": 180.0, "selected_model": "gemini-3.5-flash"}
    
    res = pre_run_estimator.estimate_comparison_pre_run(video_a, video_b, comparison_model="gemini-2.5-flash", exact_comparison_cached=False)
    
    assert res["is_complete"] is True
    assert res["video_a"]["state"] == "NEW_ANALYSIS_REQUIRED"
    assert res["video_a"]["gemini_calls"] == 1
    assert res["video_a"]["cost_low_thb"] > 0
    
    assert res["video_b"]["state"] == "NEW_ANALYSIS_REQUIRED"
    assert res["video_b"]["gemini_calls"] == 1
    assert res["video_b"]["cost_low_thb"] > 0

    assert res["comparison"]["cached"] is False
    assert res["comparison"]["gemini_calls"] == 1
    assert res["comparison"]["cost_low_thb"] > 0

    # Total must equal sum of all three components
    expected_low = round(res["video_a"]["cost_low_thb"] + res["video_b"]["cost_low_thb"] + res["comparison"]["cost_low_thb"], 2)
    assert res["total"]["cost_low_thb"] == expected_low


def test_case_2_history_reuse_a_and_new_youtube_b():
    """CASE 2: A History + B new YouTube -> A = ฿0 analysis (0 calls), B = new estimate, comparison estimate."""
    video_a = {"state": "HISTORY_REUSE", "duration_seconds": 150.0}
    video_b = {"state": "NEW_ANALYSIS_REQUIRED", "duration_seconds": 240.0, "selected_model": "gemini-3.5-flash"}

    res = pre_run_estimator.estimate_comparison_pre_run(video_a, video_b, comparison_model="gemini-2.5-flash", exact_comparison_cached=False)

    assert res["is_complete"] is True
    assert res["video_a"]["state"] == "REUSE"
    assert res["video_a"]["cost_low_thb"] == 0.0
    assert res["video_a"]["tokens_low"] == 0
    assert res["video_a"]["gemini_calls"] == 0

    assert res["video_b"]["cost_low_thb"] > 0
    assert res["video_b"]["gemini_calls"] == 1

    assert res["comparison"]["cost_low_thb"] > 0
    assert res["comparison"]["gemini_calls"] == 1

    expected_low = round(res["video_b"]["cost_low_thb"] + res["comparison"]["cost_low_thb"], 2)
    assert res["total"]["cost_low_thb"] == expected_low


def test_case_3_history_reuse_a_and_history_reuse_b():
    """CASE 3: A History + B History -> A = ฿0, B = ฿0, comparison engine only."""
    video_a = {"state": "HISTORY_REUSE", "duration_seconds": 300.0}
    video_b = {"state": "HISTORY_REUSE", "duration_seconds": 450.0}

    res = pre_run_estimator.estimate_comparison_pre_run(video_a, video_b, comparison_model="gemini-2.5-flash", exact_comparison_cached=False)

    assert res["is_complete"] is True
    assert res["video_a"]["cost_low_thb"] == 0.0
    assert res["video_a"]["gemini_calls"] == 0
    assert res["video_b"]["cost_low_thb"] == 0.0
    assert res["video_b"]["gemini_calls"] == 0

    assert res["comparison"]["cost_low_thb"] > 0
    assert res["comparison"]["gemini_calls"] == 1

    assert res["total"]["cost_low_thb"] == res["comparison"]["cost_low_thb"]
    assert res["total"]["tokens_low"] == res["comparison"]["tokens_low"]


def test_case_4_exact_comparison_cache_hit():
    """CASE 4: Exact comparison cache HIT -> total new cost ≈ ฿0, 0 Gemini calls."""
    video_a = {"state": "HISTORY_REUSE", "duration_seconds": 300.0}
    video_b = {"state": "HISTORY_REUSE", "duration_seconds": 450.0}

    res = pre_run_estimator.estimate_comparison_pre_run(video_a, video_b, comparison_model="gemini-2.5-flash", exact_comparison_cached=True)

    assert res["is_complete"] is True
    assert res["video_a"]["cost_low_thb"] == 0.0
    assert res["video_b"]["cost_low_thb"] == 0.0
    assert res["comparison"]["cached"] is True
    assert res["comparison"]["cost_low_thb"] == 0.0
    assert res["comparison"]["gemini_calls"] == 0

    assert res["total"]["cost_low_thb"] == 0.0
    assert res["total"]["cost_high_thb"] == 0.0
    assert res["total"]["tokens_low"] == 0
    assert res["total"]["tokens_high"] == 0


def test_case_5_mp4_plus_youtube():
    """CASE 5: MP4 + YouTube -> both estimated independently."""
    video_a = {"state": "NEW_ANALYSIS_REQUIRED", "duration_seconds": 90.0, "selected_model": "gemini-2.5-flash"}
    video_b = {"state": "NEW_ANALYSIS_REQUIRED", "duration_seconds": 210.0, "selected_model": "gemini-3.5-flash"}

    res = pre_run_estimator.estimate_comparison_pre_run(video_a, video_b)

    assert res["is_complete"] is True
    assert res["video_a"]["duration_seconds"] == 90.0
    assert res["video_b"]["duration_seconds"] == 210.0


def test_case_6_unresolved_duration_partial_total():
    """CASE 6: One unresolved TikTok duration -> clear partial total ("ยังประเมินไม่ครบ")."""
    video_a = {"state": "NEW_ANALYSIS_REQUIRED", "duration_seconds": 120.0, "selected_model": "gemini-3.5-flash"}
    video_b = {"state": "UNRESOLVED", "duration_seconds": None}

    res = pre_run_estimator.estimate_comparison_pre_run(video_a, video_b)

    assert res["is_complete"] is False
    assert res["video_a"]["is_resolved"] is True
    assert res["video_b"]["is_resolved"] is False
    assert res["total"]["cost_range_thb_text"] == "ยังประเมินไม่ครบ"
    assert res["total"]["tokens_range_text"] == "ยังประเมินไม่ครบ"
