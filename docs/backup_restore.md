# YAMASEE — Backup & Disaster Recovery Guide

## 1. SQLite Database Backup
Since SQLite uses Write-Ahead Logging (`WAL`), create consistent backups using the SQLite `.backup` command or `.clone`:
```bash
sqlite3 data/yamasee.db ".backup data/backups/yamasee_$(date +%Y%m%d_%H%M%S).db"
```
Or use online backup API via python script `sqlite3.connect('data/yamasee.db').backup(target)`.

## 2. Media & Analysis Cache Backup
- Backup `analysis_history/*.json` files periodically.
- Backup `cache/` directory if preserving cached video/audio files is desired.

## 3. Database Migration & Recovery
- Run database migrations before app start:
  ```bash
  python -m alembic upgrade head
  ```
- Rollback last migration if needed:
  ```bash
  python -m alembic downgrade -1
  ```
