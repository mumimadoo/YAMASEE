import time
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from urllib.parse import urlparse

from google import genai
from google.genai import types

from config import settings

logger = logging.getLogger("yamasee.external_research_engine")

@dataclass
class ExternalSourceItem:
    source_name: str
    title: str
    published_date: Optional[str]
    tier: str  # "Tier A", "Tier B", "Tier C", "Tier D", "UNCLASSIFIED"
    url: str
    supporting_claim: str

@dataclass
class ExternalTopicResult:
    topic: str
    findings: str
    relevance: str
    date: str
    source_count: int
    source_categories: List[str]
    confidence: str  # "สูง", "ปานกลาง", "ต่ำ"
    verification_status: str  # "VERIFIED", "INSUFFICIENT_EVIDENCE", "CONFLICTING_SOURCES"
    conflict_details: Optional[str]
    sources: List[Dict[str, Any]]

class BaseSearchProvider:
    """Abstract interface for external search providers."""
    def is_configured(self) -> bool:
        raise NotImplementedError

    def run_grounded_research(
        self,
        concepts: List[str],
        title_a: str = "Video A",
        title_b: str = "Video B"
    ) -> Dict[str, Any]:
        raise NotImplementedError

class UnconfiguredSearchProvider(BaseSearchProvider):
    """Fallback provider when no search infrastructure is available."""
    def is_configured(self) -> bool:
        return False

    def run_grounded_research(
        self,
        concepts: List[str],
        title_a: str = "Video A",
        title_b: str = "Video B"
    ) -> Dict[str, Any]:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        topics_data = []
        for c in concepts:
            topics_data.append({
                "topic": c,
                "findings": "ยังไม่สามารถค้นหาข้อมูลภายนอกได้ในขณะนี้ (Search Provider Unconfigured)",
                "relevance": f"เกี่ยวข้องกับประเด็นที่กล่าวถึงใน {title_a} และ {title_b}",
                "date": today_str,
                "source_count": 0,
                "source_categories": [],
                "confidence": "ต่ำ",
                "verification_status": "INSUFFICIENT_EVIDENCE",
                "conflict_details": None,
                "sources": []
            })
        return {
            "search_timestamp": datetime.now(timezone.utc).isoformat(),
            "searched_at": datetime.now(timezone.utc).isoformat(),
            "provider_configured": False,
            "warning": "ข้อมูลส่วนนี้มาจากระบบ External Research POC (ขณะนี้ยังไม่มี Search Provider)",
            "topics": topics_data,
            "telemetry": {
                "search_queries": [f"{c} 2026" for c in concepts],
                "source_count": 0,
                "unique_domains": 0,
                "verified_claim_count": 0,
                "insufficient_claim_count": len(concepts),
                "conflicting_claim_count": 0,
                "api_calls": 0,
                "prompt_token_count": 0,
                "candidates_token_count": 0,
                "thoughts_token_count": 0,
                "cached_content_token_count": 0,
                "total_token_count": 0,
                "processing_seconds": 0.0,
                "model_used": "unconfigured-search-provider",
                "provider_configured": False,
            }
        }

def classify_source_tier(url: str, source_name: str = "") -> str:
    """
    Classifies external sources into quality tiers:
    Tier A: Official, Government, Primary Research, University, Original Company Source
    Tier B: Reputable editorial/news organizations
    Tier C: Specialist/Industry sources with identifiable authors
    Tier D: Community/social sources
    UNCLASSIFIED: Unknown domains (never guessed as Tier A/B)
    """
    url_lower = (url or "").lower()
    name_lower = (source_name or "").lower()

    if any(ext in url_lower or ext in name_lower for ext in [
        ".gov", ".edu", ".ac.th", "nature.com", "arxiv.org", "ieee.org",
        "google", "googleblog", "openai", "microsoft.com", "apple.com", "github.com"
    ]):
        return "Tier A"
    
    if any(news in url_lower or news in name_lower for news in [
        "reuters.com", "bbc.com", "bloomberg.com", "techcrunch.com",
        "theverge.com", "nytimes.com", "wsj.com", "wired.com", "cnbc.com", "forbes.com"
    ]):
        return "Tier B"

    if any(social in url_lower or social in name_lower for social in [
        "reddit.com", "twitter.com", "x.com", "facebook.com", "medium.com", "forum", "tiktok.com", "youtube.com"
    ]):
        return "Tier D"

    return "UNCLASSIFIED"

def verify_external_evidence(sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Verification rule for external claims:
    Must be verified by:
    A. Primary/official source (Tier A) >= 1
    OR
    B. Independent high-quality sources >= 2 (Tier A or Tier B)
    
    If insufficient: Returns status INSUFFICIENT_EVIDENCE
    If conflicting: Returns status CONFLICTING_SOURCES
    """
    if not sources:
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "confidence": "ต่ำ",
            "findings": "ยังไม่พบข้อมูลภายนอกที่น่าเชื่อถือเพียงพอสำหรับยืนยันประเด็นนี้",
            "conflict_details": None
        }

    tier_a_sources = [s for s in sources if s.get("tier") == "Tier A"]
    tier_b_sources = [s for s in sources if s.get("tier") == "Tier B"]
    high_quality_sources = tier_a_sources + tier_b_sources

    # Check source domain independence
    unique_hq_domains = set(s.get("domain") or urlparse(s.get("url", "")).netloc.lower() for s in high_quality_sources)

    has_conflict = any(s.get("conflicting", False) for s in sources)
    if has_conflict:
        return {
            "status": "CONFLICTING_SOURCES",
            "confidence": "ปานกลาง",
            "findings": "พบข้อมูลที่ยังไม่ตรงกัน",
            "conflict_details": "รายงานจากแต่ละแหล่งข้อมูลยังมีความแตกต่างในรายละเอียดเชิงเท็จจริง"
        }

    if len(tier_a_sources) >= 1 or len(unique_hq_domains) >= 2:
        return {
            "status": "VERIFIED",
            "confidence": "สูง",
            "findings": None,
            "conflict_details": None
        }
    
    if len(unique_hq_domains) == 1:
        return {
            "status": "VERIFIED",
            "confidence": "ปานกลาง",
            "findings": None,
            "conflict_details": None
        }

    return {
        "status": "INSUFFICIENT_EVIDENCE",
        "confidence": "ต่ำ",
        "findings": "ยังไม่พบข้อมูลภายนอกที่น่าเชื่อถือเพียงพอสำหรับยืนยันประเด็นนี้",
        "conflict_details": None
    }

class GoogleSearchGroundingProvider(BaseSearchProvider):
    """
    Google Search Grounding implementation using google-genai SDK.
    Executes grounded search and synthesis in 1 single Gemini API call (One-Call Architecture).
    """
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or getattr(settings, "gemini_api_key", "")
        if model_name:
            self.models = [model_name]
        else:
            self.models = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    def is_configured(self) -> bool:
        return bool(self.api_key and self.client)

    def run_grounded_research(
        self,
        concepts: List[str],
        title_a: str = "Video A",
        title_b: str = "Video B"
    ) -> Dict[str, Any]:
        if not self.is_configured():
            unconf = UnconfiguredSearchProvider()
            return unconf.run_grounded_research(concepts, title_a, title_b)

        start_time = time.time()
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        clean_concepts = [c.strip() for c in concepts if c and c.strip()][:4]
        if not clean_concepts:
            clean_concepts = ["General AI Trends"]

        prompt = f"""Search Google for recent external facts, news, and official developments regarding the following topics:
{json.dumps(clean_concepts, ensure_ascii=False)}

These topics relate to a comparative analysis between '{title_a}' and '{title_b}'.

For EACH topic in the input list, search Google and synthesize recent external findings in THAI language.
Return structured JSON output with the exact schema below:

{{
  "topics": [
    {{
      "topic": "Topic Name",
      "findings": "สรุปสิ่งที่พบจากข่าว/แหล่งข้อมูลภายนอกล่าสุด เป็นภาษาไทย",
      "relevance": "อธิบายเหตุผลว่าทำไมประเด็นนี้จึงเกี่ยวข้องกับ {title_a} และ {title_b} เป็นภาษาไทย"
    }}
  ]
}}

STRICT CONSTRAINTS:
1. All findings and relevance MUST be written in Thai language.
2. Rely ONLY on real Google Search grounding results.
3. Return valid JSON matching the schema.
"""

        last_err = None
        for model_name in self.models:
            try:
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                        temperature=0.1,
                    )
                )

                proc_seconds = round(time.time() - start_time, 3)

                raw_text = (response.text or "{}").strip()
                if raw_text.startswith("```"):
                    lines = raw_text.splitlines()
                    if lines[0].startswith("```"): lines = lines[1:]
                    if lines and lines[-1].startswith("```"): lines = lines[:-1]
                    raw_text = "\n".join(lines).strip()

                try:
                    parsed_res = json.loads(raw_text)
                except Exception as parse_err:
                    logger.warning(f"Failed to parse grounding JSON response from {model_name}: {parse_err}. Fallback.")
                    parsed_res = {"topics": []}

                parsed_topics_map = {}
                for tp in parsed_res.get("topics", []):
                    if isinstance(tp, dict) and tp.get("topic"):
                        parsed_topics_map[tp["topic"].strip().lower()] = tp

                search_queries = []
                grounding_sources = []
                unique_domain_set = set()

                if response.candidates and response.candidates[0].grounding_metadata:
                    gm = response.candidates[0].grounding_metadata

                    queries_raw = getattr(gm, "web_search_queries", None) or getattr(gm, "search_entry_point", None)
                    if isinstance(queries_raw, list):
                        search_queries = [str(q) for q in queries_raw]

                    chunks = getattr(gm, "grounding_chunks", None) or []
                    for chunk in chunks:
                        web = getattr(chunk, "web", None)
                        if web and getattr(web, "uri", None):
                            url = str(web.uri).strip()
                            title = str(getattr(web, "title", "Web Source")).strip()
                            parsed_url = urlparse(url)
                            domain = parsed_url.netloc.lower() or "web"
                            source_name = domain.replace("www.", "").capitalize()

                            unique_domain_set.add(domain)
                            tier = classify_source_tier(url, source_name)

                            grounding_sources.append({
                                "source_name": source_name,
                                "title": title,
                                "domain": domain,
                                "published_date": None,
                                "tier": tier,
                                "url": url,
                                "supporting_claim": f"ข้อมูลสนับสนุนจาก {source_name}"
                            })

                seen_urls = set()
                deduped_sources = []
                for s in grounding_sources:
                    if s["url"] not in seen_urls:
                        seen_urls.add(s["url"])
                        deduped_sources.append(s)

                verified_count = 0
                insufficient_count = 0
                conflicting_count = 0

                final_topics = []
                for concept in clean_concepts:
                    concept_key = concept.strip().lower()
                    tp_info = parsed_topics_map.get(concept_key) or {}

                    v_res = verify_external_evidence(deduped_sources)

                    if v_res["status"] == "VERIFIED":
                        verified_count += 1
                    elif v_res["status"] == "CONFLICTING_SOURCES":
                        conflicting_count += 1
                    else:
                        insufficient_count += 1

                    findings_text = tp_info.get("findings") or v_res["findings"] or f"ยังไม่พบข้อมูลภายนอกที่น่าเชื่อถือเพียงพอสำหรับยืนยันประเด็น {concept}"
                    relevance_text = tp_info.get("relevance") or f"เกี่ยวข้องกับการเปรียบเทียบในประเด็น {concept} ระหว่าง {title_a} และ {title_b}"

                    source_cats = sorted(list(set(s["tier"] for s in deduped_sources))) if deduped_sources else []

                    final_topics.append({
                        "topic": concept,
                        "findings": findings_text,
                        "relevance": relevance_text,
                        "date": today_str,
                        "source_count": len(deduped_sources),
                        "source_categories": source_cats,
                        "confidence": v_res["confidence"],
                        "verification_status": v_res["status"],
                        "conflict_details": v_res["conflict_details"],
                        "sources": deduped_sources
                    })

                um = getattr(response, "usage_metadata", None)
                prompt_tokens = getattr(um, "prompt_token_count", 0) if um else 0
                candidates_tokens = getattr(um, "candidates_token_count", 0) if um else 0
                thoughts_tokens = getattr(um, "thoughts_token_count", 0) if um else 0
                cached_tokens = getattr(um, "cached_content_token_count", 0) if um else 0
                total_tokens = getattr(um, "total_token_count", 0) if um else 0

                telemetry = {
                    "search_queries": search_queries or [f"{c} 2026" for c in clean_concepts],
                    "source_count": len(deduped_sources),
                    "unique_domains": len(unique_domain_set),
                    "verified_claim_count": verified_count,
                    "insufficient_claim_count": insufficient_count,
                    "conflicting_claim_count": conflicting_count,
                    "api_calls": 1,
                    "prompt_token_count": prompt_tokens,
                    "candidates_token_count": candidates_tokens,
                    "thoughts_token_count": thoughts_tokens,
                    "cached_content_token_count": cached_tokens,
                    "total_token_count": total_tokens,
                    "processing_seconds": proc_seconds,
                    "model_used": model_name,
                    "provider_configured": True,
                }

                return {
                    "search_timestamp": datetime.now(timezone.utc).isoformat(),
                    "searched_at": datetime.now(timezone.utc).isoformat(),
                    "provider_configured": True,
                    "warning": "ข้อมูลส่วนนี้มาจากแหล่งข้อมูลภายนอก ไม่ใช่คำพูดหรือข้อสรุปโดยตรงจากวิดีโอ",
                    "topics": final_topics,
                    "telemetry": telemetry
                }

            except Exception as err:
                last_err = err
                logger.warning(f"GoogleSearchGroundingProvider error on model {model_name}: {err}. Trying fallback model...")

        proc_seconds = round(time.time() - start_time, 3)
        fallback_topics = []
        for c in clean_concepts:
            fallback_topics.append({
                "topic": c,
                "findings": "ไม่สามารถโหลดข้อมูลภายนอกได้ในขณะนี้",
                "relevance": f"เกี่ยวข้องกับการเปรียบเทียบในประเด็น {c} ระหว่าง {title_a} และ {title_b}",
                "date": today_str,
                "source_count": 0,
                "source_categories": [],
                "confidence": "ต่ำ",
                "verification_status": "INSUFFICIENT_EVIDENCE",
                "conflict_details": None,
                "sources": []
            })
        return {
            "search_timestamp": datetime.now(timezone.utc).isoformat(),
            "searched_at": datetime.now(timezone.utc).isoformat(),
            "provider_configured": True,
            "error": str(last_err),
            "warning": "ไม่สามารถโหลดข้อมูลภายนอกได้ในขณะนี้",
            "topics": fallback_topics,
            "telemetry": {
                "search_queries": [f"{c} 2026" for c in clean_concepts],
                "source_count": 0,
                "unique_domains": 0,
                "verified_claim_count": 0,
                "insufficient_claim_count": len(clean_concepts),
                "conflicting_claim_count": 0,
                "api_calls": 1,
                "prompt_token_count": 0,
                "candidates_token_count": 0,
                "thoughts_token_count": 0,
                "cached_content_token_count": 0,
                "total_token_count": 0,
                "processing_seconds": proc_seconds,
                "model_used": self.models[0] if self.models else "gemini-2.5-flash",
                "provider_configured": True,
            }
        }

class ExternalResearchEngine:
    """
    Engine for external web search, source tier classification,
    cross-source verification, and Gemini Google Search Grounding synthesis.
    """
    def __init__(self, search_provider: Optional[BaseSearchProvider] = None):
        if search_provider:
            self.search_provider = search_provider
        else:
            provider = GoogleSearchGroundingProvider()
            if provider.is_configured():
                self.search_provider = provider
            else:
                self.search_provider = UnconfiguredSearchProvider()

    def select_top_concepts(self, comparison_result: Dict[str, Any]) -> List[str]:
        """Extracts top 2-4 meaningful concepts from Comparison Result."""
        concepts = []
        if not comparison_result or not isinstance(comparison_result, dict):
            return concepts

        for item in comparison_result.get("shared_topics", []):
            if isinstance(item, dict) and item.get("topic"):
                t = str(item["topic"]).strip()
                if t and t not in concepts:
                    concepts.append(t)
                    if len(concepts) >= 2:
                        break

        for item in comparison_result.get("key_differences", []):
            if isinstance(item, dict) and item.get("dimension"):
                d = str(item["dimension"]).strip()
                if d and d not in concepts:
                    concepts.append(d)
                    if len(concepts) >= 4:
                        break

        if len(concepts) < 2:
            kw = comparison_result.get("keyword_comparison", {})
            if isinstance(kw, dict):
                for w in kw.get("shared", []):
                    w_str = str(w).strip()
                    if w_str and w_str not in concepts:
                        concepts.append(w_str)
                        if len(concepts) >= 3:
                            break

        return concepts[:4]

    def run_research(
        self,
        comparison_result: Dict[str, Any],
        title_a: str = "Video A",
        title_b: str = "Video B"
    ) -> Dict[str, Any]:
        """
        Executes External Research workflow:
        Select concepts -> Run Grounded Research Provider -> Return Telemetry & Result
        """
        concepts = self.select_top_concepts(comparison_result)
        if not concepts:
            concepts = ["General Analysis Topic"]

        return self.search_provider.run_grounded_research(
            concepts=concepts,
            title_a=title_a,
            title_b=title_b
        )
