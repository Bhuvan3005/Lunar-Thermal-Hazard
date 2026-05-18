import os
import sys
import requests
import psycopg2
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("ERROR: DATABASE_URL is not set in .env")
    sys.exit(1)

try:
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
except Exception as e:
    print("ERROR: Failed to connect to the database:", e)
    sys.exit(1)


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
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def fetch_json(url):
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Failed to fetch {url}: {e}")
        if hasattr(e, "response") and e.response is not None:
            print("Response code:", e.response.status_code)
            print("Response body:", e.response.text[:400])
        return None


def setup_tables():
    cursor.execute("""
    DROP TABLE IF EXISTS solar_flares, cme_events, geomagnetic_storms, cme_analysis, interplanetary_shocks, solar_energetic_particles
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS solar_wind_plasma (
        id SERIAL PRIMARY KEY,
        time_tag TIMESTAMP,
        density REAL,
        speed REAL,
        temperature REAL,
        fetched_at TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS solar_wind_mag (
        id SERIAL PRIMARY KEY,
        time_tag TIMESTAMP,
        bx_gsm REAL,
        by_gsm REAL,
        bz_gsm REAL,
        lon_gsm REAL,
        lat_gsm REAL,
        bt REAL,
        fetched_at TIMESTAMP
    )
    """)

    conn.commit()
    print("Database tables set up for NOAA solar wind data.")


def cleanup_old_nasa_tables():
    cursor.execute("""
    DROP TABLE IF EXISTS cme_analysis, cme_events, geomagnetic_storms, interplanetary_shocks, solar_energetic_particles, solar_flares
    """)
    conn.commit()
    print("Dropped old NASA DONKI tables from the database.")


def fetch_plasma_data():
    url = "https://services.swpc.noaa.gov/products/solar-wind/plasma-1-day.json"
    data = fetch_json(url)
    if not data or len(data) < 2:
        print("No plasma data available.")
        return 0

    headers = data[0]
    rows = data[1:]

    for row in rows:
        values = dict(zip(headers, row))
        cursor.execute("""
        INSERT INTO solar_wind_plasma (
            time_tag,
            density,
            speed,
            temperature,
            fetched_at
        ) VALUES (%s,%s,%s,%s,%s)
        """, (
            parse_timestamp(values.get("time_tag")),
            parse_float(values.get("density")),
            parse_float(values.get("speed")),
            parse_float(values.get("temperature")),
            datetime.now(timezone.utc),
        ))

    conn.commit()
    print(f"Inserted {len(rows)} solar wind plasma records.")
    return len(rows)


def fetch_mag_data():
    url = "https://services.swpc.noaa.gov/products/solar-wind/mag-1-day.json"
    data = fetch_json(url)
    if not data or len(data) < 2:
        print("No magnetic field data available.")
        return 0

    headers = data[0]
    rows = data[1:]

    for row in rows:
        values = dict(zip(headers, row))
        cursor.execute("""
        INSERT INTO solar_wind_mag (
            time_tag,
            bx_gsm,
            by_gsm,
            bz_gsm,
            lon_gsm,
            lat_gsm,
            bt,
            fetched_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            parse_timestamp(values.get("time_tag")),
            parse_float(values.get("bx_gsm")),
            parse_float(values.get("by_gsm")),
            parse_float(values.get("bz_gsm")),
            parse_float(values.get("lon_gsm")),
            parse_float(values.get("lat_gsm")),
            parse_float(values.get("bt")),
            datetime.now(timezone.utc),
        ))

    conn.commit()
    print(f"Inserted {len(rows)} solar wind magnetic field records.")
    return len(rows)


def main():
    cleanup_old_nasa_tables()
    setup_tables()
    plasma_count = fetch_plasma_data()
    mag_count = fetch_mag_data()
    total = plasma_count + mag_count
    if total > 0:
        print(f"\nNOAA solar wind data stored successfully: {total} records.")
    else:
        print("\nNo NOAA solar wind data was stored.")


if __name__ == "__main__":
    main()
