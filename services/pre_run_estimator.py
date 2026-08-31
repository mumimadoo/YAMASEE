"""
YAMASEE — Pre-Run Cost Estimator
Deterministic estimator for predicting AI model resource usage and cost range BEFORE starting analysis.

Rules & Definitions:
- PRE-RUN ESTIMATE: Prediction before analysis based on video duration, selected model, and historical usage profile.
- POST-RUN ESTIMATED COST: Cost Engine V1 result based on actual token telemetry, actual models/calls, thinking/cache/grounding.
- Reuses central pricing registry from services/cost_engine.py.
- Does NOT call Gemini API.
- Does NOT call Google Search or external APIs.
- Does NOT execute synchronous yt-dlp on the request path.
"""

from typing import Dict, Any, List, Optional
import math
import glob
import json
import logging
from database import SessionLocal
from models.analysis_run_history import AnalysisRunHistory
from models.analysis_record import AnalysisRecord
from services.cost_engine import (
    MODEL_PRICING,
    resolve_model_name,
    calculate_single_model_cost,
    calculate_run_cost,
    DEFAULT_FX_RATE_USD_THB,
)

logger = logging.getLogger("yamasee.pre_run_estimator")


def percentile(lst: List[float], p: float) -> float:
    """Calculates percentile p (0.0 to 1.0) using linear interpolation."""
    if not lst:
        return 0.0
    if len(lst) == 1:
        return lst[0]
    s = sorted(lst)
    idx = (len(s) - 1) * p
    lower = int(idx)
    upper = lower + 1
    weight = idx - lower
    if upper >= len(s):
        return s[-1]
    return s[lower] * (1 - weight) + s[upper] * weight


def format_duration_hhmmss(seconds: Optional[float]) -> str:
    """Formats duration in seconds as HH:MM:SS format."""
    if seconds is None or seconds <= 0:
        return "ยังไม่ทราบความยาว"
    s = int(round(seconds))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}"


class PreRunCostEstimator:
    """
    Pre-run cost and token range estimator based on real historical analysis runs.
    """

    def __init__(self):
        self.profiles: Dict[str, Dict[str, Any]] = {}
        self.global_profile: Dict[str, Any] = {}
        self.tiktok_profiles: Dict[str, Dict[str, Any]] = {}
        self.tiktok_global_profile: Dict[str, Any] = {}
        self.eligible_historical_runs_count: int = 0
        self.comparison_profile: Dict[str, Any] = {}
        self.build_profiles()

    def build_profiles(self):
        """
        Scans DB and local history files for eligible historical runs with valid duration & token telemetry.
        Builds model-specific and global usage profiles (tokens/min and cost/min percentiles).
        Also builds comparison_profile from historical VideoComparison telemetry.
        """
        runs_data = []
        db = SessionLocal()
        try:
            db_runs = db.query(AnalysisRunHistory).all()
            for r in db_runs:
                dur = float(r.video_duration) if r.video_duration else 0.0
                if dur > 0 and r.token_usage:
                    cost_res = calculate_run_cost(r.token_usage, model_used=r.model_used, video_duration=dur)
                    if cost_res and cost_res.get("total_tokens", 0) > 0 and cost_res.get("estimated_cost_thb") is not None:
                        m_resolved = resolve_model_name(r.model_used) or r.model_used or "gemini-2.5-flash"
                        runs_data.append({
                            "job_id": r.job_id,
                            "model": m_resolved,
                            "duration": dur,
                            "tokens": cost_res["total_tokens"],
                            "cost_thb": cost_res["estimated_cost_thb"]
                        })
        except Exception as e:
            logger.warning(f"Error querying AnalysisRunHistory during profile build: {e}")
        finally:
            db.close()

        # Build comparison profile from VideoComparison table
        comp_tok_list = []
        comp_cost_list = []
        db_comp = SessionLocal()
        try:
            from models.video_comparison import VideoComparison
            db_comps = db_comp.query(VideoComparison).filter(VideoComparison.status == "completed").all()
            for c in db_comps:
                m = c.model_used or "gemini-2.5-flash"
                t = c.token_usage or {}
                comp_tok = t.get("comparison", {})
                tot_t = comp_tok.get("total_tokens", 0)
                prompt_t = comp_tok.get("prompt_tokens", 0)
                cand_t = comp_tok.get("candidates_tokens", 0)
                thought_t = comp_tok.get("thoughts_tokens", 0)
                if tot_t > 0:
                    c_res = calculate_single_model_cost(m, prompt_tokens=prompt_t, candidates_tokens=cand_t, thoughts_tokens=thought_t)
                    comp_tok_list.append(tot_t)
                    comp_cost_list.append(c_res.get("cost_total_thb", 0.0))
        except Exception as e:
            logger.warning(f"Error querying VideoComparison for comparison profile: {e}")
        finally:
            db_comp.close()

        if comp_tok_list:
            self.comparison_profile = {
                "sample_count": len(comp_tok_list),
                "tokens_p25": percentile(comp_tok_list, 0.25),
                "tokens_median": percentile(comp_tok_list, 0.50),
                "tokens_p75": percentile(comp_tok_list, 0.75),
                "cost_p25": percentile(comp_cost_list, 0.25),
                "cost_median": percentile(comp_cost_list, 0.50),
                "cost_p75": percentile(comp_cost_list, 0.75),
            }
        else:
            self.comparison_profile = {
                "sample_count": 0,
                "tokens_p25": 8000.0,
                "tokens_median": 11500.0,
                "tokens_p75": 14000.0,
                "cost_p25": 0.40,
                "cost_median": 0.60,
                "cost_p75": 0.85,
            }

        # Also inspect history JSON files in analysis_history/
        json_files = glob.glob("analysis_history/*.json")
        for f in json_files:
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    d = json.load(fp)
                    job_id = d.get("job_id")
                    dur = float(d.get("duration_seconds") or d.get("duration") or 0)
                    tok = d.get("token_usage") or d.get("telemetry")
                    model = d.get("model_used") or d.get("model") or "gemini-2.5-flash"
                    if dur > 0 and tok:
                        if not any(r.get("job_id") and r["job_id"] == job_id for r in runs_data):
                            cost_res = calculate_run_cost(tok, model_used=model, video_duration=dur)
                            if cost_res and cost_res.get("total_tokens", 0) > 0 and cost_res.get("estimated_cost_thb") is not None:
                                m_resolved = resolve_model_name(model) or model
                                runs_data.append({
                                    "job_id": job_id,
                                    "model": m_resolved,
                                    "duration": dur,
                                    "tokens": cost_res["total_tokens"],
                                    "cost_thb": cost_res["estimated_cost_thb"]
                                })
            except Exception:
                pass

        self.eligible_historical_runs_count = len(runs_data)
        if not runs_data:
            self.global_profile = {
                "sample_count": 0,
                "tokens_p25": 4000.0,
                "tokens_median": 5500.0,
                "tokens_p75": 6000.0,
                "cost_p25": 0.30,
                "cost_median": 0.50,
                "cost_p75": 0.80,
            }
            return

        all_tok_pm = [r["tokens"] / (r["duration"] / 60.0) for r in runs_data]
        all_cost_pm = [r["cost_thb"] / (r["duration"] / 60.0) for r in runs_data]

        self.global_profile = {
            "sample_count": len(runs_data),
            "tokens_p25": percentile(all_tok_pm, 0.25),
            "tokens_median": percentile(all_tok_pm, 0.50),
            "tokens_p75": percentile(all_tok_pm, 0.75),
            "cost_p25": percentile(all_cost_pm, 0.25),
            "cost_median": percentile(all_cost_pm, 0.50),
            "cost_p75": percentile(all_cost_pm, 0.75),
        }

        by_model: Dict[str, List[Dict[str, Any]]] = {}
        for r in runs_data:
            m = r["model"]
            if m not in by_model:
                by_model[m] = []
            by_model[m].append(r)

        for m, items in by_model.items():
            tok_pm = [item["tokens"] / (item["duration"] / 60.0) for item in items]
            cost_pm = [item["cost_thb"] / (item["duration"] / 60.0) for item in items]
            self.profiles[m] = {
                "sample_count": len(items),
                "tokens_p25": percentile(tok_pm, 0.25),
                "tokens_median": percentile(tok_pm, 0.50),
                "tokens_p75": percentile(tok_pm, 0.75),
                "cost_p25": percentile(cost_pm, 0.25),
                "cost_median": percentile(cost_pm, 0.50),
                "cost_p75": percentile(cost_pm, 0.75),
            }

        # Build TikTok historical per-run profiles
        tiktok_runs = []
        try:
            db_tt = SessionLocal()
            arh_tiktok = db_tt.query(AnalysisRunHistory).filter(AnalysisRunHistory.source_type.ilike("%tiktok%")).all()
            for r in arh_tiktok:
                dur = float(r.video_duration) if r.video_duration else 0.0
                m = resolve_model_name(r.model_used) or r.model_used or "gemini-2.5-flash"
                if r.token_usage:
                    c_res = calculate_run_cost(r.token_usage, model_used=m, video_duration=dur)
                    if c_res and c_res.get("total_tokens", 0) > 0:
                        tiktok_runs.append({
                            "model": m,
                            "tokens": c_res["total_tokens"],
                            "cost_thb": c_res["estimated_cost_thb"],
                            "duration": dur
                        })

            ar_tiktok = db_tt.query(AnalysisRecord).filter(
                AnalysisRecord.status == "completed",
                AnalysisRecord.source_type.ilike("%tiktok%")
            ).all()
            for r in ar_tiktok:
                dur = float(r.duration_seconds) if r.duration_seconds else 0.0
                if dur <= 0:
                    continue
                m = resolve_model_name(r.model_used) or r.model_used or "gemini-2.5-flash"
                dur_mins = dur / 60.0
                prof = self.profiles.get(m) or self.global_profile
                
                run_tokens = int(round(dur_mins * prof.get("tokens_median", 5500.0)))
                c_res = calculate_single_model_cost(m, prompt_tokens=int(run_tokens * 0.5), candidates_tokens=int(run_tokens * 0.5))
                run_cost_thb = round(c_res.get("cost_total_thb", 0.0), 2)
                if run_cost_thb <= 0:
                    run_cost_thb = round(dur_mins * prof.get("cost_median", 0.50), 2)
                    
                tiktok_runs.append({
                    "model": m,
                    "tokens": run_tokens,
                    "cost_thb": run_cost_thb,
                    "duration": dur
                })
            db_tt.close()
        except Exception as e:
            logger.warning(f"Error building TikTok historical profiles: {e}")

        self.tiktok_global_profile = {}
        self.tiktok_profiles = {}

        if tiktok_runs:
            all_toks = [r["tokens"] for r in tiktok_runs]
            all_costs = [r["cost_thb"] for r in tiktok_runs]
            self.tiktok_global_profile = {
                "sample_count": len(tiktok_runs),
                "tokens_p25": int(round(percentile(all_toks, 0.25))),
                "tokens_median": int(round(percentile(all_toks, 0.50))),
                "tokens_p75": int(round(percentile(all_toks, 0.75))),
                "cost_p25": round(percentile(all_costs, 0.25), 2),
                "cost_median": round(percentile(all_costs, 0.50), 2),
                "cost_p75": round(percentile(all_costs, 0.75), 2),
            }

            tt_by_model = {}
            for r in tiktok_runs:
                m = r["model"]
                if m not in tt_by_model:
                    tt_by_model[m] = []
                tt_by_model[m].append(r)

            for m, samples in tt_by_model.items():
                m_toks = [s["tokens"] for s in samples]
                m_costs = [s["cost_thb"] for s in samples]
                self.tiktok_profiles[m] = {
                    "sample_count": len(samples),
                    "tokens_p25": int(round(percentile(m_toks, 0.25))),
                    "tokens_median": int(round(percentile(m_toks, 0.50))),
                    "tokens_p75": int(round(percentile(m_toks, 0.75))),
                    "cost_p25": round(percentile(m_costs, 0.25), 2),
                    "cost_median": round(percentile(m_costs, 0.50), 2),
                    "cost_p75": round(percentile(m_costs, 0.75), 2),
                }

    def estimate_comparison_pre_run(
        self,
        video_a_data: Dict[str, Any],
        video_b_data: Dict[str, Any],
        comparison_model: str = "gemini-2.5-flash",
        exact_comparison_cached: bool = False,
        fx_rate: float = DEFAULT_FX_RATE_USD_THB
    ) -> Dict[str, Any]:
        """
        Computes Pre-run estimate for Video Comparison action.
        """
        m_comp_resolved = resolve_model_name(comparison_model) or comparison_model or "gemini-2.5-flash"

        def _estimate_side(side_data: Dict[str, Any]):
            st = (side_data.get("state") or "UNRESOLVED").upper()
            dur = side_data.get("duration_seconds")
            model = side_data.get("selected_model") or "gemini-3.5-flash"

            if st in ("HISTORY_REUSE", "CACHE_REUSE", "REUSE", "ALREADY_READY"):
                dur_fmt = format_duration_hhmmss(dur) if (dur and float(dur) > 0) else "--:--:--"
                return {
                    "state": "REUSE",
                    "label_th": "⚡ ใช้ผลวิเคราะห์เดิม",
                    "duration_seconds": float(dur) if (dur and float(dur) > 0) else None,
                    "duration_formatted": dur_fmt,
                    "tokens_low": 0,
                    "tokens_expected": 0,
                    "tokens_high": 0,
                    "tokens_range_text": "0 Token เพิ่ม",
                    "cost_low_thb": 0.0,
                    "cost_expected_thb": 0.0,
                    "cost_high_thb": 0.0,
                    "cost_range_thb_text": "วิเคราะห์เพิ่ม ≈ ฿0.00",
                    "gemini_calls": 0,
                    "is_resolved": True
                }

            if st in ("NEW_ANALYSIS_REQUIRED", "NEW") and dur and float(dur) > 0:
                est = self.estimate_pre_run(model, float(dur), fx_rate=fx_rate)
                return {
                    "state": "NEW_ANALYSIS_REQUIRED",
                    "label_th": "✨ วิเคราะห์ใหม่",
                    "duration_seconds": float(dur),
                    "duration_formatted": est["duration_formatted"],
                    "tokens_low": est["tokens_low"],
                    "tokens_expected": est["tokens_expected"],
                    "tokens_high": est["tokens_high"],
                    "tokens_range_text": est["tokens_range_text"],
                    "cost_low_thb": est["cost_low_thb"],
                    "cost_expected_thb": est["cost_expected_thb"],
                    "cost_high_thb": est["cost_high_thb"],
                    "cost_range_thb_text": est["cost_range_thb_text"],
                    "gemini_calls": 1,
                    "is_resolved": True
                }

            dur_fmt = format_duration_hhmmss(dur) if (dur and float(dur) > 0) else "ยังไม่ทราบความยาว"
            return {
                "state": "UNRESOLVED",
                "label_th": "กำลังประเมิน...",
                "duration_seconds": float(dur) if (dur and float(dur) > 0) else None,
                "duration_formatted": dur_fmt,
                "tokens_low": None,
                "tokens_expected": None,
                "tokens_high": None,
                "tokens_range_text": "ยังไม่สามารถประมาณได้",
                "cost_low_thb": None,
                "cost_expected_thb": None,
                "cost_high_thb": None,
                "cost_range_thb_text": "ยังไม่สามารถประมาณได้",
                "gemini_calls": 0,
                "is_resolved": False
            }

        est_a = _estimate_side(video_a_data)
        est_b = _estimate_side(video_b_data)

        # Comparison engine estimate
        if exact_comparison_cached:
            comp_est = {
                "cached": True,
                "label_th": "⚡ พบผลเปรียบเทียบเดิม",
                "tokens_low": 0,
                "tokens_expected": 0,
                "tokens_high": 0,
                "tokens_range_text": "0 Token เพิ่ม",
                "cost_low_thb": 0.0,
                "cost_expected_thb": 0.0,
                "cost_high_thb": 0.0,
                "cost_range_thb_text": "วิเคราะห์เพิ่ม ≈ ฿0.00",
                "gemini_calls": 0
            }
        else:
            cp = self.comparison_profile
            tok_low = int(round(cp["tokens_p25"]))
            tok_med = int(round(cp["tokens_median"]))
            tok_high = int(round(cp["tokens_p75"]))

            if m_comp_resolved in MODEL_PRICING:
                c_low_usd = calculate_single_model_cost(m_comp_resolved, prompt_tokens=int(tok_low * 0.50), candidates_tokens=int(tok_low * 0.50))["cost_total_usd"]
                c_med_usd = calculate_single_model_cost(m_comp_resolved, prompt_tokens=int(tok_med * 0.50), candidates_tokens=int(tok_med * 0.50))["cost_total_usd"]
                c_high_usd = calculate_single_model_cost(m_comp_resolved, prompt_tokens=int(tok_high * 0.50), candidates_tokens=int(tok_high * 0.50))["cost_total_usd"]

                cost_low = round(c_low_usd * fx_rate, 2)
                cost_med = round(c_med_usd * fx_rate, 2)
                cost_high = round(c_high_usd * fx_rate, 2)
            else:
                cost_low = round(cp["cost_p25"], 2)
                cost_med = round(cp["cost_median"], 2)
                cost_high = round(cp["cost_p75"], 2)

            comp_est = {
                "cached": False,
                "label_th": "เปรียบเทียบใหม่",
                "tokens_low": tok_low,
                "tokens_expected": tok_med,
                "tokens_high": tok_high,
                "tokens_range_text": f"≈ {tok_low:,} – {tok_high:,} Tokens",
                "cost_low_thb": cost_low,
                "cost_expected_thb": cost_med,
                "cost_high_thb": cost_high,
                "cost_range_thb_text": f"≈ ฿{cost_low:.2f} – ฿{cost_high:.2f}",
                "gemini_calls": 1
            }

        is_complete = est_a["is_resolved"] and est_b["is_resolved"]

        if is_complete:
            tot_cost_low = round(est_a["cost_low_thb"] + est_b["cost_low_thb"] + comp_est["cost_low_thb"], 2)
            tot_cost_med = round(est_a["cost_expected_thb"] + est_b["cost_expected_thb"] + comp_est["cost_expected_thb"], 2)
            tot_cost_high = round(est_a["cost_high_thb"] + est_b["cost_high_thb"] + comp_est["cost_high_thb"], 2)

            tot_tok_low = est_a["tokens_low"] + est_b["tokens_low"] + comp_est["tokens_low"]
            tot_tok_high = est_a["tokens_high"] + est_b["tokens_high"] + comp_est["tokens_high"]

            tot_cost_text = f"≈ ฿{tot_cost_low:.2f} – ฿{tot_cost_high:.2f}" if tot_cost_low != tot_cost_high else f"≈ ฿{tot_cost_med:.2f}"
            tot_tok_text = f"≈ {tot_tok_low:,} – {tot_tok_high:,} Tokens" if tot_tok_low != tot_tok_high else f"≈ {tot_tok_low:,} Tokens"
        else:
            tot_cost_text = "ยังประเมินไม่ครบ"
            tot_tok_text = "ยังประเมินไม่ครบ"
            tot_cost_low = tot_cost_high = tot_tok_low = tot_tok_high = None

        return {
            "is_complete": is_complete,
            "video_a": est_a,
            "video_b": est_b,
            "comparison": comp_est,
            "total": {
                "cost_low_thb": tot_cost_low,
                "cost_high_thb": tot_cost_high,
                "cost_range_thb_text": tot_cost_text,
                "tokens_low": tot_tok_low,
                "tokens_high": tot_tok_high,
                "tokens_range_text": tot_tok_text,
            }
        }

    def estimate_tiktok_fallback(
        self,
        model_name: str,
        fx_rate: float = DEFAULT_FX_RATE_USD_THB
    ) -> Dict[str, Any]:
        """
        Computes TikTok historical per-run fallback estimate when duration cannot be resolved before analysis.
        Level 1: TikTok + selected model historical runs (if >= 5 samples)
        Level 2: All TikTok historical runs (if >= 5 samples)
        Level 3: Unavailable if < 5 total TikTok samples.
        """
        m_resolved = resolve_model_name(model_name) or model_name or "gemini-3.5-flash"
        m_prof = self.tiktok_profiles.get(m_resolved)
        
        # LEVEL 1: Model-specific TikTok profile (>= 5 samples)
        if m_prof and m_prof.get("sample_count", 0) >= 5:
            tok_low = m_prof["tokens_p25"]
            tok_med = m_prof["tokens_median"]
            tok_high = m_prof["tokens_p75"]
            cost_low = m_prof["cost_p25"]
            cost_med = m_prof["cost_median"]
            cost_high = m_prof["cost_p75"]
            note = "ประมาณจากงาน TikTok ที่ระบบเคยประมวลผลด้วยโมเดลนี้"
            level = "MODEL_SPECIFIC"
            samples = m_prof["sample_count"]

        # LEVEL 2: Global TikTok profile (>= 5 samples)
        elif self.tiktok_global_profile and self.tiktok_global_profile.get("sample_count", 0) >= 5:
            g_prof = self.tiktok_global_profile
            tok_low = g_prof["tokens_p25"]
            tok_med = g_prof["tokens_median"]
            tok_high = g_prof["tokens_p75"]

            if m_resolved in MODEL_PRICING:
                c_low_usd = calculate_single_model_cost(m_resolved, prompt_tokens=int(tok_low * 0.50), candidates_tokens=int(tok_low * 0.50))["cost_total_usd"]
                c_med_usd = calculate_single_model_cost(m_resolved, prompt_tokens=int(tok_med * 0.50), candidates_tokens=int(tok_med * 0.50))["cost_total_usd"]
                c_high_usd = calculate_single_model_cost(m_resolved, prompt_tokens=int(tok_high * 0.50), candidates_tokens=int(tok_high * 0.50))["cost_total_usd"]
                cost_low = round(c_low_usd * fx_rate, 2)
                cost_med = round(c_med_usd * fx_rate, 2)
                cost_high = round(c_high_usd * fx_rate, 2)
            else:
                cost_low = g_prof["cost_p25"]
                cost_med = g_prof["cost_median"]
                cost_high = g_prof["cost_p75"]

            note = "ประมาณจากงาน TikTok ที่ระบบเคยประมวลผล"
            level = "GLOBAL_TIKTOK"
            samples = g_prof["sample_count"]

        # LEVEL 3: Insufficient TikTok history (< 5 samples)
        else:
            return {
                "duration_known": False,
                "duration_seconds": None,
                "duration_formatted": "ยังไม่ทราบก่อนประมวลผล",
                "is_historical_fallback": True,
                "fallback_available": False,
                "fallback_level": "UNAVAILABLE",
                "model_name": m_resolved,
                "tokens_range_text": "ยังไม่สามารถประมาณได้",
                "tokens_low": None,
                "tokens_expected": None,
                "tokens_high": None,
                "cost_range_thb_text": "ยังไม่สามารถประมาณได้",
                "cost_low_thb": None,
                "cost_expected_thb": None,
                "cost_high_thb": None,
                "confidence": "UNAVAILABLE",
                "confidence_label_th": "ยังไม่สามารถประมาณได้",
                "confidence_note_th": "ข้อมูลย้อนหลัง TikTok ไม่เพียงพอเพื่อประมาณการ",
                "explanation_th": "ข้อมูลย้อนหลัง TikTok ไม่เพียงพอเพื่อประมาณการ",
                "disclaimer_th": "คุณสามารถเลือกวิเคราะห์ต่อได้ แม้ระบบยังไม่สามารถประมาณการล่วงหน้าได้",
                "historical_samples": 0
            }

        if cost_low > cost_high:
            cost_low, cost_high = cost_high, cost_low
        if cost_low > cost_med:
            cost_med = cost_low
        if cost_high < cost_med:
            cost_high = cost_med

        if tok_low > tok_high:
            tok_low, tok_high = tok_high, tok_low

        tokens_range_text = f"≈ {tok_low:,} – {tok_high:,} Tokens" if tok_low != tok_high else f"≈ {tok_med:,} Tokens"
        cost_range_thb_text = f"≈ ฿{cost_low:.2f} – ฿{cost_high:.2f}" if cost_low != cost_high else f"≈ ฿{cost_med:.2f}"

        return {
            "duration_known": False,
            "duration_seconds": None,
            "duration_formatted": "ยังไม่ทราบก่อนประมวลผล",
            "is_historical_fallback": True,
            "fallback_available": True,
            "fallback_level": level,
            "model_name": m_resolved,
            "tokens_range_text": tokens_range_text,
            "tokens_low": tok_low,
            "tokens_expected": tok_med,
            "tokens_high": tok_high,
            "cost_range_thb_text": cost_range_thb_text,
            "cost_low_thb": cost_low,
            "cost_expected_thb": cost_med,
            "cost_high_thb": cost_high,
            "confidence": "MEDIUM" if level == "MODEL_SPECIFIC" else "LOW",
            "confidence_label_th": note,
            "confidence_note_th": note,
            "explanation_th": note,
            "disclaimer_th": "ประมาณการย้อนหลังต่อหนึ่งงานวิเคราะห์ โดยไม่อ้างอิงความยาววิดีโอ ค่าใช้จ่ายจริงอาจแตกต่างตามจำนวน Token และขั้นตอนที่เกิดขึ้นจริง",
            "historical_samples": samples
        }

    def estimate_pre_run(
        self,
        model_name: str,
        duration_seconds: Optional[float],
        source_type: Optional[str] = None,
        fx_rate: float = DEFAULT_FX_RATE_USD_THB
    ) -> Dict[str, Any]:
        """
        Computes pre-run estimated token range, cost THB range, and confidence level.
        Mode A: Duration available -> Existing duration-based estimate.
        Mode B: Duration unavailable + source_type TikTok -> TikTok historical per-run fallback.
        """
        m_resolved = resolve_model_name(model_name) or model_name or "gemini-3.5-flash"

        # Mode B Check: Duration unavailable AND source_type is TikTok
        if (duration_seconds is None or float(duration_seconds) <= 0) and source_type:
            st_lower = str(source_type).lower()
            if "tiktok" in st_lower:
                return self.estimate_tiktok_fallback(m_resolved, fx_rate=fx_rate)

        duration_formatted = format_duration_hhmmss(duration_seconds)

        if duration_seconds is None or duration_seconds <= 0:
            return {
                "duration_known": False,
                "duration_seconds": None,
                "duration_formatted": "ยังไม่ทราบความยาว",
                "model_name": m_resolved,
                "tokens_range_text": "รอข้อมูลความยาววิดีโอ",
                "tokens_low": None,
                "tokens_expected": None,
                "tokens_high": None,
                "cost_range_thb_text": "รอข้อมูลความยาววิดีโอ",
                "cost_low_thb": None,
                "cost_expected_thb": None,
                "cost_high_thb": None,
                "confidence": "UNAVAILABLE",
                "confidence_label_th": "ยังไม่สามารถประเมินได้",
                "confidence_note_th": "รอข้อมูลความยาววิดีโอเพื่อประมาณการ",
                "explanation_th": "กรุณาระบุหรือรอตรวจสอบความยาววิดีโอเพื่อประมาณค่าใช้จ่าย",
                "disclaimer_th": "ค่าใช้จ่ายจริงอาจสูงหรือต่ำกว่าช่วงประมาณการ ขึ้นอยู่กับจำนวน Token, Thinking Tokens, จำนวนครั้งที่เรียกโมเดล, Failover และขั้นตอนที่เกิดขึ้นจริง",
                "historical_samples": 0
            }

        dur_mins = float(duration_seconds) / 60.0
        prof = self.profiles.get(m_resolved)

        if prof and prof.get("sample_count", 0) >= 3:
            tok_low = int(round(dur_mins * prof["tokens_p25"]))
            tok_med = int(round(dur_mins * prof["tokens_median"]))
            tok_high = int(round(dur_mins * prof["tokens_p75"]))

            cost_low = round(dur_mins * prof["cost_p25"], 2)
            cost_med = round(dur_mins * prof["cost_median"], 2)
            cost_high = round(dur_mins * prof["cost_p75"], 2)

            samples = prof["sample_count"]
            confidence = "HIGH" if samples >= 5 else "MEDIUM"
            confidence_label = "สูง" if confidence == "HIGH" else "ปานกลาง"
            explanation = "ประมาณจากข้อมูลการใช้งานจริงย้อนหลังของ YAMASEE และราคาของโมเดลที่ระบบบันทึกไว้"
            sample_cnt = samples
        else:
            g_prof = self.global_profile
            tok_low = int(round(dur_mins * g_prof["tokens_p25"]))
            tok_med = int(round(dur_mins * g_prof["tokens_median"]))
            tok_high = int(round(dur_mins * g_prof["tokens_p75"]))

            if m_resolved in MODEL_PRICING:
                c_low_usd = calculate_single_model_cost(m_resolved, prompt_tokens=int(tok_low * 0.50), candidates_tokens=int(tok_low * 0.50))["cost_total_usd"]
                c_med_usd = calculate_single_model_cost(m_resolved, prompt_tokens=int(tok_med * 0.50), candidates_tokens=int(tok_med * 0.50))["cost_total_usd"]
                c_high_usd = calculate_single_model_cost(m_resolved, prompt_tokens=int(tok_high * 0.50), candidates_tokens=int(tok_high * 0.50))["cost_total_usd"]

                cost_low = round(c_low_usd * fx_rate, 2)
                cost_med = round(c_med_usd * fx_rate, 2)
                cost_high = round(c_high_usd * fx_rate, 2)
            else:
                cost_low = round(dur_mins * g_prof["cost_p25"], 2)
                cost_med = round(dur_mins * g_prof["cost_median"], 2)
                cost_high = round(dur_mins * g_prof["cost_p75"], 2)

            confidence = "LOW"
            confidence_label = "ค่อนข้างต่ำ (อ้างอิงค่าเฉลี่ยรวม)"
            explanation = "ข้อมูลย้อนหลังของโมเดลนี้ยังไม่เพียงพอ ระบบใช้ค่าเฉลี่ยจากงานวิเคราะห์ที่ใกล้เคียง"
            sample_cnt = prof.get("sample_count", 0) if prof else 0

        if cost_low > cost_high:
            cost_low, cost_high = cost_high, cost_low
        if cost_low > cost_med:
            cost_med = cost_low
        if cost_high < cost_med:
            cost_high = cost_med

        if tok_low > tok_high:
            tok_low, tok_high = tok_high, tok_low

        tokens_range_text = f"≈ {tok_low:,} – {tok_high:,} Tokens" if tok_low != tok_high else f"≈ {tok_med:,} Tokens"

        if cost_low != cost_high:
            cost_range_thb_text = f"≈ ฿{cost_low:.2f} – ฿{cost_high:.2f}"
        else:
            cost_range_thb_text = f"≈ ฿{cost_med:.2f}"

        return {
            "duration_known": True,
            "duration_seconds": float(duration_seconds),
            "duration_formatted": duration_formatted,
            "model_name": m_resolved,
            "tokens_range_text": tokens_range_text,
            "tokens_low": tok_low,
            "tokens_expected": tok_med,
            "tokens_high": tok_high,
            "cost_range_thb_text": cost_range_thb_text,
            "cost_low_thb": cost_low,
            "cost_expected_thb": cost_med,
            "cost_high_thb": cost_high,
            "confidence": confidence,
            "confidence_label_th": confidence_label,
            "confidence_note_th": explanation,
            "explanation_th": explanation,
            "disclaimer_th": "ค่าใช้จ่ายจริงอาจสูงหรือต่ำกว่าช่วงประมาณการ ขึ้นอยู่กับจำนวน Token, Thinking Tokens, จำนวนครั้งที่เรียกโมเดล, Failover และขั้นตอนที่เกิดขึ้นจริง",
            "historical_samples": sample_cnt
        }

    def get_all_model_estimates(
        self,
        duration_seconds: Optional[float],
        models_list: Optional[List[str]] = None,
        source_type: Optional[str] = None,
        fx_rate: float = DEFAULT_FX_RATE_USD_THB
    ) -> Dict[str, Dict[str, Any]]:
        if not models_list:
            models_list = ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.6-flash"]

        res = {}
        for m in models_list:
            res[m] = self.estimate_pre_run(m, duration_seconds, source_type=source_type, fx_rate=fx_rate)
        return res


# Global singleton instance
pre_run_estimator = PreRunCostEstimator()
