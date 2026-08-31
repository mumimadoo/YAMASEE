import pytest
import asyncio
from services.duration_service import find_cached_duration, resolve_url_duration_async

def test_1_cache_hit_duration():
    # Existing analysis_history file YouTube ID: 0IJ9-d461Ao
    url = "https://www.youtube.com/watch?v=0IJ9-d461Ao"
    dur = find_cached_duration(url)
    assert dur is not None
    assert dur > 0

def test_2_async_resolve_duration_cache_hit():
    url = "https://www.youtube.com/watch?v=0IJ9-d461Ao"
    dur = asyncio.run(resolve_url_duration_async(url))
    assert dur is not None
    assert dur > 0

def test_3_async_resolve_duration_new_url():
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    dur = asyncio.run(resolve_url_duration_async(url))
    assert dur is not None
    assert dur > 0

def test_4_no_extra_gemini_calls(monkeypatch):
    import google.genai as genai
    def blow_up(*args, **kwargs):
        pytest.fail("Gemini API call attempted during duration resolution!")
    monkeypatch.setattr(genai.Client, "models", blow_up)

    dur = find_cached_duration("https://www.youtube.com/watch?v=0IJ9-d461Ao")
    assert dur is not None
