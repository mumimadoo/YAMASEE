import os
import re
import json
import hashlib
import torch
import time
import subprocess
import psutil
import shutil
import random
from typing import Optional, Any
from utils.logger import get_logger
from utils.telemetry import create_empty_token_usage, add_response_telemetry
from utils.gemini_model_policy import (
    GeminiRateLimitedError,
    RESERVE_MODELS,
    build_model_chain,
    get_rate_limit_wait,
    is_hard_quota_error,
    is_model_not_found_error,
    is_rate_limit_error,
    validate_primary_model,
)
from google import genai
from faster_whisper import WhisperModel
# Helper exceptions and classifications
class SafetyBlockError(Exception):
    """Exception raised when the Gemini API response is blocked by safety filters."""
    pass

class BillingExhaustedError(Exception):
    """Exception raised when the Gemini API project billing is exhausted."""
    pass

class AllModelsExhaustedError(Exception):
    """Exception raised when all available Gemini models are exhausted."""
    pass

# Emergency Reserve Pool — hidden models activated automatically when all primary models are exhausted
EMERGENCY_RESERVE_POOL = list(RESERVE_MODELS)

def is_retryable_error(e: Exception) -> bool:
    if isinstance(e, SafetyBlockError):
        return False
    if isinstance(e, (TypeError, NameError, AttributeError, KeyError)):
        return False
    err_str = str(e).lower()
    if any(phrase in err_str for phrase in ["api_key", "invalid api key", "auth", "credentials", "unauthorized"]):
        return False
    return True

# Helper: robust Gemini JSON parsing & extraction
def extract_valid_json(text: Optional[str], expected_schema_type: str = "transcripts") -> Optional[Any]:
    if text is None:
        return None
    text = text.strip().lstrip('\ufeff')
    if not text:
        return None

    def validate_schema(data) -> bool:
        if expected_schema_type == "transcripts":
            if not isinstance(data, dict):
                return False
            transcripts = data.get("transcripts")
            if not isinstance(transcripts, list):
                return False
            for item in transcripts:
                if not isinstance(item, dict):
                    return False
                if "id" not in item:
                    return False
            return True
        elif expected_schema_type == "text":
            if not isinstance(data, dict):
                return False
            return "text" in data
        return True

    # 1. Try simple loads
    try:
        data = json.loads(text)
        if validate_schema(data):
            return data
    except Exception:
        pass

    # 2. Extract from code fence ```json ... ``` or ``` ... ```
    fence_match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        try:
            data = json.loads(fence_match.group(1).strip())
            if validate_schema(data):
                return data
        except Exception:
            pass

    # 3. Stack-based braces scanner to locate candidate JSON object/array
    candidates = []
    for i, char in enumerate(text):
        if char in ('{', '['):
            stack = []
            for j in range(i, len(text)):
                c = text[j]
                if c in ('{', '['):
                    stack.append(c)
                elif c == '}':
                    if stack and stack[-1] == '{':
                        stack.pop()
                    else:
                        break
                elif c == ']':
                    if stack and stack[-1] == '[':
                        stack.pop()
                    else:
                        break
                if not stack:
                    candidate_str = text[i:j+1]
                    candidates.append(candidate_str)
                    break
                    
    for cand in candidates:
        try:
            data = json.loads(cand)
            if validate_schema(data):
                return data
        except Exception:
            pass

    # 4. Fallback: Concatenated individual JSON objects
    if expected_schema_type == "transcripts":
        items = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict) and "id" in item and "text" in item:
                    items.append(item)
            except Exception:
                sub_match = re.search(r'(\{.*?\})', line)
                if sub_match:
                    try:
                        item = json.loads(sub_match.group(1))
                        if isinstance(item, dict) and "id" in item and "text" in item:
                            items.append(item)
                    except Exception:
                        pass
        if items:
            data = {"transcripts": items}
            if validate_schema(data):
                return data

    return None

def log_malformed_response(raw_text: Optional[str], logger):
    if raw_text is None:
        logger.warning("Malformed JSON response received: raw response text is None")
        return
    preview = raw_text[:500]
    sanitized_preview = re.sub(r'[a-zA-Z0-9]', 'x', preview)
    logger.warning(f"Malformed JSON response received. Sanitized preview: {sanitized_preview}")

# Helper: atomic checkpoint save
def save_checkpoint(job_work_dir: str, batch_index: int, segment_range: tuple, transcription_output: list, attempt_count: int, media_hash: str, model: str, successful_segment_ids: list = None, failed_segment_ids: list = None):
    if not job_work_dir:
        return
    checkpoint_dir = os.path.join(job_work_dir, "checkpoints")
    os.makedirs(checkpoint_dir, exist_ok=True)
    
    if successful_segment_ids is None:
        successful_segment_ids = [item["id"] for item in transcription_output]
    if failed_segment_ids is None:
        failed_segment_ids = []
        
    checkpoint_data = {
        "batch_index": batch_index,
        "segment_range": segment_range,
        "transcription_output": transcription_output,
        "attempt_count": attempt_count,
        "completed_timestamp": time.time(),
        "schema_version": "1.0",
        "media_hash": media_hash,
        "model": model,
        "successful_segment_ids": successful_segment_ids,
        "failed_segment_ids": failed_segment_ids
    }
    temp_path = os.path.join(checkpoint_dir, f"batch_{batch_index}.json.tmp")
    final_path = os.path.join(checkpoint_dir, f"batch_{batch_index}.json")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(checkpoint_data, f, ensure_ascii=False, indent=2)
    shutil.move(temp_path, final_path)

# Helper: resume checkpoint migration
def find_and_copy_existing_checkpoints(current_job_work_dir: str, media_hash: str, model: str):
    if not current_job_work_dir:
        return
    cache_base = os.path.dirname(current_job_work_dir)
    if not os.path.exists(cache_base):
        return
    for folder in os.listdir(cache_base):
        other_dir = os.path.join(cache_base, folder)
        if other_dir == current_job_work_dir or not os.path.isdir(other_dir):
            continue
        other_checkpoints_dir = os.path.join(other_dir, "checkpoints")
        if os.path.exists(other_checkpoints_dir):
            ckpt_files = [f for f in os.listdir(other_checkpoints_dir) if f.endswith(".json")]
            if ckpt_files:
                try:
                    with open(os.path.join(other_checkpoints_dir, ckpt_files[0]), "r", encoding="utf-8") as f:
                        data = json.load(f)
                    compatible_models = {"gemini-3.5-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash", "mock-model", model}
                    if data.get("media_hash") == media_hash and data.get("model") in compatible_models:
                        dest_checkpoints_dir = os.path.join(current_job_work_dir, "checkpoints")
                        shutil.copytree(other_checkpoints_dir, dest_checkpoints_dir, dirs_exist_ok=True)
                        break
                except Exception:
                    pass

class TranscriptEngine:
    def __init__(self, model_size: str = "default", preferred_model: str = None):
        api_key = os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=api_key, http_options={"timeout": 60000})
        self.logger = get_logger()
        self.model_pool = ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite"]
        self.preferred_model = validate_primary_model(preferred_model)
        self.selected_model = self.preferred_model
        self.active_model = self.preferred_model
        self.models_attempted = [self.preferred_model]
        self.models_exhausted = []
        self._gemini_calls_by_model = {}
        self.fallback_chain = self.get_failover_chain(self.selected_model)
        self._gemini_request_count = 0
        self._emergency_reserve_pool = list(EMERGENCY_RESERVE_POOL)
        self._emergency_reserve_used = False
        self._reserve_models_used = []
        self._rate_limited_models = []
        self._rate_limit_attempt_count = 0
        self.token_telemetry = create_empty_token_usage()
        
        # 🎯 [P2]: Transcription Mode Configuration
        self.transcription_mode = os.getenv("TRANSCRIPTION_MODE", "adaptive_batch").strip().lower()
        self.adaptive_max_seconds = 30.0
        self.adaptive_max_segments = 6
        
        # 🧪 TRANSCRIPT_BATCH_EXPERIMENT Feature Flag
        self.transcript_batch_experiment = (
            os.getenv("TRANSCRIPT_BATCH_EXPERIMENT", "false")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"}
        )
        if self.transcript_batch_experiment:
            self.adaptive_max_seconds = 60.0
            self.adaptive_max_segments = 10
            self.logger.info("🧪 [Experiment] TRANSCRIPT_BATCH_EXPERIMENT enabled: 60s / 10 segments")
        
        # 🎯 [P1-Addition]: Distribution Quality Check Configuration
        self.enable_distribution_check = (
            os.getenv("ENABLE_DISTRIBUTION_CHECK", "true")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"}
        )
        self.distribution_max_chars_per_second = float(
            os.getenv("DISTRIBUTION_MAX_CHARS_PER_SECOND", "22.0")
        )
        self.distribution_min_segment_seconds = float(
            os.getenv("DISTRIBUTION_MIN_SEGMENT_SECONDS", "1.0")
        )
        self.distribution_retry_split_enabled = (
            os.getenv("DISTRIBUTION_RETRY_SPLIT_ENABLED", "true")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"}
        )
        self.distribution_max_batch_share = float(
            os.getenv("DISTRIBUTION_MAX_BATCH_SHARE", "0.65")
        )
        
        # Whisper Setup
        self.whisper_model_name = None
        self.whisper_device = "cuda" if torch.cuda.is_available() else "cpu"
        self.whisper_compute_type = "float16" if self.whisper_device == "cuda" else "int8"
        self.model = self._load_whisper_model()
        
    def _load_whisper_model(self):
        models = ["tiny", "base"]
        for name in models:
            try:
                self.logger.info(f"Loading Whisper model: {name}")
                model = WhisperModel(name, device=self.whisper_device, compute_type=self.whisper_compute_type)
                self.whisper_model_name = name
                return model
            except Exception as e:
                self.logger.error(f"Error loading model {name}: {e}")
                continue
        raise RuntimeError("Failed to load any lightweight Whisper model.")

    def _is_thai_text(self, text: str) -> bool:
        for char in text:
            if '\u0e00' <= char <= '\u0e7f':
                return True
        return False

    def _check_language_sanity(self, results: list, batch: list, result_by_id: dict = None) -> list:
        # Collect texts from both current results and already transcribed segments
        all_texts = [res.get("text", "") for res in results]
        if result_by_id:
            all_texts.extend(result_by_id.values())
            
        thai_segments_count = sum(1 for t in all_texts if self._is_thai_text(t))
        total_texts = len(all_texts)
        
        is_predominantly_thai = (total_texts > 0 and (thai_segments_count / total_texts) >= 0.4)
        
        failed_ids = []
        if is_predominantly_thai:
            for res in results:
                text = res.get("text", "")
                seg_id = res.get("id")
                # Exclude spaces/punctuation, focus on alphabetical letters
                letters_only = "".join(c for c in text if c.isalpha())
                if len(letters_only) > 15 and not self._is_thai_text(text):
                    failed_ids.append(seg_id)
        return failed_ids

    def _find_suspicious_distribution(self, batch: list, accepted_by_id: dict) -> set:
        suspicious_ids = set()
        
        # Rule 2: Chars per second
        for segment in batch:
            seg_id = int(segment["id"])
            text = str(accepted_by_id.get(seg_id, "") or "").strip()

            if not text:
                continue

            duration = max(
                self.distribution_min_segment_seconds,
                float(segment["end"]) - float(segment["start"])
            )

            compact_text = re.sub(r"\s+", "", text)
            chars_per_second = len(compact_text) / duration

            if chars_per_second > self.distribution_max_chars_per_second:
                suspicious_ids.add(seg_id)
        
        # Rule 3: Batch share
        if len(batch) >= 3:
            total_chars = 0
            lengths = {}
            for segment in batch:
                seg_id = int(segment["id"])
                text = str(accepted_by_id.get(seg_id, "") or "").strip()
                compact_text = re.sub(r"\s+", "", text)
                lengths[seg_id] = len(compact_text)
                total_chars += len(compact_text)
            
            if total_chars > 0:
                for seg_id, length in lengths.items():
                    if length / total_chars > self.distribution_max_batch_share:
                        suspicious_ids.add(seg_id)
        
        return suspicious_ids

    def _normalize_batch_results(self, batch: list, batch_results: list) -> dict:
        expected_ids = {int(seg["id"]) for seg in batch}
        normalized = {}
        for res in batch_results:
            seg_id = self._normalize_transcript_id(res.get("id"))
            if seg_id in expected_ids:
                text = str(res.get("text", "") or "").strip()
                if text:
                    # Duplicate: Keep the first one as per current implementation
                    if seg_id not in normalized:
                        normalized[seg_id] = text
        return normalized
    def get_failover_chain(self, selected_model: str) -> list:
        return build_model_chain(selected_model)[:-len(RESERVE_MODELS)]

    def _get_full_failover_chain_with_reserve(self) -> list:
        """Returns the full failover chain including emergency reserve models.
        Primary chain first, then emergency reserve pool in fixed order."""
        return list(self.fallback_chain) + list(self._emergency_reserve_pool)

    def _counted_generate_content(self, **kwargs):
        self._gemini_request_count += 1
        model = kwargs.get("model")
        if model:
            self._gemini_calls_by_model[model] = self._gemini_calls_by_model.get(model, 0) + 1
        response = self.client.models.generate_content(**kwargs)
        add_response_telemetry(self.token_telemetry, "transcription", model, response)
        return response

    def transcribe_audio(self, audio_path: str, cache_dir: str = None, job_id: str = None, progress_callback = None, cancel_check_fn = None) -> dict:
        self._gemini_request_count = 0
        self.token_telemetry = create_empty_token_usage()
        if not cache_dir: cache_dir = os.path.dirname(audio_path)
        self.cache_dir = cache_dir
        
        # 🎯 [P1-3]: ใช้ hash จากเนื้อหาไฟล์จริง
        def hash_file_content(path):
            digest = hashlib.sha256()
            with open(path, "rb") as file:
                for block in iter(lambda: file.read(1024 * 1024), b""):
                    digest.update(block)
            return digest.hexdigest()[:16]

        audio_hash = hash_file_content(audio_path)
        
        # Resume migration check
        find_and_copy_existing_checkpoints(cache_dir, audio_hash, self.preferred_model)
        
        whisper_map, _ = self._get_whisper_map(audio_path, audio_hash, cache_dir)
        
        # 🎯 [P2]: รองรับโหมด adaptive_batch, single_vad, legacy
        if self.transcription_mode == "adaptive_batch":
            cleaned_timeline = self._transcribe_adaptive_batches(
                audio_path, whisper_map, self.preferred_model,
                job_id=job_id, progress_callback=progress_callback, cancel_check_fn=cancel_check_fn, audio_hash=audio_hash, job_work_dir=cache_dir
            )
        elif self.transcription_mode == "single_vad":
            cleaned_timeline = self._transcribe_single_vad_segments(
                audio_path, whisper_map, self.preferred_model,
                job_id=job_id, progress_callback=progress_callback, cancel_check_fn=cancel_check_fn
            )
        else:
            cleaned_timeline = self._gemini_transcribed_timeline(
                audio_path, whisper_map, self.preferred_model,
                job_id=job_id, progress_callback=progress_callback, cancel_check_fn=cancel_check_fn
            )
            
        validation_report = self.validate_timeline_integrity(cleaned_timeline, whisper_map)
        
        return {
            "timeline": cleaned_timeline,
            "metadata": {
                "text_source": "gemini_cleaned",
                "timing_source": "whisper_vad_timestamps",
                "whisper_model_used": self.whisper_model_name,
                "gemini_request_count": self._gemini_request_count,
                **validation_report
            }
        }

    # 🎯 [P2]: Adaptive Batch Building
    def _build_adaptive_batches(self, whisper_map):
        batches = []
        current_batch = []
        batch_start = None
        
        for segment in whisper_map:
            if not current_batch:
                current_batch.append(segment)
                batch_start = float(segment["start"])
                continue
            
            # Check constraints
            num_segments = len(current_batch) + 1
            duration = float(segment["end"]) - batch_start
            
            if num_segments <= self.adaptive_max_segments and duration <= self.adaptive_max_seconds:
                current_batch.append(segment)
            else:
                batches.append(current_batch)
                current_batch = [segment]
                batch_start = float(segment["start"])
                
        if current_batch:
            batches.append(current_batch)
        return batches

    # 🎯 [P2]: Adaptive Transcription
    def _transcribe_adaptive_batches(self, audio_path: str, whisper_map: list, preferred_model: str, job_id: str = None, progress_callback = None, cancel_check_fn = None, audio_hash: str = None, job_work_dir: str = None) -> list:
        start_time = time.time()
        batches = self._build_adaptive_batches(whisper_map)
        result_by_id = {}
        
        total_vad_segments = len(whisper_map)
        total_batches = len(batches)
        batch_success_segments = 0
        single_vad_fallback_segments = 0
        failed_segments = 0
        failed_segment_ids = set()
        dist_triggered = 0
        dist_retry_accepted = 0
        dist_retry_rejected = 0
        dist_extra_requests = 0
        
        # Load completed batches from checkpoints
        completed_checkpoints = {}
        if job_work_dir:
            checkpoint_dir = os.path.join(job_work_dir, "checkpoints")
            if os.path.exists(checkpoint_dir):
                for file in os.listdir(checkpoint_dir):
                    if file.endswith(".json") and file.startswith("batch_"):
                        try:
                            with open(os.path.join(checkpoint_dir, file), "r", encoding="utf-8") as f:
                                data = json.load(f)
                            idx = data["batch_index"]
                            completed_checkpoints[idx] = data
                        except Exception:
                            pass

        for i, batch in enumerate(batches):
            # Check if this batch is already completed in checkpoints
            if i in completed_checkpoints:
                self.logger.info(f"Skipping completed batch {i} (loaded from checkpoint)")
                checkpoint_data = completed_checkpoints[i]
                batch_failed_for_this_skipped_batch = set()
                for item in checkpoint_data["transcription_output"]:
                    if item.get("status") == "failed" or "text" not in item:
                        f_id = item["id"]
                        batch_failed_for_this_skipped_batch.add(f_id)
                        if f_id not in failed_segment_ids:
                            failed_segment_ids.add(f_id)
                            failed_segments += 1
                    else:
                        result_by_id[item["id"]] = item["text"]
                
                # Check for recorded failed segments in checkpoint
                saved_failed = checkpoint_data.get("failed_segment_ids", [])
                for f_id in saved_failed:
                    batch_failed_for_this_skipped_batch.add(f_id)
                    if f_id not in failed_segment_ids:
                        failed_segment_ids.add(f_id)
                        failed_segments += 1
                
                batch_success_segments += len(batch) - len(batch_failed_for_this_skipped_batch)
                
                # Report progress for skipped batch
                if progress_callback:
                    msg = f"กำลังถอดเสียงชุดที่ {i+1} จาก {total_batches} ประมวลผลแล้ว {batch_success_segments} จาก {total_vad_segments} ช่วงเสียง"
                    progress_callback(
                        batch_index=i+1,
                        total_batches=total_batches,
                        attempt=1,
                        completed_segs=batch_success_segments,
                        total_segs=total_vad_segments,
                        msg=msg
                    )
                continue

            self.logger.info(f"Adaptive batch start: batch_index={i}, start={batch[0]['start']}, end={batch[-1]['end']}, duration={float(batch[-1]['end']) - float(batch[0]['start'])}, segment_count={len(batch)}, expected_ids={[seg['id'] for seg in batch]}")
            
            # Transcription for batch with retries and cancellation check
            batch_start = float(batch[0]["start"])
            batch_end = float(batch[-1]["end"])
            duration = batch_end - batch_start
            
            success = False
            batch_results = []
            
            # Model failover retry loop for this batch
            # Build full chain: primary + emergency reserve
            full_chain = self._get_full_failover_chain_with_reserve()
            
            model_index = -1
            for idx, model in enumerate(full_chain):
                if model not in self.models_exhausted:
                    model_index = idx
                    break
            else:
                # All models (primary + reserve) exhausted!
                total_segs = len(whisper_map)
                completed_segs = len(result_by_id)
                pct = round((completed_segs / total_segs) * 100, 2) if total_segs > 0 else 0.0
                err_msg = (
                    "ไม่สามารถถอดความให้เสร็จสมบูรณ์ได้\n\n"
                    "โมเดล Gemini ที่สามารถใช้ได้ในขณะนี้ถูกจำกัดการใช้งานครบทั้งหมดแล้ว\n\n"
                    "ความคืบหน้าที่สำเร็จถูกบันทึกไว้แล้ว\n\n"
                    f"รายละเอียดความคืบหน้า:\n"
                    f"- ถอดความสำเร็จ: {completed_segs} จาก {total_segs} ช่วงเสียง ({pct}%)\n"
                    f"- โมเดลที่ถูกจำกัดการใช้งาน: {self.models_exhausted}"
                )
                if all(model in self._rate_limited_models for model in full_chain):
                    raise GeminiRateLimitedError(
                        selected_model=self.selected_model,
                        final_model=full_chain[-1],
                        attempted_models=list(full_chain),
                        attempt_count=self._rate_limit_attempt_count,
                        quota_type="hard_daily",
                    )
                raise AllModelsExhaustedError(err_msg)

            # Track if we're entering emergency reserve territory
            if model_index >= len(self.fallback_chain):
                if not self._emergency_reserve_used:
                    self._emergency_reserve_used = True
                    self.logger.warning(
                        f"PRIMARY_MODELS_EXHAUSTED: All primary models exhausted. "
                        f"Entering Emergency Reserve Pool. exhausted_models={self.models_exhausted}"
                    )

            audio_file_cache = {}
            while model_index < len(full_chain):
                current_model = full_chain[model_index]
                self.active_model = current_model
                
                if current_model in self.models_exhausted:
                    model_index += 1
                    continue
                
                if current_model not in self.models_attempted:
                    self.models_attempted.append(current_model)
                
                # Track emergency reserve model usage
                if current_model in self._emergency_reserve_pool and current_model not in self._reserve_models_used:
                    self._reserve_models_used.append(current_model)
                    self.logger.info(f"MODEL_RESERVE\nmodel={current_model}")
                    if not self._emergency_reserve_used:
                        self._emergency_reserve_used = True
                    self.logger.info(
                        f"EMERGENCY_RESERVE_ACTIVATED: Using reserve model {current_model}"
                    )
                
                max_attempts = 5
                model_failed = False
                immediate_failover = False
                
                for attempt in range(max_attempts):
                    # Check cancellation first
                    if cancel_check_fn:
                        cancel_check_fn()
                        
                    # Report progress
                    if progress_callback:
                        attempt_str = f" (ลองใหม่ครั้งที่ {attempt+1})" if attempt > 0 else ""
                        if current_model in self._emergency_reserve_pool:
                            reserve_str = f" | โมเดลหลักถูกจำกัดการใช้งาน ระบบกำลังใช้โมเดลสำรอง {current_model} เพื่อดำเนินการต่อ"
                        else:
                            reserve_str = ""
                        msg = f"กำลังถอดเสียงชุดที่ {i+1} จาก {total_batches}{attempt_str} ประมวลผลแล้ว {batch_success_segments} จาก {total_vad_segments} ช่วงเสียง{reserve_str}"
                        progress_callback(
                            batch_index=i+1,
                            total_batches=total_batches,
                            attempt=attempt+1,
                            completed_segs=batch_success_segments,
                            total_segs=total_vad_segments,
                            msg=msg
                        )
                    
                    try:
                        self.logger.info(f"MODEL_ATTEMPT\nmodel={current_model}\nattempt={attempt+1}/{max_attempts}")
                        batch_results = self._transcribe_one_batch(audio_path, batch, batch_start, duration, current_model, audio_file_cache)
                        
                        if not batch_results:
                            raise ValueError("Empty batch results returned")
                            
                        # Validate completeness
                        expected_ids = {int(seg["id"]) for seg in batch}
                        returned_ids = []
                        for res in batch_results:
                            if isinstance(res, dict) and "id" in res:
                                try:
                                    returned_ids.append(int(res["id"]))
                                except (ValueError, TypeError):
                                    pass
                                    
                        missing_ids = expected_ids - set(returned_ids)
                        
                        if self.transcript_batch_experiment:
                            self.logger.info(
                                f"🧪 [Completeness Check] Batch {i}: "
                                f"expected_ids={sorted(list(expected_ids))}, "
                                f"returned_ids={sorted(returned_ids)}, "
                                f"missing_ids={sorted(list(missing_ids))}"
                            )
                        
                        # Under experiment, completeness requires zero missing IDs
                        if self.transcript_batch_experiment and len(missing_ids) > 0:
                            raise ValueError(f"Incomplete batch: missing segments {sorted(list(missing_ids))}")
                            
                        success = True
                        break
                        
                    except Exception as e:
                        self.logger.error(f"Batch transcription attempt {attempt+1} failed with model {current_model}: {e}")
                        if is_model_not_found_error(e):
                            self.logger.warning(
                                f"MODEL_UNAVAILABLE\nmodel={current_model}\nreason=MODEL_NOT_FOUND\naction=FAILOVER"
                            )
                            if current_model not in self.models_exhausted:
                                self.models_exhausted.append(current_model)
                            immediate_failover = True
                            break
                        rate_limited = is_rate_limit_error(e)
                        if rate_limited:
                            self._rate_limit_attempt_count += 1
                        
                        # Check billing exhaustion
                        err_str = str(e).lower()
                        is_billing = any(phrase in err_str for phrase in [
                            "billing limit", "billing is not enabled", "prepaid credits depleted",
                            "prepaid credit depleted", "billing account", "billing_disabled", "billing not enabled"
                        ])
                        if is_billing:
                            raise BillingExhaustedError(f"Billing limit or credit exhausted: {e}")
                            
                        # Check daily quota exhaustion
                        is_daily = is_hard_quota_error(e) or any(phrase in err_str for phrase in [
                            "generaterequestsperdayperprojectpermodel", "daily limit", "daily quota", "daily_quota", "quota exceeded for the day"
                        ])
                        if is_daily:
                            self.logger.warning(f"Daily quota exhausted for model {current_model}. Failing over immediately.")
                            if current_model not in self.models_exhausted:
                                self.models_exhausted.append(current_model)
                            if current_model not in self._rate_limited_models:
                                self._rate_limited_models.append(current_model)
                            
                            next_model = None
                            for next_m in full_chain[model_index + 1:]:
                                if next_m not in self.models_exhausted:
                                    next_model = next_m
                                    break
                            
                            self.logger.info(
                                f"MODEL_FAILOVER:\n"
                                f"batch={i}\n"
                                f"from={current_model}\n"
                                f"to={next_model}\n"
                                f"failure_category=DAILY_MODEL_QUOTA_EXHAUSTED\n"
                                f"reason={e}"
                            )
                            immediate_failover = True
                            break # Break attempt loop to fail over immediately
                            
                        # If not daily limit, check if retryable error
                        if not is_retryable_error(e):
                            raise e
                            
                        # Bounded retry: if we are on the last attempt, fail over
                        if attempt == max_attempts - 1:
                            self.logger.warning(f"Bounded retry failed for model {current_model}. Failing over.")
                            if rate_limited:
                                if current_model not in self.models_exhausted:
                                    self.models_exhausted.append(current_model)
                                if current_model not in self._rate_limited_models:
                                    self._rate_limited_models.append(current_model)
                            
                            next_model = None
                            for next_m in full_chain[model_index + 1:]:
                                if next_m not in self.models_exhausted:
                                    next_model = next_m
                                    break
                                    
                            self.logger.info(
                                f"MODEL_FAILOVER:\n"
                                f"batch={i}\n"
                                f"from={current_model}\n"
                                f"to={next_model}\n"
                                f"failure_category=BOUNDED_RETRY_EXHAUSTED\n"
                                f"reason={e}"
                            )
                            model_failed = True
                            break
                            
                        # Bounded retry sleep/backoff
                        if is_rate_limit_error(e):
                            backoff, wait_source = get_rate_limit_wait(e, attempt)
                            self.logger.warning(
                                f"RATE_LIMIT\nmodel={current_model}\nattempt={attempt+1}/{max_attempts}"
                                f"\nwait={backoff:.3f}\nsource={wait_source}"
                            )
                        else:
                            backoff = 2.0 * (2 ** attempt) + random.uniform(0.0, 1.0)
                        time.sleep(backoff)
                
                # If we succeeded, break out of model failover loop
                if success:
                    break
                    
                # If we failed (either immediate or bounded retry exhausted), move to next model
                model_index += 1

            if not success and all(m in self.models_exhausted for m in full_chain):
                total_segs = len(whisper_map)
                completed_segs = len(result_by_id)
                pct = round((completed_segs / total_segs) * 100, 2) if total_segs > 0 else 0.0
                err_msg = (
                    "ไม่สามารถถอดความให้เสร็จสมบูรณ์ได้\n\n"
                    "โมเดล Gemini ที่สามารถใช้ได้ในขณะนี้ถูกจำกัดการใช้งานครบทั้งหมดแล้ว\n\n"
                    "ความคืบหน้าที่สำเร็จถูกบันทึกไว้แล้ว\n\n"
                    f"รายละเอียดความคืบหน้า:\n"
                    f"- ถอดความสำเร็จ: {completed_segs} จาก {total_segs} ช่วงเสียง ({pct}%)\n"
                    f"- โมเดลที่ถูกจำกัดการใช้งาน: {self.models_exhausted}"
                )
                if all(model in self._rate_limited_models for model in full_chain):
                    raise GeminiRateLimitedError(
                        selected_model=self.selected_model,
                        final_model=full_chain[-1],
                        attempted_models=list(full_chain),
                        attempt_count=self._rate_limit_attempt_count,
                        quota_type="hard_daily" if self._rate_limit_attempt_count == len(full_chain) else "temporary",
                    )
                raise AllModelsExhaustedError(err_msg)

            accepted_by_id = {}
            meta = getattr(self, "_last_call_metadata", {
                "candidate_count": 0,
                "finish_reason": "none",
                "safety_blocked": False,
                "response_text_present": False
            })
            self.logger.info(
                f"Batch transcription status: batch_index={i}, "
                f"attempt={attempt+1 if success else max_attempts}, "
                f"model={self.active_model}, "
                f"response_text_present={meta['response_text_present']}, "
                f"candidate_count={meta['candidate_count']}, "
                f"finish_reason={meta['finish_reason']}, "
                f"safety_blocked={meta['safety_blocked']}, "
                f"fallback_used={not success}"
            )

            expected_ids = {int(seg["id"]) for seg in batch}
            returned_ids = []
            if success and batch_results:
                for res in batch_results:
                    if isinstance(res, dict) and "id" in res:
                        try:
                            returned_ids.append(int(res["id"]))
                        except (ValueError, TypeError):
                            pass

            missing_ids = expected_ids - set(returned_ids)
            duplicate_ids = {x for x in returned_ids if returned_ids.count(x) > 1}
            unexpected_ids = set(returned_ids) - expected_ids

            if self.transcript_batch_experiment:
                self.logger.info(
                    f"🧪 [Completeness Check] Batch {i}: "
                    f"expected_ids={sorted(list(expected_ids))}, "
                    f"returned_ids={sorted(returned_ids)}, "
                    f"missing_ids={sorted(list(missing_ids))}, "
                    f"duplicate_ids={sorted(list(duplicate_ids))}, "
                    f"unexpected_ids={sorted(list(unexpected_ids))}"
                )

            # Determine if batch is accepted as complete
            if self.transcript_batch_experiment:
                is_complete = success and (len(missing_ids) == 0)
            else:
                is_complete = success

            if success:
                accepted_by_id = self._normalize_batch_results(batch, batch_results)
                # Apply language sanity check to detect obvious language shifts
                results_list = [{"id": k, "text": v} for k, v in accepted_by_id.items()]
                bad_seg_ids = self._check_language_sanity(results_list, batch, result_by_id)
                if bad_seg_ids:
                    self.logger.warning(f"Language sanity check failed for segment IDs: {bad_seg_ids}. Removing to trigger fallback.")
                    for b_id in bad_seg_ids:
                        accepted_by_id.pop(b_id, None)
            
            if self.enable_distribution_check and success:
                suspicious_ids = self._find_suspicious_distribution(batch, accepted_by_id)
                if suspicious_ids:
                    dist_triggered += 1
                    if len(batch) > 1 and self.distribution_retry_split_enabled:
                        mid = len(batch) // 2
                        left_batch = batch[:mid]
                        right_batch = batch[mid:]
                        
                        if cancel_check_fn: cancel_check_fn()
                        left_results = self._transcribe_one_batch(audio_path, left_batch, float(left_batch[0]["start"]), float(left_batch[-1]["end"]) - float(left_batch[0]["start"]), self.active_model)
                        
                        if cancel_check_fn: cancel_check_fn()
                        right_results = self._transcribe_one_batch(audio_path, right_batch, float(right_batch[0]["start"]), float(right_batch[-1]["end"]) - float(right_batch[0]["start"]), self.active_model)
                        dist_extra_requests += 2
                        
                        retry_by_id = {**self._normalize_batch_results(left_batch, left_results), **self._normalize_batch_results(right_batch, right_results)}
                        # Apply language sanity check to retry results
                        retry_results_list = [{"id": k, "text": v} for k, v in retry_by_id.items()]
                        bad_retry_ids = self._check_language_sanity(retry_results_list, batch, result_by_id)
                        if bad_retry_ids:
                            self.logger.warning(f"Language sanity check failed for retry segment IDs: {bad_retry_ids}. Removing.")
                            for b_id in bad_retry_ids:
                                retry_by_id.pop(b_id, None)
                                
                        suspicious_ids_after = self._find_suspicious_distribution(batch, retry_by_id)
                        original_total_chars = sum(len(re.sub(r"\s+", "", text)) for text in accepted_by_id.values())
                        retry_total_chars = sum(len(re.sub(r"\s+", "", text)) for text in retry_by_id.values())
                        
                        if (len(retry_by_id) >= len(accepted_by_id) and
                            len(suspicious_ids_after) < len(suspicious_ids) and
                            retry_total_chars >= original_total_chars * 0.90):
                            self.logger.info(f"Distribution retry result: batch_index={i}, decision=accepted_retry, original_suspicious_count={len(suspicious_ids)}, retry_suspicious_count={len(suspicious_ids_after)}, original_nonempty_ids={len(accepted_by_id)}, retry_nonempty_ids={len(retry_by_id)}, original_total_chars={original_total_chars}, retry_total_chars={retry_total_chars}")
                            accepted_by_id = retry_by_id
                            dist_retry_accepted += 1
                        else:
                            self.logger.warning(f"Distribution retry result: batch_index={i}, decision=kept_original, original_suspicious_count={len(suspicious_ids)}, retry_suspicious_count={len(suspicious_ids_after)}, original_nonempty_ids={len(accepted_by_id)}, retry_nonempty_ids={len(retry_by_id)}, original_total_chars={original_total_chars}, retry_total_chars={retry_total_chars}")
                            dist_retry_rejected += 1
                    else:
                        self.logger.warning(f"Distribution check triggered: batch_index={i}, segment_count={len(batch)}, suspicious_ids={suspicious_ids}")

            # Store results
            for seg_id, text in accepted_by_id.items():
                result_by_id[seg_id] = text
                batch_success_segments += 1
            
            expected_ids = {int(seg["id"]) for seg in batch}
            accepted_ids = set(accepted_by_id.keys())
            missing_ids = expected_ids - accepted_ids
            
            # Fallback for missing
            fallback_run_count = 0
            curr_batch_failed_ids = []
            for m_id in missing_ids:
                if cancel_check_fn: cancel_check_fn()
                seg = next(s for s in batch if s["id"] == m_id)
                self.logger.info(f"Fallback for missing segment_id={m_id}")
                
                success_fallback = False
                failed_models_for_this_segment = set()
                while True:
                    active_index = -1
                    for idx, model in enumerate(self._get_full_failover_chain_with_reserve()):
                        if model not in self.models_exhausted and model not in failed_models_for_this_segment:
                            self.active_model = model
                            active_index = idx
                            break
                    else:
                        break # No models available
                    
                    if self.active_model not in self.models_attempted:
                        self.models_attempted.append(self.active_model)
                    
                    # Track emergency reserve model usage in fallback
                    if self.active_model in self._emergency_reserve_pool and self.active_model not in self._reserve_models_used:
                        self._reserve_models_used.append(self.active_model)
                        if not self._emergency_reserve_used:
                            self._emergency_reserve_used = True
                        
                    try:
                        text = self._transcribe_one_vad_segment(
                            audio_path, seg["id"], float(seg["start"]), float(seg["end"]) - float(seg["start"]), self.active_model
                        )
                        if text:
                            # Apply language sanity check to fallback text
                            bad_fallback_ids = self._check_language_sanity([{"id": m_id, "text": text}], batch, result_by_id)
                            if bad_fallback_ids:
                                self.logger.warning(f"Language sanity check failed for fallback segment_id={m_id} using model {self.active_model}.")
                                failed_models_for_this_segment.add(self.active_model)
                                continue # Try next model
                            
                            result_by_id[m_id] = text
                            single_vad_fallback_segments += 1
                            fallback_run_count += 1
                            success_fallback = True
                        break
                    except Exception as e:
                        self.logger.error(f"Fallback transcription attempt failed with model {self.active_model}: {e}")
                        if is_model_not_found_error(e):
                            self.logger.warning(
                                f"MODEL_UNAVAILABLE\nmodel={self.active_model}\nreason=MODEL_NOT_FOUND\naction=FAILOVER"
                            )
                            if self.active_model not in self.models_exhausted:
                                self.models_exhausted.append(self.active_model)
                            continue
                        err_str = str(e).lower()
                        is_billing = any(phrase in err_str for phrase in [
                            "billing limit", "billing is not enabled", "prepaid credits depleted",
                            "prepaid credit depleted", "billing account", "billing_disabled", "billing not enabled"
                        ])
                        if is_billing:
                            raise BillingExhaustedError(f"Billing limit or credit exhausted: {e}")
                            
                        is_daily = any(phrase in err_str for phrase in [
                            "generaterequestsperdayperprojectpermodel", "daily limit", "daily quota", "daily_quota", "quota exceeded for the day"
                        ])
                        if is_daily:
                            self.logger.warning(f"Daily quota exhausted for model {self.active_model} during fallback. Failing over.")
                            if self.active_model not in self.models_exhausted:
                                self.models_exhausted.append(self.active_model)
                            continue # Try next model
                            
                        # For other exceptions in fallback, break and mark failed
                        break
                
                if not success_fallback:
                    failed_segments += 1
                    failed_segment_ids.add(m_id)
                    curr_batch_failed_ids.append(m_id)
                    self.logger.error(
                        f"Fallback transcription failed for segment_id={m_id}; "
                        "marking segment as failed."
                    )
            
            # Save batch checkpoint atomically only when completed successfully
            if success:
                checkpoint_output = []
                checkpoint_success_ids = []
                for k, v in accepted_by_id.items():
                    checkpoint_output.append({"id": k, "text": v})
                    checkpoint_success_ids.append(k)
                for m_id in missing_ids:
                    if m_id in result_by_id:  # succeeded in VAD fallback
                        checkpoint_output.append({"id": m_id, "text": result_by_id[m_id]})
                        checkpoint_success_ids.append(m_id)
                        
                save_checkpoint(
                    job_work_dir=job_work_dir,
                    batch_index=i,
                    segment_range=(batch[0]["id"], batch[-1]["id"]),
                    transcription_output=checkpoint_output,
                    attempt_count=attempt+1,
                    media_hash=audio_hash,
                    model=self.active_model,
                    successful_segment_ids=checkpoint_success_ids,
                    failed_segment_ids=curr_batch_failed_ids
                )
            
            # Detailed Logging Requirement
            self.logger.info(
                f"[Batch Optimization Experiment Log]\n"
                f"  batch_id: batch_{i}\n"
                f"  expected_count: {len(expected_ids)}\n"
                f"  returned_count: {len(returned_ids)}\n"
                f"  missing_count: {len(missing_ids)}\n"
                f"  duplicate_count: {len(duplicate_ids)}\n"
                f"  fallback_count: {fallback_run_count}\n"
                f"  failed_segment_ids: {sorted(list(failed_segment_ids & expected_ids))}"
            )
            
            # Diagnostics
            self.logger.info(f"Batch completed: accepted={len(accepted_ids)}, missing={len(missing_ids)}, fallback={fallback_run_count}, failed_segment_ids={sorted(list(failed_segment_ids & expected_ids))}, invalid=0, elapsed={time.time() - start_time:.2f}")

        elapsed = time.time() - start_time
        log_msg = f"Adaptive batch processing completed\ntotal_vad_segments={total_vad_segments}\ntotal_batches={total_batches}\nbatch_success_segments={batch_success_segments}\nsingle_vad_fallback_segments={single_vad_fallback_segments}\nfailed_segments={failed_segments}\nfailed_segment_ids={sorted(list(failed_segment_ids))}\ntotal_gemini_requests={self._gemini_request_count}\nelapsed_seconds={elapsed:.2f}"
        if self.enable_distribution_check:
            log_msg += f"\ndistribution_check_enabled={self.enable_distribution_check}\ndistribution_triggered_batches={dist_triggered}\ndistribution_retry_accepted_batches={dist_retry_accepted}\ndistribution_retry_rejected_batches={dist_retry_rejected}\ndistribution_extra_requests={dist_extra_requests}"
        self.logger.info(log_msg)
        
        # Log final model usage summary
        summary_lines = ["Final Gemini Model Usage Summary:"]
        summary_lines.append("  Primary Models:")
        for m in self.fallback_chain:
            count = self._gemini_calls_by_model.get(m, 0)
            summary_lines.append(f"    {m}: {count} requests")
        summary_lines.append(f"  Primary Models Exhausted: {'YES' if self._emergency_reserve_used else 'NO'}")
        summary_lines.append(f"  Emergency Reserve Used: {'YES' if self._emergency_reserve_used else 'NO'}")
        if self._emergency_reserve_used:
            summary_lines.append("  Reserve Models:")
            for m in self._emergency_reserve_pool:
                count = self._gemini_calls_by_model.get(m, 0)
                if count > 0 or m in self._reserve_models_used:
                    summary_lines.append(f"    {m}: {count} requests")
            summary_lines.append(f"  Reserve Models Used: {self._reserve_models_used}")
        self.logger.info("\n".join(summary_lines))
        
        # Build timeline based on whisper_map
        timeline = []
        for segment in whisper_map:
            seg_id = segment["id"]
            timeline_item = {
                "id": seg_id,
                "start": float(segment["start"]),
                "end": float(segment["end"]),
                "label": self.format_to_strategic_label(float(segment["start"])),
            }
            if seg_id in failed_segment_ids:
                # A failed fallback must never masquerade as an empty transcript.
                timeline_item["status"] = "failed"
            elif seg_id in result_by_id:
                timeline_item["status"] = "successful"
                timeline_item["text"] = result_by_id[seg_id]
            else:
                timeline_item["status"] = "missing"
            timeline.append(timeline_item)
        return sorted(timeline, key=lambda item: item["start"])

    # Transcribe one batch
    def _transcribe_one_batch(self, audio_path: str, batch: list, batch_start: float, duration: float, preferred_model: str, audio_file_cache: dict = None) -> list:
        if duration <= 0: return []
        
        # Check if we already have the uploaded file in cache
        audio_file = None
        if audio_file_cache is not None:
            audio_file = audio_file_cache.get(batch_start)
            
        temp_audio = f"temp_batch_{os.getpid()}_{batch_start}_{int(time.time())}.wav"
        if getattr(self, "cache_dir", None):
            temp_audio = os.path.join(self.cache_dir, temp_audio)
            
        try:
            if not audio_file:
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(max(0.0, batch_start)),
                    "-i", audio_path,
                    "-t", str(duration),
                    "-vn",
                    "-ac", "1",
                    "-ar", "16000",
                    "-c:a", "pcm_s16le",
                    temp_audio
                ]
                subprocess.run(cmd, check=True, capture_output=True)
                audio_file = self.client.files.upload(file=temp_audio)
                if audio_file_cache is not None:
                    audio_file_cache[batch_start] = audio_file
            
            vad_info = []
            for s in batch:
                vad_info.append({
                    "id": s["id"], 
                    "relative_start": float(s["start"]) - batch_start, 
                    "relative_end": float(s["end"]) - batch_start
                })
            
            prompt = (
                "You are a professional verbatim speech-to-text engine.\n"
                "Transcribe every spoken word in this audio segment exactly as heard.\n"
                "Rules:\n"
                "1. Return only valid JSON.\n"
                "2. Output format: {\"transcripts\": [{\"id\": int, \"text\": \"string\"}, ...]}\n"
                "3. Each ID in VAD IDs MUST be transcribed exactly once.\n"
                "4. No timestamps, no summaries, no IDs in output text.\n"
                "5. Preserve the ORIGINAL SPOKEN LANGUAGE exactly. NEVER translate the speech into another language.\n"
                "6. NEVER summarize or paraphrase. NEVER replace speech with background or world knowledge.\n"
                "7. NEVER invent names, events, facts, sentences, or missing speech. If speech is unclear, do not guess.\n"
                "8. Transcribe ONLY speech actually audible in the supplied audio corresponding to the given VAD timestamps.\n"
                f"VAD IDs: {json.dumps(vad_info)}"
            )
            
            response = self._counted_generate_content(
                model=preferred_model, 
                contents=[audio_file, prompt],
                config={"temperature": 0.0, "response_mime_type": "application/json"}
            )
            
            # Safe JSON extraction and validation
            data = extract_valid_json(response.text, "transcripts")
            if not data:
                log_malformed_response(response.text, self.logger)
                raise ValueError("Gemini returned invalid or malformed JSON")
                
            results = []
            expected_ids = {s["id"] for s in batch}
            for res in data.get("transcripts", []):
                seg_id = self._normalize_transcript_id(res.get("id"))
                if seg_id in expected_ids:
                    results.append({"id": seg_id, "text": str(res.get("text", "") or "").strip()})
            return results
        finally:
            if os.path.exists(temp_audio):
                try: os.remove(temp_audio)
                except Exception: pass

    # 🎯 [P1-Addition]: Single VAD Transcription Mode
    def _transcribe_single_vad_segments(self, audio_path: str, whisper_map: list, preferred_model: str) -> list:
        start_time = time.time()
        timeline = []
        successful_segments = 0
        failed_segments = 0
        
        for segment in whisper_map:
            seg_id = segment["id"]
            start = float(segment["start"])
            end = float(segment["end"])
            duration = max(0.0, end - start)
            
            text = self._transcribe_one_vad_segment(
                audio_path, seg_id, start, duration, preferred_model
            )
            
            if text:
                successful_segments += 1
            else:
                failed_segments += 1
                
            timeline.append({
                "id": seg_id,
                "start": start,
                "end": end,
                "label": self.format_to_strategic_label(start),
                "text": text
            })
        
        elapsed = time.time() - start_time
        self.logger.info(f"Single-VAD transcription completed\ntotal_segments={len(whisper_map)}\nsuccessful_segments={successful_segments}\nfailed_segments={failed_segments}\nintegrity_candidate_percent={self.validate_timeline_integrity(timeline, whisper_map)['integrity_percent']}\nelapsed_seconds={elapsed:.2f}")
        
        return sorted(timeline, key=lambda item: item["start"])

    # 🎯 [P1-Addition]: Transcribe one segment
    def _transcribe_one_vad_segment(self, audio_path: str, seg_id: int, start: float, duration: float, preferred_model: str) -> str:
        if duration <= 0:
            self.logger.warning(f"Segment duration {duration} is <= 0 for id={seg_id}")
            return ""

        temp_audio = f"temp_vad_{os.getpid()}_{seg_id}_{int(time.time())}.wav"
        if getattr(self, "cache_dir", None):
            temp_audio = os.path.join(self.cache_dir, temp_audio)
        
        try:
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(max(0.0, start)),
                "-i", audio_path,
                "-t", str(duration),
                "-vn",
                "-ac", "1",
                "-ar", "16000",
                "-c:a", "pcm_s16le",
                temp_audio
            ]
            subprocess.run(cmd, check=True, capture_output=True)

            prompt = """You are a professional verbatim speech-to-text engine.
Transcribe every spoken word in this audio segment exactly as heard.
Rules:
1. Return only valid JSON.
2. Output format: {"text": "transcribed speech"}
3. NEVER translate speech into another language. Preserve the ORIGINAL SPOKEN LANGUAGE exactly.
4. NEVER summarize or paraphrase. NEVER replace speech with background or world knowledge.
5. NEVER invent names, events, facts, sentences, or missing speech. If speech is unclear, do not guess.
6. Transcribe ONLY speech actually audible in the supplied audio segment.
7. For Thai, use natural Thai writing and do not insert spaces between every Thai word.
8. Do not return timestamps.
9. Do not return IDs.
10. If there is no intelligible speech, return {"text": ""}."""

            audio_file = None
            for attempt in range(3):
                try:
                    if not audio_file:
                        audio_file = self.client.files.upload(file=temp_audio)
                    # wait for file to be ready (optional but good practice)
                    time.sleep(1) 
                    response = self._counted_generate_content(
                        model=preferred_model, 
                        contents=[audio_file, prompt],
                        config={"temperature": 0.0, "response_mime_type": "application/json"}
                    )
                    
                    data = extract_valid_json(response.text, "text")
                    if not data:
                        log_malformed_response(response.text, self.logger)
                        raise ValueError("Gemini returned invalid or malformed JSON")
                    text = str(data.get("text", "") or "").strip()
                    return text
                except Exception as e:
                    self.logger.error(f"Single VAD transcription segment_id={seg_id} start={start} end={start+duration} attempt={attempt+1} model={preferred_model} failed: {e}")
                    if is_model_not_found_error(e):
                        self.logger.warning(
                            f"MODEL_UNAVAILABLE\nmodel={preferred_model}\nreason=MODEL_NOT_FOUND\naction=FAILOVER"
                        )
                        raise
                    if isinstance(e, (TypeError, NameError, AttributeError, KeyError)):
                        raise e
            
            return ""
        finally:
            if os.path.exists(temp_audio):
                try: os.remove(temp_audio)
                except Exception: pass

    # Legacy Fallback
    def _gemini_transcribed_timeline(self, audio_path, whisper_map, preferred_model) -> list:
        self.logger.info("Transcribing audio (5-min Chunking)...")
        
        # Map Whisper map to ID for lookups
        whisper_map_dict = {seg["id"]: seg for seg in whisper_map}
        timeline_results = {seg["id"]: {"text": "", "status": "missing"} for seg in whisper_map}
        
        chunks = []
        current_chunk = []
        current_chunk_start = None
        
        for seg in whisper_map:
            if current_chunk_start is None:
                current_chunk_start = float(seg["start"])
            
            # 5 min target, 6 min max
            if current_chunk and (float(seg["end"]) - current_chunk_start) > 360:
                chunks.append(current_chunk)
                current_chunk = []
                current_chunk_start = float(seg["start"])
                
            current_chunk.append(seg)
            if (float(seg["end"]) - current_chunk_start) >= 300:
                chunks.append(current_chunk)
                current_chunk = []
                current_chunk_start = None
        if current_chunk:
            chunks.append(current_chunk)
            
        for chunk in chunks:
            chunk_start = float(chunk[0]["start"])
            chunk_end = float(chunk[-1]["end"])
            
            # Log chunk diagnostics
            self.logger.info(f"Gemini chunk: start={chunk_start}, end={chunk_end}, IDs={chunk[0]['id']}-{chunk[-1]['id']}")
            
            transcription_result = self._gemini_chunk_transcribe(audio_path, chunk_start, chunk_end - chunk_start, chunk, preferred_model)
            
            for res in transcription_result:
                timeline_results[res["id"]] = {"text": res["text"], "status": "present"}
        
        final_timeline = []
        for seg_id, seg in whisper_map_dict.items():
            final_timeline.append({
                "id": seg_id,
                "start": seg["start"],
                "end": seg["end"],
                "label": self.format_to_strategic_label(float(seg["start"])),
                "text": timeline_results[seg_id]["text"]
            })
            
        return sorted(final_timeline, key=lambda x: x["start"])

    def _normalize_transcript_id(self, raw_id):
        if isinstance(raw_id, bool): return None
        if isinstance(raw_id, int): return raw_id
        if isinstance(raw_id, float): return int(raw_id) if raw_id.is_integer() else None
        if isinstance(raw_id, str):
            value = raw_id.strip()
            return int(value) if value.isdigit() else None
        if isinstance(raw_id, (list, tuple)):
            return self._normalize_transcript_id(raw_id[0]) if len(raw_id) == 1 else None
        return None

    def _gemini_chunk_transcribe(self, audio_path: str, start: float, duration: float, chunk: list, preferred_model: str) -> list:
        # 🎯 [P1-2]: ใช้ WAV re-encode แทน copy
        temp_audio = f"temp_chunk_{int(start)}.wav"
        if getattr(self, "cache_dir", None):
            temp_audio = os.path.join(self.cache_dir, temp_audio)

        try:
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(max(0.0, start)),
                "-i", audio_path,
                "-t", str(duration),
                "-vn",
                "-ac", "1",
                "-ar", "16000",
                "-c:a", "pcm_s16le",
                temp_audio
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            
            vad_info = []
            chunk_start = float(chunk[0]["start"])
            expected_chunk_ids = set()
            for s in chunk:
                expected_chunk_ids.add(int(s["id"]))
                vad_info.append({"id": s["id"], "relative_start": float(s["start"]) - chunk_start, "relative_end": float(s["end"]) - chunk_start})
            
            prompt = (
                "Transcribe the audio snippet for each VAD ID.\n"
                "ID TYPE: The id field MUST be a single integer, never an array, string, object, or range.\n"
                f"VAD IDs: {json.dumps(vad_info)}\n"
                "Format: {\"transcripts\": [{\"id\": int, \"text\": \"string\"}, ...]}\n"
            )
            
            results = []
            audio_file = None
            for attempt in range(3):
                try:
                    if not audio_file:
                        audio_file = self.client.files.upload(file=temp_audio)
                    response = self._counted_generate_content(
                        model=preferred_model, 
                        contents=[audio_file, prompt], 
                        config={"temperature": 0.0, "response_mime_type": "application/json"}
                    )
                    data = extract_valid_json(response.text, "transcripts")
                    if data:
                        transcripts = data.get("transcripts", [])
                        
                        # Diagnostics logging
                        expected_count = len(expected_chunk_ids)
                        accepted_ids = []
                        invalid_count = 0
                        
                        for res in transcripts:
                            if not isinstance(res, dict):
                                self.logger.warning(f"Skipping invalid Gemini transcript item: {res!r}")
                                invalid_count += 1
                                continue
    
                            seg_id = self._normalize_transcript_id(res.get("id"))
                            
                            if seg_id is None:
                                self.logger.warning(f"Skipping Gemini transcript with invalid id: {res.get('id')!r}")
                                invalid_count += 1
                                continue
    
                            if seg_id not in expected_chunk_ids:
                                self.logger.warning(f"Skipping Gemini transcript id outside current chunk: {seg_id}")
                                continue
                                
                            results.append({"id": seg_id, "text": str(res.get("text", "") or "")})
                            accepted_ids.append(seg_id)
                        
                        missing_count = expected_count - len(set(accepted_ids))
                        self.logger.info(f"Chunk diagnostic: Expected={expected_count}, Accepted={len(accepted_ids)}, Invalid={invalid_count}, Missing={missing_count}")
                        break
                    else:
                        log_malformed_response(response.text, self.logger)
                        raise ValueError("Gemini returned invalid or malformed JSON")
                except Exception as e:
                    self.logger.error(f"Attempt {attempt+1} failed: {e}")
                    if is_model_not_found_error(e):
                        self.logger.warning(
                            f"MODEL_UNAVAILABLE\nmodel={preferred_model}\nreason=MODEL_NOT_FOUND\naction=FAILOVER"
                        )
                        raise
                    if isinstance(e, (TypeError, NameError, AttributeError, KeyError)):
                        raise e
            
            return results
        finally:
            if os.path.exists(temp_audio):
                try:
                    os.remove(temp_audio)
                except Exception as clean_err:
                    self.logger.error(f"Failed to clean up temp file {temp_audio}: {clean_err}")

    def _get_whisper_map(self, audio_path, audio_hash, cache_dir):
        # 🎯 [P1-3]: ใช้ whisper_v2 namespace
        cache_path = os.path.join(cache_dir, "whisper_maps", f"whisper_v2_{audio_hash}.json")
        if os.path.exists(cache_path):
            with open(cache_path, 'r', encoding='utf-8') as f: return json.load(f), {}
        
        segments, _ = self.model.transcribe(audio_path, language="th", word_timestamps=False, beam_size=1, best_of=1, temperature=0, condition_on_previous_text=False, vad_filter=True)
        
        # Log diagnostics
        segments_list = list(segments)
        self.logger.info(f"Whisper segments count: {len(segments_list)}")
        last_timestamp = segments_list[-1].end if segments_list else 0
        self.logger.info(f"Last Whisper timestamp: {last_timestamp}")
        
        whisper_map = [{"id": i, "start": float(s.start), "end": float(s.end)} for i, s in enumerate(segments_list)]
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, 'w', encoding='utf-8') as f: json.dump(whisper_map, f, ensure_ascii=False)
        return whisper_map, {}

    def validate_timeline_integrity(self, timeline: list, whisper_map: list) -> dict:
        expected_ids = {
            seg.get("id")
            for seg in whisper_map
            if seg.get("id") is not None
        }
        
        timeline_by_id = {seg.get("id"): seg for seg in timeline if seg.get("id") is not None}
        
        successful_ids = []
        failed_ids = []
        missing_ids = []
        
        for seg_id in sorted(expected_ids):
            seg = timeline_by_id.get(seg_id)
            if not seg:
                missing_ids.append(seg_id)
            elif seg.get("status") == "failed":
                failed_ids.append(seg_id)
            elif seg.get("status") == "successful":
                successful_ids.append(seg_id)
            else:
                # Fallback if no status field
                if str(seg.get("text", "")).strip():
                    successful_ids.append(seg_id)
                else:
                    missing_ids.append(seg_id)
                    
        if not expected_ids:
            integrity_percent = 0.0
        else:
            integrity_percent = round(len(successful_ids) / len(expected_ids) * 100, 2)
            
        return {
            "integrity_percent": integrity_percent,
            "total_segments": len(timeline),
            "missing_segment_ids": missing_ids,
            "successful_segment_ids": successful_ids,
            "failed_segment_ids": failed_ids,
            "successful_segments": len(successful_ids),
            "failed_segments": len(failed_ids),
            "missing_segments": len(missing_ids)
        }

    def format_to_strategic_label(self, seconds: float) -> str:
        """Formats seconds into strategic timestamp label e.g. [MM:SS] or [HH:MM:SS]."""
        if seconds is None or seconds < 0:
            seconds = 0.0
        total_sec = int(seconds)
        hours = total_sec // 3600
        minutes = (total_sec % 3600) // 60
        secs = total_sec % 60
        if hours > 0:
            return f"[{hours:02d}:{minutes:02d}:{secs:02d}]"
        return f"[{minutes:02d}:{secs:02d}]"

    def build_readable_timeline(self, words: list) -> list:
        """Groups aligned word dicts into readable timeline segments."""
        if not words:
            return []
        start_time = words[0].get("start", 0.0)
        end_time = words[-1].get("end", 0.0)
        combined_text = "".join(w.get("word", "") for w in words)
        return [{
            "start": start_time,
            "end": end_time,
            "text": combined_text
        }]
