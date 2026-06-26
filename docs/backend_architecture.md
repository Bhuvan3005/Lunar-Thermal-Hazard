# Backend Architecture

## Overview

The backend is a FastAPI application that serves two concerns:

1. **Navigation API** — loads the lunar hazard graph at startup and exposes HTTP endpoints for node listing and A\* route planning.
2. **Data pipeline scripts** — a set of standalone Python modules that ingest terrain and space weather data, compute hazard scores, and train/run the GNN.

---

## Module Map

```
backend/
├── route_api.py               FastAPI app — startup, CORS, endpoints
├── graph_builder.py           DB loader → adjacency list cache
├── pathfinding.py             A* search (haversine heuristic)
├── supabase_client.py         Supabase client factory
│
├── lunar_terrain_dataset.py   Pipeline stage 1 — NASA tile ingestion
├── noaa_solar_wind_fetch.py   Pipeline stage 2 — NOAA space weather
├── generate_lunar_hazard_dataset.py  Pipeline stage 3 — hazard scoring
├── gnn_predictions.py         Pipeline stage 4 — GNN training (offline)
├── infer_live_hazards.py      Pipeline stage 5 — live inference (worker)
│
└── supabase_schema.sql        Supabase table DDL reference
```

---

## Startup Sequence

```
uvicorn route_api:app
    │
    ▼
lifespan() context manager
    │
    ├── graph_builder.load_graph()
    │       └── SELECT * FROM lunar_hazard_nodes  (SQLAlchemy)
    │       └── build adjacency list  (8-directional + cross-tile edges)
    │       └── cache in module-level _graph, _nodes_by_id
    │
    └── FastAPI ready — serves /health, /nodes, /route
```

---

## Request Flow — POST /route

```
Client POST /route { start_node_id, goal_node_id, mode }
    │
    ▼
route_api.plan_route()
    └── _require_graph()           — 503 if graph not loaded
    └── astar(start, goal, graph)
            └── PLANNING_MODES[mode]   — distance/hazard weights
            └── heapq min-heap         — f = g + h
            └── haversine heuristic    — great-circle distance
            └── _edge_cost()           — dist_w * km + hazard_w * score
    └── PathResult → RouteResponse
```

---

## Graph Builder

The graph is built once at startup and cached in memory for the lifetime of the process.

- **Intra-tile edges**: each node connects to up to 8 spatial neighbours via `(tile_x, tile_y, super_row±1, super_col±1)` lookup.
- **Cross-tile edges**: right/bottom/diagonal boundary nodes are linked to adjacent tiles' border nodes.
- **Edge weight**: pre-computed haversine distance (km) between node centroids on the Moon (R = 1737.4 km).

---

## Hazard Score

Each node's hazard score is a weighted sum of normalised physical quantities:

```
score = 0.25 * illumination
      + 0.20 * solar_wind_speed / 800
      + 0.12 * plasma_density / 20
      + 0.13 * |Bt| / 15
      + 0.15 * roughness
      + 0.15 * slope / 30°
      + spatial_correction(lat, lon, terrain)
```

Labels are assigned by percentile thresholds on the score distribution:
- SAFE     < p50
- MODERATE < p85
- HIGH     < p95
- EXTREME  ≥ p95
