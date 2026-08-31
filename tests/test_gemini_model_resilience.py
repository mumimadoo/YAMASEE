from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

from engines.ai_analysis_engine import AIAnalysisEngine
from engines.comparison_engine import ComparisonEngine, ComparisonEngineQuotaError
from engines.transcript_engine import TranscriptEngine
from utils.gemini_model_policy import (
    GeminiRateLimitedError,
    RESERVE_MODELS,
    build_model_chain,
    classify_gemini_error,
    get_retry_after_seconds,
    run_with_model_fallback,
    validate_primary_model,
)


EXPECTED_CHAINS = {
    "gemini-3.5-flash": [
        "gemini-3.5-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite",
        "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash",
    ],
    "gemini-2.5-flash": [
        "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.5-flash",
        "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash",
    ],
    "gemini-2.5-flash-lite": [
        "gemini-2.5-flash-lite", "gemini-3.5-flash", "gemini-2.5-flash",
        "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash",
    ],
}


class SilentLogger:
    def info(self, *_args, **_kwargs): pass
    def warning(self, *_args, **_kwargs): pass


def rate_limit_error(message="temporary quota", retry_after=None):
    headers = {} if retry_after is None else {"Retry-After": str(retry_after)}
    return genai_errors.ClientError(
        429,
        {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": message}},
        response=SimpleNamespace(headers=headers),
    )


@pytest.mark.parametrize("selected,expected", EXPECTED_CHAINS.items())
def test_locked_model_chains(selected, expected):
    assert build_model_chain(selected) == expected
    assert TranscriptEngine.get_failover_chain(object(), selected) + list(RESERVE_MODELS) == expected


def test_invalid_primary_model_uses_safe_default():
    assert validate_primary_model("gemini-arbitrary-injected") == "gemini-3.5-flash"


@pytest.mark.parametrize("selected", EXPECTED_CHAINS)
def test_selected_model_is_first_main_analysis_runtime_call(selected):
    engine = AIAnalysisEngine(api_key="test-key", preferred_model=selected)
    calls = []

    class FakeModels:
        def generate_content(self, *, model, **_kwargs):
            calls.append(model)
            return SimpleNamespace(text='{"summary": []}', usage_metadata=None)

    engine.client = SimpleNamespace(models=FakeModels())
    engine.generate_analytics("prompt", ["text"])
    assert calls == [selected]
    assert engine.successful_model == selected


@pytest.mark.parametrize("selected", EXPECTED_CHAINS)
def test_selected_model_is_first_comparison_runtime_call(selected, monkeypatch):
    engine = ComparisonEngine(api_key="test-key", preferred_model=selected)
    calls = []

    class FakeModels:
        def generate_content(self, *, model, **_kwargs):
            calls.append(model)
            raise ValueError("non-rate-limit sentinel")

    engine.client = SimpleNamespace(models=FakeModels())
    snapshot = SimpleNamespace(analysis_id="a")
    engine.build_comparison_prompt = lambda _a, _b: "prompt"
    monkeypatch.setattr("engines.comparison_engine.extract_deterministic_keywords", lambda _a, _b: {})
    with pytest.raises(ValueError, match="sentinel"):
        engine.run_comparison(snapshot, SimpleNamespace(analysis_id="b"))
    assert calls == [selected]


def test_temporary_429_uses_exponential_backoff(monkeypatch):
    monkeypatch.setattr("utils.gemini_model_policy.random.uniform", lambda _a, _b: 0.0)
    waits = []
    calls = []

    def invoke(model):
        calls.append(model)
        if len(calls) < 5:
            raise rate_limit_error()
        return "ok"

    result, model = run_with_model_fallback(
        invoke,
        selected_model="gemini-3.5-flash",
        logger=SilentLogger(),
        sleep_fn=waits.append,
    )
    assert (result, model) == ("ok", "gemini-3.5-flash")
    assert waits == [2.0, 4.0, 8.0, 16.0]
    assert calls == ["gemini-3.5-flash"] * 5


def test_retry_after_takes_priority_and_is_bounded():
    assert get_retry_after_seconds(rate_limit_error(retry_after=7)) == 7.0
    assert get_retry_after_seconds(rate_limit_error(retry_after=9999)) == 60.0


def test_429_then_same_model_success_does_not_fallback():
    calls = []
    waits = []

    def invoke(model):
        calls.append(model)
        if len(calls) == 1:
            raise rate_limit_error(retry_after=3)
        return "ok"

    result, model = run_with_model_fallback(
        invoke,
        selected_model="gemini-2.5-flash",
        logger=SilentLogger(),
        sleep_fn=waits.append,
    )
    assert (result, model) == ("ok", "gemini-2.5-flash")
    assert calls == ["gemini-2.5-flash", "gemini-2.5-flash"]
    assert waits == [3.0]


def test_exhausted_model_falls_back_in_locked_order():
    calls = []

    def invoke(model):
        calls.append(model)
        if model == "gemini-2.5-flash-lite":
            raise rate_limit_error()
        return "ok"

    result, model = run_with_model_fallback(
        invoke,
        selected_model="gemini-2.5-flash-lite",
        logger=SilentLogger(),
        sleep_fn=lambda _seconds: None,
    )
    assert (result, model) == ("ok", "gemini-3.5-flash")
    assert calls == ["gemini-2.5-flash-lite"] * 5 + ["gemini-3.5-flash"]


def test_hard_daily_quota_fails_over_immediately():
    calls = []

    def invoke(model):
        calls.append(model)
        if model == "gemini-3.5-flash":
            raise rate_limit_error("GenerateRequestsPerDayPerProjectPerModel daily quota")
        return "ok"

    result, model = run_with_model_fallback(
        invoke,
        selected_model="gemini-3.5-flash",
        logger=SilentLogger(),
        sleep_fn=lambda _seconds: pytest.fail("hard quota must not sleep"),
    )
    assert (result, model) == ("ok", "gemini-2.5-flash")
    assert calls == ["gemini-3.5-flash", "gemini-2.5-flash"]


def test_all_models_rate_limited_raises_explicit_status():
    calls = []

    def invoke(model):
        calls.append(model)
        raise rate_limit_error("daily quota per day")

    with pytest.raises(GeminiRateLimitedError) as caught:
        run_with_model_fallback(
            invoke,
            selected_model="gemini-2.5-flash",
            logger=SilentLogger(),
            sleep_fn=lambda _seconds: None,
        )
    error = caught.value
    assert error.reason == "RATE_LIMITED"
    assert error.attempted_models == EXPECTED_CHAINS["gemini-2.5-flash"]
    assert error.attempt_count == 6
    assert tuple(error.attempted_models[-3:]) == RESERVE_MODELS


def test_model_404_is_classified_and_fails_over_without_same_model_retry():
    calls = []
    waits = []

    class ModelNotFoundError(Exception):
        code = 404
        status = "NOT_FOUND"

    def invoke(model):
        calls.append(model)
        if model == "gemini-3.5-flash":
            raise ModelNotFoundError("model not found or unsupported for generateContent")
        return "ok"

    result, model = run_with_model_fallback(
        invoke,
        selected_model="gemini-3.5-flash",
        logger=SilentLogger(),
        sleep_fn=waits.append,
    )

    assert classify_gemini_error(ModelNotFoundError()) == "MODEL_NOT_FOUND"
    assert (result, model) == ("ok", "gemini-2.5-flash")
    assert calls == ["gemini-3.5-flash", "gemini-2.5-flash"]
    assert waits == []


def test_removed_model_is_never_reached_by_any_locked_chain():
    assert all("gemini-3-flash" not in chain for chain in EXPECTED_CHAINS.values())


def test_comparison_model_404_fails_over_immediately(monkeypatch):
    engine = ComparisonEngine(api_key="test-key", preferred_model="gemini-3.5-flash")
    calls = []

    class ModelNotFoundError(Exception):
        code = 404
        status = "NOT_FOUND"

    class FakeModels:
        def generate_content(self, *, model, **_kwargs):
            calls.append(model)
            if model == "gemini-3.5-flash":
                raise ModelNotFoundError("unsupported for generateContent")
            return SimpleNamespace(text='{}', usage_metadata=None)

    engine.client = SimpleNamespace(models=FakeModels())
    engine.build_comparison_prompt = lambda _a, _b: "prompt"
    engine.verify_and_clean_comparison = lambda data, _a, _b: (data, {})
    monkeypatch.setattr("engines.comparison_engine.extract_deterministic_keywords", lambda _a, _b: {})

    _result, _telemetry, model, _seconds = engine.run_comparison(
        SimpleNamespace(analysis_id="a"),
        SimpleNamespace(analysis_id="b"),
    )

    assert model == "gemini-2.5-flash"
    assert calls == ["gemini-3.5-flash", "gemini-2.5-flash"]


def test_non_429_is_not_classified_as_rate_limited():
    with pytest.raises(RuntimeError, match="programming failure"):
        run_with_model_fallback(
            lambda _model: (_ for _ in ()).throw(RuntimeError("programming failure")),
            selected_model="gemini-3.5-flash",
            logger=SilentLogger(),
            sleep_fn=lambda _seconds: None,
        )


def test_comparison_all_models_rate_limited_is_explicit(monkeypatch):
    engine = ComparisonEngine(api_key="test-key", preferred_model="gemini-2.5-flash-lite")
    calls = []

    class FakeModels:
        def generate_content(self, *, model, **_kwargs):
            calls.append(model)
            raise rate_limit_error("daily quota per day")

    engine.client = SimpleNamespace(models=FakeModels())
    engine.build_comparison_prompt = lambda _a, _b: "prompt"
    monkeypatch.setattr("engines.comparison_engine.extract_deterministic_keywords", lambda _a, _b: {})
    with pytest.raises(ComparisonEngineQuotaError, match="RATE_LIMITED"):
        engine.run_comparison(SimpleNamespace(analysis_id="a"), SimpleNamespace(analysis_id="b"))
    assert calls == EXPECTED_CHAINS["gemini-2.5-flash-lite"]
