import os
import sys
import requests
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL or SUPABASE_KEY is not set in .env")
    sys.exit(1)

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print("ERROR: Failed to initialize Supabase client:", e)
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
            return datetime.strptime(value, fmt).isoformat()
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
        return None

def fetch_plasma_data():
    url = "https://services.swpc.noaa.gov/products/solar-wind/plasma-1-day.json"
    data = fetch_json(url)
    if not data or len(data) < 2:
        print("No plasma data available.")
        return 0

    headers = data[0]
    rows = data[1:]
    
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

    try:
        supabase.table("solar_wind_plasma").upsert(insert_data).execute()
        print(f"Inserted {len(rows)} solar wind plasma records.")
        return len(rows)
    except Exception as e:
        print(f"ERROR inserting plasma data: {e}")
        return 0

def fetch_mag_data():
    url = "https://services.swpc.noaa.gov/products/solar-wind/mag-1-day.json"
    data = fetch_json(url)
    if not data or len(data) < 2:
        print("No magnetic field data available.")
        return 0

    headers = data[0]
    rows = data[1:]

    insert_data = []
    for row in rows:
        values = dict(zip(headers, row))
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

    try:
        supabase.table("solar_wind_mag").upsert(insert_data).execute()
        print(f"Inserted {len(rows)} solar wind magnetic field records.")
        return len(rows)
    except Exception as e:
        print(f"ERROR inserting mag data: {e}")
        return 0

def main():
    print("Fetching data from NOAA and inserting via Supabase REST API...")
    plasma_count = fetch_plasma_data()
    mag_count = fetch_mag_data()
    total = plasma_count + mag_count
    if total > 0:
        print(f"\nNOAA solar wind data stored successfully: {total} records.")
    else:
        print("\nNo NOAA solar wind data was stored.")

if __name__ == "__main__":
    main()
