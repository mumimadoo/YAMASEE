import pytest
from schemas.comparison import ClearDifferenceItem, ContentDrivenTopicAnalysis
from engines.comparison_engine import (
    validate_comparison_language,
    remap_comparison_orientation,
    ComparisonEngine,
    ComparisonVideoSnapshot
)

def test_clear_difference_item_schema_new():
    item = ClearDifferenceItem(
        title="แหล่งข้อมูลที่ใช้สนับสนุนเรื่องต่างกันอย่างชัดเจน",
        video_a="อ้างข้อมูลจากการตรวจค้น จำนวนรถ และอัตราดอกเบี้ย",
        video_b="อ้างคำบอกเล่าของแม่และเหตุการณ์ภายในครอบครัว",
        significance="Video A ทำให้ผู้ชมเข้าใจเหตุการณ์ผ่านข้อมูลเชิงคดี ขณะที่ Video B ทำให้เข้าใจผ่านประสบการณ์ของผู้ได้รับผลกระทบ"
    )
    assert item.title == "แหล่งข้อมูลที่ใช้สนับสนุนเรื่องต่างกันอย่างชัดเจน"
    assert item.video_a == "อ้างข้อมูลจากการตรวจค้น จำนวนรถ และอัตราดอกเบี้ย"
    assert item.video_b == "อ้างคำบอกเล่าของแม่และเหตุการณ์ภายในครอบครัว"
    assert item.significance.startswith("Video A ทำให้ผู้ชมเข้าใจ")

def test_clear_difference_item_schema_legacy_fallback():
    item = ClearDifferenceItem(
        title="จุดเน้นของเนื้อหา",
        description="Video A เน้นกฎหมาย Video B เน้นความสัมพันธ์"
    )
    assert item.title == "จุดเน้นของเนื้อหา"
    assert item.description == "Video A เน้นกฎหมาย Video B เน้นความสัมพันธ์"
    assert item.video_a is None
    assert item.video_b is None
    assert item.significance is None

def test_language_validation_for_new_key_differences():
    valid_data = {
        "topic_analysis": {
            "key_differences": [
                {
                    "title": "ข้อเท็จจริงทางกฎหมายที่ต่างกัน",
                    "video_a": "กล่าวถึงอัตราดอกเบี้ยเกินกว่าที่กฎหมายกำหนด",
                    "video_b": "ไม่พบการกล่าวถึงประเด็นนี้ใน Video B",
                    "significance": "แสดงให้เห็นว่า Video A ให้รายละเอียดทางกฎหมายที่ลึกซึ้งกว่า"
                }
            ]
        }
    }
    assert validate_comparison_language(valid_data) == []

    invalid_data = {
        "topic_analysis": {
            "key_differences": [
                {
                    "title": "Legal aspects difference and primary focus",
                    "video_a": "Mentions interest rates exceeding legal limit",
                    "video_b": "No mention of legal aspects in Video B",
                    "significance": "Shows Video A provides deeper legal detail"
                }
            ]
        }
    }
    violations = validate_comparison_language(invalid_data)
    assert len(violations) >= 3
    assert "topic_analysis.key_differences[0].title" in violations
    assert "topic_analysis.key_differences[0].video_a" in violations

def test_remap_comparison_orientation_swaps_video_a_and_b():
    data = {
        "comparison_overview": {
            "focus_video_a": "Focus A",
            "focus_video_b": "Focus B"
        },
        "topic_analysis": {
            "video_a_topics": [{"title": "Topic A1", "description": "Desc A1"}],
            "video_b_topics": [{"title": "Topic B1", "description": "Desc B1"}],
            "key_differences": [
                {
                    "title": "Finding 1",
                    "video_a": "Evidence A",
                    "video_b": "Evidence B",
                    "significance": "Significance 1"
                }
            ]
        }
    }

    remapped = remap_comparison_orientation(data)
    # Overview swapped
    assert remapped["comparison_overview"]["focus_video_a"] == "Focus B"
    assert remapped["comparison_overview"]["focus_video_b"] == "Focus A"
    # Topics swapped
    assert remapped["topic_analysis"]["video_a_topics"][0]["title"] == "Topic B1"
    assert remapped["topic_analysis"]["video_b_topics"][0]["title"] == "Topic A1"
    # Key differences evidence swapped
    assert remapped["topic_analysis"]["key_differences"][0]["video_a"] == "Evidence B"
    assert remapped["topic_analysis"]["key_differences"][0]["video_b"] == "Evidence A"
    # Significance remains the same
    assert remapped["topic_analysis"]["key_differences"][0]["significance"] == "Significance 1"

def test_prompt_contains_new_instructions():
    snap_a = ComparisonVideoSnapshot(
        analysis_id="id_a",
        source_type="youtube",
        title="Video A Title",
        duration_seconds=60.0,
        analyzed_at="2026-08-20T00:00:00",
        transcript=[],
        existing_analysis={},
        fingerprint="fp_a"
    )
    snap_b = ComparisonVideoSnapshot(
        analysis_id="id_b",
        source_type="youtube",
        title="Video B Title",
        duration_seconds=60.0,
        analyzed_at="2026-08-20T00:00:00",
        transcript=[],
        existing_analysis={},
        fingerprint="fp_b"
    )

    engine = ComparisonEngine(api_key="test_key")
    prompt = engine.build_comparison_prompt(snap_a, snap_b)

    assert "NO PREDEFINED CATEGORIES" in prompt
    assert "SUBSTANTIVE DIFFERENCES" in prompt
    assert "NEW VALUE ADD" in prompt
    assert "VARIABLE COUNT" in prompt
    assert "significance" in prompt
    assert "video_a" in prompt
    assert "video_b" in prompt
