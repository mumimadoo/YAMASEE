import threading
from typing import Dict, Any

class OperationalMetrics:
    def __init__(self):
        self._lock = threading.Lock()
        self.jobs_running: int = 0
        self.jobs_completed: int = 0
        self.jobs_failed: int = 0
        self.retry_count: int = 0
        self.cache_hits: int = 0
        self.cache_misses: int = 0
        self.http_413_count: int = 0
        self.http_415_count: int = 0
        self.http_429_count: int = 0
        
        # Durations
        self._total_processing_time: float = 0.0
        self._processing_count: int = 0

        self._total_download_time: float = 0.0
        self._download_count: int = 0

        self._total_transcription_time: float = 0.0
        self._transcription_count: int = 0

        self._total_ai_analysis_time: float = 0.0
        self._ai_analysis_count: int = 0

    def inc(self, counter_name: str, value: int = 1):
        with self._lock:
            if hasattr(self, counter_name):
                setattr(self, counter_name, getattr(self, counter_name) + value)

    def dec(self, counter_name: str, value: int = 1):
        with self._lock:
            if hasattr(self, counter_name):
                current = getattr(self, counter_name)
                setattr(self, counter_name, max(0, current - value))

    def record_duration(self, category: str, duration_seconds: float):
        with self._lock:
            if category == "processing":
                self._total_processing_time += duration_seconds
                self._processing_count += 1
            elif category == "download":
                self._total_download_time += duration_seconds
                self._download_count += 1
            elif category == "transcription":
                self._total_transcription_time += duration_seconds
                self._transcription_count += 1
            elif category == "ai_analysis":
                self._total_ai_analysis_time += duration_seconds
                self._ai_analysis_count += 1

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            avg_processing = round(self._total_processing_time / self._processing_count, 3) if self._processing_count > 0 else 0.0
            avg_download = round(self._total_download_time / self._download_count, 3) if self._download_count > 0 else 0.0
            avg_transcription = round(self._total_transcription_time / self._transcription_count, 3) if self._transcription_count > 0 else 0.0
            avg_ai_analysis = round(self._total_ai_analysis_time / self._ai_analysis_count, 3) if self._ai_analysis_count > 0 else 0.0

            return {
                "jobs_running": self.jobs_running,
                "jobs_completed": self.jobs_completed,
                "jobs_failed": self.jobs_failed,
                "retry_count": self.retry_count,
                "cache_hits": self.cache_hits,
                "cache_misses": self.cache_misses,
                "http_413_count": self.http_413_count,
                "http_415_count": self.http_415_count,
                "http_429_count": self.http_429_count,
                "avg_processing_time_seconds": avg_processing,
                "avg_download_time_seconds": avg_download,
                "avg_transcription_time_seconds": avg_transcription,
                "avg_ai_analysis_time_seconds": avg_ai_analysis,
            }

metrics = OperationalMetrics()
