import os
import psycopg2
import pandas as pd
import numpy as np
import torch
import torch.nn.functional as F

from dotenv import load_dotenv

from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split

from torch_geometric.data import Data
from torch_geometric.nn import GCNConv

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
# LOAD HAZARD DATA
# =========================================================

query = """

SELECT *
FROM lunar_hazard_nodes

"""

df = pd.read_sql(query, conn)

print("Loaded nodes:", len(df))

# =========================================================
# ENCODE LABELS
# =========================================================

label_encoder = LabelEncoder()

df["label_encoded"] = label_encoder.fit_transform(
    df["hazard_label"]
)

print("\nLabel Mapping:")

for idx, label in enumerate(label_encoder.classes_):
    print(idx, "->", label)

# =========================================================
# NODE FEATURES
# =========================================================

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
    "bz_gsm"

]

X = df[features].values

# =========================================================
# NORMALIZE FEATURES
# =========================================================

X = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-8)

# =========================================================
# LABELS
# =========================================================

y = df["label_encoded"].values

# =========================================================
# CREATE GRAPH EDGES
# =========================================================

# Connect neighboring supernodes
# Based on:
# tile_x
# tile_y
# super_row
# super_col

edge_list = []

# =========================================================
# FAST LOOKUP
# =========================================================

node_lookup = {}

for idx, row in df.iterrows():

    key = (
        row["tile_x"],
        row["tile_y"],
        row["super_row"],
        row["super_col"]
    )

    node_lookup[key] = idx

# =========================================================
# CREATE NEIGHBOR EDGES
# =========================================================

directions = [

    (-1, 0),
    (1, 0),

    (0, -1),
    (0, 1),

    (-1, -1),
    (-1, 1),

    (1, -1),
    (1, 1)

]

for idx, row in df.iterrows():

    tile_x = row["tile_x"]
    tile_y = row["tile_y"]

    super_row = row["super_row"]
    super_col = row["super_col"]

    for dr, dc in directions:

        neighbor_key = (
            tile_x,
            tile_y,
            super_row + dr,
            super_col + dc
        )

        if neighbor_key in node_lookup:

            neighbor_idx = node_lookup[neighbor_key]

            edge_list.append([idx, neighbor_idx])

# =========================================================
# EDGE INDEX
# =========================================================

edge_index = torch.tensor(
    edge_list,
    dtype=torch.long
).t().contiguous()

print("\nEdges:", edge_index.shape[1])

# =========================================================
# TORCH TENSORS
# =========================================================

x = torch.tensor(X, dtype=torch.float)

y = torch.tensor(y, dtype=torch.long)

# =========================================================
# TRAIN / TEST MASKS
# =========================================================

num_nodes = len(df)

indices = np.arange(num_nodes)

train_idx, test_idx = train_test_split(
    indices,
    test_size=0.2,
    random_state=42
)

train_mask = torch.zeros(num_nodes, dtype=torch.bool)
test_mask = torch.zeros(num_nodes, dtype=torch.bool)

train_mask[train_idx] = True
test_mask[test_idx] = True

# =========================================================
# CREATE GRAPH DATA
# =========================================================

data = Data(
    x=x,
    edge_index=edge_index,
    y=y
)

data.train_mask = train_mask
data.test_mask = test_mask

print("\nGraph Data:")
print(data)

# =========================================================
# GCN MODEL
# =========================================================

class LunarGCN(torch.nn.Module):

    def __init__(self, in_channels, hidden_channels, out_channels):

        super().__init__()

        self.conv1 = GCNConv(
            in_channels,
            hidden_channels
        )

        self.conv2 = GCNConv(
            hidden_channels,
            out_channels
        )

    # -----------------------------------------------------

    def forward(self, x, edge_index):

        x = self.conv1(x, edge_index)

        x = F.relu(x)

        x = F.dropout(
            x,
            p=0.3,
            training=self.training
        )

        x = self.conv2(x, edge_index)

        return x

# =========================================================
# MODEL INIT
# =========================================================

device = torch.device(
    "cuda" if torch.cuda.is_available() else "cpu"
)

model = LunarGCN(

    in_channels=x.shape[1],

    hidden_channels=64,

    out_channels=len(label_encoder.classes_)

).to(device)

data = data.to(device)

# =========================================================
# OPTIMIZER
# =========================================================

optimizer = torch.optim.Adam(
    model.parameters(),
    lr=0.01
)

# =========================================================
# TRAIN LOOP
# =========================================================

model.train()

epochs = 100

for epoch in range(epochs):

    optimizer.zero_grad()

    out = model(
        data.x,
        data.edge_index
    )

    loss = F.cross_entropy(
        out[data.train_mask],
        data.y[data.train_mask]
    )

    loss.backward()

    optimizer.step()

    if epoch % 10 == 0:

        print(
            f"Epoch {epoch} | Loss: {loss.item():.4f}"
        )

# =========================================================
# EVALUATION
# =========================================================

model.eval()

with torch.no_grad():

    pred = model(
        data.x,
        data.edge_index
    ).argmax(dim=1)

correct = (
    pred[data.test_mask]
    ==
    data.y[data.test_mask]
).sum()

acc = int(correct) / int(data.test_mask.sum())

print("\nTest Accuracy:", round(acc, 4))

# =========================================================
# ADD PREDICTIONS
# =========================================================

df["gnn_prediction"] = (
    pred.cpu().numpy()
)

df["gnn_prediction_label"] = (
    label_encoder.inverse_transform(
        df["gnn_prediction"]
    )
)

# =========================================================
# SHOW SAMPLE PREDICTIONS
# =========================================================

print("\nSample Predictions:")

print(

    df[[
        "hazard_label",
        "gnn_prediction_label"
    ]]

    .head(20)

)

# =========================================================
# SAVE MODEL
# =========================================================

torch.save(
    model.state_dict(),
    "lunagraph_gcn_model.pth"
)

print("\nModel saved: lunagraph_gcn_model.pth")

# =========================================================
# CLOSE
# =========================================================

conn.close()