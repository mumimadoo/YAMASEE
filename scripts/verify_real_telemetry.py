import os
import sys
import json
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
from database import SessionLocal
from engines.transcript_engine import TranscriptEngine
from engines.ai_analysis_engine import AIAnalysisEngine
from services.analysis_history_service import persist_completed_analysis
from models.user import User
from utils.telemetry import create_empty_token_usage, merge_token_usage

load_dotenv()

def main():
    print("=== STARTING REAL SINGLE JOB TELEMETRY VERIFICATION ===")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not found in environment.")
        return

    audio_path = os.path.abspath("scratch/real_test.wav")
    if not os.path.exists(audio_path):
        print(f"ERROR: Audio file {audio_path} does not exist.")
        return

    db = SessionLocal()
    user = db.query(User).first()
    if not user:
        print("ERROR: No user found in database.")
        db.close()
        return

    job_id = f"job_real_verify_{int(time.time())}"
    job_token_usage = create_empty_token_usage()

    # 1. Run Transcript Engine
    print("Running TranscriptEngine...")
    t0 = time.time()
    t_engine = TranscriptEngine(preferred_model="gemini-2.5-flash")
    t_result = t_engine.transcribe_audio(audio_path=audio_path, job_id=job_id)
    t_duration = time.time() - t0
    merge_token_usage(job_token_usage, t_engine.token_telemetry)
    print(f"TranscriptEngine completed in {t_duration:.2f}s")
    print("Transcript telemetry:", json.dumps(t_engine.token_telemetry, indent=2, ensure_ascii=False))

    # 2. Run AI Analysis Engine
    print("Running AIAnalysisEngine...")
    ai_engine = AIAnalysisEngine(api_key=api_key, preferred_model="gemini-2.5-flash")
    prompt = "วิเคราะห์ข้อความสั้นๆ นี้และตอบเป็น JSON summary 1 บรรทัด"
    text_lines = ["Speaker 1 - ทดสอบการถอดเสียงและวัดโทเคน"]
    a_result = ai_engine.generate_analytics(prompt, text_lines)
    merge_token_usage(job_token_usage, ai_engine.token_telemetry)
    print("AI Analysis telemetry:", json.dumps(ai_engine.token_telemetry, indent=2, ensure_ascii=False))

    # 3. Combined Job Token Usage
    print("Total Job Token Usage:", json.dumps(job_token_usage, indent=2, ensure_ascii=False))

    # 4. Persist to DB
    result_payload = {
        "timeline": [{"label": "00:00", "start": 0.0, "end": 3.0, "text": "ทดสอบระบบ"}],
        "summary": ["ทดสอบระบบการวัดโทเคนเรียบร้อย"],
        "duration_seconds": 3.0
    }

    cache, record = persist_completed_analysis(
        db=db,
        user_id=user.id,
        job_id=job_id,
        media_key=f"real_verify_{int(time.time())}",
        source_type="local",
        result_json=result_payload,
        original_filename="real_test.wav",
        model_used="gemini-2.5-flash",
        duration_seconds=3.0,
        processing_seconds=t_duration,
        token_usage=job_token_usage
    )
    db.close()
    print("=== VERIFICATION COMPLETED SUCCESSFULLY ===")
    print(f"Job ID: {job_id}")

if __name__ == "__main__":
    main()
