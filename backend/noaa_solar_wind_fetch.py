"""
noaa_solar_wind_fetch.py
=========================
Pipeline stage 2: Fetch and store NOAA solar wind data.

Pulls the latest 24 hours of solar wind plasma and magnetic field data from
NOAA's Space Weather Prediction Center REST API and upserts it into Supabase.

Inputs:  NOAA SWPC public JSON endpoints (no API key required)
Outputs: solar_wind_plasma, solar_wind_mag tables in Supabase

Pipeline: lunar_terrain_dataset → [THIS] → generate_lunar_hazard_dataset
"""

import logging
import os
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [NOAA] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

PLASMA_URL = "https://services.swpc.noaa.gov/products/solar-wind/plasma-1-day.json"
MAG_URL    = "https://services.swpc.noaa.gov/products/solar-wind/mag-1-day.json"


def _get_supabase_client() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        logger.error("SUPABASE_URL or SUPABASE_KEY is not set.")
        sys.exit(1)
    return create_client(url, key)


def _parse_float(value) -> float | None:
    """Safely coerce a NOAA JSON value to float, returning None on failure."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_timestamp(value: str | None) -> str | None:
    """Parse NOAA timestamp strings to ISO-8601 format."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).isoformat()
        except ValueError:
            continue
    return None


def _fetch_json(url: str) -> list | None:
    """Fetch a JSON list from a NOAA endpoint. Returns None on failure."""
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error("Failed to fetch %s: %s", url, exc)
        return None


def fetch_plasma_data(supabase: Client) -> int:
    """
    Fetch 24 h solar wind plasma data and upsert into solar_wind_plasma.

    Returns the number of records upserted.
    """
    data = _fetch_json(PLASMA_URL)
    if not data or len(data) < 2:
        logger.warning("No plasma data returned from NOAA.")
        return 0

    headers, rows = data[0], data[1:]
    fetched_at = datetime.now(timezone.utc).isoformat()
    records = [
        {
            "time_tag":   _parse_timestamp(dict(zip(headers, row)).get("time_tag")),
            "density":    _parse_float(dict(zip(headers, row)).get("density")),
            "speed":      _parse_float(dict(zip(headers, row)).get("speed")),
            "temperature": _parse_float(dict(zip(headers, row)).get("temperature")),
            "fetched_at": fetched_at,
        }
        for row in rows
    ]

    try:
        supabase.table("solar_wind_plasma").upsert(records).execute()
        logger.info("Upserted %d plasma records.", len(records))
        return len(records)
    except Exception as exc:
        logger.error("Failed to upsert plasma data: %s", exc)
        return 0


def fetch_mag_data(supabase: Client) -> int:
    """
    Fetch 24 h solar wind magnetic field data and upsert into solar_wind_mag.

    Returns the number of records upserted.
    """
    data = _fetch_json(MAG_URL)
    if not data or len(data) < 2:
        logger.warning("No magnetic field data returned from NOAA.")
        return 0

    headers, rows = data[0], data[1:]
    fetched_at = datetime.now(timezone.utc).isoformat()
    records = [
        {
            "time_tag": _parse_timestamp(dict(zip(headers, row)).get("time_tag")),
            "bx_gsm":  _parse_float(dict(zip(headers, row)).get("bx_gsm")),
            "by_gsm":  _parse_float(dict(zip(headers, row)).get("by_gsm")),
            "bz_gsm":  _parse_float(dict(zip(headers, row)).get("bz_gsm")),
            "lon_gsm": _parse_float(dict(zip(headers, row)).get("lon_gsm")),
            "lat_gsm": _parse_float(dict(zip(headers, row)).get("lat_gsm")),
            "bt":      _parse_float(dict(zip(headers, row)).get("bt")),
            "fetched_at": fetched_at,
        }
        for row in rows
    ]

    try:
        supabase.table("solar_wind_mag").upsert(records).execute()
        logger.info("Upserted %d magnetic field records.", len(records))
        return len(records)
    except Exception as exc:
        logger.error("Failed to upsert magnetic field data: %s", exc)
        return 0


def main() -> None:
    supabase = _get_supabase_client()
    logger.info("Fetching NOAA solar wind data…")
    plasma_count = fetch_plasma_data(supabase)
    mag_count    = fetch_mag_data(supabase)
    logger.info("NOAA fetch complete: %d plasma + %d mag records.", plasma_count, mag_count)


if __name__ == "__main__":
    main()
