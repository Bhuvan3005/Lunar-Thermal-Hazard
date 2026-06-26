# Lunar Thermal Hazard Prediction & Mission Planning System

<div align="center">

**Real-time lunar hazard intelligence and autonomous rover route planning powered by Graph Neural Networks, A\* pathfinding, and live NOAA space weather data.**

[![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![PyTorch](https://img.shields.io/badge/PyTorch-Geometric-red?logo=pytorch)](https://pytorch-geometric.readthedocs.io)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react)](https://react.dev)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker)](https://docs.docker.com/compose/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

</div>

---

## Overview

LunaGraph is an end-to-end system that ingests NASA Moon terrain imagery and NOAA real-time space weather feeds, derives hazard predictions for every navigable cell on the lunar surface using a Graph Convolutional Network, and plans optimal rover routes through A\* search — all visualised on an interactive 3-D globe rendered with Three.js.

---

## Features

- **Real NASA terrain data** — LOLA DEM (118 m/px) elevation and Horn-algorithm slope per node
- **Live NOAA space weather** — solar wind plasma and magnetic field data refreshed every 6 hours
- **Graph Neural Network (GraphSAGE)** — classifies every lunar supernode as SAFE / MODERATE / HIGH / EXTREME
- **A\* Mission Planning** — three modes: shortest path, safest path, balanced
- **Interactive 3-D globe** — React + Three.js with clickable hazard nodes and glowing route tubes
- **Supabase PostgreSQL** — fully managed cloud database; no self-hosted Postgres required
- **Production Docker deployment** — single `docker compose up -d` on any Linux VM

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.12, FastAPI, Uvicorn |
| **ML** | PyTorch, PyTorch Geometric (GraphSAGE), scikit-learn |
| **Path Planning** | A\* with haversine great-circle heuristic |
| **Frontend** | React 18, Vite, Three.js, @react-three/fiber |
| **Database** | Supabase (PostgreSQL 15, managed cloud) |
| **Data Sources** | NASA Moon Trek WMTS, NASA LOLA DEM, NOAA SWPC REST API |
| **Containerisation** | Docker, Docker Compose, Nginx |

---

## Architecture

```
NASA Moon Trek WMTS tiles          NASA LOLA DEM (118 m/px)
        │                                    │
        └────────────┬───────────────────────┘
                     ▼
          lunar_terrain_dataset.py
          (elevation, slope, roughness, crater density, shadow score)
                     │
                     ▼
          noaa_solar_wind_fetch.py  ◄──── NOAA SWPC REST API
          (solar wind speed, plasma density, Bt, Bx, By, Bz)
                     │
                     ▼
          generate_lunar_hazard_dataset.py
          (composite hazard score → SAFE / MODERATE / HIGH / EXTREME labels)
                     │
                     ▼
          gnn_predictions.py  [offline training]
          (GraphSAGE: 3-layer, 64 hidden, class-balanced CE loss)
                     │
          lunagraph_gcn_model.pth
                     │
                     ▼
          infer_live_hazards.py  [worker, every 6 h]
          (live GNN inference → DB predictions)
                     │
                     ▼
          FastAPI  (route_api.py)
          ├── GET  /health
          ├── GET  /nodes
          └── POST /route  (A* planner)
                     │
                     ▼
          Supabase PostgreSQL
                     │
                     ▼
          React + Three.js
          (3-D globe, hazard overlays, route tube, analytics panels)
```

---

## Screenshots

> Place screenshots in the `assets/` folder and uncomment the lines below.

| View | Preview |
|---|---|
| 3-D Moon globe | `assets/screenshot_globe.png` |
| Hazard overlay | `assets/screenshot_hazards.png` |
| Route planning | `assets/screenshot_route.png` |
| Analytics panel | `assets/screenshot_analytics.png` |

---

## Installation

### Prerequisites

- Python 3.12+
- Node.js 20+
- A Supabase project (free tier works)
- NASA LOLA DEM file (see [Data](#data))

### 1. Clone

```bash
git clone https://github.com/<your-username>/Lunar_Thermal_Hazard.git
cd Lunar_Thermal_Hazard
```

### 2. Environment

```bash
cp .env.example .env
# Edit .env — fill in SUPABASE_URL, SUPABASE_KEY, DATABASE_URL
```

### 3. Backend

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cd backend
uvicorn route_api:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Frontend

```bash
cd frontend
cp .env.example .env   # set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY
npm install
npm run dev
```

---

## Docker Setup

Single-command production deployment:

```bash
cp .env.example .env   # fill in credentials
docker compose up -d
```

Services:
| Container | Port | Role |
|---|---|---|
| `lunar_backend` | 8000 (internal) | FastAPI + GNN inference |
| `lunar_frontend` | 80 | React SPA via Nginx |
| `lunar_worker` | — | Scheduled NOAA + inference jobs |

Health checks, log rotation, and graceful shutdown are pre-configured.

---

## Data

### NASA LOLA DEM

The `Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif` (~8.5 GB) is required for terrain processing. Download from:

> https://astrogeology.usgs.gov/search/details/Moon/LRO/LOLA/Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014

Place the file in the project root. It is excluded from Git via `.gitignore`.

### Running the Pipeline (first time)

```bash
# 1. Populate lunar_regions (fetch NASA tiles + LOLA elevation)
python backend/lunar_terrain_dataset.py --zoom 4

# 2. Fetch initial NOAA data
python backend/noaa_solar_wind_fetch.py

# 3. Build hazard nodes (aggregation + scoring)
python backend/generate_lunar_hazard_dataset.py

# 4. Train GNN (produces lunagraph_gcn_model.pth)
python backend/gnn_predictions.py

# 5. Run live inference
python backend/infer_live_hazards.py
```

---

## Project Structure

```
Lunar_Thermal_Hazard/
├── backend/
│   ├── route_api.py                  FastAPI app — /health, /nodes, /route
│   ├── graph_builder.py              Loads DB nodes, builds adjacency list
│   ├── pathfinding.py                A* with haversine heuristic
│   ├── infer_live_hazards.py         Live GNN inference → DB
│   ├── gnn_predictions.py            GNN training script (offline)
│   ├── generate_lunar_hazard_dataset.py  Hazard score computation
│   ├── lunar_terrain_dataset.py      NASA tile ingestion + LOLA DEM
│   ├── noaa_solar_wind_fetch.py      NOAA SWPC API ingestion
│   ├── supabase_client.py            Supabase client factory
│   ├── supabase_schema.sql           Supabase table definitions
│   ├── lunagraph_gcn_model.pth       Trained model weights (git-ignored)
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/MoonViewer.jsx  Main 3-D visualization + planning UI
│   │   ├── App.jsx
│   │   ├── main.jsx
│   │   └── styles.css
│   ├── nginx.conf                    SPA routing + /api proxy
│   ├── Dockerfile
│   └── package.json
├── worker/
│   └── Dockerfile
├── assets/                           Screenshots for README
├── docs/                             Architecture and schema docs
├── worker_entrypoint.py              APScheduler entry point
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .gitignore
├── LICENSE
└── README.md
```

---

## Data Pipeline

```
NASA Moon Trek WMTS  →  raw tile images (grayscale)
        │
        ▼  split into 16×32 patches per tile
        │  compute roughness, crater density, shadow score
        │  query LOLA DEM → real elevation + Horn slope
        ▼
lunar_regions (Supabase)

NOAA SWPC API  →  1-day plasma + mag JSON
        ▼
solar_wind_plasma, solar_wind_mag (Supabase)

lunar_regions + NOAA  →  2×2 patch aggregation → supernodes
        │  composite hazard score (6 physical + 3 spatial components)
        │  percentile-based SAFE/MODERATE/HIGH/EXTREME labels
        ▼
lunar_hazard_nodes (Supabase)

lunar_hazard_nodes  →  graph construction (8-directional edges)
        │  GraphSAGE training (150 epochs, class-balanced CE)
        ▼
lunagraph_gcn_model.pth

live: every 6 h → infer_live_hazards.py → update predictions in DB
        │
        ▼
FastAPI /nodes → React globe
```

---

## Machine Learning

### Graph Construction

Each supernode (2×2 aggregated patch, ~240 m × 240 m) becomes a graph node. Edges connect all 8 spatial neighbours within the same tile. Cross-tile boundary edges are added by matching border (super_row, super_col) values.

### Node Features (11-dimensional)

| Feature | Source |
|---|---|
| elevation | NASA LOLA DEM (metres) |
| roughness | image standard deviation |
| crater_density | Canny edge density |
| shadow_score | 1 − mean brightness |
| illumination | 1 − shadow_score |
| solar_wind_speed | NOAA plasma (km/s) |
| plasma_density | NOAA plasma (p/cm³) |
| magnetic_field_bt | NOAA mag (nT) |
| bx_gsm, by_gsm, bz_gsm | NOAA mag (nT) |

### GNN Architecture

```
Input (11 features)
    └── SAGEConv(11→64) → BatchNorm → ReLU → Dropout(0.3)
    └── SAGEConv(64→64) → BatchNorm → ReLU → Dropout(0.3)
    └── SAGEConv(64→4)
Output: SAFE / MODERATE / HIGH / EXTREME
```

Training uses inverse-frequency class weights to address severe label imbalance (SAFE nodes dominate).

---

## Mission Planning

### A\* Algorithm

The planner uses the pre-built adjacency graph from `graph_builder.py` and finds the optimal path between any two nodes on the lunar surface.

### Cost Function

```
edge_cost = distance_weight × geographic_distance_km
          + hazard_weight   × hazard_score_of_destination_node
```

### Planning Modes

| Mode | `distance_weight` | `hazard_weight` |
|---|---|---|
| `shortest` | 1.0 | 0.0 |
| `safest` | 0.2 | 1.0 |
| `balanced` | 1.0 | 1.0 |

### Heuristic

Admissible haversine great-circle distance to the goal on the Moon (radius = 1737.4 km), scaled by `distance_weight` to guarantee optimality.

---

## API Endpoints

### `GET /health`

Liveness probe. Returns graph statistics.

```json
{
  "status": "ok",
  "graph_loaded": true,
  "node_count": 12288,
  "edge_count": 94032,
  "available_modes": ["shortest", "safest", "balanced"]
}
```

### `GET /nodes`

Returns all navigable nodes for frontend rendering.

```json
[
  {
    "node_id": 0,
    "latitude": 12.34,
    "longitude": -45.67,
    "hazard_label": "SAFE",
    "hazard_score": 0.231
  }
]
```

### `POST /route`

Plan an optimal rover route.

**Request**
```json
{
  "start_node_id": 42,
  "goal_node_id": 1337,
  "mode": "balanced"
}
```

**Response**
```json
{
  "path": [42, 43, 89, ...],
  "path_details": [{ "node_id": 42, "latitude": 12.34, "longitude": -45.67, ... }],
  "distance_km": 84.3,
  "risk_score": 12.7,
  "estimated_cost": 96.9,
  "nodes_visited": 4210,
  "mode": "balanced",
  "avg_hazard_score": 0.182,
  "node_count": 31
}
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SUPABASE_URL` | ✅ | Supabase project REST URL |
| `SUPABASE_KEY` | ✅ | Supabase anon / service-role key |
| `DATABASE_URL` | ✅ | PostgreSQL connection string (for SQLAlchemy) |
| `MODEL_PATH` | ✅ | Path to `.pth` inside container |
| `VITE_SUPABASE_URL` | ✅ | Supabase URL injected at frontend build time |
| `VITE_SUPABASE_ANON_KEY` | ✅ | Supabase anon key for frontend |
| `PORT` | ⚪ | Backend port (default: 8000) |
| `PYTHONUNBUFFERED` | ⚪ | Set to `1` for immediate Docker log output |
| `NOAA_FETCH_INTERVAL_HOURS` | ⚪ | Worker NOAA fetch frequency (default: 6) |
| `DATASET_INTERVAL_HOURS` | ⚪ | Worker dataset regen frequency (default: 24) |
| `INFERENCE_INTERVAL_HOURS` | ⚪ | Worker inference frequency (default: 6) |

---

## Future Improvements

- **Explainable AI** — GNN attention weights overlaid on the globe to show which features drive each hazard classification
- **Multi-rover coordination** — joint A\* planning to prevent route conflicts between concurrent missions
- **Temporal forecasting** — replace static NOAA snapshot with a time-series model (LSTM / Temporal GNN) for predictive hazard evolution
- **Uncertainty quantification** — MC-Dropout or ensemble inference to provide confidence intervals on hazard labels
- **Oracle Cloud / Azure CI/CD** — automated pipeline via GitHub Actions deploying to a cloud VM on every push
- **Offline terrain tiles** — cache NASA WMTS tiles locally to support air-gapped deployment

---

## License

[MIT](LICENSE)

---

## Author

**Bhuvan**  
B.Tech Computer Science  
[GitHub](https://github.com/Bhuvan3005) · [LinkedIn](https://linkedin.com/in/bhuvanm3005)

> *Built to demonstrate the intersection of planetary science, graph machine learning, and real-time data engineering.*
