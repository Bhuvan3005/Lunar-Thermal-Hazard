import logging
import os
from datetime import datetime, timezone

import pandas as pd
import psycopg2
import torch
import torch.nn.functional as F
from dotenv import load_dotenv
from psycopg2.extras import execute_batch
from sklearn.preprocessing import LabelEncoder
from torch_geometric.data import Data
from torch_geometric.nn import GCNConv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
INTERVAL_HOURS = 6

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [INFERENCE] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)


def get_db_connection():
    if not DATABASE_URL:
        logger.error("DATABASE_URL is not configured in .env")
        raise RuntimeError("DATABASE_URL is required")
    return psycopg2.connect(DATABASE_URL)


def ensure_prediction_schema(conn):
    with conn.cursor() as cursor:
        cursor.execute(
            """
            ALTER TABLE lunar_hazard_nodes
            ADD COLUMN IF NOT EXISTS gnn_prediction TEXT
            """
        )
        cursor.execute(
            """
            ALTER TABLE lunar_hazard_nodes
            ADD COLUMN IF NOT EXISTS prediction_confidence REAL
            """
        )
        cursor.execute(
            """
            ALTER TABLE lunar_hazard_nodes
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP
            """
        )
    conn.commit()
    logger.info("Ensured lunar_hazard_nodes prediction schema is up to date.")


def load_latest_noaa_values(conn):
    plasma_query = """
    SELECT time_tag, density, speed, temperature
    FROM solar_wind_plasma
    ORDER BY time_tag DESC
    LIMIT 1
    """
    mag_query = """
    SELECT time_tag, bx_gsm, by_gsm, bz_gsm, lon_gsm, lat_gsm, bt
    FROM solar_wind_mag
    ORDER BY time_tag DESC
    LIMIT 1
    """

    plasma_df = pd.read_sql(plasma_query, conn)
    mag_df = pd.read_sql(mag_query, conn)

    if plasma_df.empty or mag_df.empty:
        raise RuntimeError("Unable to load latest NOAA values from database.")

    latest_plasma = plasma_df.iloc[0].to_dict()
    latest_mag = mag_df.iloc[0].to_dict()

    logger.info(
        "Latest NOAA rows loaded: plasma at %s, mag at %s.",
        latest_plasma.get("time_tag"),
        latest_mag.get("time_tag"),
    )

    return latest_plasma, latest_mag


def load_lunar_nodes(conn):
    query = "SELECT * FROM lunar_hazard_nodes"
    df = pd.read_sql(query, conn)
    logger.info("Loaded %d lunar hazard nodes from database.", len(df))
    if df.empty:
        raise RuntimeError("No lunar_hazard_nodes records available for inference.")
    if "node_id" not in df.columns:
        raise RuntimeError("Database table lunar_hazard_nodes must contain a node_id column.")
    return df.reset_index(drop=True)


def apply_latest_noaa_values(df, plasma_values, mag_values):
    feature_updates = {
        "solar_wind_speed": plasma_values.get("speed"),
        "plasma_density": plasma_values.get("density"),
        "magnetic_field_bt": mag_values.get("bt"),
        "bx_gsm": mag_values.get("bx_gsm"),
        "by_gsm": mag_values.get("by_gsm"),
        "bz_gsm": mag_values.get("bz_gsm"),
    }

    for column, value in feature_updates.items():
        if column in df.columns:
            df[column] = value
            logger.debug("Applied latest NOAA %s=%s to node features.", column, value)

    return df


def build_edge_index(df):
    edge_list = []
    node_lookup = {}

    for idx, row in df.iterrows():
        node_lookup[(row["tile_x"], row["tile_y"], row["super_row"], row["super_col"])] = idx

    directions = [
        (-1, 0),
        (1, 0),
        (0, -1),
        (0, 1),
        (-1, -1),
        (-1, 1),
        (1, -1),
        (1, 1),
    ]

    for idx, row in df.iterrows():
        for dr, dc in directions:
            neighbor_key = (
                row["tile_x"],
                row["tile_y"],
                row["super_row"] + dr,
                row["super_col"] + dc,
            )
            if neighbor_key in node_lookup:
                edge_list.append([idx, node_lookup[neighbor_key]])

    if not edge_list:
        raise RuntimeError("No graph edges were built from lunar_hazard_nodes.")

    edge_index = torch.tensor(edge_list, dtype=torch.long).t().contiguous()
    logger.info("Built graph edge_index with %d nodes and %d edges.", len(df), edge_index.shape[1])
    return edge_index


def normalize_features(values):
    values = values.astype(float)
    mean = values.mean(axis=0)
    std = values.std(axis=0)
    normalized = (values - mean) / (std + 1e-8)
    return normalized


class LunarGCN(torch.nn.Module):
    def __init__(self, in_channels, hidden_channels, out_channels):
        super().__init__()
        self.conv1 = GCNConv(in_channels, hidden_channels)
        self.conv2 = GCNConv(hidden_channels, out_channels)

    def forward(self, x, edge_index):
        x = self.conv1(x, edge_index)
        x = F.relu(x)
        x = self.conv2(x, edge_index)
        return x


def load_trained_model(in_channels, num_classes):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = LunarGCN(in_channels, hidden_channels=64, out_channels=num_classes).to(device)
    model.load_state_dict(torch.load("lunagraph_gcn_model.pth", map_location=device))
    model.eval()
    logger.info("Loaded trained GCN model from lunagraph_gcn_model.pth on %s.", device)
    return model, device


def infer_predictions(df):
    features = [
        "elevation",
        "roughness",
        "crater_density",
        "shadow_score",
        "illumination",
        "solar_wind_speed",
        "plasma_density",
        "magnetic_field_bt",
        "bx_gsm",
        "by_gsm",
        "bz_gsm",
    ]

    missing = [feature for feature in features if feature not in df.columns]
    if missing:
        raise RuntimeError(f"Missing required feature columns for inference: {missing}")

    X = df[features].fillna(0).values
    X = normalize_features(X)
    edge_index = build_edge_index(df)

    df["hazard_label"] = df["hazard_label"].astype(str)
    label_encoder = LabelEncoder()
    label_encoder.fit(df["hazard_label"])

    model, device = load_trained_model(X.shape[1], len(label_encoder.classes_))

    with torch.no_grad():
        data = Data(x=torch.tensor(X, dtype=torch.float).to(device), edge_index=edge_index.to(device))
        out = model(data.x, data.edge_index)
        probabilities = F.softmax(out, dim=1).cpu()
        predicted_classes = probabilities.argmax(dim=1).numpy()
        confidence_scores = probabilities.max(dim=1).values.numpy()

    predicted_labels = label_encoder.inverse_transform(predicted_classes)
    df["gnn_prediction"] = predicted_labels
    df["prediction_confidence"] = confidence_scores
    df["updated_at"] = datetime.now(timezone.utc)

    logger.info("Inference completed for %d lunar nodes.", len(df))
    return df


def batch_update_predictions(conn, df, plasma_values, mag_values):
    update_columns = ["gnn_prediction", "prediction_confidence", "updated_at"]
    noaa_columns = [
        "solar_wind_speed",
        "plasma_density",
        "magnetic_field_bt",
        "bx_gsm",
        "by_gsm",
        "bz_gsm",
    ]

    update_with_noaa = all(column in df.columns for column in noaa_columns)
    if update_with_noaa:
        update_columns.extend(noaa_columns)

    assignment_sql = ", ".join(f"{col} = %s" for col in update_columns)
    update_sql = f"UPDATE lunar_hazard_nodes SET {assignment_sql} WHERE node_id = %s"

    records = []
    for _, row in df.iterrows():
        values = [row[col] for col in ["gnn_prediction", "prediction_confidence", "updated_at"]]
        if update_with_noaa:
            values.extend([row[col] for col in noaa_columns])
        values.append(int(row["node_id"]))
        records.append(tuple(values))

    with conn.cursor() as cursor:
        execute_batch(cursor, update_sql, records, page_size=500)
    conn.commit()

    logger.info("Batch updated %d lunar hazard nodes with predictions and latest NOAA fields.", len(records))


def summarize_predictions(df):
    counts = df["gnn_prediction"].value_counts()
    hazard_levels = ["SAFE", "MODERATE", "HIGH", "EXTREME"]
    summary = {level: int(counts.get(level, 0)) for level in hazard_levels}

    logger.info("Prediction counts: %s", summary)
    logger.info("Full prediction breakdown:\n%s", counts.to_string())

    confidence_stats = df["prediction_confidence"].describe()
    logger.info("Prediction confidence statistics:\n%s", confidence_stats.to_string())

    distribution = (
        df.groupby("gnn_prediction")["prediction_confidence"]
        .describe()
        .reset_index()
    )
    logger.info("Hazard confidence distribution by predicted label:\n%s", distribution.to_string(index=False))


def run_live_inference():
    logger.info("Starting live lunar hazard inference.")
    with get_db_connection() as conn:
        ensure_prediction_schema(conn)
        plasma_values, mag_values = load_latest_noaa_values(conn)
        df = load_lunar_nodes(conn)
        df = apply_latest_noaa_values(df, plasma_values, mag_values)
        df = infer_predictions(df)
        batch_update_predictions(conn, df, plasma_values, mag_values)
        summarize_predictions(df)
    logger.info("Live inference completed at %s.", datetime.now(timezone.utc).isoformat())
    return df


def main():
    run_live_inference()


if __name__ == "__main__":
    main()
