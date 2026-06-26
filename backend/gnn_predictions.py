"""
gnn_predictions.py
===================
GNN training script (offline, run once).

Loads lunar_hazard_nodes from the database, constructs the spatial graph,
trains a 3-layer GraphSAGE classifier with class-balanced cross-entropy loss,
evaluates on a held-out test split, and saves the model weights.

Inputs:  lunar_hazard_nodes (Supabase PostgreSQL)
Outputs: lunagraph_gcn_model.pth (model weights)

Pipeline: generate_lunar_hazard_dataset → [THIS] → infer_live_hazards
NOTE: This script trains the model. For live inference use infer_live_hazards.py.
"""

import os
import sys
import logging

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from dotenv import load_dotenv
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sqlalchemy import create_engine
from torch_geometric.data import Data
from torch_geometric.nn import SAGEConv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [GNN] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

FEATURE_COLUMNS = [
    "elevation", "roughness", "crater_density", "shadow_score",
    "illumination", "solar_wind_speed", "plasma_density",
    "magnetic_field_bt", "bx_gsm", "by_gsm", "bz_gsm",
]
HIDDEN_CHANNELS = 64
EPOCHS = 150
LEARNING_RATE = 0.01
WEIGHT_DECAY = 1e-4
DROPOUT = 0.3
MODEL_OUTPUT = "lunagraph_gcn_model.pth"

# 8-directional neighbourhood for supernode graph construction
DIRECTIONS = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]


class LunarGNN(torch.nn.Module):
    """
    3-layer GraphSAGE classifier with BatchNorm and dropout.

    Architecture:
        SAGEConv(in → 64)  →  BN  →  ReLU  →  Dropout(0.3)
        SAGEConv(64 → 64)  →  BN  →  ReLU  →  Dropout(0.3)
        SAGEConv(64 → num_classes)
    """

    def __init__(self, in_channels: int, hidden_channels: int, out_channels: int):
        super().__init__()
        self.conv1 = SAGEConv(in_channels, hidden_channels)
        self.bn1   = torch.nn.BatchNorm1d(hidden_channels)
        self.conv2 = SAGEConv(hidden_channels, hidden_channels)
        self.bn2   = torch.nn.BatchNorm1d(hidden_channels)
        self.conv3 = SAGEConv(hidden_channels, out_channels)

    def forward(self, x, edge_index):
        x = F.dropout(F.relu(self.bn1(self.conv1(x, edge_index))), p=DROPOUT, training=self.training)
        x = F.dropout(F.relu(self.bn2(self.conv2(x, edge_index))), p=DROPOUT, training=self.training)
        return self.conv3(x, edge_index)


def build_edge_index(df: pd.DataFrame) -> torch.Tensor:
    """
    Build a graph edge_index by connecting each supernode to its 8 spatial neighbours.

    Nodes are identified by (tile_x, tile_y, super_row, super_col). Edges are added
    for all 8-directional neighbours that exist in the same tile.
    """
    node_lookup = {
        (row.tile_x, row.tile_y, row.super_row, row.super_col): idx
        for idx, row in df.iterrows()
    }
    edges = []
    for idx, row in df.iterrows():
        for dr, dc in DIRECTIONS:
            key = (row.tile_x, row.tile_y, row.super_row + dr, row.super_col + dc)
            if key in node_lookup:
                edges.append([idx, node_lookup[key]])

    return torch.tensor(edges, dtype=torch.long).t().contiguous()


def load_graph_data(engine) -> Data:
    """Load hazard nodes from DB, encode labels, and return a PyG Data object."""
    df = pd.read_sql("SELECT * FROM lunar_hazard_nodes", engine)
    logger.info("Loaded %d nodes from lunar_hazard_nodes.", len(df))
    if df.empty:
        logger.error("No data found — run generate_lunar_hazard_dataset.py first.")
        sys.exit(1)

    label_encoder = LabelEncoder()
    y_encoded = label_encoder.fit_transform(df["hazard_label"])
    logger.info("Classes: %s", list(label_encoder.classes_))

    X = df[FEATURE_COLUMNS].fillna(0).values.astype(float)
    X = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-8)

    edge_index = build_edge_index(df)
    logger.info("Graph: %d nodes, %d edges.", len(df), edge_index.shape[1])

    indices = np.arange(len(df))
    train_idx, test_idx = train_test_split(indices, test_size=0.2, random_state=42)
    train_mask = torch.zeros(len(df), dtype=torch.bool)
    test_mask  = torch.zeros(len(df), dtype=torch.bool)
    train_mask[train_idx] = True
    test_mask[test_idx]   = True

    data = Data(
        x=torch.tensor(X, dtype=torch.float),
        edge_index=edge_index,
        y=torch.tensor(y_encoded, dtype=torch.long),
    )
    data.train_mask = train_mask
    data.test_mask  = test_mask
    return data, label_encoder


def compute_class_weights(data: Data, num_classes: int, device) -> torch.Tensor:
    """Compute inverse-frequency class weights to handle label imbalance."""
    counts = torch.bincount(data.y[data.train_mask].cpu(), minlength=num_classes).float()
    weights = 1.0 / (counts + 1e-6)
    weights = weights / weights.sum() * num_classes
    return weights.to(device)


def train(model, data, optimizer, class_weights) -> float:
    model.train()
    optimizer.zero_grad()
    out = model(data.x, data.edge_index)
    loss = F.cross_entropy(out[data.train_mask], data.y[data.train_mask], weight=class_weights)
    loss.backward()
    optimizer.step()
    return loss.item()


def evaluate(model, data, label_encoder) -> None:
    model.eval()
    with torch.no_grad():
        pred = model(data.x, data.edge_index).argmax(dim=1)
    y_true = data.y[data.test_mask].cpu().numpy()
    y_pred = pred[data.test_mask].cpu().numpy()
    acc = (y_true == y_pred).mean()
    logger.info("Test accuracy: %.4f", acc)
    logger.info("\n%s", classification_report(y_true, y_pred, target_names=label_encoder.classes_, zero_division=0))
    logger.info("Confusion matrix:\n%s", confusion_matrix(y_true, y_pred))


def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL is not set.")
        sys.exit(1)

    engine = create_engine(database_url)
    data, label_encoder = load_graph_data(engine)
    engine.dispose()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("Training on %s.", device)
    data = data.to(device)

    model = LunarGNN(
        in_channels=data.x.shape[1],
        hidden_channels=HIDDEN_CHANNELS,
        out_channels=len(label_encoder.classes_),
    ).to(device)

    class_weights = compute_class_weights(data, len(label_encoder.classes_), device)
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)

    for epoch in range(EPOCHS):
        loss = train(model, data, optimizer, class_weights)
        if epoch % 15 == 0:
            logger.info("Epoch %03d | Loss: %.4f", epoch, loss)

    evaluate(model, data, label_encoder)

    torch.save(model.state_dict(), MODEL_OUTPUT)
    logger.info("Model saved to %s.", MODEL_OUTPUT)


if __name__ == "__main__":
    main()