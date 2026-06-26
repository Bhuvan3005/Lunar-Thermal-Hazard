"""
generate_lunar_hazard_dataset.py
=================================
Pipeline stage 3: Builds the lunar_hazard_nodes table in Supabase.

Reads lunar_regions + latest NOAA solar wind tables, aggregates raw patches into
supernodes, computes a composite hazard score per node, and writes the result to
lunar_hazard_nodes.

Pipeline: lunar_terrain_dataset → noaa_solar_wind_fetch → [THIS] → gnn_predictions
"""

import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from dotenv import load_dotenv
from psycopg2.extras import execute_batch
from rasterio.windows import Window
from sqlalchemy import create_engine

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [HAZARD_GEN] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

DEM_PATH = Path(__file__).resolve().parent.parent / "Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif"
AGG_PATCH_ROWS = 2
AGG_PATCH_COLS = 2

_dem_dataset = None
_dem_transform = None
_dem_nodata = None
_dem_shape = None


def load_dem() -> None:
    """Open the LOLA DEM GeoTIFF via rasterio memory-mapping (no RAM overhead)."""
    global _dem_dataset, _dem_transform, _dem_nodata, _dem_shape
    if not DEM_PATH.exists():
        logger.error("LOLA DEM not found at %s", DEM_PATH)
        sys.exit(1)
    _dem_dataset = rasterio.open(str(DEM_PATH))
    _dem_transform = _dem_dataset.transform
    _dem_nodata = _dem_dataset.nodata
    _dem_shape = _dem_dataset.shape
    logger.info("LOLA DEM loaded: %s (%d×%d pixels)", DEM_PATH.name, *_dem_shape)


def _latlon_to_pixel(lat: float, lon: float) -> tuple[int, int]:
    """Convert geographic (lat, lon) to DEM raster pixel (row, col)."""
    col, row = ~_dem_transform * (lon, lat)
    return int(round(row)), int(round(col))


def query_dem_elevation(lat: float, lon: float) -> float:
    """Return LOLA DEM elevation in metres at the given lat/lon, or 0.0 on miss."""
    if _dem_dataset is None:
        return 0.0
    row, col = _latlon_to_pixel(lat, lon)
    if row < 0 or row >= _dem_shape[0] or col < 0 or col >= _dem_shape[1]:
        return 0.0
    try:
        data = _dem_dataset.read(1, window=Window(col, row, 1, 1))
        v = float(data[0, 0])
        return 0.0 if (_dem_nodata is not None and v == _dem_nodata) else v
    except Exception:
        return 0.0


def compute_slope(lat: float, lon: float) -> float:
    """
    Compute terrain slope (degrees) using the Horn algorithm on a 3×3 DEM window.

    Horn's formula (same as GDAL gdaldem):
        dz/dx = ((c+2f+i) - (a+2d+g)) / (8*cellsize_x)
        dz/dy = ((g+2h+i) - (a+2b+c)) / (8*cellsize_y)
        slope  = arctan(sqrt(dz_dx² + dz_dy²))
    """
    if _dem_dataset is None:
        return 0.0
    cr, cc = _latlon_to_pixel(lat, lon)
    if cr < 1 or cr >= _dem_shape[0] - 1 or cc < 1 or cc >= _dem_shape[1] - 1:
        return 0.0
    try:
        data = _dem_dataset.read(1, window=Window(cc - 1, cr - 1, 3, 3)).astype(float)
    except Exception:
        return 0.0
    if _dem_nodata is not None and np.any(data == _dem_nodata):
        return 0.0
    # 1 degree ≈ 30.3 km on the Moon
    cx = abs(_dem_transform.a) * 30_300.0
    cy = abs(_dem_transform.e) * 30_300.0
    a, b, c = data[0]; d, _, f = data[1]; g, h, i = data[2]
    dz_dx = ((c + 2*f + i) - (a + 2*d + g)) / (8.0 * cx)
    dz_dy = ((g + 2*h + i) - (a + 2*b + c)) / (8.0 * cy)
    return float(np.degrees(np.arctan(np.sqrt(dz_dx**2 + dz_dy**2))))


def load_inputs(engine) -> tuple[pd.DataFrame, dict]:
    """Load lunar_regions and latest NOAA rows from the database."""
    lunar_df = pd.read_sql("SELECT * FROM lunar_regions", engine)
    logger.info("Loaded %d lunar region patches.", len(lunar_df))
    if lunar_df.empty:
        logger.error("lunar_regions is empty — run lunar_terrain_dataset.py first.")
        sys.exit(1)

    mag_df = pd.read_sql("SELECT * FROM solar_wind_mag ORDER BY time_tag DESC LIMIT 1", engine)
    plasma_df = pd.read_sql("SELECT * FROM solar_wind_plasma ORDER BY time_tag DESC LIMIT 1", engine)

    if mag_df.empty:
        logger.warning("solar_wind_mag empty — using zero defaults for magnetic fields.")
        bx_gsm = by_gsm = bz_gsm = bt = 0.0
    else:
        r = mag_df.iloc[0]
        bx_gsm, by_gsm, bz_gsm, bt = (
            float(r["bx_gsm"] or 0), float(r["by_gsm"] or 0),
            float(r["bz_gsm"] or 0), float(r["bt"] or 0),
        )

    if plasma_df.empty:
        logger.warning("solar_wind_plasma empty — using typical quiet-Sun defaults.")
        speed, density, temperature = 400.0, 5.0, 100_000.0
    else:
        r = plasma_df.iloc[0]
        speed = float(r["speed"] or 400.0)
        density = float(r["density"] or 5.0)
        temperature = float(r["temperature"] or 100_000.0)

    return lunar_df, dict(
        speed=speed, density=density, temperature=temperature,
        bt=bt, bx_gsm=bx_gsm, by_gsm=by_gsm, bz_gsm=bz_gsm,
    )


def aggregate_supernodes(lunar_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 2×2 raw patches into a single supernode by averaging."""
    lunar_df["super_row"] = lunar_df["patch_row"] // AGG_PATCH_ROWS
    lunar_df["super_col"] = lunar_df["patch_col"] // AGG_PATCH_COLS
    agg = (
        lunar_df.groupby(["zoom", "tile_x", "tile_y", "super_row", "super_col"])
        .agg(latitude=("latitude", "mean"), longitude=("longitude", "mean"),
             elevation=("elevation", "mean"), roughness=("roughness", "mean"),
             crater_density=("crater_density", "mean"), shadow_score=("shadow_score", "mean"))
        .reset_index()
    )
    logger.info("Aggregated %d supernodes from %d patches.", len(agg), len(lunar_df))
    return agg


def enrich_with_dem(agg: pd.DataFrame) -> pd.DataFrame:
    """Replace patch-averaged elevation with real LOLA values and add slope."""
    logger.info("Querying LOLA DEM for %d supernode centroids…", len(agg))
    elevs, slopes = [], []
    for _, row in agg.iterrows():
        elevs.append(query_dem_elevation(row["latitude"], row["longitude"]))
        slopes.append(compute_slope(row["latitude"], row["longitude"]))
    agg["elevation"] = elevs
    agg["slope"] = slopes
    return agg


def compute_hazard_scores(agg: pd.DataFrame, noaa: dict) -> pd.DataFrame:
    """
    Compute a composite hazard score in [0, 1] for each supernode.

    Primary components (weights):
        illumination (1 - shadow)   25%   — shadowed areas hide hazards
        solar wind speed (norm)     20%   — high speed increases radiation
        plasma density (norm)       12%   — higher density = more ionisation
        magnetic field Bt (norm)    13%   — field strength proxy for radiation shielding
        surface roughness           15%   — image-derived texture proxy
        terrain slope (norm/30°)    15%   — >30° considered impassable for rovers

    Spatial structure correction:
        polar latitude factor        15%   — cos(lat); poles are inherently riskier
        longitudinal terminator wave 10%   — terminator zone oscillates risk
        terrain risk composite       25%   — roughness + shadow + craters + slope
    """
    agg["solar_wind_speed"]  = noaa["speed"]
    agg["plasma_density"]    = noaa["density"]
    agg["temperature"]       = noaa["temperature"]
    agg["magnetic_field_bt"] = noaa["bt"]
    agg["bx_gsm"] = noaa["bx_gsm"]
    agg["by_gsm"] = noaa["by_gsm"]
    agg["bz_gsm"] = noaa["bz_gsm"]
    agg["illumination"] = 1.0 - agg["shadow_score"]

    slope_norm   = (agg["slope"] / 30.0).clip(0, 1)
    speed_norm   = (agg["solar_wind_speed"] / 800.0).clip(0, 1)
    density_norm = (agg["plasma_density"] / 20.0).clip(0, 1)
    bt_norm      = (np.abs(agg["magnetic_field_bt"]) / 15.0).clip(0, 1)

    agg["hazard_score"] = (
        0.25 * agg["illumination"]
        + 0.20 * speed_norm
        + 0.12 * density_norm
        + 0.13 * bt_norm
        + 0.15 * agg["roughness"]
        + 0.15 * slope_norm
    ).clip(0.0, 1.0)

    lat_norm     = np.cos(np.radians(agg["latitude"]))
    lon_wave     = (np.sin(np.radians(agg["longitude"] * 2)) + 1) / 2
    terrain_risk = (
        0.40 * agg["roughness"] + 0.25 * agg["shadow_score"]
        + 0.15 * agg["crater_density"] + 0.20 * slope_norm
    )
    agg["hazard_score"] = (
        agg["hazard_score"] + 0.15 * lat_norm + 0.10 * lon_wave + 0.25 * terrain_risk
    ).clip(0.0, 1.0)

    return agg


def assign_hazard_labels(agg: pd.DataFrame) -> pd.DataFrame:
    """
    Assign four-class hazard labels using percentile thresholds.
        SAFE     < p50  |  MODERATE < p85  |  HIGH < p95  |  EXTREME >= p95
    """
    q50, q85, q95 = (agg["hazard_score"].quantile(p) for p in (0.50, 0.85, 0.95))

    def _classify(s):
        if s < q50: return "SAFE"
        if s < q85: return "MODERATE"
        if s < q95: return "HIGH"
        return "EXTREME"

    agg["hazard_label"] = agg["hazard_score"].apply(_classify)
    agg["node_id"] = np.arange(len(agg))
    logger.info("Label counts:\n%s", agg["hazard_label"].value_counts().to_string())
    return agg


def ensure_schema(conn) -> None:
    """Create required tables and add any missing columns (idempotent)."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS solar_wind_mag (
                id BIGSERIAL PRIMARY KEY, time_tag TIMESTAMPTZ UNIQUE,
                bx_gsm REAL, by_gsm REAL, bz_gsm REAL,
                lon_gsm REAL, lat_gsm REAL, bt REAL,
                fetched_at TIMESTAMPTZ DEFAULT NOW())""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS solar_wind_plasma (
                id BIGSERIAL PRIMARY KEY, time_tag TIMESTAMPTZ UNIQUE,
                density REAL, speed REAL, temperature REAL,
                fetched_at TIMESTAMPTZ DEFAULT NOW())""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS lunar_hazard_nodes (
                node_id BIGINT, created_at TIMESTAMP DEFAULT NOW(),
                zoom INTEGER, tile_x INTEGER, tile_y INTEGER,
                super_row INTEGER, super_col INTEGER,
                latitude REAL, longitude REAL,
                elevation REAL, slope REAL, roughness REAL,
                crater_density REAL, shadow_score REAL, illumination REAL,
                solar_wind_speed REAL, plasma_density REAL, temperature REAL,
                magnetic_field_bt REAL, bx_gsm REAL, by_gsm REAL, bz_gsm REAL,
                hazard_score REAL, hazard_label TEXT)""")
        cur.execute("ALTER TABLE lunar_hazard_nodes ADD COLUMN IF NOT EXISTS slope REAL")
    conn.commit()


def write_hazard_nodes(conn, agg: pd.DataFrame) -> None:
    """Truncate and repopulate lunar_hazard_nodes."""
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE lunar_hazard_nodes")

    records = [
        (int(r.node_id), int(r.zoom), int(r.tile_x), int(r.tile_y),
         int(r.super_row), int(r.super_col),
         float(r.latitude), float(r.longitude), float(r.elevation), float(r.slope),
         float(r.roughness), float(r.crater_density), float(r.shadow_score),
         float(r.illumination), float(r.solar_wind_speed), float(r.plasma_density),
         float(r.temperature), float(r.magnetic_field_bt),
         float(r.bx_gsm), float(r.by_gsm), float(r.bz_gsm),
         float(r.hazard_score), str(r.hazard_label))
        for r in agg.itertuples()
    ]

    with conn.cursor() as cur:
        execute_batch(cur, """
            INSERT INTO lunar_hazard_nodes (
                node_id, zoom, tile_x, tile_y, super_row, super_col,
                latitude, longitude, elevation, slope, roughness, crater_density,
                shadow_score, illumination, solar_wind_speed, plasma_density, temperature,
                magnetic_field_bt, bx_gsm, by_gsm, bz_gsm, hazard_score, hazard_label
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, records, page_size=1000)
    conn.commit()
    logger.info("Inserted %d hazard nodes into lunar_hazard_nodes.", len(records))


def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL is not configured.")
        sys.exit(1)

    load_dem()
    engine = create_engine(database_url)
    conn = engine.raw_connection()
    try:
        ensure_schema(conn)
        lunar_df, noaa = load_inputs(engine)
        agg = aggregate_supernodes(lunar_df)
        agg = enrich_with_dem(agg)
        agg = compute_hazard_scores(agg, noaa)
        agg = assign_hazard_labels(agg)
        write_hazard_nodes(conn, agg)
        logger.info("Hazard dataset generation complete.")
    finally:
        conn.close()
        engine.dispose()
        if _dem_dataset is not None:
            _dem_dataset.close()


if __name__ == "__main__":
    main()