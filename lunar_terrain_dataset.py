import argparse
import io
import os
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
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


def compute_features(patch: np.ndarray) -> dict:
    elevation = float(patch.mean()) / 255.0
    roughness = float(patch.std()) / 255.0
    edges = cv2.Canny(patch, threshold1=50, threshold2=150)
    crater_density = float(np.count_nonzero(edges)) / float(edges.size)
    shadow_score = 1.0 - float(patch.mean()) / 255.0

    return {
        "elevation": elevation,
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
                features = compute_features(patch)
                latitude, longitude = compute_patch_coordinates(
                    zoom, x, y, patch_row, patch_col, patch_rows, patch_cols
                )
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

if __name__ == "__main__":
    main()
