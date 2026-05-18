"# Lunar-Thermal-Hazard

## Overview

This project now integrates NASA Moon Trek WMTS services for real-time lunar terrain visualization and graph-based thermal intelligence.

### Features

- WMTS GetCapabilities XML parsing from NASA Moon Trek
- Dynamic tile streaming for lunar terrain mosaics and DEM layers
- CesiumJS-powered Moon globe with NASA lunar texture overlays
- Terrain patch graph construction using grid-based node segmentation
- NetworkX graph generation with elevation, roughness, crater density, and shadow-prone features
- AI thermal hazard scoring using a PyTorch model skeleton
- FastAPI backend proxy for WMTS tiles and terrain intelligence endpoints

## Backend Setup

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Run the FastAPI server:

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Available backend endpoints:

- `GET /api/wmts/capabilities`
- `GET /api/wmts/tile/{Style}/{TileMatrixSet}/{TileMatrix}/{TileRow}/{TileCol}.png`
- `GET /api/terrain/graph`
- `GET /api/terrain/heatmap`
- `GET /api/terrain/primary-layer`

## Frontend Setup

Install frontend dependencies and run the React dashboard:

```bash
cd frontend
npm install
npm run dev
```

Open the displayed Vite URL to view the interactive Moon globe and thermal hazard dashboard.

## Notes

- The primary Moon texture source is configured for `LRO_WAC_Mosaic_Global_303ppd_v02`.
- The graph generator uses a 16x32 patch grid for terrain-aware nodes and adjacency edges.
- The thermal hazard overlay is drawn dynamically on top of NASA lunar tiles.
" 
