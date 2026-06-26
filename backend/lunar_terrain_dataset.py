import argparse
import io
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import rasterio
from rasterio.windows import Window
import requests
from supabase import create_client, Client
from dotenv import load_dotenv
from PIL import Image

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

WMTS_TILE_URL = (
    "https://trek.nasa.gov/tiles/Moon/EQ/LRO_WAC_Mosaic_Global_303ppd_v02/1.0.0/default/default028mm/{z}/{y}/{x}.jpg"
)

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [TERRAIN] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

# =========================================================
# LOLA DEM SETUP
# =========================================================

# Path to NASA LOLA DEM GeoTIFF (8.5 GB, memory-mapped via rasterio)
DEM_PATH = Path(__file__).resolve().parent.parent / "Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif"

_dem_dataset = None
_dem_transform = None
_dem_bounds = None
_dem_nodata = None
_dem_shape = None


def load_dem():
    """
    Open the LOLA DEM GeoTIFF once. Uses rasterio's memory-mapped
    file handle — the 8.5 GB raster is NOT loaded into RAM.
    """
    global _dem_dataset, _dem_transform, _dem_bounds, _dem_nodata, _dem_shape

    if not DEM_PATH.exists():
        logger.error("LOLA DEM not found at %s", DEM_PATH)
        logger.error("Download from: https://astrogeology.usgs.gov/search/details/Moon/LRO/LOLA/Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014")
        sys.exit(1)

    _dem_dataset = rasterio.open(str(DEM_PATH))
    _dem_transform = _dem_dataset.transform
    _dem_bounds = _dem_dataset.bounds
    _dem_nodata = _dem_dataset.nodata
    _dem_shape = _dem_dataset.shape

    logger.info("LOLA DEM loaded successfully: %s", DEM_PATH.name)
    logger.info("  CRS: %s", _dem_dataset.crs)
    logger.info("  Shape: %d rows × %d cols", _dem_shape[0], _dem_shape[1])
    logger.info("  Bounds: left=%.2f, bottom=%.2f, right=%.2f, top=%.2f",
                _dem_bounds.left, _dem_bounds.bottom,
                _dem_bounds.right, _dem_bounds.top)
    logger.info("  Pixel size: %.6f° (≈%.1f m at equator)",
                abs(_dem_transform.a), abs(_dem_transform.a) * 30.3)  # 1° ≈ 30.3 km on Moon
    logger.info("  NoData value: %s", _dem_nodata)
    logger.info("  Dtype: %s", _dem_dataset.dtypes[0])


def _latlon_to_pixel(lat: float, lon: float) -> tuple:
    """
    Convert geographic coordinates (lat, lon) to pixel coordinates
    (row, col) in the DEM raster using its affine transform.

    The LOLA Global DEM uses a simple cylindrical projection where:
    - X axis = longitude (-180 to 180)
    - Y axis = latitude (-90 to 90)
    """
    # rasterio's ~transform converts (x, y) -> (col, row)
    # For geographic CRS: x = longitude, y = latitude
    col, row = ~_dem_transform * (lon, lat)
    return int(round(row)), int(round(col))


def query_dem_elevation(lat: float, lon: float) -> float:
    """
    Query the LOLA DEM for elevation (meters) at a given lat/lon.
    Uses a windowed read to fetch only the single pixel needed.

    Returns 0.0 if coordinates fall outside DEM bounds.
    """
    if _dem_dataset is None:
        return 0.0

    row, col = _latlon_to_pixel(lat, lon)

    # Bounds check
    if row < 0 or row >= _dem_shape[0] or col < 0 or col >= _dem_shape[1]:
        return 0.0

    # Read a single pixel via windowed read (no RAM overhead)
    window = Window(col, row, 1, 1)
    try:
        data = _dem_dataset.read(1, window=window)
        value = float(data[0, 0])

        # Check for NoData
        if _dem_nodata is not None and value == _dem_nodata:
            return 0.0

        return value
    except Exception:
        return 0.0


def compute_slope(lat: float, lon: float) -> float:
    """
    Compute terrain slope (degrees) at a given lat/lon using the
    Horn algorithm on a 3×3 DEM neighborhood.

    Horn algorithm (same as GDAL gdaldem slope):
        dz/dx = ((c + 2f + i) - (a + 2d + g)) / (8 * cellsize_x)
        dz/dy = ((g + 2h + i) - (a + 2b + c)) / (8 * cellsize_y)
        slope = arctan(sqrt(dz_dx² + dz_dy²))

    Where the 3×3 window is:
        a  b  c
        d  e  f
        g  h  i

    Returns slope in degrees. Returns 0.0 if outside DEM bounds.
    """
    if _dem_dataset is None:
        return 0.0

    center_row, center_col = _latlon_to_pixel(lat, lon)

    # Need a 3×3 window, so center must be at least 1 pixel from edges
    if (center_row < 1 or center_row >= _dem_shape[0] - 1 or
            center_col < 1 or center_col >= _dem_shape[1] - 1):
        return 0.0

    # Read the 3×3 neighborhood
    window = Window(center_col - 1, center_row - 1, 3, 3)
    try:
        data = _dem_dataset.read(1, window=window).astype(float)
    except Exception:
        return 0.0

    # Check for NoData in any of the 9 cells
    if _dem_nodata is not None and np.any(data == _dem_nodata):
        return 0.0

    # Horn algorithm
    # Cell size in meters (DEM resolution ≈ 118 m per pixel)
    cellsize_x = abs(_dem_transform.a) * 30300.0  # degrees to meters (Moon: 1° ≈ 30.3 km)
    cellsize_y = abs(_dem_transform.e) * 30300.0

    a, b, c = data[0, 0], data[0, 1], data[0, 2]
    d, e, f = data[1, 0], data[1, 1], data[1, 2]
    g, h, i = data[2, 0], data[2, 1], data[2, 2]

    dz_dx = ((c + 2*f + i) - (a + 2*d + g)) / (8.0 * cellsize_x)
    dz_dy = ((g + 2*h + i) - (a + 2*b + c)) / (8.0 * cellsize_y)

    slope_rad = np.arctan(np.sqrt(dz_dx**2 + dz_dy**2))
    slope_deg = np.degrees(slope_rad)

    return float(slope_deg)


def fetch_tile(z: int, x: int, y: int, timeout: int = 30, retries: int = 3) -> Image.Image:
    url = WMTS_TILE_URL.format(z=z, x=x, y=y)
    last_exception = None

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            tile = Image.open(io.BytesIO(response.content)).convert("L")
            return tile
        except Exception as e:
            last_exception = e
            print(f"WARNING: fetch_tile attempt {attempt} failed for z={z} x={x} y={y}: {e}")

    raise RuntimeError(f"Unable to fetch tile after {retries} attempts: {last_exception}")


def split_into_patches(image: Image.Image, patch_rows: int, patch_cols: int):
    image_np = np.array(image, dtype=np.uint8)
    height, width = image_np.shape
    patch_height = height // patch_rows
    patch_width = width // patch_cols

    if patch_height <= 0 or patch_width <= 0:
        raise ValueError(
            f"Tile image too small for {patch_rows}x{patch_cols} patches: {width}x{height}"
        )

    for row in range(patch_rows):
        for col in range(patch_cols):
            y0 = row * patch_height
            x0 = col * patch_width
            patch = image_np[y0 : y0 + patch_height, x0 : x0 + patch_width]
            yield row, col, patch


def compute_features(patch: np.ndarray, lat: float, lon: float) -> dict:
    """
    Compute terrain features for a single image patch.

    - elevation: REAL meters from LOLA DEM (replaces patch.mean()/255)
    - slope: degrees from Horn algorithm on DEM neighborhood
    - roughness: image standard deviation (texture proxy)
    - crater_density: edge density via Canny filter
    - shadow_score: inverse of image brightness (1 = fully shadowed)
    """
    # Real elevation from LOLA DEM (meters above reference sphere)
    elevation = query_dem_elevation(lat, lon)

    # Slope from DEM neighborhood (degrees)
    slope = compute_slope(lat, lon)

    # Image-based features (still valid — they capture visual texture)
    roughness = float(patch.std()) / 255.0
    edges = cv2.Canny(patch, threshold1=50, threshold2=150)
    crater_density = float(np.count_nonzero(edges)) / float(edges.size)
    shadow_score = 1.0 - float(patch.mean()) / 255.0

    return {
        "elevation": elevation,
        "slope": slope,
        "roughness": roughness,
        "crater_density": crater_density,
        "shadow_score": shadow_score,
    }

def compute_patch_coordinates(
    zoom: int,
    tile_x: int,
    tile_y: int,
    patch_row: int,
    patch_col: int,
    patch_rows: int,
    patch_cols: int,
) -> tuple[float, float]:
    tile_count_x = 2**zoom
    tile_count_y = 2 ** (zoom - 1)
    patch_fraction_x = (tile_x + (patch_col + 0.5) / patch_cols) / tile_count_x
    patch_fraction_y = (tile_y + (patch_row + 0.5) / patch_rows) / tile_count_y

    longitude = patch_fraction_x * 360.0 - 180.0
    latitude = 90.0 - patch_fraction_y * 180.0
    return latitude, longitude

def insert_into_database(supabase: Client, rows: list[dict]):
    try:
        supabase.table("lunar_regions").upsert(rows).execute()
    except Exception as e:
        print(f"ERROR: Failed to insert data into Supabase: {e}")

def build_dataset(
    zoom: int,
    patch_rows: int,
    patch_cols: int,
    supabase: Client,
    max_tiles: int | None = None,
    start_x: int = 0,
    start_y: int = 0,
):
    tile_count_x = 2**zoom
    tile_count_y = 2 ** (zoom - 1)
    if start_x < 0 or start_y < 0:
        raise ValueError("start_x and start_y must both be non-negative")
    if start_x >= tile_count_x or start_y >= tile_count_y:
        raise ValueError(
            f"Start coordinate out of range for zoom {zoom}: "
            f"start_x={start_x}, start_y={start_y}, "
            f"max_x={tile_count_x-1}, max_y={tile_count_y-1}"
        )

    # Track elevation and slope ranges for logging
    all_elevations = []
    all_slopes = []

    tile_counter = 0
    inserted = 0

    for y in range(tile_count_y):
        if y < start_y:
            continue
        for x in range(tile_count_x):
            if y == start_y and x < start_x:
                continue
            if max_tiles is not None and tile_counter >= max_tiles:
                break

            print(f"Processing tile z={zoom}, x={x}, y={y}")
            tile_image = fetch_tile(zoom, x, y)
            tile_rows = []

            for patch_row, patch_col, patch in split_into_patches(
                tile_image, patch_rows, patch_cols
            ):
                latitude, longitude = compute_patch_coordinates(
                    zoom, x, y, patch_row, patch_col, patch_rows, patch_cols
                )
                features = compute_features(patch, latitude, longitude)

                all_elevations.append(features["elevation"])
                all_slopes.append(features["slope"])

                tile_rows.append(
                    {
                        "zoom": zoom,
                        "tile_x": x,
                        "tile_y": y,
                        "patch_row": patch_row,
                        "patch_col": patch_col,
                        "latitude": latitude,
                        "longitude": longitude,
                        "elevation": features["elevation"],
                        "slope": features["slope"],
                        "roughness": features["roughness"],
                        "crater_density": features["crater_density"],
                        "shadow_score": features["shadow_score"],
                    }
                )

            # Insert in chunks if needed, but 512 patches is usually fine for a single insert
            insert_into_database(supabase, tile_rows)
            
            tile_counter += 1
            inserted += len(tile_rows)
            print(f" Stored {len(tile_rows)} patches from tile x={x} y={y}")

        if max_tiles is not None and tile_counter >= max_tiles:
            break

    # Log elevation and slope ranges
    if all_elevations:
        logger.info("Elevation range: %.1f m to %.1f m (mean: %.1f m)",
                     min(all_elevations), max(all_elevations),
                     np.mean(all_elevations))
    if all_slopes:
        logger.info("Slope range: %.2f° to %.2f° (mean: %.2f°)",
                     min(all_slopes), max(all_slopes),
                     np.mean(all_slopes))

    print(
        f"Dataset generation complete: {inserted} lunar patch rows inserted "
        f"across {tile_counter} tiles."
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate lunar terrain region dataset from NASA Moon Trek WMTS tiles."
    )
    parser.add_argument("--zoom", type=int, default=4, help="Zoom level to iterate for the Moon WMTS tiles.")
    parser.add_argument(
        "--patch-rows",
        type=int,
        default=16,
        help="Number of patch rows to split each tile into.",
    )
    parser.add_argument(
        "--patch-cols",
        type=int,
        default=32,
        help="Number of patch columns to split each tile into.",
    )
    parser.add_argument(
        "--max-tiles",
        type=int,
        default=None,
        help="Maximum number of tiles to process, useful for testing.",
    )
    parser.add_argument(
        "--start-x",
        type=int,
        default=0,
        help="Starting tile X coordinate when resuming processing.",
    )
    parser.add_argument(
        "--start-y",
        type=int,
        default=0,
        help="Starting tile Y coordinate when resuming processing.",
    )
    return parser.parse_args()


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL or SUPABASE_KEY is not set in .env")
        sys.exit(1)

    # Load the LOLA DEM before processing tiles
    load_dem()

    args = parse_args()

    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as exc:
        print("ERROR: Could not initialize Supabase client:", exc)
        sys.exit(1)

    build_dataset(
        zoom=args.zoom,
        patch_rows=args.patch_rows,
        patch_cols=args.patch_cols,
        supabase=supabase,
        max_tiles=args.max_tiles,
        start_x=args.start_x,
        start_y=args.start_y,
    )

    # Close the DEM file handle
    if _dem_dataset is not None:
        _dem_dataset.close()
        logger.info("LOLA DEM file handle closed.")

if __name__ == "__main__":
    main()
