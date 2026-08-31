# YAMASEE — แผนปรับระบบครั้งใหญ่: Login, User History และฐานข้อมูล

> เอกสารนี้เป็นข้อกำหนดสำหรับให้ Gemini CLI ลงมือแก้โครงการจริง  
> เป้าหมายคือเพิ่มระบบสมาชิกและประวัติการวิเคราะห์ โดย **ห้ามทำระบบวิเคราะห์เดิมเสีย**

---

## 1. เป้าหมายของงาน

เพิ่มระบบดังต่อไปนี้ให้โครงการ YAMASEE:

1. หน้าแนะนำระบบ (Landing)
2. หน้าสมัครสมาชิก
3. หน้าเข้าสู่ระบบ
4. หน้า Dashboard วิเคราะห์เดิม
5. หน้าประวัติการวิเคราะห์ของผู้ใช้
6. หน้ารายละเอียดผลการวิเคราะห์ย้อนหลัง
7. ระบบฐานข้อมูล SQLite ที่ย้ายไป PostgreSQL ได้ในอนาคต
8. ระบบ Session แบบปลอดภัย
9. ระบบแยก Global Cache ออกจาก User History
10. ระบบตรวจสิทธิ์เจ้าของข้อมูลทุกครั้ง
11. ระบบลบไฟล์ชั่วคราวเพื่อลดพื้นที่
12. ระบบ Migration และ Seed สำหรับการพัฒนา
13. ระบบทดสอบ API สำคัญ

---

## 2. ข้อห้ามสำคัญ

Gemini CLI ต้องทำตามกฎต่อไปนี้:

- ห้ามรื้อ TranscriptEngine, AudioEngine, VideoEngine, AIAnalysisEngine และ KnowledgeEngine
- ห้ามเปลี่ยนรูปแบบ result JSON เดิมโดยไม่สร้าง compatibility layer
- ห้ามลบ endpoint เดิมจนกว่า endpoint ใหม่จะทำงานและผ่านการทดสอบ
- ห้ามเก็บรหัสผ่านแบบ plain text
- ห้ามส่ง password hash กลับ frontend
- ห้ามใช้ user_id ที่รับมาจาก frontend เป็นตัวตัดสินสิทธิ์
- ต้องอ่าน user_id จาก session ฝั่ง backend เท่านั้น
- ห้ามให้ผู้ใช้เปิดประวัติของคนอื่นด้วยการเดา record ID
- ห้ามเก็บวิดีโอและเสียงถาวรโดยอัตโนมัติ
- ห้ามยัดระบบใหม่ทั้งหมดลง main.py, index.html หรือ app.js
- ห้ามแก้หลายระยะพร้อมกันโดยไม่มี checkpoint
- ทุกระยะต้องรันระบบเดิมและตรวจว่า Dashboard ยังทำงาน
- ก่อนแก้ไฟล์ต้องสร้างสำเนาในโฟลเดอร์ `_backup_before_auth_history`

---

## 3. สภาพโครงการเดิมที่ต้องรักษา

โครงการปัจจุบันใช้:

- FastAPI เป็น backend
- HTML, CSS และ JavaScript ธรรมดาเป็น frontend
- BackgroundTasks สำหรับงานวิเคราะห์
- `JOBS_DATA` เป็นสถานะงานในหน่วยความจำ
- `analysis_history/*.json` เป็นคลังผลวิเคราะห์เดิม
- Frontend polling `/job_status/{job_id}`
- ระบบประมวลผลวิดีโอ เสียง Transcript และ Gemini แยกเป็น Engine
- ผลลัพธ์ Dashboard ถูกส่งเป็น JSON ก้อนเดียว

กระบวนการเดิม:

```text
Frontend ส่งวิดีโอ/URL
→ Backend สร้าง job_id
→ BackgroundTasks รัน enterprise_processing_pipeline
→ Frontend poll /job_status/{job_id}
→ เมื่อ completed เรียก injectProcessedDataToDashboard(result)
```

กระบวนการนี้ต้องยังทำงานหลังปรับระบบ

---

## 4. สถาปัตยกรรมเป้าหมาย

```text
project/
├── main.py
├── config.py
├── database.py
├── requirements.txt
├── .env.example
│
├── routers/
│   ├── __init__.py
│   ├── pages.py
│   ├── auth.py
│   ├── history.py
│   └── analysis.py
│
├── services/
│   ├── __init__.py
│   ├── auth_service.py
│   ├── cache_service.py
│   ├── history_service.py
│   └── cleanup_service.py
│
├── models/
│   ├── __init__.py
│   ├── user.py
│   ├── analysis_cache.py
│   └── analysis_record.py
│
├── schemas/
│   ├── analysis_schemas.py
│   ├── auth_schemas.py
│   └── history_schemas.py
│
├── dependencies/
│   ├── __init__.py
│   └── auth.py
│
├── engines/
│   ├── video_engine.py
│   ├── audio_engine.py
│   ├── transcript_engine.py
│   ├── ai_analysis_engine.py
│   └── knowledge_engine.py
│
├── templates/
│   ├── landing.html
│   ├── login.html
│   ├── register.html
│   ├── dashboard.html
│   ├── history.html
│   └── analysis_detail.html
│
├── static/
│   ├── css/
│   │   ├── theme.css
│   │   ├── auth.css
│   │   ├── dashboard.css
│   │   └── history.css
│   └── js/
│       ├── theme.js
│       ├── auth.js
│       ├── dashboard.js
│       ├── history.js
│       └── analysis_detail.js
│
├── data/
│   └── yamasee.db
├── analysis_history/
├── cache/
└── tests/
    ├── test_auth.py
    ├── test_history.py
    └── test_permissions.py
```

ระยะแรกยังไม่จำเป็นต้องแยก `enterprise_processing_pipeline` ออกจาก main.py ทันที  
ให้เพิ่มระบบรอบของเดิมก่อน แล้วค่อยแยกเมื่อทุกอย่างผ่านการทดสอบ

---

## 5. เทคโนโลยีที่ใช้

ใช้ของฟรีและทำงานในเครื่อง:

- FastAPI
- SQLAlchemy 2.x
- SQLite
- Alembic
- passlib + bcrypt
- SessionMiddleware ของ Starlette
- Pydantic
- Jinja2
- pytest
- httpx

เพิ่มใน `requirements.txt`:

```txt
sqlalchemy>=2.0
alembic>=1.13
passlib[bcrypt]>=1.7
python-multipart>=0.0.9
jinja2>=3.1
itsdangerous>=2.2
email-validator>=2.1
pytest>=8.0
httpx>=0.27
```

---

## 6. ตัวแปรสภาพแวดล้อม

สร้าง `.env.example`

```env
APP_ENV=development
APP_SECRET_KEY=CHANGE_THIS_TO_A_LONG_RANDOM_SECRET
DATABASE_URL=sqlite:///./data/yamasee.db
SESSION_HTTPS_ONLY=false
SESSION_MAX_AGE_SECONDS=604800
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
CACHE_DIR=cache
HISTORY_DIR=analysis_history
KEEP_MEDIA_FILES=false
```

กฎ:

- ห้าม commit `.env`
- Secret key ต้องยาวอย่างน้อย 32 ตัวอักษร
- Production ต้องเปิด `SESSION_HTTPS_ONLY=true`

---

## 7. Database Schema

### 7.1 users

```text
id                  INTEGER PRIMARY KEY
username            VARCHAR(80) NOT NULL
email               VARCHAR(255) UNIQUE NOT NULL
password_hash       VARCHAR(255) NOT NULL
is_active           BOOLEAN NOT NULL DEFAULT TRUE
created_at          DATETIME NOT NULL
updated_at          DATETIME NOT NULL
last_login_at       DATETIME NULL
```

Index:

```text
UNIQUE INDEX users_email_unique ON users(email)
INDEX users_created_at_idx ON users(created_at)
```

### 7.2 analysis_cache

คลังผลวิเคราะห์ส่วนกลางเพื่อประหยัดค่า AI

```text
id                  INTEGER PRIMARY KEY
media_key           VARCHAR(255) UNIQUE NOT NULL
source_type         VARCHAR(30) NOT NULL
source_url          TEXT NULL
original_filename   TEXT NULL
file_hash           VARCHAR(64) NULL
duration_seconds    FLOAT NULL
model_used          VARCHAR(100) NULL
result_json         JSON/TEXT NOT NULL
created_at          DATETIME NOT NULL
updated_at          DATETIME NOT NULL
last_accessed_at    DATETIME NOT NULL
```

`media_key`:

- YouTube: `youtube_<video_id>`
- TikTok: `tiktok_<video_id>`
- Upload: `local_sha256_<hash16>`

### 7.3 analysis_records

ประวัติส่วนตัวของผู้ใช้

```text
id                  INTEGER PRIMARY KEY
public_id           VARCHAR(36) UNIQUE NOT NULL
user_id             INTEGER NOT NULL FK users.id
cache_id            INTEGER NULL FK analysis_cache.id
job_id              VARCHAR(100) NULL
display_title       VARCHAR(255) NOT NULL
source_type         VARCHAR(30) NOT NULL
source_url          TEXT NULL
original_filename   TEXT NULL
thumbnail_url       TEXT NULL
file_size_bytes     INTEGER NULL
duration_seconds    FLOAT NULL
status              VARCHAR(20) NOT NULL
progress            INTEGER NOT NULL DEFAULT 0
model_used          VARCHAR(100) NULL
processing_seconds  FLOAT NULL
error_message       TEXT NULL
created_at          DATETIME NOT NULL
updated_at          DATETIME NOT NULL
completed_at        DATETIME NULL
```

สถานะที่อนุญาต:

```text
queued
processing
completed
failed
cancelled
```

Index:

```text
INDEX records_user_created_idx ON analysis_records(user_id, created_at)
INDEX records_user_status_idx ON analysis_records(user_id, status)
UNIQUE INDEX records_public_id_unique ON analysis_records(public_id)
```

---

## 8. หลักการ Cache และ History

ต้องแยกแนวคิด:

```text
Global Analysis Cache ≠ User History
```

ตัวอย่าง:

```text
User A วิเคราะห์คลิป X
→ สร้าง cache X
→ สร้าง record ของ User A

User B วิเคราะห์คลิป X
→ ใช้ cache X
→ สร้าง record ใหม่ของ User B
→ ไม่เรียก Gemini ซ้ำ
```

การลบ record ของผู้ใช้:

- ลบเฉพาะ `analysis_records`
- ไม่ลบ `analysis_cache` ทันที
- การล้าง cache ให้ทำผ่าน maintenance ภายหลัง

---

## 9. Authentication

### 9.1 Password

ใช้ bcrypt ผ่าน passlib:

```python
CryptContext(schemes=["bcrypt"], deprecated="auto")
```

เงื่อนไขรหัสผ่าน:

- อย่างน้อย 8 ตัวอักษร
- ต้องมีตัวอักษรและตัวเลข
- ความยาวสูงสุด 128 ตัวอักษร
- ห้าม trim รหัสผ่านโดยไม่แจ้งผู้ใช้

### 9.2 Session

หลัง Login:

```python
request.session["user_id"] = user.id
request.session["email"] = user.email
```

Logout:

```python
request.session.clear()
```

Session configuration:

```python
SessionMiddleware(
    secret_key=settings.app_secret_key,
    max_age=settings.session_max_age_seconds,
    same_site="lax",
    https_only=settings.session_https_only
)
```

### 9.3 Dependency

สร้าง:

```python
get_current_user(request, db)
require_current_user(request, db)
```

- `get_current_user` คืน user หรือ None
- `require_current_user` คืน 401/redirect เมื่อไม่ Login

ห้ามรับ user_id จาก Form หรือ JSON เพื่อใช้ตรวจเจ้าของข้อมูล

---

## 10. API Contract

### Auth

#### POST `/api/auth/register`

Request:

```json
{
  "username": "Narakorn",
  "email": "user@example.com",
  "password": "Password123",
  "confirm_password": "Password123"
}
```

Response 201:

```json
{
  "success": true,
  "user": {
    "id": 1,
    "username": "Narakorn",
    "email": "user@example.com"
  }
}
```

Errors:

- 400 รหัสผ่านไม่ตรงกัน
- 409 อีเมลซ้ำ
- 422 รูปแบบข้อมูลผิด

#### POST `/api/auth/login`

```json
{
  "email": "user@example.com",
  "password": "Password123"
}
```

Response:

```json
{
  "success": true,
  "redirect_url": "/dashboard"
}
```

#### POST `/api/auth/logout`

Response:

```json
{
  "success": true,
  "redirect_url": "/login"
}
```

#### GET `/api/auth/me`

```json
{
  "authenticated": true,
  "user": {
    "id": 1,
    "username": "Narakorn",
    "email": "user@example.com"
  }
}
```

### History

#### GET `/api/history`

Query:

```text
page=1
page_size=20
search=
status=
sort=latest
```

Response:

```json
{
  "items": [],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_items": 0,
    "total_pages": 0
  }
}
```

#### GET `/api/history/{public_id}`

ตรวจว่า record.user_id เท่ากับ session user ทุกครั้ง

#### PATCH `/api/history/{public_id}`

อนุญาตเปลี่ยนเฉพาะ `display_title`

#### DELETE `/api/history/{public_id}`

ลบเฉพาะ record ของเจ้าของ

#### POST `/api/history/{public_id}/reanalyze`

พฤติกรรม:

- ใช้ source เดิม
- ถ้ามี cache ให้สร้าง record ใหม่จาก cache
- ถ้าต้องรันใหม่จริง ให้มี parameter `force=true`
- `force=true` ต้องไม่เป็นค่าเริ่มต้นเพื่อประหยัดเงิน

---

## 11. Page Routes

```text
GET /                       landing.html
GET /login                  login.html
GET /register               register.html
GET /dashboard              dashboard.html (ต้อง Login)
GET /history                history.html (ต้อง Login)
GET /history/{public_id}    analysis_detail.html (ต้องเป็นเจ้าของ)
```

ถ้า Login แล้วเปิด `/login` หรือ `/register` ให้ redirect `/dashboard`

---

## 12. การเชื่อมกับ Pipeline เดิม

### 12.1 สร้าง record ก่อนเริ่มงาน

เมื่อรับคำขอวิเคราะห์:

```text
1. ตรวจ session
2. อ่าน input
3. สร้าง media_key
4. ตรวจ analysis_cache
5. สร้าง analysis_record
6. ถ้ามี cache → completed
7. ถ้าไม่มี → queued และเริ่ม BackgroundTasks
```

JOBS_DATA ใหม่ควรมี:

```python
JOBS_DATA[job_id] = {
    "status": "queued",
    "progress": 0,
    "result": None,
    "record_public_id": record.public_id,
    "owner_user_id": current_user.id
}
```

### 12.2 เปลี่ยน signature ของ pipeline อย่างระวัง

จาก:

```python
enterprise_processing_pipeline(
    job_id,
    mode,
    youtube_url,
    file_bytes,
    file_name,
    selected_model
)
```

เป็น:

```python
enterprise_processing_pipeline(
    job_id=job_id,
    record_id=record.id,
    owner_user_id=current_user.id,
    mode=final_mode,
    youtube_url=final_url,
    file_bytes=file_bytes,
    file_name=file_name,
    selected_model=model
)
```

### 12.3 ทุก progress update ต้องอัปเดต 2 แห่ง

```python
set_job_progress(job_id, "processing", 30)
history_service.update_progress(record_id, "processing", 30)
```

สร้าง helper ห้ามเขียนซ้ำหลายที่:

```python
def update_job_state(job_id, record_id, *, status=None, progress=None, error=None):
    ...
```

### 12.4 เมื่อเสร็จ

```text
1. เตรียม final_result
2. upsert analysis_cache ด้วย media_key
3. ผูก record.cache_id
4. status = completed
5. progress = 100
6. completed_at = now
7. processing_seconds = elapsed
8. JOBS_DATA[job_id].result = final_result
9. ลบไฟล์ชั่วคราวตาม KEEP_MEDIA_FILES
```

### 12.5 เมื่อผิดพลาด

ต้องทำทั้ง:

```python
JOBS_DATA[job_id]["status"] = "failed"
JOBS_DATA[job_id]["error"] = safe_error_message
```

และ:

```text
analysis_records.status = failed
analysis_records.error_message = safe_error_message
analysis_records.updated_at = now
```

ห้ามส่ง stack trace ให้ frontend

---

## 13. Compatibility กับ analysis_history เดิม

ห้ามลบไฟล์ JSON เดิม

สร้าง migration script:

```text
scripts/import_legacy_history.py
```

หน้าที่:

1. อ่านทุก `.json` ใน `analysis_history`
2. หา media_key จากชื่อไฟล์
3. ตรวจ result JSON
4. เพิ่ม `knowledge_tree` ค่าเริ่มต้นถ้าไม่มี
5. บันทึกเป็น `analysis_cache`
6. ไม่สร้าง user history โดยอัตโนมัติ เว้นแต่มี legacy owner
7. สรุปจำนวน import, skip และ error

ต้องรองรับการรันซ้ำโดยไม่สร้างข้อมูลซ้ำ

---

## 14. Frontend Design

### 14.1 Theme

คงระบบ Day/Night เดิม และย้าย token ไป `theme.css`

ทุกหน้าต้องใช้:

- Logo เดียวกัน
- Theme toggle เดียวกัน
- Font Sarabun + Plus Jakarta Sans
- CSS variables เดียวกัน
- Header เดียวกัน

### 14.2 Landing

องค์ประกอบ:

- Logo + ชื่อระบบ
- คำอธิบายระบบ
- ปุ่ม “เริ่มวิเคราะห์”
- ปุ่ม “เข้าสู่ระบบ”
- การ์ดความสามารถ 3 ใบ:
  - ถอดความ
  - วิเคราะห์ 9 โมดูล
  - เก็บประวัติ
- Responsive
- ถ้า Login แล้ว ปุ่มหลักไป `/dashboard`

### 14.3 Login

- Email
- Password
- Toggle แสดงรหัสผ่าน
- Login button
- Error area แบบไม่ใช้ alert
- Link สมัครสมาชิก
- Loading state
- Enter เพื่อ submit
- ป้องกัน double-submit

### 14.4 Register

- Username
- Email
- Password
- Confirm password
- Password requirements
- Loading state
- Error message ราย field
- ปุ่ม “สร้างบัญชี” ไม่ใช่ “Log in”

### 14.5 Dashboard

ใช้หน้าเดิมเป็นฐาน

เพิ่ม header navigation:

```text
วิเคราะห์ใหม่ | ประวัติ | ชื่อผู้ใช้ | ออกจากระบบ | Theme
```

ข้อกำหนด:

- ห้ามทำโมดูลเดิมหาย
- ห้ามเปลี่ยน ID element ที่ `app.js` ใช้อยู่โดยไม่มี compatibility
- แยก script dashboard เดิมไป `dashboard.js` ทีละส่วน
- ระยะแรกสามารถคง `app.js` เดิมและเพิ่ม `auth-nav.js`

### 14.6 History

Toolbar:

- Search
- Filter status
- Sort
- ปุ่มวิเคราะห์ใหม่

รายการต้องแสดง:

- thumbnail
- display_title
- source type
- วันที่
- duration
- status
- processing time
- ปุ่มดูผล
- ปุ่มวิเคราะห์ใหม่
- เมนูเปลี่ยนชื่อ/ลบ

Empty state:

```text
ยังไม่มีประวัติการวิเคราะห์
[เริ่มวิเคราะห์รายการแรก]
```

### 14.7 Analysis Detail

แสดงผลจาก `result_json` โดย reuse renderer เดิมให้มากที่สุด

ต้องมี:

- Back to history
- ชื่อรายการ
- วันที่
- Source
- Status
- Transcript
- Summary
- Keywords
- Sentiment
- Chapters
- Communication
- Knowledge Tree
- Download TXT/PDF
- Reanalyze

ห้ามเรียก Gemini เมื่อเปิดหน้ารายละเอียดเก่า

---

## 15. Security Checklist

- [ ] Password hash ด้วย bcrypt
- [ ] Session secret จาก env
- [ ] HttpOnly session cookie
- [ ] SameSite=Lax
- [ ] HTTPS-only ใน production
- [ ] Normalize email เป็น lowercase
- [ ] ตรวจ email duplicate แบบ case-insensitive
- [ ] จำกัด login attempts แบบพื้นฐาน
- [ ] ทุก history query มี `user_id=current_user.id`
- [ ] Public ID ใช้ UUID ไม่ใช้เลข id ตรง ๆ
- [ ] ไม่ส่ง path จริงของ server
- [ ] Validate file extension และ MIME
- [ ] จำกัด upload size
- [ ] หลีกเลี่ยง `shell=True` ในโค้ดใหม่
- [ ] Error response ไม่เปิดเผย secret
- [ ] Logout clear session
- [ ] ป้องกัน open redirect

---

## 16. Cleanup Policy

หลังวิเคราะห์เสร็จ:

- ลบ temporary audio
- ลบ temporary upload
- ลบ remux video ถ้าไม่ต้องใช้เล่นย้อนหลัง
- คงเฉพาะ result JSON และ metadata
- ถ้า source เป็น YouTube ให้ใช้ URL เดิมสำหรับ player
- ถ้าเป็น local file หน้า history อาจแสดง “ไฟล์ภายในเครื่องไม่ได้เก็บไว้”

สร้าง:

```python
cleanup_processing_files(paths: list[str], keep_media: bool)
```

ทุก path ต้องตรวจว่าอยู่ใต้ CACHE_DIR หรือ STATIC_DIR ก่อนลบ

---

## 17. Phased Implementation

### Phase 0 — Backup และ Audit

1. สำรองไฟล์
2. รันระบบเดิม
3. จด endpoint เดิม
4. บันทึก screenshot หน้าเดิม
5. ทดสอบวิเคราะห์หนึ่ง YouTube และหนึ่ง local file
6. เก็บ sample result JSON

Checkpoint:
- ระบบเดิมยังทำงาน 100%

### Phase 1 — Database Foundation

สร้าง:

- config.py
- database.py
- models
- Alembic
- initial migration

Checkpoint:
- เปิดแอปได้
- สร้าง `data/yamasee.db`
- tables ครบ

### Phase 2 — Authentication Backend

สร้าง auth schemas, service, router, dependency และ session middleware

Checkpoint:
- register
- login
- me
- logout
- duplicate email
- invalid password

### Phase 3 — Auth Pages

สร้าง landing, login, register และ shared theme

Checkpoint:
- UI responsive
- error state
- login redirect
- logout

### Phase 4 — Protect Dashboard

- ย้าย index เดิมเป็น dashboard
- route ต้อง Login
- nav แสดง username
- endpoint วิเคราะห์ต้อง Login

Checkpoint:
- anonymous เปิดไม่ได้
- user login ใช้งานเดิมได้

### Phase 5 — History Persistence

- สร้าง analysis record
- update status/progress
- save cache
- link record to cache

Checkpoint:
- วิเคราะห์เสร็จแล้วมี record
- restart server แล้วประวัติยังอยู่

### Phase 6 — History UI

สร้าง list, search, filter, sort, pagination, rename, delete

Checkpoint:
- user เห็นเฉพาะของตัวเอง

### Phase 7 — Detail Page

reuse renderer เดิมเพื่อแสดง result_json

Checkpoint:
- เปิดผลเก่าโดยไม่เรียก AI

### Phase 8 — Legacy Import

import analysis_history เดิมเป็น cache

Checkpoint:
- รันซ้ำได้
- ไม่ duplicate

### Phase 9 — Tests และ Hardening

- auth tests
- permission tests
- history tests
- upload limit
- cleanup
- error handling

---

## 18. Acceptance Criteria

งานถือว่าเสร็จเมื่อ:

1. สมัครสมาชิกได้
2. Login/Logout ได้
3. Dashboard เปิดได้เฉพาะผู้ Login
4. วิเคราะห์ของเดิมยังทำงาน
5. ทุกงานถูกผูกกับผู้ใช้
6. ประวัติยังอยู่หลัง restart
7. User A เปิด record ของ User B ไม่ได้
8. คลิปซ้ำใช้ cache และไม่เรียก AI ซ้ำ
9. เปิดผลเก่าไม่เรียก AI
10. Rename และ Delete history ได้
11. Theme ทำงานทุกหน้า
12. Mobile layout ใช้งานได้
13. ไม่มี password ใน log
14. ไม่มี API key ใน frontend
15. Tests สำคัญผ่าน

---

## 19. รูปแบบรายงานของ Gemini CLI หลังแต่ละ Phase

Gemini CLI ต้องตอบ:

```text
PHASE:
FILES CREATED:
FILES MODIFIED:
DATABASE CHANGES:
API CHANGES:
TESTS RUN:
TEST RESULTS:
MANUAL CHECK:
RISKS:
ROLLBACK:
NEXT PHASE:
```

ห้ามตอบเพียงว่า “ทำเสร็จแล้ว”

---

## 20. คำสั่งเริ่มต้นสำหรับ Gemini CLI

1. อ่านทุกไฟล์ก่อนแก้
2. แสดง project tree
3. สรุป endpoint เดิม
4. สรุป dependency
5. ทำ Phase 0 เท่านั้น
6. รออนุมัติก่อน Phase 1
