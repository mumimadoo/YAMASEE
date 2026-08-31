#!/bin/bash
set -e

# Create symlinks for ffmpeg and ffprobe inside app directory so yt-dlp can locate them via --ffmpeg-location
ln -sf $(which ffmpeg) /app/ffmpeg
ln -sf $(which ffprobe) /app/ffprobe

# Wait for database if using PostgreSQL
if [[ "$DATABASE_URL" == *postgres* ]]; then
  echo "Waiting for database to be ready..."
  python -c "
import os, time, psycopg
db_url = os.getenv('DATABASE_URL', '')
conn_str = db_url.replace('+psycopg', '')
for i in range(30):
    try:
        psycopg.connect(conn_str)
        print('Database is ready!')
        exit(0)
    except Exception as e:
        print(f'Database not ready (attempt {i+1}/30), retrying in 1s...')
        time.sleep(1)
exit(1)
"
fi

# Run alembic migrations
echo "Running database migrations..."
python -m alembic upgrade head

# Start uvicorn
echo "Starting FastAPI server..."
exec python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
