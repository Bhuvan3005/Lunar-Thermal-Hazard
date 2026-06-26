# ============================================================
# Backend Dockerfile — Lunar Thermal Hazard
# FastAPI + PyTorch GNN on python:3.12-slim
# ============================================================

# --- Stage: production image ---
FROM python:3.12-slim AS backend

# ---- System dependencies ----
# libgomp1  : OpenMP runtime required by PyTorch CPU builds
# libglib2.0-0, libgl1 : required by OpenCV
# gdal-bin, libgdal-dev : required by rasterio
# gcc / g++ : needed to compile some Python packages from source
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
 && pip install --no-cache-dir -r requirements.txt

# ---- Copy application source ----
COPY backend/ .

# ---- Trained GNN model ----
# The .pth file lives inside backend/ — already copied above.
# MODEL_PATH env var points to it at runtime.

# ---- Ownership ----
RUN chown -R appuser:appgroup /app

# ---- Switch to non-root ----
USER appuser

# ---- Expose FastAPI port ----
EXPOSE 8000

# ---- Health check ----
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# ---- Graceful-shutdown Uvicorn ----
# --workers 1  : single process avoids shared-graph conflicts
# --log-level  : all logs to stdout (Docker captures them)
CMD ["uvicorn", "route_api:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--log-level", "info", \
     "--timeout-graceful-shutdown", "30"]
