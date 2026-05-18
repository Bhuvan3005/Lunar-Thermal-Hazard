import argparse
import io
import os
import sys
from datetime import datetime

import cv2
import numpy as np
import psycopg2
import requests
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

DATABASE_URL = "https://eujmzfwoxtbbzcjabifq.supabase.co"
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


def create_lunar_regions_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS lunar_regions (
            id SERIAL PRIMARY KEY,
            zoom INTEGER NOT NULL,
            tile_x INTEGER NOT NULL,
            tile_y INTEGER NOT NULL,
            patch_row INTEGER NOT NULL,
            patch_col INTEGER NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            elevation REAL NOT NULL,
            roughness REAL NOT NULL,
            crater_density REAL NOT NULL,
            shadow_score REAL NOT NULL,
            inserted_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )
        """
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_lunar_regions_tile_patch "
        "ON lunar_regions (zoom, tile_x, tile_y, patch_row, patch_col)"
    )


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


def insert_into_database(connection, rows):
    with connection.cursor() as cursor:
        create_lunar_regions_table(cursor)
        insert_query = (
            "INSERT INTO lunar_regions "
            "(zoom, tile_x, tile_y, patch_row, patch_col, latitude, longitude, "
            "elevation, roughness, crater_density, shadow_score) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        )
        cursor.executemany(insert_query, rows)
        connection.commit()


def build_dataset(
    zoom: int,
    patch_rows: int,
    patch_cols: int,
    connection,
    max_tiles: int | None = None,
):
    tile_count_x = 2**zoom
    tile_count_y = 2 ** (zoom - 1)
    tile_counter = 0
    inserted = 0

    for y in range(tile_count_y):
        for x in range(tile_count_x):
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
                    (
                        zoom,
                        x,
                        y,
                        patch_row,
                        patch_col,
                        latitude,
                        longitude,
                        features["elevation"],
                        features["roughness"],
                        features["crater_density"],
                        features["shadow_score"],
                    )
                )

            insert_into_database(connection, tile_rows)
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
    return parser.parse_args()


def main():
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL is not set in .env")
        sys.exit(1)

    args = parse_args()

    try:
        connection = psycopg2.connect(DATABASE_URL)
    except Exception as exc:
        print("ERROR: Could not connect to the PostgreSQL database:", exc)
        sys.exit(1)

    try:
        build_dataset(
            zoom=args.zoom,
            patch_rows=args.patch_rows,
            patch_cols=args.patch_cols,
            connection=connection,
            max_tiles=args.max_tiles,
        )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
