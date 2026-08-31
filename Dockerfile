FROM python:3.11-slim

# Install system dependencies: ffmpeg, nodejs, curl, and clean cache
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set up working directory
WORKDIR /app

# Copy requirements file first to utilize Docker build cache
COPY requirements.txt /app/requirements.txt

# Install python packages, cpu-only torch, and yt-dlp
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir yt-dlp psutil

# Copy application files (respecting .dockerignore)
COPY . /app

# Ensure entrypoint is executable and has Unix line endings
RUN chmod +x /app/docker/entrypoint.sh \
    && sed -i 's/\r$//' /app/docker/entrypoint.sh

# Expose FastAPI application port
EXPOSE 8000

# Set entrypoint
ENTRYPOINT ["/app/docker/entrypoint.sh"]
