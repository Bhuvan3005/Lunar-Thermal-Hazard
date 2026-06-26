"""
route_api.py
============
FastAPI backend for the Lunar Rover Mission Planning System.

Endpoints:
  GET  /health   -- Liveness probe + graph stats
  GET  /nodes    -- All navigable nodes (lat/lon/hazard) for frontend
  POST /route    -- A* route planning between two lunar nodes

Start with:
  python route_api.py
  or
  uvicorn route_api:app --host 0.0.0.0 --port 8000 --reload
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Literal, Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from graph_builder import load_graph, get_all_nodes
from pathfinding import astar, PLANNING_MODES

# =========================================================
# SETUP
# =========================================================

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ROUTE_API] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Cached graph (module-level, shared across requests)
_graph: Optional[dict] = None
_nodes_by_id: Optional[dict] = None


# =========================================================
# LIFESPAN â€” build graph at startup
# =========================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load and cache the navigation graph when the server starts."""
    global _graph, _nodes_by_id
    logger.info("Server startup: loading lunar navigation graph â€¦")
    try:
        _graph, _nodes_by_id = load_graph()
        logger.info(
            "Navigation graph ready: %d nodes loaded.", len(_nodes_by_id)
        )
    except Exception as exc:
        logger.error("Failed to build navigation graph: %s", exc)
        # Server starts anyway; requests will fail gracefully.
    yield
    logger.info("Server shutting down.")


# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI(
    title="Lunar Rover Mission Planning API",
    description=(
        "A* pathfinding on the lunar hazard graph. "
        "Supports shortest, safest, and balanced routing modes."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Allow all HTTP/HTTPS origins dynamically (supports allow_credentials=True)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex="https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# REQUEST / RESPONSE MODELS
# =========================================================

class RouteRequest(BaseModel):
    start_node_id: int = Field(..., description="Node ID of the rover start position")
    goal_node_id: int = Field(..., description="Node ID of the target destination")
    mode: Literal["shortest", "safest", "balanced"] = Field(
        "balanced", description="Path planning mode"
    )


class NodeDetail(BaseModel):
    node_id: int
    latitude: float
    longitude: float
    hazard_label: str
    hazard_score: float
    elevation: float
    roughness: float


class RouteResponse(BaseModel):
    path: list[int]
    path_details: list[NodeDetail]
    distance_km: float
    risk_score: float
    estimated_cost: float
    nodes_visited: int
    mode: str
    avg_hazard_score: float
    node_count: int


class HealthResponse(BaseModel):
    status: str
    graph_loaded: bool
    node_count: int
    edge_count: int
    available_modes: list[str]


class NavigableNode(BaseModel):
    node_id: int
    latitude: float
    longitude: float
    hazard_label: str
    hazard_score: float


# =========================================================
# DEPENDENCY HELPER
# =========================================================

def _require_graph():
    """Raise 503 if the graph hasn't been loaded yet."""
    if _graph is None or _nodes_by_id is None:
        raise HTTPException(
            status_code=503,
            detail="Navigation graph not yet loaded. Retry in a few seconds.",
        )
    return _graph, _nodes_by_id


# =========================================================
# ENDPOINTS
# =========================================================

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health():
    """
    Liveness probe. Returns graph statistics when loaded.
    """
    loaded = _graph is not None and _nodes_by_id is not None
    node_count = len(_nodes_by_id) if loaded else 0
    edge_count = sum(len(v) for v in _graph.values()) if loaded else 0

    return HealthResponse(
        status="ok",
        graph_loaded=loaded,
        node_count=node_count,
        edge_count=edge_count,
        available_modes=list(PLANNING_MODES.keys()),
    )


@app.get("/nodes", response_model=list[NavigableNode], tags=["Navigation"])
async def get_nodes():
    """
    Returns all navigable lunar nodes with lat/lon and hazard data.
    Used by the frontend to render clickable node targets.
    """
    graph, nodes_by_id = _require_graph()
    result = []
    for nid, node in nodes_by_id.items():
        result.append(NavigableNode(
            node_id=nid,
            latitude=float(node.get("latitude", 0)),
            longitude=float(node.get("longitude", 0)),
            hazard_label=str(
                node.get("hazard_label") or "SAFE"
            ),
            hazard_score=float(node.get("hazard_score") or 0),
            
        ))
    return result


@app.post("/route", response_model=RouteResponse, tags=["Navigation"])
async def plan_route(request: RouteRequest):
    """
    Plan an optimal rover route between two lunar nodes using A*.

    **Modes**:
    - `shortest`  â€” minimize geographic distance
    - `safest`    â€” minimize hazard exposure
    - `balanced`  â€” balance distance and hazard equally
    """
    graph, nodes_by_id = _require_graph()

    logger.info(
        "Route request: start=%d, goal=%d, mode=%s",
        request.start_node_id, request.goal_node_id, request.mode,
    )

    if request.start_node_id == request.goal_node_id:
        raise HTTPException(
            status_code=400,
            detail="start_node_id and goal_node_id must be different.",
        )

    result = astar(
        start_id=request.start_node_id,
        goal_id=request.goal_node_id,
        graph=graph,
        nodes_by_id=nodes_by_id,
        mode=request.mode,
    )

    if not result.success:
        raise HTTPException(status_code=404, detail=result.error)

    # Compute average hazard
    avg_hazard = (
        result.risk_score / len(result.path) if result.path else 0.0
    )

    # Validate and coerce path_details
    validated_details = []
    for d in result.path_details:
        validated_details.append(NodeDetail(
            node_id=d["node_id"],
            latitude=d["latitude"],
            longitude=d["longitude"],
            hazard_label=d["hazard_label"],
            hazard_score=d["hazard_score"],
            elevation=d["elevation"],
            roughness=d["roughness"],
        ))

    return RouteResponse(
        path=result.path,
        path_details=validated_details,
        distance_km=result.distance_km,
        risk_score=result.risk_score,
        estimated_cost=result.estimated_cost,
        nodes_visited=result.nodes_visited,
        mode=result.mode,
        avg_hazard_score=round(avg_hazard, 3),
        node_count=len(result.path),
    )


# =========================================================
# ENTRYPOINT
# =========================================================

if __name__ == "__main__":
    uvicorn.run(
        "route_api:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
