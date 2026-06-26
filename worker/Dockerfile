# ============================================================
# Worker Dockerfile — Lunar Thermal Hazard
# Scheduled jobs: NOAA fetch → hazard dataset → live inference
# Uses the same python:3.12-slim base as the backend.
# ============================================================

FROM python:3.12-slim AS worker

# ---- System dependencies (same as backend) ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    libglib2.0-0 \
    libgl1 \
    libgdal-dev \
    gdal-bin \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ---- Non-root user ----
RUN groupadd --gid 1001 appgroup \
 && useradd  --uid 1001 --gid 1001 --no-create-home appuser

# ---- Working directory ----
WORKDIR /app

# ---- Install Python dependencies (cached layer) ----
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir apscheduler

# ---- Copy backend source (worker scripts live there) ----
COPY backend/ .

# ---- Copy entrypoint script ----
COPY worker_entrypoint.py .

# ---- Ownership ----
RUN chown -R appuser:appgroup /app

# ---- Switch to non-root ----
USER appuser

# ---- Health check: ensure the Python process is alive ----
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD pgrep -f worker_entrypoint.py || exit 1

# ---- Start the scheduler ----
CMD ["python", "-u", "worker_entrypoint.py"]
