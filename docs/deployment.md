# 🚀 Lunar Thermal Hazard — Production Deployment Guide

## What Was Created

| File | Purpose |
|---|---|
| `backend/Dockerfile` | FastAPI + PyTorch GNN image (`python:3.12-slim`) |
| `frontend/Dockerfile` | Multi-stage Node build → Nginx serve |
| `frontend/nginx.conf` | SPA routing, `/api/` proxy, gzip, security headers |
| `worker/Dockerfile` | Periodic-job container (APScheduler) |
| `worker_entrypoint.py` | Schedules NOAA fetch → dataset gen → GNN inference |
| `docker-compose.yml` | Orchestrates all 3 services + named volume + internal network |
| `.env.example` | Safe template to commit; real `.env` stays git-ignored |
| `.dockerignore` | Excludes secrets, `__pycache__`, `node_modules`, 8 GB GeoTIFF |

---

## Project Layout After Containerization

```
Lunar_Thermal_Hazard/
├── backend/
│   ├── Dockerfile
│   ├── route_api.py
│   ├── lunagraph_gcn_model.pth   ← must exist before build
│   └── ...
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf
│   └── ...
├── worker/
│   └── Dockerfile
├── worker_entrypoint.py
├── docker-compose.yml
├── .env                  ← real secrets (git-ignored)
├── .env.example          ← commit this
├── .dockerignore
└── requirements.txt
```

---

## Local Quick Start

```bash
# 1. Copy the env template and fill in your Supabase credentials
cp .env.example .env
# Edit .env: SUPABASE_URL, SUPABASE_KEY, DATABASE_URL

# 2. Build and launch all services
docker compose up -d --build

# 3. Verify services are healthy
docker compose ps
```

- **Frontend**: http://localhost  
- **Backend API** (via Nginx proxy): http://localhost/api/health

---

## Oracle Cloud Ubuntu VM — Single-Command Deployment

### 1 — Install Docker on the VM

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER
newgrp docker
```

### 2 — Clone and Configure

```bash
git clone https://github.com/<your-org>/Lunar_Thermal_Hazard.git
cd Lunar_Thermal_Hazard
cp .env.example .env
nano .env    # fill in SUPABASE_URL, SUPABASE_KEY, DATABASE_URL
```

> **⚠️ Important:** The trained model `backend/lunagraph_gcn_model.pth` is **git-ignored**.
> Copy it to the server manually before building:
> ```bash
> scp backend/lunagraph_gcn_model.pth ubuntu@<vm-ip>:~/Lunar_Thermal_Hazard/backend/
> ```

### 3 — Deploy

```bash
docker compose up -d
docker compose ps      # all three services should show "healthy"
```

### 4 — Open the Firewall

**Oracle Cloud Console:**
1. Networking → VCN → Security Lists → Add Ingress Rule
2. Protocol: TCP, Destination Port: **80**

**OS-level iptables on the VM:**
```bash
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
sudo apt install -y iptables-persistent
sudo netfilter-persistent save
```

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `SUPABASE_URL` | ✅ | — | Supabase project REST URL |
| `SUPABASE_KEY` | ✅ | — | Supabase anon / service-role key |
| `DATABASE_URL` | ✅ | — | PostgreSQL URL for SQLAlchemy |
| `MODEL_PATH` | ✅ | `/app/lunagraph_gcn_model.pth` | Path inside container |
| `PYTHONUNBUFFERED` | ✅ | `1` | Unbuffered stdout for Docker logs |
| `NOAA_FETCH_INTERVAL_HOURS` | ⚪ | `6` | NOAA fetch frequency |
| `DATASET_INTERVAL_HOURS` | ⚪ | `24` | Dataset regeneration frequency |
| `INFERENCE_INTERVAL_HOURS` | ⚪ | `6` | GNN inference frequency |

---

## Health Checks

| Service | Command | Expected |
|---|---|---|
| **Backend** | `curl http://localhost/api/health` | `{"status":"ok","graph_loaded":true,...}` |
| **Frontend** | `curl http://localhost/health` | `healthy` |
| **Worker** | `docker compose exec worker pgrep -f worker_entrypoint.py` | Exit 0 |

---

## Worker Job Schedule

All three jobs run **immediately at startup**, then repeat on schedule:

- `noaa_solar_wind_fetch.py` — every **6 hours**
- `generate_lunar_hazard_dataset.py` — every **24 hours**
- `infer_live_hazards.py` — every **6 hours**

> **🚫 The GNN model is never retrained by the worker** — inference only.

---

## Persistent Model Volume

Both `backend` and `worker` share the Docker named volume `model_data` mounted at `/app/lunagraph_gcn_model.pth`.

```bash
# Replace model without rebuilding
docker cp ./backend/lunagraph_gcn_model.pth lunar_backend:/app/lunagraph_gcn_model.pth
docker compose restart backend worker
```

---

## Updating the Application

```bash
git pull
docker compose up -d --build          # rebuild all
docker compose up -d --build backend  # rebuild one service
```

---

## Troubleshooting

### Backend 503 / graph not loaded
```bash
docker compose logs backend | grep -iE "error|failed|database"
# Fix DATABASE_URL in .env then:
docker compose restart backend
```

### Worker exits immediately
```bash
docker compose logs worker
# Common cause: SUPABASE_URL or SUPABASE_KEY missing in .env
```

### Frontend blank page / 404 on refresh
```bash
docker compose up -d --build frontend
```

### `.pth` model not found inside container
```bash
ls backend/lunagraph_gcn_model.pth   # must exist on host
docker compose up -d --build backend
```

### Port 80 already in use
```bash
sudo systemctl stop apache2 && sudo systemctl disable apache2
docker compose up -d
```

### Disk space / image cleanup
```bash
docker system prune -af && docker system df
```

### View logs
```bash
docker compose logs -f                 # all services
docker compose logs --tail=100 worker  # last 100 lines of worker
```

---

## TLS / HTTPS (Optional)

Use a Cloudflare proxy (free plan) pointed at the VM's public IP on port 80, or install Certbot directly on the host VM and mount the certs into the frontend container for port 443.
