"""
graph_builder.py
================
Builds and caches the lunar navigation graph from the lunar_hazard_nodes table.

Reuses the same 8-directional neighbor logic from gnn_predictions.py.
Each node becomes a navigation vertex; neighbor edges carry pre-computed
haversine distances (km) as weights.

The graph is built ONCE at server startup and cached in module-level memory.
All A* requests share the same graph without rebuilding.
"""

import math
import logging
import os
from typing import Optional

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

logger = logging.getLogger(__name__)

# =========================================================
# CONSTANTS
# =========================================================

MOON_RADIUS_KM = 1737.4

# 8-directional neighbors (same as gnn_predictions.py)
DIRECTIONS = [
    (-1, 0), (1, 0),
    (0, -1), (0, 1),
    (-1, -1), (-1, 1),
    (1, -1), (1, 1),
]

# Hazard label → numeric score (fallback when hazard_score column is null)
HAZARD_LABEL_SCORE = {
    "SAFE": 1.0,
    "MODERATE": 5.0,
    "HIGH": 20.0,
    "EXTREME": 100.0,
}

# =========================================================
# MODULE-LEVEL CACHE
# =========================================================

_graph: Optional[dict] = None          # adjacency list: {node_id: [EdgeDict, ...]}
_nodes_by_id: Optional[dict] = None    # {node_id: node_dict}
_graph_loaded: bool = False

# =========================================================
# HAVERSINE DISTANCE
# =========================================================

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Great-circle distance between two lat/lon points on the Moon (km).
    Uses Moon radius = 1737.4 km.
    """
    r = MOON_RADIUS_KM
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


# =========================================================
# HAZARD SCORE HELPER
# =========================================================

def resolve_hazard_score(node: dict) -> float:
    """
    Returns the numeric hazard score for cost computation.
    Prefers the database hazard_score column.
    Falls back to label mapping if null/zero.
    """
    raw = node.get("hazard_score")
    if raw is not None and raw > 0:
        return float(raw)

    # Use hazard_label as the authoritative classification
    label = node.get("hazard_label") or "SAFE"
    return HAZARD_LABEL_SCORE.get(str(label).upper(), 1.0)


# =========================================================
# DATABASE LOADER
# =========================================================

def _load_nodes_from_db() -> pd.DataFrame:
    """Load all lunar_hazard_nodes from the Supabase/Postgres database."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured in .env")

    logger.info("Connecting to database using SQLAlchemy to load lunar_hazard_nodes …")
    engine = create_engine(database_url)

    query = """
        SELECT
            node_id,
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
            magnetic_field_bt,
            hazard_score,
            hazard_label
        FROM lunar_hazard_nodes
        ORDER BY node_id
    """
    df = pd.read_sql(query, engine)

    logger.info("Loaded %d lunar hazard nodes from database.", len(df))
    return df


# =========================================================
# GRAPH BUILDER
# =========================================================

def _build_graph(df: pd.DataFrame) -> tuple[dict, dict]:
    """
    Constructs the navigation graph from the loaded DataFrame.

    Edges are built in two phases:
    1. Intra-tile: same 8-directional neighbor logic as gnn_predictions.py
    2. Cross-tile: connects boundary supernodes across tile edges by
       matching (super_row, super_col) at the tile borders.

    Returns:
        graph       : {node_id: [{"neighbor_id": int, "distance_km": float}, ...]}
        nodes_by_id : {node_id: {all node fields}}
    """
    logger.info("Building navigation graph …")

    # -- Node lookup by full spatial key (tile_x, tile_y, super_row, super_col) --
    spatial_key_to_id: dict[tuple, int] = {}
    nodes_by_id: dict[int, dict] = {}

    for _, row in df.iterrows():
        nid = int(row["node_id"])
        key = (
            int(row["tile_x"]),
            int(row["tile_y"]),
            int(row["super_row"]),
            int(row["super_col"]),
        )
        spatial_key_to_id[key] = nid
        nodes_by_id[nid] = row.to_dict()

    # -- Determine max super_row / super_col per tile (for boundary detection) --
    # Compute per-tile dimensions
    tile_dims: dict[tuple, tuple] = {}  # (tile_x, tile_y) -> (max_sr, max_sc)
    for key in spatial_key_to_id:
        tx, ty, sr, sc = key
        tile = (tx, ty)
        if tile not in tile_dims:
            tile_dims[tile] = (sr, sc)
        else:
            cur_sr, cur_sc = tile_dims[tile]
            tile_dims[tile] = (max(cur_sr, sr), max(cur_sc, sc))

    # -- Adjacency list with pre-computed distances --
    graph: dict[int, list] = {nid: [] for nid in nodes_by_id}
    added_edges: set[tuple] = set()  # avoid duplicate edges

    def _add_edge(src: int, dst: int):
        if (src, dst) in added_edges:
            return
        added_edges.add((src, dst))
        added_edges.add((dst, src))

        src_node = nodes_by_id[src]
        dst_node = nodes_by_id[dst]
        dist_km = haversine_km(
            float(src_node["latitude"]), float(src_node["longitude"]),
            float(dst_node["latitude"]), float(dst_node["longitude"]),
        )
        graph[src].append({"neighbor_id": dst, "distance_km": dist_km})
        graph[dst].append({"neighbor_id": src, "distance_km": dist_km})

    # Phase 1: Intra-tile 8-directional neighbors
    for _, row in df.iterrows():
        nid = int(row["node_id"])
        tx = int(row["tile_x"])
        ty = int(row["tile_y"])
        sr = int(row["super_row"])
        sc = int(row["super_col"])

        for dr, dc in DIRECTIONS:
            neighbor_key = (tx, ty, sr + dr, sc + dc)
            if neighbor_key in spatial_key_to_id:
                nbr_id = spatial_key_to_id[neighbor_key]
                _add_edge(nid, nbr_id)

    # Phase 2: Cross-tile boundary connections
    # For each tile, connect its right/bottom boundary nodes to the
    # adjacent tile's left/top boundary nodes when super_row/col match.
    for (tx, ty), (max_sr, max_sc) in tile_dims.items():

        # Right boundary: connect (tx, ty, sr, max_sc) → (tx+1, ty, sr, 0)
        right_tile = (tx + 1, ty)
        if right_tile in tile_dims:
            for sr in range(max_sr + 1):
                src_key = (tx, ty, sr, max_sc)
                dst_key = (tx + 1, ty, sr, 0)
                if src_key in spatial_key_to_id and dst_key in spatial_key_to_id:
                    _add_edge(
                        spatial_key_to_id[src_key],
                        spatial_key_to_id[dst_key],
                    )

        # Bottom boundary: connect (tx, ty, max_sr, sc) → (tx, ty+1, 0, sc)
        bottom_tile = (tx, ty + 1)
        if bottom_tile in tile_dims:
            for sc in range(max_sc + 1):
                src_key = (tx, ty, max_sr, sc)
                dst_key = (tx, ty + 1, 0, sc)
                if src_key in spatial_key_to_id and dst_key in spatial_key_to_id:
                    _add_edge(
                        spatial_key_to_id[src_key],
                        spatial_key_to_id[dst_key],
                    )

        # Diagonal: connect (tx, ty, max_sr, max_sc) → (tx+1, ty+1, 0, 0)
        diag_tile = (tx + 1, ty + 1)
        if diag_tile in tile_dims:
            src_key = (tx, ty, max_sr, max_sc)
            dst_key = (tx + 1, ty + 1, 0, 0)
            if src_key in spatial_key_to_id and dst_key in spatial_key_to_id:
                _add_edge(
                    spatial_key_to_id[src_key],
                    spatial_key_to_id[dst_key],
                )

    total_edges = sum(len(v) for v in graph.values())
    logger.info(
        "Navigation graph built: %d nodes, %d directed edges.",
        len(graph), total_edges,
    )
    return graph, nodes_by_id



# =========================================================
# PUBLIC API
# =========================================================

def load_graph(force_reload: bool = False) -> tuple[dict, dict]:
    """
    Returns the cached (graph, nodes_by_id) tuple.
    Builds from DB on the first call or if force_reload=True.
    Thread-safe for single-process deployments (uvicorn default).

    Returns:
        graph       : adjacency list
        nodes_by_id : node metadata dict
    """
    global _graph, _nodes_by_id, _graph_loaded

    if _graph_loaded and not force_reload:
        return _graph, _nodes_by_id

    df = _load_nodes_from_db()
    _graph, _nodes_by_id = _build_graph(df)
    _graph_loaded = True
    return _graph, _nodes_by_id


def get_node(node_id: int) -> Optional[dict]:
    """Returns metadata for a single node. Graph must be loaded first."""
    if _nodes_by_id is None:
        return None
    return _nodes_by_id.get(int(node_id))


def get_all_nodes() -> dict:
    """Returns the full nodes_by_id dict."""
    if _nodes_by_id is None:
        return {}
    return _nodes_by_id
