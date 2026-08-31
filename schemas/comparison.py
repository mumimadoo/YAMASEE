from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

class EvidenceVerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    UNVERIFIED = "UNVERIFIED"

class ComparisonTranscriptSegment(BaseModel):
    segment_id: int = Field(description="Preserved index or original integer segment ID")
    start: float = Field(description="Segment start time in seconds")
    end: float = Field(description="Segment end time in seconds")
    label: str = Field(description="Formatted timestamp label, e.g. [00:01]")
    text: str = Field(description="Authoritative speech segment text")
    speaker: Optional[str] = Field(default=None, description="Optional speaker identifier")

class ComparisonVideoSnapshot(BaseModel):
    analysis_id: str = Field(description="Public ID of original AnalysisRecord")
    job_id: Optional[str] = Field(default=None, description="Job ID if available")
    source_type: str = Field(description="Video source type (youtube, tiktok, mp4, etc.)")
    source_url: Optional[str] = Field(default=None, description="Original source URL")
    title: str = Field(description="Sanitized display title or original filename")
    duration_seconds: float = Field(description="Video duration in seconds")
    thumbnail: Optional[str] = Field(default=None, description="Thumbnail URL if available")
    analyzed_at: str = Field(description="ISO timestamp when analysis completed")
    model_used: Optional[str] = Field(default=None, description="Model used for initial analysis")
    transcript: List[ComparisonTranscriptSegment] = Field(
        description="Normalized speech segments excluding failed segments"
    )
    existing_analysis: Dict[str, Any] = Field(
        description="Normalized output dictionary of existing analysis modules"
    )
    fingerprint: str = Field(description="Lightweight input hash for staleness checking")

class EvidenceReference(BaseModel):
    video: Literal["A", "B"] = Field(description="Refers to Video A or Video B")
    segment_id: int = Field(description="Authoritative segment ID in the transcript")
    start: float = Field(description="Claim start timestamp in seconds")
    end: float = Field(description="Claim end timestamp in seconds")
    timestamp: str = Field(description="Formatted human timestamp e.g. 03:12")

class VerifiedClaim(BaseModel):
    claim: str = Field(description="Statement or claim made by AI")
    evidence: Optional[EvidenceReference] = Field(default=None, description="Pointer to real transcript segment")
    verification_status: EvidenceVerificationStatus = Field(
        default=EvidenceVerificationStatus.UNVERIFIED,
        description="Backend verification status against real transcript text"
    )
    resolved_transcript_text: Optional[str] = Field(
        default=None,
        description="Resolved authoritative transcript segment text from snapshot"
    )

# ---------------------------------------------------------
# Phase 5 Restructured 6-Section Contract
# ---------------------------------------------------------

# 01 comparison_overview
class ComparisonOverview(BaseModel):
    summary: str = Field(description="Macro comparative summary overview of both videos")
    focus_video_a: str = Field(description="Main focus/premise of Video A")
    focus_video_b: str = Field(description="Main focus/premise of Video B")
    target_audience_comparison: Optional[str] = Field(default=None, description="Audience comparison")

# 02 topic_analysis (Content-Driven Section 2)
class ContentDrivenTopicItem(BaseModel):
    title: str = Field(description="Specific topic title describing what the video actually discusses")
    description: str = Field(description="Concise 1-2 line explanation of this topic in the video")

class ClearDifferenceItem(BaseModel):
    title: str = Field(description="Title of Finding discovered from actual video content")
    video_a: Optional[str] = Field(default=None, description="Fact, data, or point in Video A related to this finding")
    video_b: Optional[str] = Field(default=None, description="Fact, data, or point in Video B related to this finding")
    significance: Optional[str] = Field(default=None, description="Short explanation of why this difference is meaningful or impacts overall interpretation")
    description: Optional[str] = Field(default=None, description="Legacy comparative description for backward compatibility")

class ContentDrivenTopicAnalysis(BaseModel):
    video_a_topics: List[ContentDrivenTopicItem] = Field(default_factory=list, description="3-5 important topics actually present in Video A")
    video_b_topics: List[ContentDrivenTopicItem] = Field(default_factory=list, description="3-5 important topics actually present in Video B")
    key_differences: List[ClearDifferenceItem] = Field(default_factory=list, description="2-4 clearest meaningful differences derived from discovered topics")

# Legacy 02 comparison_topics (Unified Section 2)
class UnifiedComparisonTopic(BaseModel):
    topic: str = Field(description="Title of comparison topic")
    category: Literal["shared", "difference", "unique_a", "unique_b"] = Field(
        description="Relationship category: 'shared' (both videos), 'difference' (contrast), 'unique_a' (only Video A), 'unique_b' (only Video B)"
    )
    description_a: str = Field(description="Concise perspective or stance for Video A")
    description_b: str = Field(description="Concise perspective or stance for Video B")

# Legacy sub-section models retained for backward compatibility with old cached JSON records
class SharedTopic(BaseModel):
    topic: str = Field(description="Shared topic name")
    description_a: str = Field(description="How Video A addresses this topic")
    description_b: str = Field(description="How Video B addresses this topic")
    evidence_a: Optional[EvidenceReference] = Field(default=None)
    evidence_b: Optional[EvidenceReference] = Field(default=None)

class KeyDifference(BaseModel):
    dimension: str = Field(description="Dimension of contrast e.g. Perspective, Method, Conclusion")
    video_a_perspective: str = Field(description="Video A's stance/perspective")
    video_b_perspective: str = Field(description="Video B's stance/perspective")
    significance: str = Field(description="Why this difference matters")
    evidence_a: Optional[EvidenceReference] = Field(default=None)
    evidence_b: Optional[EvidenceReference] = Field(default=None)

class UniqueTopicItem(BaseModel):
    topic: str
    description: str
    evidence: Optional[EvidenceReference] = Field(default=None)

class UniqueTopics(BaseModel):
    video_a: List[UniqueTopicItem] = Field(default_factory=list, description="Topics unique to Video A")
    video_b: List[UniqueTopicItem] = Field(default_factory=list, description="Topics unique to Video B")

# 03 viewpoint_relationships
class ViewpointRelationship(BaseModel):
    topic: str = Field(description="Topic under analysis")
    relationship_type: Literal["supporting", "different_view", "contradicting"] = Field(
        description="Cross-video relationship category"
    )
    summary: str = Field(description="Explanation of relationship between viewpoints")
    evidence_a: Optional[EvidenceReference] = Field(default=None)
    evidence_b: Optional[EvidenceReference] = Field(default=None)

# Legacy keyword comparison model
class KeywordComparison(BaseModel):
    video_a_only: List[str] = Field(default_factory=list, description="Keywords unique to Video A")
    shared: List[str] = Field(default_factory=list, description="Keywords shared by both videos")
    video_b_only: List[str] = Field(default_factory=list, description="Keywords unique to Video B")

# 05 sentiment_comparison
class SentimentComparison(BaseModel):
    video_a_sentiment: str = Field(description="Dominant tone and emotional style of Video A")
    video_b_sentiment: str = Field(description="Dominant tone and emotional style of Video B")
    comparison_notes: str = Field(description="Comparative sentiment synthesis")

# Legacy evidence timeline item model
class EvidenceTimelineItem(BaseModel):
    topic: str = Field(description="Topic or comparison focal point")
    time_range_a: str = Field(description="Time range in Video A e.g. 01:20 - 02:15")
    time_range_b: str = Field(description="Time range in Video B e.g. 05:10 - 06:05")
    comparison_point: str = Field(description="Summary of comparative observation across timelines")
    evidence_a: Optional[EvidenceReference] = Field(default=None)
    evidence_b: Optional[EvidenceReference] = Field(default=None)

# 06 final_comparative_insight
class FinalComparativeInsight(BaseModel):
    core_takeaway: str = Field(description="Primary takeaway from comparing both videos")
    comparative_conclusion: str = Field(description="Executive comparative conclusion")
    recommendation: Optional[str] = Field(default=None, description="Contextual recommendation or next steps")

class ComparisonResultContract(BaseModel):
    comparison_overview: ComparisonOverview
    topic_analysis: Optional[ContentDrivenTopicAnalysis] = Field(
        default=None,
        description="Content-driven topic discovery and derived clear differences"
    )
    comparison_topics: List[UnifiedComparisonTopic] = Field(default_factory=list, description="Legacy major comparison topics")
    viewpoint_relationships: List[ViewpointRelationship] = Field(default_factory=list)
    sentiment_comparison: SentimentComparison
    final_comparative_insight: FinalComparativeInsight
    # Optional legacy fields for backward compatibility
    shared_topics: Optional[List[SharedTopic]] = Field(default_factory=list)
    key_differences: Optional[List[KeyDifference]] = Field(default_factory=list)
    unique_topics: Optional[UniqueTopics] = Field(default_factory=UniqueTopics)
    keyword_comparison: Optional[KeywordComparison] = None
    evidence_timeline: Optional[List[EvidenceTimelineItem]] = Field(default_factory=list)

# Candidate Selection Schemas
class CandidateVideoItem(BaseModel):
    public_id: str
    analysis_id: Optional[str] = None
    display_title: str
    source_type: str
    source_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    thumbnail_url: Optional[str] = None
    completed_at: Optional[str] = None
    segment_count: int

class CandidateVideosResponse(BaseModel):
    items: List[CandidateVideoItem]
    total: int
    page: int
    page_size: int
    total_pages: int

class ComparisonRequest(BaseModel):
    analysis_id_a: str
    analysis_id_b: str
    comparison_model: Optional[str] = Field(default="gemini-2.5-flash", description="User-selected comparison model")

class EvidenceValidationRequest(BaseModel):
    evidence: EvidenceReference
    snapshot_a: ComparisonVideoSnapshot
    snapshot_b: ComparisonVideoSnapshot

class Phase2InputPreparationResponse(BaseModel):
    snapshot_a_char_count: int
    snapshot_b_char_count: int
    combined_char_count: int
    estimated_transcript_tokens: int
    gemini_context_safe: bool
    prompt_preview: str

class ComparisonSideStateInput(BaseModel):
    state: Optional[str] = Field(default="UNRESOLVED", description="Video cost state: HISTORY_REUSE, CACHE_REUSE, ALREADY_READY, NEW_ANALYSIS_REQUIRED, UNRESOLVED")
    duration_seconds: Optional[float] = Field(default=None, description="Video duration in seconds")
    selected_model: Optional[str] = Field(default="gemini-3.5-flash", description="Model selected for single-video analysis")
    analysis_id: Optional[str] = Field(default=None, description="Analysis public ID if history/cache item")
    url: Optional[str] = Field(default=None, description="Source URL if YouTube/TikTok")

class ComparisonPreRunEstimateRequest(BaseModel):
    video_a: Optional[ComparisonSideStateInput] = Field(default_factory=ComparisonSideStateInput)
    video_b: Optional[ComparisonSideStateInput] = Field(default_factory=ComparisonSideStateInput)
    comparison_model: Optional[str] = Field(default="gemini-2.5-flash", description="Model selected for comparison engine")
    exact_comparison_cached: Optional[bool] = Field(default=False, description="Explicit exact comparison cache hit override")
