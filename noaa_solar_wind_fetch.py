import logging
import os
import sys
<<<<<<< HEAD
import requests
from supabase import create_client, Client
from dotenv import load_dotenv
=======
>>>>>>> 7972a30 (Added Gnn and rendered)
from datetime import datetime, timezone

import psycopg2
import requests
from dotenv import load_dotenv
from psycopg2.extras import execute_batch

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

<<<<<<< HEAD
if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL or SUPABASE_KEY is not set in .env")
    sys.exit(1)

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print("ERROR: Failed to initialize Supabase client:", e)
    sys.exit(1)
=======
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [NOAA] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

if not DATABASE_URL:
    logger.error("DATABASE_URL is not set in .env")
    sys.exit(1)


def connect_db():
    return psycopg2.connect(DATABASE_URL)
>>>>>>> 7972a30 (Added Gnn and rendered)

def parse_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def parse_timestamp(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).isoformat()
        except ValueError:
            continue
    return None

def fetch_json(url):
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
<<<<<<< HEAD
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Failed to fetch {url}: {e}")
        return None

def fetch_plasma_data():
=======
    except requests.exceptions.RequestException as exc:
        logger.error("Failed to fetch NOAA data from %s: %s", url, exc)
        if hasattr(exc, "response") and exc.response is not None:
            logger.error("Response code: %s", exc.response.status_code)
            logger.error("Response body: %s", exc.response.text[:400])
        return None


def ensure_noaa_tables(conn):
    with conn.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS solar_wind_plasma (
                id SERIAL PRIMARY KEY,
                time_tag TIMESTAMP NOT NULL UNIQUE,
                density REAL,
                speed REAL,
                temperature REAL,
                fetched_at TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS solar_wind_mag (
                id SERIAL PRIMARY KEY,
                time_tag TIMESTAMP NOT NULL UNIQUE,
                bx_gsm REAL,
                by_gsm REAL,
                bz_gsm REAL,
                lon_gsm REAL,
                lat_gsm REAL,
                bt REAL,
                fetched_at TIMESTAMP
            )
            """
        )
    conn.commit()
    logger.info("Validated NOAA ingestion schema in Supabase database.")


def insert_rows(conn, table, columns, row_entries):
    if not row_entries:
        return 0

    placeholders = ", ".join("%s" for _ in columns)
    insert_sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) ON CONFLICT (time_tag) DO NOTHING"

    with conn.cursor() as cursor:
        execute_batch(cursor, insert_sql, row_entries, page_size=200)
    conn.commit()
    return len(row_entries)


def fetch_plasma_data(conn):
>>>>>>> 7972a30 (Added Gnn and rendered)
    url = "https://services.swpc.noaa.gov/products/solar-wind/plasma-1-day.json"
    data = fetch_json(url)
    if not data or len(data) < 2:
        logger.warning("No plasma data available from NOAA.")
        return 0

    headers = data[0]
    rows = data[1:]
<<<<<<< HEAD
    
    insert_data = []
    for row in rows:
        values = dict(zip(headers, row))
        insert_data.append({
            "time_tag": parse_timestamp(values.get("time_tag")),
            "density": parse_float(values.get("density")),
            "speed": parse_float(values.get("speed")),
            "temperature": parse_float(values.get("temperature")),
            "fetched_at": datetime.now(timezone.utc).isoformat()
        })
=======
    row_entries = []

    for row in rows:
        values = dict(zip(headers, row))
        row_entries.append(
            (
                parse_timestamp(values.get("time_tag")),
                parse_float(values.get("density")),
                parse_float(values.get("speed")),
                parse_float(values.get("temperature")),
                datetime.now(timezone.utc),
            )
        )

    count = insert_rows(
        conn,
        "solar_wind_plasma",
        ["time_tag", "density", "speed", "temperature", "fetched_at"],
        row_entries,
    )

    logger.info("NOAA plasma ingestion completed with %d records inserted or skipped duplicates.", count)
    return count
>>>>>>> 7972a30 (Added Gnn and rendered)

    try:
        supabase.table("solar_wind_plasma").upsert(insert_data).execute()
        print(f"Inserted {len(rows)} solar wind plasma records.")
        return len(rows)
    except Exception as e:
        print(f"ERROR inserting plasma data: {e}")
        return 0

def fetch_mag_data(conn):
    url = "https://services.swpc.noaa.gov/products/solar-wind/mag-1-day.json"
    data = fetch_json(url)
    if not data or len(data) < 2:
        logger.warning("No magnetic field data available from NOAA.")
        return 0

    headers = data[0]
    rows = data[1:]
    row_entries = []

    insert_data = []
    for row in rows:
        values = dict(zip(headers, row))
<<<<<<< HEAD
        insert_data.append({
            "time_tag": parse_timestamp(values.get("time_tag")),
            "bx_gsm": parse_float(values.get("bx_gsm")),
            "by_gsm": parse_float(values.get("by_gsm")),
            "bz_gsm": parse_float(values.get("bz_gsm")),
            "lon_gsm": parse_float(values.get("lon_gsm")),
            "lat_gsm": parse_float(values.get("lat_gsm")),
            "bt": parse_float(values.get("bt")),
            "fetched_at": datetime.now(timezone.utc).isoformat()
        })
=======
        row_entries.append(
            (
                parse_timestamp(values.get("time_tag")),
                parse_float(values.get("bx_gsm")),
                parse_float(values.get("by_gsm")),
                parse_float(values.get("bz_gsm")),
                parse_float(values.get("lon_gsm")),
                parse_float(values.get("lat_gsm")),
                parse_float(values.get("bt")),
                datetime.now(timezone.utc),
            )
        )

    count = insert_rows(
        conn,
        "solar_wind_mag",
        [
            "time_tag",
            "bx_gsm",
            "by_gsm",
            "bz_gsm",
            "lon_gsm",
            "lat_gsm",
            "bt",
            "fetched_at",
        ],
        row_entries,
    )

    logger.info("NOAA magnetic field ingestion completed with %d records inserted or skipped duplicates.", count)
    return count


def run_noaa_ingest():
    with connect_db() as conn:
        ensure_noaa_tables(conn)
        plasma_count = fetch_plasma_data(conn)
        mag_count = fetch_mag_data(conn)

    total = plasma_count + mag_count
    logger.info("NOAA ingestion finished: %d plasma rows, %d mag rows, %d total.", plasma_count, mag_count, total)
    return {
        "plasma_rows": plasma_count,
        "mag_rows": mag_count,
        "total_rows": total,
    }
>>>>>>> 7972a30 (Added Gnn and rendered)

    try:
        supabase.table("solar_wind_mag").upsert(insert_data).execute()
        print(f"Inserted {len(rows)} solar wind magnetic field records.")
        return len(rows)
    except Exception as e:
        print(f"ERROR inserting mag data: {e}")
        return 0

def main():
<<<<<<< HEAD
    print("Fetching data from NOAA and inserting via Supabase REST API...")
    plasma_count = fetch_plasma_data()
    mag_count = fetch_mag_data()
    total = plasma_count + mag_count
    if total > 0:
        print(f"\nNOAA solar wind data stored successfully: {total} records.")
    else:
        print("\nNo NOAA solar wind data was stored.")
=======
    run_noaa_ingest()
>>>>>>> 7972a30 (Added Gnn and rendered)

if __name__ == "__main__":
    main()
