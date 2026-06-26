"""
pathfinding.py
==============
A* pathfinding algorithm for the Lunar Rover Mission Planning System.

Uses the navigation graph produced by graph_builder.py.
Implements haversine great-circle heuristic on the Moon surface.

Supports three planning modes:
  - shortest  : minimize geographic distance only
  - safest    : minimize hazard exposure (slight distance penalty)
  - balanced  : balance distance and hazard equally
"""

import heapq
import math
import logging
from dataclasses import dataclass, field
from typing import Optional

from graph_builder import (
    haversine_km,
    resolve_hazard_score,
    MOON_RADIUS_KM,
)

logger = logging.getLogger(__name__)

# =========================================================
# PLANNING MODES
# =========================================================

PLANNING_MODES = {
    "shortest": {
        "distance_weight": 1.0,
        "hazard_weight": 0.0,
    },
    "safest": {
        "distance_weight": 0.2,
        "hazard_weight": 1.0,
    },
    "balanced": {
        "distance_weight": 1.0,
        "hazard_weight": 1.0,
    },
}


# =========================================================
# RESULT DATACLASS
# =========================================================

@dataclass
class PathResult:
    """Result returned by the A* planner."""
    path: list[int]                    # ordered list of node_ids
    distance_km: float                 # total great-circle distance
    risk_score: float                  # sum of hazard scores along path
    estimated_cost: float              # total A* cost (objective value)
    nodes_visited: int                 # nodes popped from priority queue
    mode: str                          # planning mode used
    success: bool = True
    error: Optional[str] = None

    # Per-node detail for the response payload
    path_details: list[dict] = field(default_factory=list)


# =========================================================
# PRIORITY QUEUE ITEM
# =========================================================

@dataclass(order=True)
class _PQItem:
    """Priority queue entry. Comparable by f_score only."""
    f_score: float
    node_id: int = field(compare=False)
    g_score: float = field(compare=False)   # cost from start to this node
    dist_so_far: float = field(compare=False)
    risk_so_far: float = field(compare=False)


# =========================================================
# HEURISTIC
# =========================================================

def _heuristic(
    node: dict,
    goal_node: dict,
    distance_weight: float,
) -> float:
    """
    Admissible heuristic: straight-line haversine distance to goal.
    Scaled by distance_weight so it never overestimates the true cost.
    """
    h = haversine_km(
        float(node["latitude"]),
        float(node["longitude"]),
        float(goal_node["latitude"]),
        float(goal_node["longitude"]),
    )
    return distance_weight * h


# =========================================================
# EDGE COST
# =========================================================

def _edge_cost(
    dist_km: float,
    neighbor_node: dict,
    distance_weight: float,
    hazard_weight: float,
) -> float:
    """
    Traversal cost for moving to a neighbor node.

    cost = distance_weight * geographic_distance_km
         + hazard_weight   * hazard_score_of_destination
    """
    h_score = resolve_hazard_score(neighbor_node)
    return (distance_weight * dist_km) + (hazard_weight * h_score)


# =========================================================
# A* ALGORITHM
# =========================================================

def astar(
    start_id: int,
    goal_id: int,
    graph: dict,
    nodes_by_id: dict,
    mode: str = "balanced",
) -> PathResult:
    """
    A* search from start_id to goal_id on the lunar navigation graph.

    Parameters
    ----------
    start_id    : node_id of the start node
    goal_id     : node_id of the goal node
    graph       : adjacency list {node_id: [{"neighbor_id", "distance_km"}]}
    nodes_by_id : {node_id: node_dict} with lat/lon/hazard fields
    mode        : one of "shortest", "safest", "balanced"

    Returns
    -------
    PathResult with full path, distance, risk, cost, and statistics.
    """
    mode_key = mode.lower().strip()
    if mode_key not in PLANNING_MODES:
        return PathResult(
            path=[], distance_km=0, risk_score=0,
            estimated_cost=0, nodes_visited=0,
            mode=mode, success=False,
            error=f"Unknown mode '{mode}'. Valid: {list(PLANNING_MODES)}",
        )

    weights = PLANNING_MODES[mode_key]
    d_w = weights["distance_weight"]
    h_w = weights["hazard_weight"]

    # Validate start and goal
    if start_id not in nodes_by_id:
        return PathResult(
            path=[], distance_km=0, risk_score=0,
            estimated_cost=0, nodes_visited=0,
            mode=mode, success=False,
            error=f"start_node_id {start_id} not found in graph.",
        )
    if goal_id not in nodes_by_id:
        return PathResult(
            path=[], distance_km=0, risk_score=0,
            estimated_cost=0, nodes_visited=0,
            mode=mode, success=False,
            error=f"goal_node_id {goal_id} not found in graph.",
        )

    goal_node = nodes_by_id[goal_id]
    start_node = nodes_by_id[start_id]

    # -- Data structures --
    open_set: list[_PQItem] = []        # min-heap
    came_from: dict[int, int] = {}      # node_id -> parent node_id
    g_score: dict[int, float] = {start_id: 0.0}
    dist_tracker: dict[int, float] = {start_id: 0.0}
    risk_tracker: dict[int, float] = {start_id: resolve_hazard_score(start_node)}
    visited: set[int] = set()

    # Push start
    h0 = _heuristic(start_node, goal_node, d_w)
    heapq.heappush(open_set, _PQItem(
        f_score=h0,
        node_id=start_id,
        g_score=0.0,
        dist_so_far=0.0,
        risk_so_far=0.0,
    ))

    nodes_popped = 0

    while open_set:
        current = heapq.heappop(open_set)
        current_id = current.node_id

        if current_id in visited:
            continue
        visited.add(current_id)
        nodes_popped += 1

        # -- Goal reached --
        if current_id == goal_id:
            path = _reconstruct_path(came_from, current_id)
            total_dist = dist_tracker.get(goal_id, 0.0)
            total_risk = risk_tracker.get(goal_id, 0.0)
            total_cost = g_score.get(goal_id, 0.0)

            # Build per-node detail list
            path_details = _build_path_details(path, nodes_by_id)

            logger.info(
                "A* [%s]: path length=%d nodes, dist=%.2f km, risk=%.2f, cost=%.2f, expanded=%d",
                mode_key, len(path), total_dist, total_risk, total_cost, nodes_popped,
            )
            return PathResult(
                path=path,
                distance_km=round(total_dist, 3),
                risk_score=round(total_risk, 3),
                estimated_cost=round(total_cost, 3),
                nodes_visited=nodes_popped,
                mode=mode_key,
                success=True,
                path_details=path_details,
            )

        # -- Expand neighbors --
        for edge in graph.get(current_id, []):
            nbr_id = edge["neighbor_id"]
            if nbr_id in visited:
                continue

            nbr_node = nodes_by_id[nbr_id]
            edge_dist = edge["distance_km"]

            step_cost = _edge_cost(edge_dist, nbr_node, d_w, h_w)
            tentative_g = g_score[current_id] + step_cost

            if tentative_g < g_score.get(nbr_id, math.inf):
                came_from[nbr_id] = current_id
                g_score[nbr_id] = tentative_g
                dist_tracker[nbr_id] = dist_tracker.get(current_id, 0.0) + edge_dist
                risk_tracker[nbr_id] = (
                    risk_tracker.get(current_id, 0.0)
                    + resolve_hazard_score(nbr_node)
                )
                h = _heuristic(nbr_node, goal_node, d_w)
                heapq.heappush(open_set, _PQItem(
                    f_score=tentative_g + h,
                    node_id=nbr_id,
                    g_score=tentative_g,
                    dist_so_far=dist_tracker[nbr_id],
                    risk_so_far=risk_tracker[nbr_id],
                ))

    # -- No path found --
    logger.warning(
        "A* [%s]: No path from %d to %d. Expanded %d nodes.",
        mode_key, start_id, goal_id, nodes_popped,
    )
    return PathResult(
        path=[], distance_km=0, risk_score=0,
        estimated_cost=0, nodes_visited=nodes_popped,
        mode=mode_key, success=False,
        error=f"No path found from node {start_id} to node {goal_id}.",
    )


# =========================================================
# PATH RECONSTRUCTION
# =========================================================

def _reconstruct_path(came_from: dict, current_id: int) -> list[int]:
    """Reconstructs the path by tracing came_from back to the start."""
    path = [current_id]
    while current_id in came_from:
        current_id = came_from[current_id]
        path.append(current_id)
    path.reverse()
    return path


# =========================================================
# PATH DETAIL BUILDER
# =========================================================

def _build_path_details(path: list[int], nodes_by_id: dict) -> list[dict]:
    """Builds the per-node detail list included in PathResult."""
    details = []
    for nid in path:
        node = nodes_by_id.get(nid, {})
        details.append({
            "node_id": nid,
            "latitude": float(node.get("latitude", 0)),
            "longitude": float(node.get("longitude", 0)),
            "hazard_label": str(node.get("hazard_label") or "SAFE"),
            "hazard_score": float(node.get("hazard_score") or 0),
            "prediction_confidence": 0.0,
            "elevation": float(node.get("elevation") or 0),
            "roughness": float(node.get("roughness") or 0),
        })
    return details
