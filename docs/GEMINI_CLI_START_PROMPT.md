# Prompt สำหรับส่งให้ Gemini CLI

คุณเป็น Senior Full-Stack Engineer และ Software Migration Engineer

ภารกิจของคุณคือเพิ่มระบบ Login, User History และ Database ให้โครงการ YAMASEE FastAPI โดยรักษาระบบวิเคราะห์วิดีโอเดิมทั้งหมด

## เอกสารบังคับ
อ่านไฟล์ `YAMASEE_AUTH_HISTORY_MASTER_PLAN.md` ทั้งหมดก่อนลงมือ และถือว่าเอกสารนั้นเป็น Source of Truth

## กฎการทำงาน
1. อย่าเริ่มแก้โค้ดทันที
2. อ่านโครงสร้างโปรเจกต์และทุกไฟล์ที่เกี่ยวข้องก่อน
3. ห้ามรื้อ Engine เดิม
4. ห้ามทำ endpoint เดิมหาย
5. ห้ามทำ Dashboard เดิมเสีย
6. ทำทีละ Phase
7. หลังแต่ละ Phase ต้องรันทดสอบและรายงาน
8. หากข้อกำหนดขัดกับโค้ดจริง ให้หยุดและอธิบายก่อน
9. ห้ามใช้ข้อมูลจำลองใน production path
10. ห้าม hardcode secret
11. ห้ามเก็บ password แบบ plain text
12. ห้ามเชื่อ user_id จาก frontend
13. ต้องตรวจเจ้าของ history ฝั่ง backend
14. สร้าง backup ก่อนแก้
15. อย่าดำเนินการ Phase ถัดไปโดยอัตโนมัติ

## งานแรก: Phase 0 เท่านั้น

ดำเนินการดังนี้:

1. แสดง project tree ปัจจุบัน
2. ตรวจ `main.py`, `index.html`, `app.js`, `style.css`
3. ตรวจ engines และ schemas
4. สรุป endpoint ทั้งหมด
5. ระบุจุดสร้าง job
6. ระบุจุดอัปเดต progress
7. ระบุจุดสร้าง final result
8. ระบุจุดบันทึก `analysis_history`
9. ระบุจุด frontend polling
10. ระบุ element ID ที่ app.js พึ่งพา
11. สร้างโฟลเดอร์ `_backup_before_auth_history`
12. สำรองเฉพาะ source code และ config โดยไม่รวม cache, media, .env, API keys
13. รัน syntax check Python
14. รันระบบเดิมหรือ test ที่มี
15. อย่าแก้ behavior ใด ๆ ใน Phase 0

## รูปแบบรายงาน

PHASE: 0 — Backup and Audit

FILES CREATED:
FILES MODIFIED:
ENDPOINT INVENTORY:
CURRENT DATA FLOW:
FRONTEND DEPENDENCIES:
TESTS RUN:
TEST RESULTS:
RISKS:
ROLLBACK:
QUESTIONS/BLOCKERS:
READY FOR PHASE 1: YES/NO

หยุดหลังรายงาน Phase 0 และรอคำสั่งต่อไป
