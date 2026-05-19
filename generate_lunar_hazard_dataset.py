import psycopg2
import pandas as pd
import numpy as np
import os

from dotenv import load_dotenv
from psycopg2.extras import execute_batch

# =========================================================
# LOAD ENV
# =========================================================

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# =========================================================
# CONNECT DATABASE
# =========================================================

conn = psycopg2.connect(DATABASE_URL)

# =========================================================
# LOAD LUNAR REGIONS
# =========================================================

lunar_query = """
SELECT *
FROM lunar_regions
"""

lunar_df = pd.read_sql(lunar_query, conn)

print("Loaded lunar regions:", len(lunar_df))

# =========================================================
# FETCH LATEST NOAA MAG DATA
# =========================================================

mag_query = """

SELECT *
FROM solar_wind_mag
ORDER BY time_tag DESC
LIMIT 1

"""

mag_df = pd.read_sql(mag_query, conn)

# =========================================================
# FETCH LATEST NOAA PLASMA DATA
# =========================================================

plasma_query = """

SELECT *
FROM solar_wind_plasma
ORDER BY time_tag DESC
LIMIT 1

"""

plasma_df = pd.read_sql(plasma_query, conn)

# =========================================================
# EXTRACT NOAA VALUES
# =========================================================

bx_gsm = float(mag_df.iloc[0]["bx_gsm"])
by_gsm = float(mag_df.iloc[0]["by_gsm"])
bz_gsm = float(mag_df.iloc[0]["bz_gsm"])

bt = float(mag_df.iloc[0]["bt"])

speed = float(plasma_df.iloc[0]["speed"])
density = float(plasma_df.iloc[0]["density"])
temperature = float(plasma_df.iloc[0]["temperature"])

print("\nLIVE NOAA VALUES")
print("Speed:", speed)
print("Density:", density)
print("Magnetic Field:", bt)

# =========================================================
# PATCH AGGREGATION
# =========================================================

AGG_PATCH_ROWS = 2
AGG_PATCH_COLS = 2

lunar_df["super_row"] = (
    lunar_df["patch_row"] // AGG_PATCH_ROWS
)

lunar_df["super_col"] = (
    lunar_df["patch_col"] // AGG_PATCH_COLS
)

# =========================================================
# CREATE SUPERNODES
# =========================================================

aggregated = (
    lunar_df.groupby([
        "zoom",
        "tile_x",
        "tile_y",
        "super_row",
        "super_col"
    ])
    .agg({

        "latitude": "mean",
        "longitude": "mean",

        "elevation": "mean",
        "roughness": "mean",
        "crater_density": "mean",
        "shadow_score": "mean"

    })
    .reset_index()
)

print("Created supernodes:", len(aggregated))

# =========================================================
# ADD NOAA FEATURES
# =========================================================

aggregated["solar_wind_speed"] = speed
aggregated["plasma_density"] = density
aggregated["temperature"] = temperature

aggregated["magnetic_field_bt"] = bt

aggregated["bx_gsm"] = bx_gsm
aggregated["by_gsm"] = by_gsm
aggregated["bz_gsm"] = bz_gsm

# =========================================================
# NORMALIZATION
# =========================================================

aggregated["speed_norm"] = (
    aggregated["solar_wind_speed"] / 800.0
)

aggregated["density_norm"] = (
    aggregated["plasma_density"] / 20.0
)

aggregated["bt_norm"] = (
    np.abs(aggregated["magnetic_field_bt"]) / 15.0
)

# =========================================================
# ILLUMINATION
# =========================================================

aggregated["illumination"] = (
    1.0 - aggregated["shadow_score"]
)

# =========================================================
# BALANCED HAZARD SCORE
# =========================================================

aggregated["hazard_score"] = (

    0.30 * aggregated["illumination"]

    + 0.25 * aggregated["speed_norm"]

    + 0.15 * aggregated["density_norm"]

    + 0.15 * aggregated["bt_norm"]

    + 0.15 * aggregated["roughness"]

)

# =========================================================
# CLAMP
# =========================================================

aggregated["hazard_score"] = (
    aggregated["hazard_score"]
    .clip(0.0, 1.0)
)

# =========================================================
# LABEL GENERATION
# =========================================================

def classify(score):

    if score < 0.35:
        return "SAFE"

    elif score < 0.55:
        return "MODERATE"

    elif score < 0.75:
        return "HIGH"

    else:
        return "EXTREME"

# ---------------------------------------------------------

aggregated["hazard_label"] = (
    aggregated["hazard_score"]
    .apply(classify)
)

# =========================================================
# DEBUG DISTRIBUTION
# =========================================================

print("\nHAZARD SCORE DISTRIBUTION")
print(
    aggregated["hazard_score"]
    .describe()
)

print("\nLABEL COUNTS")
print(
    aggregated["hazard_label"]
    .value_counts()
)

# =========================================================
# CREATE NODE IDS
# =========================================================

aggregated["node_id"] = np.arange(len(aggregated))

# =========================================================
# CREATE TABLE
# =========================================================

cursor = conn.cursor()

cursor.execute("""

CREATE TABLE IF NOT EXISTS lunar_hazard_nodes (

    node_id BIGINT,

    created_at TIMESTAMP DEFAULT NOW(),

    zoom INTEGER,

    tile_x INTEGER,
    tile_y INTEGER,

    super_row INTEGER,
    super_col INTEGER,

    latitude REAL,
    longitude REAL,

    elevation REAL,
    roughness REAL,
    crater_density REAL,
    shadow_score REAL,

    illumination REAL,

    solar_wind_speed REAL,
    plasma_density REAL,
    temperature REAL,

    magnetic_field_bt REAL,

    bx_gsm REAL,
    by_gsm REAL,
    bz_gsm REAL,

    hazard_score REAL,

    hazard_label TEXT
)

""")

conn.commit()

# =========================================================
# CLEAR OLD DATA
# =========================================================

cursor.execute("""

TRUNCATE TABLE lunar_hazard_nodes

""")

conn.commit()

# =========================================================
# PREPARE RECORDS
# =========================================================

records = []

for _, row in aggregated.iterrows():

    records.append((

        int(row["node_id"]),

        int(row["zoom"]),

        int(row["tile_x"]),
        int(row["tile_y"]),

        int(row["super_row"]),
        int(row["super_col"]),

        float(row["latitude"]),
        float(row["longitude"]),

        float(row["elevation"]),
        float(row["roughness"]),
        float(row["crater_density"]),
        float(row["shadow_score"]),

        float(row["illumination"]),

        float(row["solar_wind_speed"]),
        float(row["plasma_density"]),
        float(row["temperature"]),

        float(row["magnetic_field_bt"]),

        float(row["bx_gsm"]),
        float(row["by_gsm"]),
        float(row["bz_gsm"]),

        float(row["hazard_score"]),

        str(row["hazard_label"])

    ))

# =========================================================
# INSERT QUERY
# =========================================================

insert_query = """

INSERT INTO lunar_hazard_nodes (

    node_id,

    zoom,

    tile_x,
    tile_y,

    super_row,
    super_col,

    latitude,
    longitude,

    elevation,
    roughness,
    crater_density,
    shadow_score,

    illumination,

    solar_wind_speed,
    plasma_density,
    temperature,

    magnetic_field_bt,

    bx_gsm,
    by_gsm,
    bz_gsm,

    hazard_score,
    hazard_label

)

VALUES (
    %s,%s,%s,%s,%s,%s,
    %s,%s,%s,%s,%s,%s,
    %s,%s,%s,%s,%s,%s,
    %s,%s,%s,%s
)

"""

# =========================================================
# BATCH INSERT
# =========================================================

execute_batch(
    cursor,
    insert_query,
    records,
    page_size=1000
)

conn.commit()

print("\nLunar hazard table updated successfully.")
print("Inserted rows:", len(records))

# =========================================================
# CLOSE
# =========================================================

cursor.close()
conn.close()