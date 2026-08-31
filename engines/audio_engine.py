import os
import subprocess
from config import settings
from utils.logger import logger

class AudioEngine:
    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir

    def extract_audio(self, video_path: str, output_name: str) -> str:
        """แปลงไฟล์วิดีโอเป็นเสียง .mp3 ด้วย ffmpeg พร้อม bounded timeout"""
        audio_path = os.path.join(self.cache_dir, f"{output_name}.mp3")
        cmd = [
            "ffmpeg", "-y", "-i", video_path, 
            "-vn", "-acodec", "libmp3lame", "-q:a", "2", 
            audio_path
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                timeout=settings.ffmpeg_timeout_seconds
            )
            logger.info(f"✅ สกัดเสียงสำเร็จ: {audio_path}")
            return audio_path
        except subprocess.TimeoutExpired as e:
            logger.error(f"❌ ffmpeg extract_audio timed out after {settings.ffmpeg_timeout_seconds}s")
            if os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                except Exception:
                    pass
            raise RuntimeError(f"Media extraction timed out after {settings.ffmpeg_timeout_seconds}s") from e
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.decode("utf-8", errors="ignore") if e.stderr else str(e)
            logger.error(f"❌ สกัดเสียงล้มเหลว: {err_msg}")
            raise e

    def split_audio_into_chunks(self, audio_path: str, chunk_length: float = 60.0) -> list:
        pass
