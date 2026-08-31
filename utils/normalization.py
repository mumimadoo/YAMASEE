import math
import re
from typing import Any, Dict, List, Optional, Tuple

def parse_time_string_to_seconds(value: str) -> Optional[float]:
    if not isinstance(value, str):
        return None
    val = value.strip().replace("[", "").replace("]", "")
    if "speaker" in val.lower():
        return None
    # Split by ':'
    parts = val.split(":")
    try:
        parts = [float(p) for p in parts]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        elif len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    except ValueError:
        pass
    return None

def format_seconds_to_time(seconds: float) -> str:
    if seconds is None or seconds < 0:
        seconds = 0.0
    total_sec = int(round(seconds))
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def format_time_range(start: Optional[float], end: Optional[float]) -> str:
    if start is None and end is None:
        return ""
    start_str = format_seconds_to_time(start) if start is not None else "00:00"
    end_str = format_seconds_to_time(end) if end is not None else "00:00"
    return f"{start_str} - {end_str}"

def extract_segment_timestamps(segment: dict) -> Tuple[Optional[float], Optional[float]]:
    start = None
    end = None
    
    # Try start variants
    for key in ["start", "start_time", "start_seconds"]:
        if key in segment and segment[key] is not None:
            try:
                start = float(segment[key])
                break
            except (ValueError, TypeError):
                pass
                
    # Try end variants
    for key in ["end", "end_time", "end_seconds"]:
        if key in segment and segment[key] is not None:
            try:
                end = float(segment[key])
                break
            except (ValueError, TypeError):
                pass
                
    # Try timestamp/time variants (e.g. if start is still None)
    if start is None:
        for key in ["time", "timestamp"]:
            if key in segment and segment[key] is not None:
                val = segment[key]
                if isinstance(val, (int, float)):
                    start = float(val)
                elif isinstance(val, str):
                    parsed = parse_time_string_to_seconds(val)
                    if parsed is not None:
                        start = parsed
                break
                
    return start, end

def format_duration_thai(seconds: float) -> str:
    if seconds is None or seconds <= 0:
        return "0 นาที"
    
    total_seconds = int(round(seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    
    parts = []
    if hours > 0:
        parts.append(f"{hours} ชั่วโมง")
    if minutes > 0:
        parts.append(f"{minutes} นาที")
    if secs > 0 or not parts:
        parts.append(f"{secs} วินาที")
        
    return " ".join(parts)

def normalize_duration_seconds(duration_raw, timeline=None) -> float:
    # If duration_raw is numeric
    if isinstance(duration_raw, (int, float)):
        if duration_raw > 0:
            return float(duration_raw)
    
    # If duration_raw is a string
    if isinstance(duration_raw, str):
        val = duration_raw.strip()
        if "speaker" in val.lower():
            pass
        else:
            try:
                num = float(val)
                if num > 0:
                    return num
            except ValueError:
                pass
            
            parts = val.split(":")
            if len(parts) >= 2:
                try:
                    parts = [float(p) for p in parts]
                    if len(parts) == 2:
                        return parts[0] * 60 + parts[1]
                    elif len(parts) == 3:
                        return parts[0] * 3600 + parts[1] * 60 + parts[2]
                except ValueError:
                    pass
                    
            hours = 0.0
            minutes = 0.0
            seconds = 0.0
            
            hr_match = re.search(r'(\d+)\s*ชั่วโมง', val)
            min_match = re.search(r'(\d+)\s*นาที', val)
            sec_match = re.search(r'(\d+)\s*วินาที', val)
            
            if hr_match or min_match or sec_match:
                if hr_match:
                    hours = float(hr_match.group(1))
                if min_match:
                    minutes = float(min_match.group(1))
                if sec_match:
                    seconds = float(sec_match.group(1))
                total = hours * 3600 + minutes * 60 + seconds
                if total > 0:
                    return total

    # Fallback to timeline end time
    if timeline:
        for seg in reversed(timeline):
            _, end_val = extract_segment_timestamps(seg)
            if end_val is not None:
                try:
                    end_num = float(end_val)
                    if end_num > 0:
                        return end_num
                except ValueError:
                    pass
                    
    return 0.0

def normalize_communication_intelligence(data: dict) -> Tuple[list, Any]:
    analysis_list = []
    distribution = None
    
    timeline_keys = [
        "communication_analysis",
        "communication_intelligence",
        "communication_strategy",
        "strategy_timeline",
        "communication_timeline",
        "strategies",
        "sentiment_analysis",
        "sentiment_table"
    ]
    
    raw_timeline = None
    for key in timeline_keys:
        if key in data and data[key]:
            raw_timeline = data[key]
            break
            
    if isinstance(raw_timeline, list):
        for item in raw_timeline:
            if not isinstance(item, dict):
                continue
            
            # Extract time range
            time_range = item.get("time_range") or item.get("time") or item.get("label") or ""
            
            # Extract strategy
            strategy = (
                item.get("strategy") or 
                item.get("purpose") or 
                item.get("key_trigger") or 
                item.get("trigger") or 
                ""
            )
            
            # Extract emotion
            emotion = (
                item.get("emotion") or 
                item.get("sentiment") or 
                item.get("current_emotion") or 
                "เป็นกลาง"
            )
            
            time_range_str = str(time_range).strip()
            if time_range_str.startswith("[") and time_range_str.endswith("]"):
                time_range_str = time_range_str[1:-1]
                
            analysis_list.append({
                "time_range": time_range_str,
                "strategy": str(strategy),
                "emotion": str(emotion)
            })
            
    overview_keys = [
        "communication_distribution",
        "emotional_overview",
        "dominant_sentiment_summary",
        "dominant_sentiment"
    ]
    
    for key in overview_keys:
        if key in data and data[key]:
            distribution = data[key]
            break
            
    return analysis_list, distribution

def normalize_analysis_result(data: dict) -> dict:
    if not isinstance(data, dict):
        return {}
        
    analysis_keys = {
        "timeline", "summary", "telemetry", "keywords_chart", 
        "sentiment_table", "video_chapters", "communication_analysis",
        "communication_intelligence", "communication_strategy", 
        "strategy_timeline", "communication_timeline", "strategies",
        "sentiment_analysis", "dominant_sentiment_summary", "dominant_sentiment",
        "communication_distribution"
    }
    if data and not any(k in data for k in analysis_keys):
        return data
        
    normalized = data.copy()
    
    # 1. Normalize timeline
    timeline = normalized.get("timeline", [])
    normalized_timeline = []
    if isinstance(timeline, list):
        for item in timeline:
            if not isinstance(item, dict):
                continue
            norm_item = item.copy()
            start, end = extract_segment_timestamps(norm_item)
            if start is not None:
                norm_item["start"] = float(start)
            if end is not None:
                norm_item["end"] = float(end)
            
            # Ensure text is string
            if norm_item.get("status") == "failed":
                norm_item.pop("text", None)
            elif "text" in norm_item:
                norm_item["text"] = str(norm_item["text"])
            
            # Normalize label
            label = norm_item.get("label", "") or norm_item.get("time", "")
            if not label or "speaker" in str(label).lower():
                if start is not None:
                    label = f"[{format_seconds_to_time(start)}]"
            norm_item["label"] = str(label)
            norm_item["time"] = norm_item["label"]
            normalized_timeline.append(norm_item)
            
    normalized["timeline"] = normalized_timeline
    
    # 2. Normalize duration_seconds
    raw_duration = normalized.get("duration_seconds")
    if raw_duration is None:
        telemetry = normalized.get("telemetry", {})
        raw_duration = telemetry.get("duration")
        
    duration_seconds = normalize_duration_seconds(raw_duration, normalized_timeline)
    normalized["duration_seconds"] = duration_seconds
    
    # 3. Normalize telemetry metrics
    telemetry = normalized.get("telemetry", {}).copy()
    
    total_words = sum(len(item.get("text", "").split()) for item in normalized_timeline)
    total_sentences = sum(item.get("text", "").count(".") + item.get("text", "").count("?") + 1 for item in normalized_timeline)
    
    telemetry["duration"] = format_duration_thai(duration_seconds)
    
    duration_mins = (duration_seconds / 60.0) if duration_seconds > 0 else 1.0
    telemetry["wpm"] = f"{int(round(total_words / duration_mins))} คำ/นาที"
    telemetry["words"] = f"{total_words} คำ"
    telemetry["sentences"] = f"{total_sentences} ประโยค"
    
    if "topics" not in telemetry or not telemetry["topics"]:
        summary = normalized.get("summary", [])
        telemetry["topics"] = summary[0][:20] if summary else "General Analysis"
        
    normalized["telemetry"] = telemetry
    
    # 4. Normalize Module 6
    comm_analysis, comm_dist = normalize_communication_intelligence(normalized)
    normalized["communication_analysis"] = comm_analysis
    normalized["communication_distribution"] = comm_dist
    
    # 5. Compute canonical current_emotion
    current_emotion = normalized.get("current_emotion")
    if not current_emotion:
        if comm_analysis and isinstance(comm_analysis, list) and len(comm_analysis) > 0:
            first_seg = comm_analysis[0]
            if isinstance(first_seg, dict) and first_seg.get("emotion"):
                current_emotion = first_seg["emotion"]
                
    if not current_emotion:
        sent_table = normalized.get("sentiment_table", [])
        if sent_table and isinstance(sent_table, list) and len(sent_table) > 0:
            first_seg = sent_table[0]
            if isinstance(first_seg, dict) and first_seg.get("sentiment"):
                current_emotion = first_seg["sentiment"]
                
    if not current_emotion:
        comm_dist_val = normalized.get("communication_distribution") or normalized.get("dominant_sentiment")
        if comm_dist_val and isinstance(comm_dist_val, str) and len(comm_dist_val.strip()) > 0 and len(comm_dist_val) < 50:
            current_emotion = comm_dist_val.strip()
            
    normalized["current_emotion"] = current_emotion
    
    return normalized
