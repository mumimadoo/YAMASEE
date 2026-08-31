import re
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from google import genai

from config import settings
from utils.logger import logger
from utils.telemetry import create_empty_token_usage, add_response_telemetry
from utils.gemini_model_policy import (
    RATE_LIMITED_MESSAGE,
    RESERVE_MODELS,
    build_model_chain,
    get_rate_limit_wait,
    is_hard_quota_error,
    is_model_not_found_error,
    is_rate_limit_error,
    validate_primary_model,
)
from schemas.comparison import (
    ComparisonVideoSnapshot,
    ComparisonResultContract,
    ComparisonOverview,
    SharedTopic,
    KeyDifference,
    UniqueTopics,
    UniqueTopicItem,
    ViewpointRelationship,
    KeywordComparison,
    SentimentComparison,
    EvidenceTimelineItem,
    FinalComparativeInsight,
    EvidenceReference,
    EvidenceVerificationStatus,
)
from services.comparison_service import validate_evidence

class ComparisonEngineError(Exception):
    """Raised when Comparison AI processing fails."""
    pass

class ComparisonEngineQuotaError(ComparisonEngineError):
    """Raised when Gemini API quota is exhausted."""
    pass

ALLOWED_RELATIONSHIP_TYPES = {"supporting", "different_view", "contradicting"}

def is_thai_analytical_text(text: str) -> bool:
    """
    Validates whether analytical prose text is written in Thai.
    Allows short technical names/terms (e.g. 'AI', 'Google AI Studio', 'YouTube', 'TikTok').
    For long prose paragraphs (> 25 chars), flags as invalid if predominantly English with no/near-zero Thai characters.
    """
    if not text or not isinstance(text, str):
        return True

    cleaned = text.strip()
    if len(cleaned) <= 25:
        return True

    thai_chars = len(re.findall(r'[\u0e00-\u0e7f]', cleaned))
    eng_chars = len(re.findall(r'[a-zA-Z]', cleaned))

    total_alpha = thai_chars + eng_chars
    if total_alpha > 15:
        if thai_chars == 0 or (thai_chars / total_alpha) < 0.15:
            return False

    return True

def validate_comparison_language(result_dict: Dict[str, Any]) -> List[str]:
    """
    Extracts all substantial analytical prose fields (EXCLUDING authoritative transcript evidence text)
    and checks if any section contains non-Thai prose paragraphs.
    Returns list of violating field paths (e.g. ['sentiment_comparison.comparison_notes']).
    """
    violating = []

    def _check_field(field_path: str, val: Any):
        if isinstance(val, str) and not is_thai_analytical_text(val):
            violating.append(field_path)

    # 01 comparison_overview
    overview = result_dict.get("comparison_overview", {})
    if isinstance(overview, dict):
        _check_field("comparison_overview.summary", overview.get("summary"))
        _check_field("comparison_overview.focus_video_a", overview.get("focus_video_a"))
        _check_field("comparison_overview.focus_video_b", overview.get("focus_video_b"))
        _check_field("comparison_overview.target_audience_comparison", overview.get("target_audience_comparison"))

    # 02 topic_analysis (Content-Driven Section 2)
    topic_analysis = result_dict.get("topic_analysis", {})
    if isinstance(topic_analysis, dict):
        for idx, item in enumerate(topic_analysis.get("video_a_topics", [])):
            if isinstance(item, dict):
                _check_field(f"topic_analysis.video_a_topics[{idx}].title", item.get("title"))
                _check_field(f"topic_analysis.video_a_topics[{idx}].description", item.get("description"))
        for idx, item in enumerate(topic_analysis.get("video_b_topics", [])):
            if isinstance(item, dict):
                _check_field(f"topic_analysis.video_b_topics[{idx}].title", item.get("title"))
                _check_field(f"topic_analysis.video_b_topics[{idx}].description", item.get("description"))
        for idx, item in enumerate(topic_analysis.get("key_differences", [])):
            if isinstance(item, dict):
                _check_field(f"topic_analysis.key_differences[{idx}].title", item.get("title"))
                _check_field(f"topic_analysis.key_differences[{idx}].video_a", item.get("video_a"))
                _check_field(f"topic_analysis.key_differences[{idx}].video_b", item.get("video_b"))
                _check_field(f"topic_analysis.key_differences[{idx}].significance", item.get("significance"))
                _check_field(f"topic_analysis.key_differences[{idx}].description", item.get("description"))

    # Legacy 02 comparison_topics
    for idx, item in enumerate(result_dict.get("comparison_topics", [])):
        if isinstance(item, dict):
            _check_field(f"comparison_topics[{idx}].topic", item.get("topic"))
            _check_field(f"comparison_topics[{idx}].description_a", item.get("description_a"))
            _check_field(f"comparison_topics[{idx}].description_b", item.get("description_b"))

    # Legacy shared_topics
    for idx, item in enumerate(result_dict.get("shared_topics", [])):
        if isinstance(item, dict):
            _check_field(f"shared_topics[{idx}].topic", item.get("topic"))
            _check_field(f"shared_topics[{idx}].description_a", item.get("description_a"))
            _check_field(f"shared_topics[{idx}].description_b", item.get("description_b"))

    # Legacy key_differences
    for idx, item in enumerate(result_dict.get("key_differences", [])):
        if isinstance(item, dict):
            _check_field(f"key_differences[{idx}].dimension", item.get("dimension"))
            _check_field(f"key_differences[{idx}].video_a_perspective", item.get("video_a_perspective"))
            _check_field(f"key_differences[{idx}].video_b_perspective", item.get("video_b_perspective"))
            _check_field(f"key_differences[{idx}].significance", item.get("significance"))

    # Legacy unique_topics
    unique = result_dict.get("unique_topics", {})
    if isinstance(unique, dict):
        for idx, item in enumerate(unique.get("video_a", [])):
            if isinstance(item, dict):
                _check_field(f"unique_topics.video_a[{idx}].topic", item.get("topic"))
                _check_field(f"unique_topics.video_a[{idx}].description", item.get("description"))
        for idx, item in enumerate(unique.get("video_b", [])):
            if isinstance(item, dict):
                _check_field(f"unique_topics.video_b[{idx}].topic", item.get("topic"))
                _check_field(f"unique_topics.video_b[{idx}].description", item.get("description"))

    # 03 viewpoint_relationships
    for idx, item in enumerate(result_dict.get("viewpoint_relationships", [])):
        if isinstance(item, dict):
            _check_field(f"viewpoint_relationships[{idx}].topic", item.get("topic"))
            _check_field(f"viewpoint_relationships[{idx}].summary", item.get("summary"))

    # 05 sentiment_comparison
    sent = result_dict.get("sentiment_comparison", {})
    if isinstance(sent, dict):
        _check_field("sentiment_comparison.video_a_sentiment", sent.get("video_a_sentiment"))
        _check_field("sentiment_comparison.video_b_sentiment", sent.get("video_b_sentiment"))
        _check_field("sentiment_comparison.comparison_notes", sent.get("comparison_notes"))

    # Legacy evidence_timeline
    for idx, item in enumerate(result_dict.get("evidence_timeline", [])):
        if isinstance(item, dict):
            _check_field(f"evidence_timeline[{idx}].topic", item.get("topic"))
            _check_field(f"evidence_timeline[{idx}].comparison_point", item.get("comparison_point"))

    # 06 final_comparative_insight
    insight = result_dict.get("final_comparative_insight", {})
    if isinstance(insight, dict):
        _check_field("final_comparative_insight.core_takeaway", insight.get("core_takeaway"))
        _check_field("final_comparative_insight.comparative_conclusion", insight.get("comparative_conclusion"))
        _check_field("final_comparative_insight.recommendation", insight.get("recommendation"))

    return violating

def extract_deterministic_keywords(
    snapshot_a: ComparisonVideoSnapshot,
    snapshot_b: ComparisonVideoSnapshot
) -> Dict[str, List[str]]:
    """
    Computes exact, deterministic set intersection and differences for keywords
    between Video A and Video B based on their audited existing analysis.
    """
    kw_a_raw = snapshot_a.existing_analysis.get("keywords", [])
    kw_b_raw = snapshot_b.existing_analysis.get("keywords", [])

    def _extract_words(raw_list: list) -> List[str]:
        words = []
        for item in raw_list:
            if isinstance(item, dict):
                w = str(item.get("keyword") or item.get("text") or "").strip()
            elif isinstance(item, str):
                w = item.strip()
            else:
                w = ""
            if w and w not in words:
                words.append(w)
        return words

    words_a = _extract_words(kw_a_raw)
    words_b = _extract_words(kw_b_raw)

    set_a = set(w.lower() for w in words_a)
    set_b = set(w.lower() for w in words_b)

    # Preserve original casing
    map_a = {w.lower(): w for w in words_a}
    map_b = {w.lower(): w for w in words_b}

    shared_keys = set_a & set_b
    a_only_keys = set_a - set_b
    b_only_keys = set_b - set_a

    video_a_only = [map_a[k.lower()] for k in words_a if k.lower() in a_only_keys]
    shared = [map_a.get(k, map_b.get(k, k)) for k in shared_keys]
    video_b_only = [map_b[k.lower()] for k in words_b if k.lower() in b_only_keys]

    return {
        "video_a_only": video_a_only,
        "shared": shared,
        "video_b_only": video_b_only,
    }

def remap_evidence_video_identifier(evidence_dict: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Flips evidence video identifier ('A' <-> 'B') for orientation remapping."""
    if not evidence_dict or not isinstance(evidence_dict, dict):
        return evidence_dict

    res = evidence_dict.copy()
    v = str(res.get("video", "")).upper()
    if v == "A":
        res["video"] = "B"
    elif v == "B":
        res["video"] = "A"
    return res

def remap_comparison_orientation(result_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remaps presentation fields of a comparison result when serving a cached entry
    where requested Video A is stored as Video B in the underlying canonical pair.
    """
    if not result_json or not isinstance(result_json, dict):
        return result_json

    remapped = json.loads(json.dumps(result_json)) # Deep copy

    # 1. 01 comparison_overview
    overview = remapped.get("comparison_overview", {})
    if isinstance(overview, dict):
        f_a = overview.get("focus_video_a", "")
        f_b = overview.get("focus_video_b", "")
        overview["focus_video_a"] = f_b
        overview["focus_video_b"] = f_a

    # 2. topic_analysis (Content-Driven Section 2)
    topic_analysis = remapped.get("topic_analysis", {})
    if isinstance(topic_analysis, dict):
        ta_a = topic_analysis.get("video_a_topics", [])
        ta_b = topic_analysis.get("video_b_topics", [])
        topic_analysis["video_a_topics"] = ta_b
        topic_analysis["video_b_topics"] = ta_a

        kd = topic_analysis.get("key_differences", [])
        if isinstance(kd, list):
            for item in kd:
                if isinstance(item, dict):
                    v_a = item.get("video_a")
                    v_b = item.get("video_b")
                    if v_a is not None or v_b is not None:
                        item["video_a"] = v_b
                        item["video_b"] = v_a

    # Legacy comparison_topics (Unified Section 2)
    comp_topics = remapped.get("comparison_topics", [])
    if isinstance(comp_topics, list):
        for item in comp_topics:
            if not isinstance(item, dict):
                continue
            d_a = item.get("description_a", "")
            d_b = item.get("description_b", "")
            cat = item.get("category", "")
            item["description_a"] = d_b
            item["description_b"] = d_a
            if cat == "unique_a":
                item["category"] = "unique_b"
            elif cat == "unique_b":
                item["category"] = "unique_a"

    # Legacy 02 shared_topics
    shared_topics = remapped.get("shared_topics", [])
    if isinstance(shared_topics, list):
        for item in shared_topics:
            if not isinstance(item, dict):
                continue
            desc_a = item.get("description_a", "")
            desc_b = item.get("description_b", "")
            ev_a = item.get("evidence_a")
            ev_b = item.get("evidence_b")

            item["description_a"] = desc_b
            item["description_b"] = desc_a
            item["evidence_a"] = remap_evidence_video_identifier(ev_b)
            item["evidence_b"] = remap_evidence_video_identifier(ev_a)

    # 3. 03 key_differences
    key_differences = remapped.get("key_differences", [])
    if isinstance(key_differences, list):
        for item in key_differences:
            if not isinstance(item, dict):
                continue
            p_a = item.get("video_a_perspective", "")
            p_b = item.get("video_b_perspective", "")
            ev_a = item.get("evidence_a")
            ev_b = item.get("evidence_b")

            item["video_a_perspective"] = p_b
            item["video_b_perspective"] = p_a
            item["evidence_a"] = remap_evidence_video_identifier(ev_b)
            item["evidence_b"] = remap_evidence_video_identifier(ev_a)

    # 4. 04 unique_topics
    unique_topics = remapped.get("unique_topics", {})
    if isinstance(unique_topics, dict):
        u_a = unique_topics.get("video_a", [])
        u_b = unique_topics.get("video_b", [])

        # Swap lists and remap internal evidence video IDs
        new_u_a = []
        for item in u_b:
            if isinstance(item, dict):
                item_copy = item.copy()
                if "evidence" in item_copy:
                    item_copy["evidence"] = remap_evidence_video_identifier(item_copy["evidence"])
                new_u_a.append(item_copy)

        new_u_b = []
        for item in u_a:
            if isinstance(item, dict):
                item_copy = item.copy()
                if "evidence" in item_copy:
                    item_copy["evidence"] = remap_evidence_video_identifier(item_copy["evidence"])
                new_u_b.append(item_copy)

        unique_topics["video_a"] = new_u_a
        unique_topics["video_b"] = new_u_b

    # 5. 05 viewpoint_relationships
    vp_list = remapped.get("viewpoint_relationships", [])
    if isinstance(vp_list, list):
        for item in vp_list:
            if not isinstance(item, dict):
                continue
            ev_a = item.get("evidence_a")
            ev_b = item.get("evidence_b")
            item["evidence_a"] = remap_evidence_video_identifier(ev_b)
            item["evidence_b"] = remap_evidence_video_identifier(ev_a)

    # 6. 06 keyword_comparison
    kw = remapped.get("keyword_comparison", {})
    if isinstance(kw, dict):
        kw_a = kw.get("video_a_only", [])
        kw_b = kw.get("video_b_only", [])
        kw["video_a_only"] = kw_b
        kw["video_b_only"] = kw_a

    # 7. 07 sentiment_comparison
    sent = remapped.get("sentiment_comparison", {})
    if isinstance(sent, dict):
        s_a = sent.get("video_a_sentiment", "")
        s_b = sent.get("video_b_sentiment", "")
        sent["video_a_sentiment"] = s_b
        sent["video_b_sentiment"] = s_a

    # 8. 08 evidence_timeline
    ev_timeline = remapped.get("evidence_timeline", [])
    if isinstance(ev_timeline, list):
        for item in ev_timeline:
            if not isinstance(item, dict):
                continue
            tr_a = item.get("time_range_a", "")
            tr_b = item.get("time_range_b", "")
            ev_a = item.get("evidence_a")
            ev_b = item.get("evidence_b")

            item["time_range_a"] = tr_b
            item["time_range_b"] = tr_a
            item["evidence_a"] = remap_evidence_video_identifier(ev_b)
            item["evidence_b"] = remap_evidence_video_identifier(ev_a)

    return remapped

GENERIC_TOPIC_HEADINGS = {
    "เนื้อหาหลัก", "ลักษณะตัวละครหลัก", "ตัวละครหลัก", "ตัวละคร",
    "ประเด็นทางกฎหมาย", "ประเด็นสำคัญ", "ประเด็นร่วม", "จุดแตกต่างสำคัญ",
    "ประเด็นเฉพาะ", "เหตุการณ์", "เรื่องทั่วไป", "สังคม", "บุคคล",
    "ประเด็น video a", "ประเด็น video b", "ประเด็นสำคัญใน video a", "ประเด็นสำคัญใน video b"
}

def sanitize_topic_analysis(topic_analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    Post-processes topic_analysis to ensure:
    1. Generic predefined headings are removed or converted to content-driven titles.
    2. Near-duplicate topics are deduplicated.
    3. Max 6 topics per video enforced without forced filler topics.
    """
    if not isinstance(topic_analysis, dict):
        return topic_analysis

    def clean_topic_list(items: List[Any]) -> List[Dict[str, str]]:
        cleaned = []
        seen_titles = set()

        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            desc = str(item.get("description", "")).strip()

            title_lower = title.lower()
            if title_lower in GENERIC_TOPIC_HEADINGS or any(g in title_lower for g in ["เนื้อหาหลัก", "ลักษณะตัวละครหลัก"]):
                if desc and len(desc) > 5 and desc.lower() not in GENERIC_TOPIC_HEADINGS:
                    parts = [p.strip() for p in desc.split(" ") if p.strip()]
                    title = " ".join(parts[:5]).rstrip(".,:;")
                else:
                    continue

            if not title or title.lower() in seen_titles or title.lower() in GENERIC_TOPIC_HEADINGS:
                continue

            seen_titles.add(title.lower())
            cleaned.append({"title": title, "description": desc})
            if len(cleaned) >= 6:
                break

        return cleaned

    topic_analysis["video_a_topics"] = clean_topic_list(topic_analysis.get("video_a_topics", []))
    topic_analysis["video_b_topics"] = clean_topic_list(topic_analysis.get("video_b_topics", []))
    return topic_analysis

class ComparisonEngine:
    """
    Core engine for comparative reasoning over two video snapshots.
    Uses Gemini API for semantic comparison and verifies all evidence references
    against authoritative transcript segments.
    """
    def __init__(self, api_key: Optional[str] = None, preferred_model: Optional[str] = None):
        key = api_key or settings.gemini_api_key
        if not key:
            raise ComparisonEngineError("GEMINI_API_KEY is not configured.")

        self.client = genai.Client(api_key=key)
        self.token_telemetry = {
            "comparison": {
                "requests": 0,
                "prompt_tokens": 0,
                "candidates_tokens": 0,
                "cached_tokens": 0,
                "thoughts_tokens": 0,
                "total_tokens": 0,
            },
            "models": {}
        }

        self.selected_model = validate_primary_model(preferred_model, default="gemini-2.5-flash")
        self.models = build_model_chain(self.selected_model, default="gemini-2.5-flash")

    def build_comparison_prompt(
        self,
        snapshot_a: ComparisonVideoSnapshot,
        snapshot_b: ComparisonVideoSnapshot
    ) -> str:
        """
        Builds a single comprehensive comparative analysis prompt incorporating:
        - Video A/B titles & metadata
        - Full authoritative transcripts with segment IDs and timestamp labels
        - Summaries, topics, sentiment, and chapters
        - Strict constraints on evidence verification and allowed relationship types.
        """
        transcript_a_lines = [
            f"  [Segment {s.segment_id} | {s.label}] {s.text}"
            for s in snapshot_a.transcript
        ]
        transcript_b_lines = [
            f"  [Segment {s.segment_id} | {s.label}] {s.text}"
            for s in snapshot_b.transcript
        ]

        summary_a = snapshot_a.existing_analysis.get("summary", [])
        summary_b = snapshot_b.existing_analysis.get("summary", [])

        sent_a = snapshot_a.existing_analysis.get("dominant_sentiment", "")
        sent_b = snapshot_b.existing_analysis.get("dominant_sentiment", "")

        prompt = f"""You are an expert video intelligence analyst comparing two videos.

=== VIDEO A METADATA ===
Title: {snapshot_a.title}
Source Type: {snapshot_a.source_type}
Duration: {snapshot_a.duration_seconds:.1f} seconds
Dominant Sentiment: {sent_a}
Summary: {json.dumps(summary_a, ensure_ascii=False)}

=== VIDEO A TRANSCRIPT (Authoritative Segments) ===
{chr(10).join(transcript_a_lines)}

=== VIDEO B METADATA ===
Title: {snapshot_b.title}
Source Type: {snapshot_b.source_type}
Duration: {snapshot_b.duration_seconds:.1f} seconds
Dominant Sentiment: {sent_b}
Summary: {json.dumps(summary_b, ensure_ascii=False)}

=== VIDEO B TRANSCRIPT (Authoritative Segments) ===
{chr(10).join(transcript_b_lines)}

=== COMPARISON INSTRUCTIONS ===
Perform a deep comparative analysis of Video A and Video B based STRICTLY and ONLY on the provided transcripts and metadata above.
DO NOT use external knowledge. DO NOT invent facts, timestamps, quotes, or segment IDs.

ROLE SEPARATION (SECTION 1 vs SECTION 2):
- Section 1 (comparison_overview): Macro overview answering what both videos are about overall and how they differ high-level.
- Section 2 (topic_analysis):
  * top part (video_a_topics, video_b_topics): Discover specific topics for Video A and Video B independently from actual content.
  * bottom part (key_differences): "When analyzing the discovered topics and real evidence from Video A and Video B together, what meaningful differences do we discover?"
  * DO NOT make key_differences a second summary repeat of Section 1!

CRITICAL REASONING ORDER FOR SECTION 2 (วิเคราะห์ประเด็นและความแตกต่าง):
STEP 1: อ่านเนื้อหาของ Video A ทั้งหมด แล้วระบุประเด็นสำคัญที่เกิดขึ้นจริงจากเนื้อหา โดยไม่กำหนดหมวดหมู่ล่วงหน้า (2–6 natural topics).
STEP 2: ทำแบบเดียวกันกับ Video B อย่างอิสระ (2–6 natural topics). ไม่บังคับให้มีจำนวนประเด็นเท่ากัน.
STEP 3: เปรียบเทียบชุดประเด็นและหลักฐานจริงที่ค้นพบจาก Video A และ Video B.
STEP 4: ค้นพบความแตกต่างที่มีนัยสำคัญ (Meaningful Differences) ที่เพิ่มข้อมูลหรือมุมมองใหม่จาก Section 1.

RULES FOR KEY DIFFERENCES (ความแตกต่างที่ชัดเจน):
1. NO PREDEFINED CATEGORIES: ห้ามใช้หัวข้อบังคับ/ตายตัว เช่น "จุดเน้นของเนื้อหา", "ประเภทเนื้อหา", "ลักษณะตัวละคร", "ประเด็นทางกฎหมาย", "วิธีการนำเสนอ". ชื่อหัวข้อ (title) ของแต่ละ Difference Finding ต้องเกิดจากข้อมูลจริงของวิดีโอคู่นั้น.
2. SUBSTANTIVE DIFFERENCES: ให้ค้นหาความแตกต่างที่มีสาระ เช่น ข้อเท็จจริงที่ต่างกัน, ตัวเลข/ข้อมูลเชิงปริมาณ, เหตุการณ์, บุคคล, สาเหตุ, ผลกระทบ, หลักฐาน, ข้อกล่าวอ้าง, ข้อสรุป, ลำดับเหตุการณ์, สิ่งที่ A พูดแต่ B ไม่พูด, สิ่งที่ B พูดแต่ A ไม่พูด, หรือความขัดแย้งของข้อมูล.
3. NEW VALUE ADD: ต้องเพิ่มข้อมูลใหม่เฉพาะเจาะจง ห้ามพูดซ้ำแค่ "A พูดเรื่อง X ส่วน B พูดเรื่อง Y" โดยไม่มี comparative insight.
4. VARIABLE COUNT: จำนวน key_differences ขึ้นอยู่กับข้อมูลจริง (0, 1, 2, 3, 4 หรือมากกว่า). หากวิดีโอทั้งสองไม่มีความแตกต่างเพิ่มเติมที่มีคุณค่ามากกว่า Section 1 ให้ส่งค่า key_differences เป็น [] (อาร์เรย์ว่าง) ห้าม hallucinate หรือเติมข้อมูลหลอก!
5. EVIDENCE GROUNDING: ข้อมูลใน video_a และ video_b ต้องมาจากเนื้อหาจริง หากฝั่งใดไม่ได้กล่าวถึงประเด็นนั้น ให้ระบุว่า "ไม่พบการกล่าวถึงประเด็นนี้ใน Video A" หรือ "ไม่พบการกล่าวถึงประเด็นนี้ใน Video B".

Return a SINGLE JSON object matching the schema below:

{{
  "comparison_overview": {{
    "summary": "Macro comparison overview synthesizing core differences and similarities",
    "focus_video_a": "Primary focus and premise of Video A",
    "focus_video_b": "Primary focus and premise of Video B",
    "target_audience_comparison": "Comparative target audience analysis"
  }},
  "topic_analysis": {{
    "video_a_topics": [
      {{
        "title": "Specific content-driven topic title in Video A (e.g. การปราบปรามธุรกิจรับจำนำรถผิดกฎหมาย)",
        "description": "Concise 1-2 line explanation of what Video A discusses"
      }}
    ],
    "video_b_topics": [
      {{
        "title": "Specific content-driven topic title in Video B (e.g. ปัญหาการดูแลบุตรพิการในครอบครัว)",
        "description": "Concise 1-2 line explanation of what Video B discusses"
      }}
    ],
    "key_differences": [
      {{
        "title": "Content-driven finding title derived from actual video content (e.g. แหล่งข้อมูลที่ใช้สนับสนุนเรื่องต่างกันอย่างชัดเจน)",
        "video_a": "Specific fact, data, or evidence from Video A (or 'ไม่พบการกล่าวถึงประเด็นนี้ใน Video A')",
        "video_b": "Specific fact, data, or evidence from Video B (or 'ไม่พบการกล่าวถึงประเด็นนี้ใน Video B')",
        "significance": "Short explanation of why this difference is meaningful or impacts overall interpretation"
      }}
    ]
  }},
  "viewpoint_relationships": [
    {{
      "topic": "Topic under analysis",
      "relationship_type": "supporting|different_view|contradicting",
      "summary": "Explanation of relationship between perspectives"
    }}
  ],
  "sentiment_comparison": {{
    "video_a_sentiment": "Tone summary for Video A",
    "video_b_sentiment": "Tone summary for Video B",
    "comparison_notes": "Comparative sentiment synthesis"
  }},
  "final_comparative_insight": {{
    "core_takeaway": "Primary key takeaway",
    "comparative_conclusion": "Executive comparative conclusion",
    "recommendation": "Actionable insight or recommendation"
  }}
}}

CRITICAL RULES FOR CONTENT-DRIVEN ANALYSIS & LANGUAGE:
1. อ่านเนื้อหาของ Video A ทั้งหมดก่อน แล้วระบุประเด็นสำคัญที่เกิดขึ้นจริงจากเนื้อหา โดยไม่กำหนดหมวดหมู่ล่วงหน้า
2. ทำแบบเดียวกันกับ Video B อย่างอิสระ ไม่จำเป็นที่ Video A และ Video B จะต้องมีจำนวนประเด็นเท่ากัน
3. ชื่อประเด็นต้องเฉพาะเจาะจงและบอกได้ทันทีว่าคลิปกำลังกล่าวถึงเรื่องอะไร
4. ห้ามใช้ชื่อหัวข้อทั่วไป เช่น "เนื้อหาหลัก", "ตัวละครหลัก", "ประเด็นทางกฎหมาย", "ประเด็นสำคัญ", "เหตุการณ์", "เรื่องทั่วไป", "สังคม", "บุคคล"
5. ห้ามสร้างประเด็นหลอกเพื่อให้โครงสร้างครบ ให้ใช้ประเด็นที่มีอยู่จริงเท่านั้น (สูงสุดไม่เกิน 6 ประเด็นต่อวิดีโอ)
6. รวมหรือลบประเด็นที่ซ้ำซ้อนกันออก ให้เหลือเฉพาะประเด็นหลักที่แตกต่างกันชัดเจน
7. ห้ามสร้าง mandatory "ประเด็นร่วม" หรือ "ประเด็นเฉพาะ" ให้ความเหมือนหรือต่างแสดงใน "ความแตกต่างที่ชัดเจน" อย่างเป็นธรรมชาติ
8. 'relationship_type' in 'viewpoint_relationships' MUST BE EXACTLY ONE OF: 'supporting', 'different_view', or 'contradicting'.
9. ตอบผลการวิเคราะห์ทั้งหมดเป็นภาษาไทยเท่านั้น ห้ามสร้างคำอธิบาย บทสรุป หรือ synthesis เป็นภาษาอังกฤษ (ยกเว้นชื่อเฉพาะหรือศัพท์เทคนิค)
10. DO NOT translate authoritative transcript evidence or quotes. Transcript evidence text MUST remain in its original spoken language unchanged.
11. Output valid raw JSON only.
"""
        return prompt

    def run_comparison(
        self,
        snapshot_a: ComparisonVideoSnapshot,
        snapshot_b: ComparisonVideoSnapshot
    ) -> Tuple[Dict[str, Any], Dict[str, Any], str, float]:
        """
        Executes single-call structured AI comparison generation over snapshot_a and snapshot_b.
        Returns (result_dict, token_telemetry_dict, model_used, processing_seconds).
        """
        start_time = time.time()
        prompt = self.build_comparison_prompt(snapshot_a, snapshot_b)

        # Pre-compute deterministic keyword comparison
        det_keywords = extract_deterministic_keywords(snapshot_a, snapshot_b)

        last_exception = None
        for model_index, model_name in enumerate(self.models):
            if model_name in RESERVE_MODELS:
                logger.info(f"MODEL_RESERVE\nmodel={model_name}")
            for attempt in range(5):
                try:
                    logger.info(
                        f"MODEL_ATTEMPT\nmodel={model_name}\nattempt={attempt+1}/5"
                    )
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config={
                            "response_mime_type": "application/json",
                            "response_schema": ComparisonResultContract,
                            "temperature": 0.1,
                        }
                    )

                    proc_seconds = time.time() - start_time
                    add_response_telemetry(self.token_telemetry, "comparison", model_name, response)

                    raw_text = response.text or "{}"
                    raw_text_clean = raw_text.strip()
                    if raw_text_clean.startswith("```"):
                        lines = raw_text_clean.splitlines()
                        if lines[0].startswith("```"):
                            lines = lines[1:]
                        if lines and lines[-1].startswith("```"):
                            lines = lines[:-1]
                        raw_text_clean = "\n".join(lines).strip()

                    try:
                        parsed_json = json.loads(raw_text_clean)
                    except Exception as parse_err:
                        logger.warning(f"Failed to parse JSON output from {model_name}: {parse_err}. Retrying with repair...")
                        repaired = re.sub(r'[\r\n]+', ' ', raw_text_clean)
                        parsed_json = json.loads(repaired)

                    # Check output language consistency
                    violating_fields = validate_comparison_language(parsed_json)
                    if violating_fields:
                        logger.warning(
                            f"Language validation failed for fields: {violating_fields}. Executing bounded corrective retry..."
                        )
                        retry_prompt = prompt + (
                            f"\n\nCRITICAL FIX REQUIRED: The following analytical fields were generated in English instead of Thai: {', '.join(violating_fields)}. "
                            f"Re-generate ALL analytical prose, summaries, and synthesis in THAI. "
                            f"DO NOT translate segment evidence text or transcript quotes."
                        )
                        retry_response = self.client.models.generate_content(
                            model=model_name,
                            contents=retry_prompt,
                            config={
                                "response_mime_type": "application/json",
                                "response_schema": ComparisonResultContract,
                                "temperature": 0.1,
                            }
                        )
                        add_response_telemetry(self.token_telemetry, "comparison", model_name, retry_response)
                        retry_text = (retry_response.text or "{}").strip()
                        if retry_text.startswith("```"):
                            r_lines = retry_text.splitlines()
                            if r_lines[0].startswith("```"): r_lines = r_lines[1:]
                            if r_lines and r_lines[-1].startswith("```"): r_lines = r_lines[:-1]
                            retry_text = "\n".join(r_lines).strip()
                        parsed_json = json.loads(retry_text)

                        violating_still = validate_comparison_language(parsed_json)
                        if violating_still:
                            logger.error(f"Bounded corrective retry still contained non-Thai fields: {violating_still}")

                    # Overwrite keyword_comparison with deterministic calculation
                    parsed_json["keyword_comparison"] = det_keywords

                    # Perform evidence verification & post-processing
                    verified_json, evidence_counts = self.verify_and_clean_comparison(
                        parsed_json, snapshot_a, snapshot_b
                    )

                    return verified_json, self.token_telemetry, model_name, round(proc_seconds, 2)

                except Exception as e:
                    last_exception = e
                    if is_model_not_found_error(e):
                        logger.warning(
                            f"MODEL_UNAVAILABLE\nmodel={model_name}\nreason=MODEL_NOT_FOUND\naction=FAILOVER"
                        )
                        break
                    if not is_rate_limit_error(e):
                        raise
                    if is_hard_quota_error(e):
                        break
                    if attempt < 4:
                        wait_seconds, wait_source = get_rate_limit_wait(e, attempt)
                        logger.warning(
                            f"RATE_LIMIT\nmodel={model_name}\nattempt={attempt+1}/5"
                            f"\nwait={wait_seconds:.3f}\nsource={wait_source}"
                        )
                        time.sleep(wait_seconds)

            if model_index + 1 < len(self.models):
                failover_reason = "MODEL_NOT_FOUND" if last_exception and is_model_not_found_error(last_exception) else "RATE_LIMITED"
                logger.warning(
                    f"MODEL_FAILOVER\nfrom={model_name}\nto={self.models[model_index + 1]}\nreason={failover_reason}"
                )

        if last_exception and is_rate_limit_error(last_exception):
            raise ComparisonEngineQuotaError(f"RATE_LIMITED: {RATE_LIMITED_MESSAGE}")

        raise ComparisonEngineError(f"Video comparison AI generation failed across all models: {last_exception}")

    def verify_and_clean_comparison(
        self,
        result_dict: Dict[str, Any],
        snapshot_a: ComparisonVideoSnapshot,
        snapshot_b: ComparisonVideoSnapshot
    ) -> Tuple[Dict[str, Any], Dict[str, int]]:
        """
        Validates evidence references in the AI result against authoritative transcript segments.
        Resolves authoritative transcript text, downgrades invalid relationship types,
        and returns updated result_dict and evidence counts.
        """
        counts = {"VERIFIED": 0, "PARTIALLY_VERIFIED": 0, "UNVERIFIED": 0}

        def _verify_ev(ev_data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            if not ev_data or not isinstance(ev_data, dict):
                return None
            res = validate_evidence(ev_data, snapshot_a, snapshot_b)
            status = res.get("status", EvidenceVerificationStatus.UNVERIFIED.value)
            counts[status] = counts.get(status, 0) + 1

            if status in {EvidenceVerificationStatus.VERIFIED.value, EvidenceVerificationStatus.PARTIALLY_VERIFIED.value}:
                cleaned = ev_data.copy()
                cleaned["verification_status"] = status
                if res.get("resolved_text"):
                    cleaned["resolved_transcript_text"] = res["resolved_text"]
                return cleaned
            else:
                # Unverified evidence: return cleaned evidence marked UNVERIFIED without fake quotes
                cleaned = ev_data.copy()
                cleaned["verification_status"] = EvidenceVerificationStatus.UNVERIFIED.value
                cleaned["resolved_transcript_text"] = None
                return cleaned

        cleaned_result = json.loads(json.dumps(result_dict))

        # 1. shared_topics
        for item in cleaned_result.get("shared_topics", []):
            if isinstance(item, dict):
                item["evidence_a"] = _verify_ev(item.get("evidence_a"))
                item["evidence_b"] = _verify_ev(item.get("evidence_b"))

        # 2. key_differences
        for item in cleaned_result.get("key_differences", []):
            if isinstance(item, dict):
                item["evidence_a"] = _verify_ev(item.get("evidence_a"))
                item["evidence_b"] = _verify_ev(item.get("evidence_b"))

        # 3. unique_topics
        unique = cleaned_result.get("unique_topics", {})
        if isinstance(unique, dict):
            for item in unique.get("video_a", []):
                if isinstance(item, dict):
                    item["evidence"] = _verify_ev(item.get("evidence"))
            for item in unique.get("video_b", []):
                if isinstance(item, dict):
                    item["evidence"] = _verify_ev(item.get("evidence"))

        # 4. viewpoint_relationships
        for item in cleaned_result.get("viewpoint_relationships", []):
            if isinstance(item, dict):
                rel_type = str(item.get("relationship_type", "")).lower()
                if rel_type not in ALLOWED_RELATIONSHIP_TYPES:
                    item["relationship_type"] = "different_view"
                item["evidence_a"] = _verify_ev(item.get("evidence_a"))
                item["evidence_b"] = _verify_ev(item.get("evidence_b"))

        # 5. evidence_timeline
        for item in cleaned_result.get("evidence_timeline", []):
            if isinstance(item, dict):
                item["evidence_a"] = _verify_ev(item.get("evidence_a"))
                item["evidence_b"] = _verify_ev(item.get("evidence_b"))

        # 6. topic_analysis (Content-driven sanitization)
        if "topic_analysis" in cleaned_result and isinstance(cleaned_result["topic_analysis"], dict):
            cleaned_result["topic_analysis"] = sanitize_topic_analysis(cleaned_result["topic_analysis"])

        return cleaned_result, counts
