from google import genai
import json

from utils.logger import logger
from utils.telemetry import create_empty_token_usage, add_response_telemetry
from utils.gemini_model_policy import (
    build_model_chain,
    run_with_model_fallback,
    validate_primary_model,
)

class AIAnalysisEngine:
    def __init__(self, api_key: str, preferred_model: str = None):
        self.client = genai.Client(api_key=api_key)
        self.token_telemetry = create_empty_token_usage()
        
        self.selected_model = validate_primary_model(preferred_model)
        self.models = build_model_chain(self.selected_model)
        self.successful_model = None

    def generate_analytics(self, prompt: str, text_array: list):
        """จัดการ Logic การเรียก API หลายโมเดลแบบวนลูป เพื่อแก้ปัญหาโควตา"""
        def call_model(model_name):
            response = self.client.models.generate_content(
                model=model_name,
                contents=[prompt, json.dumps(text_array, ensure_ascii=False)],
                config={'response_mime_type': 'application/json', 'temperature': 0.0}
            )
            add_response_telemetry(self.token_telemetry, "analysis", model_name, response)
            return json.loads(response.text)

        result, self.successful_model = run_with_model_fallback(
            call_model,
            selected_model=self.selected_model,
            logger=logger,
        )
        return result
