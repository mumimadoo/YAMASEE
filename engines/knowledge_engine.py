from google import genai
import json
import time
from utils.logger import logger
from utils.telemetry import create_empty_token_usage, add_response_telemetry
from utils.gemini_model_policy import build_model_chain, is_model_not_found_error, validate_primary_model

class KnowledgeEngine:
    def __init__(self, api_key: str, preferred_model: str = None):
        self.client = genai.Client(api_key=api_key)
        self.token_telemetry = create_empty_token_usage()
        
        selected_model = validate_primary_model(preferred_model)
        logger.info(f"KnowledgeEngine: Using preferred model: {selected_model}")
        self.models = build_model_chain(selected_model)

    def generate_knowledge_tree(self, timeline: list) -> dict:
        """แปลง Transcript เป็นโครงสร้างแผนผังองค์ความรู้ระดับยุทธศาสตร์ (Executive Knowledge Tree)"""
        try:
            if not timeline:
                logger.warning("KnowledgeEngine: Timeline is empty.")
                return {"main_topics": []}

            # 1. จัดเตรียมข้อมูล Timeline ให้กับพร้อมท์ (Prompt)
            formatted_lines = []
            for item in timeline:
                start_sec = item.get("start", 0.0)
                end_sec = item.get("end", 0.0)
                text = item.get("text", "").strip()
                if text:
                    formatted_lines.append(f"[{start_sec:.2f} - {end_sec:.2f}]: {text}")

            if not formatted_lines:
                logger.warning("KnowledgeEngine: Formatted transcript lines are empty.")
                return {"main_topics": []}

            transcript_text = "\n".join(formatted_lines)

            # 2. ตั้งค่าพร้อมท์วิเคราะห์เจาะลึกเฉพาะประเด็นยุทธศาสตร์สำคัญ (Executive Summary Prompt)
            prompt = (
                "You are an expert Strategic Information Architect.\n"
                "Your task is to extract an Executive Topic Summary (Knowledge Tree) from the provided speech transcript timeline.\n\n"
                "CRITICAL PRINCIPLES:\n"
                "1. Focus ONLY on key, high-value, and important topics of the video. Act as an Executive Topic Summary.\n"
                "2. DO NOT try to cover every second or every sentence of the transcript from start to end. Ignore transition sentences, repetitive examples, chit-chat, and minor details.\n"
                "3. Keep the structure to exactly TWO levels: Main Topics (หัวข้อหลัก) and Sub Topics (หัวข้อย่อย).\n"
                "4. Time ranges are strictly metadata of the Sub Topic. DO NOT create a third level in the structure for occurrences/timestamps.\n"
                "5. If a Sub Topic is discussed in multiple non-contiguous parts of the video, represent it as ONE Sub Topic, but include all its time ranges in the 'time_ranges' list.\n"
                "6. For a typical 7-minute video, there should be roughly 2 to 5 Main Topics, and 4 to 12 Sub Topics in total. Adjust proportionally based on video length and density, but keep it high-level.\n"
                "7. Output ONLY valid JSON matching the schema below.\n\n"
                "Output JSON Schema:\n"
                "{\n"
                "  \"main_topics\": [\n"
                "    {\n"
                "      \"title\": \"ชื่อหัวข้อหลัก (Thai)\",\n"
                "      \"summary\": \"สรุปหัวข้อหลักแบบสั้นกระชับ (Thai)\",\n"
                "      \"sub_topics\": [\n"
                "        {\n"
                "          \"title\": \"ชื่อหัวข้อย่อย (Thai)\",\n"
                "          \"summary\": \"สรุปสาระสำคัญของหัวข้อย่อยแบบสั้นกระชับ (Thai)\",\n"
                "          \"time_ranges\": [\n"
                "            {\n"
                "              \"start\": 0.0,\n"
                "              \"end\": 45.0\n"
                "            }\n"
                "          ]\n"
                "        }\n"
                "      ]\n"
                "    }\n"
                "  ]\n"
                "}"
            )

            # 3. รันระบบ Failover Loop เพื่อเรียกใช้โมเดลตามลำดับความพร้อม
            raw_tree = None
            for model_name in self.models:
                for attempt in range(3):
                    try:
                        logger.info(f"KnowledgeEngine: Requesting knowledge summary using model {model_name} (Attempt {attempt+1})")
                        response = self.client.models.generate_content(
                            model=model_name,
                            contents=[prompt, transcript_text],
                            config={'response_mime_type': 'application/json', 'temperature': 0.0}
                        )
                        add_response_telemetry(self.token_telemetry, "analysis", model_name, response)
                        raw_tree = json.loads(response.text)
                        break
                    except Exception as e:
                        logger.warning(f"KnowledgeEngine attempt {attempt+1} failed on model {model_name}: {e}")
                        if is_model_not_found_error(e):
                            logger.warning(
                                f"MODEL_UNAVAILABLE\nmodel={model_name}\nreason=MODEL_NOT_FOUND\naction=FAILOVER"
                            )
                            break
                        if attempt < 2:
                            time.sleep(1.5)
                if raw_tree is not None:
                    break

            if raw_tree is None:
                logger.error("KnowledgeEngine: All models failed to generate content or parse JSON.")
                return {"main_topics": []}

            # 4. ทำการ Validation และ Merge ข้อมูลหัวข้อซ้ำที่เกิดจากโมเดล AI
            validated_tree = self.validate_and_merge_tree(raw_tree)
            return validated_tree

        except Exception as ex:
            logger.exception(f"KnowledgeEngine: Critical failure in generate_knowledge_tree: {ex}")
            return {"main_topics": []}

    def validate_and_merge_tree(self, raw_data: dict) -> dict:
        """ตรวจสอบความถูกต้องของข้อมูลตามกฎ Validation และทำการยุบรวมข้อมูลหัวข้อที่ซ้ำซ้อน"""
        if not isinstance(raw_data, dict) or "main_topics" not in raw_data:
            logger.warning("KnowledgeEngine validation: Raw data is not a dictionary or lacks 'main_topics'.")
            return {"main_topics": []}

        validated_main_topics = []
        seen_main_topics = {}  # main_topic_title -> index in validated_main_topics

        for raw_topic in raw_data.get("main_topics", []):
            if not isinstance(raw_topic, dict):
                continue

            main_title = str(raw_topic.get("title", "")).strip()
            main_summary = str(raw_topic.get("summary", "")).strip()
            if not main_title:
                continue

            # 1. ยุบรวมหัวข้อหลักที่มีชื่อตรงกัน
            if main_title in seen_main_topics:
                main_node = validated_main_topics[seen_main_topics[main_title]]
                if main_summary and not main_node["summary"]:
                    main_node["summary"] = main_summary
            else:
                main_node = {
                    "title": main_title,
                    "summary": main_summary,
                    "sub_topics": []
                }
                validated_main_topics.append(main_node)
                seen_main_topics[main_title] = len(validated_main_topics) - 1

            # ดึงแผนผังหัวข้อย่อยปัจจุบัน
            seen_sub_topics = {}  # sub_title -> index in main_node["sub_topics"]
            for idx, sub in enumerate(main_node["sub_topics"]):
                seen_sub_topics[sub["title"]] = idx

            for raw_sub in raw_topic.get("sub_topics", []):
                if not isinstance(raw_sub, dict):
                    continue

                sub_title = str(raw_sub.get("title", "")).strip()
                sub_summary = str(raw_sub.get("summary", "")).strip()
                if not sub_title:
                    continue

                # 2. ยุบรวมหัวข้อย่อยที่มีชื่อตรงกัน
                if sub_title in seen_sub_topics:
                    sub_node = main_node["sub_topics"][seen_sub_topics[sub_title]]
                    if sub_summary and not sub_node["summary"]:
                        sub_node["summary"] = sub_summary
                else:
                    sub_node = {
                        "title": sub_title,
                        "summary": sub_summary,
                        "time_ranges": []
                    }
                    main_node["sub_topics"].append(sub_node)
                    seen_sub_topics[sub_title] = len(main_node["sub_topics"]) - 1

                for tr in raw_sub.get("time_ranges", []):
                    if not isinstance(tr, dict):
                        continue

                    try:
                        start = float(tr.get("start", 0))
                        end = float(tr.get("end", 0))
                    except (ValueError, TypeError):
                        continue

                    # 3. จัดการเวลาให้ Start < End
                    if start >= end:
                        if start > end:
                            start, end = end, start
                        else:
                            end = start + 5.0

                    sub_node["time_ranges"].append({
                        "start": start,
                        "end": end
                    })

        # 4. เรียงลำดับช่วงเวลาในแต่ละ Sub Topic และลบค่าที่ว่างเปล่าออก
        final_main_topics = []
        for main_topic in validated_main_topics:
            cleaned_subs = []
            for sub in main_topic["sub_topics"]:
                # กรองช่วงเวลาและเรียงตามเวลาเริ่มต้น
                if sub["time_ranges"]:
                    sub["time_ranges"].sort(key=lambda x: x["start"])
                else:
                    # ถ้าไม่มี time ranges เลย ให้สร้างค่าเริ่มต้นไว้ป้องกันพัง
                    sub["time_ranges"] = [{"start": 0.0, "end": 5.0}]
                cleaned_subs.append(sub)
            
            if cleaned_subs:
                main_topic["sub_topics"] = cleaned_subs
                final_main_topics.append(main_topic)

        logger.info(f"KnowledgeEngine validation: Successfully merged and validated {len(final_main_topics)} main topics.")
        return {"main_topics": final_main_topics}
