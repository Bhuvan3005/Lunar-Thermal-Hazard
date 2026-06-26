# Database Schema

All tables live in a Supabase (PostgreSQL 15) managed cloud database.
Run `backend/supabase_schema.sql` in the Supabase SQL Editor to initialise.

---

## lunar_regions

Raw terrain patches extracted from NASA Moon Trek WMTS tiles.
Populated by `lunar_terrain_dataset.py`.

| Column | Type | Description |
|---|---|---|
| id | BIGSERIAL PK | Auto-incrementing row ID |
| zoom | INTEGER | WMTS zoom level |
| tile_x | INTEGER | WMTS tile X index |
| tile_y | INTEGER | WMTS tile Y index |
| patch_row | INTEGER | Patch row within tile |
| patch_col | INTEGER | Patch column within tile |
| latitude | DOUBLE PRECISION | Patch centroid latitude |
| longitude | DOUBLE PRECISION | Patch centroid longitude |
| elevation | DOUBLE PRECISION | LOLA DEM elevation (metres) |
| slope | DOUBLE PRECISION | Horn-algorithm slope (degrees) |
| roughness | DOUBLE PRECISION | Image std dev / 255 |
| crater_density | DOUBLE PRECISION | Canny edge density |
| shadow_score | DOUBLE PRECISION | 1 − mean brightness |
| created_at | TIMESTAMPTZ | Insert timestamp |

**Unique constraint**: (zoom, tile_x, tile_y, patch_row, patch_col)

---

## solar_wind_plasma

1-day solar wind plasma measurements from NOAA SWPC.
Populated by `noaa_solar_wind_fetch.py` every 6 hours.

| Column | Type | Description |
|---|---|---|
| id | BIGSERIAL PK | |
| time_tag | TIMESTAMPTZ UNIQUE | Measurement timestamp (UTC) |
| density | REAL | Proton density (p/cm³) |
| speed | REAL | Solar wind speed (km/s) |
| temperature | REAL | Proton temperature (K) |
| fetched_at | TIMESTAMPTZ | Ingest timestamp |

---

## solar_wind_mag

1-day solar wind magnetic field measurements from NOAA SWPC.

| Column | Type | Description |
|---|---|---|
| id | BIGSERIAL PK | |
| time_tag | TIMESTAMPTZ UNIQUE | Measurement timestamp (UTC) |
| bx_gsm | REAL | Bx in GSM coordinates (nT) |
| by_gsm | REAL | By in GSM coordinates (nT) |
| bz_gsm | REAL | Bz in GSM coordinates (nT) |
| lon_gsm | REAL | GSM longitude (degrees) |
| lat_gsm | REAL | GSM latitude (degrees) |
| bt | REAL | Total field magnitude (nT) |
| fetched_at | TIMESTAMPTZ | Ingest timestamp |

---

## lunar_hazard_nodes

Aggregated supernodes with computed hazard scores and GNN predictions.
Populated by `generate_lunar_hazard_dataset.py`; predictions updated by `infer_live_hazards.py`.

| Column | Type | Description |
|---|---|---|
| node_id | BIGINT | Sequential node identifier |
| zoom / tile_x / tile_y | INTEGER | Source tile coordinates |
| super_row / super_col | INTEGER | Supernode grid position within tile |
| latitude / longitude | REAL | Supernode centroid coordinates |
| elevation | REAL | LOLA elevation (metres) |
| slope | REAL | Horn slope (degrees) |
| roughness | REAL | Terrain texture proxy |
| crater_density | REAL | Edge density proxy for craters |
| shadow_score | REAL | Shadow fraction |
| illumination | REAL | 1 − shadow_score |
| solar_wind_speed | REAL | Snapshot from NOAA (km/s) |
| plasma_density | REAL | Snapshot from NOAA (p/cm³) |
| temperature | REAL | Snapshot from NOAA (K) |
| magnetic_field_bt | REAL | Total field magnitude (nT) |
| bx_gsm / by_gsm / bz_gsm | REAL | Field components (nT) |
| hazard_score | REAL | Composite score in [0, 1] |
| hazard_label | TEXT | SAFE / MODERATE / HIGH / EXTREME |
| gnn_prediction | TEXT | Live GNN-predicted label |
| prediction_confidence | REAL | Softmax confidence for predicted class |
| updated_at | TIMESTAMP | Last inference update |
