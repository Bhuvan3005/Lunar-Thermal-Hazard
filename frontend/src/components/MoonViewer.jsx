// @ts-nocheck

/**
 * MoonViewer.jsx
 * ==============
 * Lunar Rover Mission Planning System — main visualization component.
 *
 * Features:
 *  - 3D Moon globe with existing hazard node overlays (unchanged)
 *  - Mission Planning Panel: select start/goal nodes, choose mode, generate route
 *  - A* route visualization: glowing TubeGeometry on moon surface
 *  - Route Analytics Panel: distance, hazard, node count, avg score
 *  - Enhanced hover tooltip with full node detail
 */

import React, {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import { Canvas, useFrame } from '@react-three/fiber';

import {
  OrbitControls,
  Sphere,
  Stars,
} from '@react-three/drei';

import * as THREE from 'three';

import { createClient } from '@supabase/supabase-js';

// =====================================================
// CONSTANTS
// =====================================================

const API_BASE = 'http://localhost:8000';
const MOON_RADIUS = 2;          // Three.js units
const HAZARD_RADIUS = 2.06;     // Hazard dots sit just above surface
const ROUTE_RADIUS = 2.055;     // Route tube slightly above surface

const ROUTE_COLORS = {
  shortest: '#3b82f6',
  safest:   '#22c55e',
  balanced: '#ffffff',
};

const HAZARD_COLORS = {
  SAFE:     '#00d9ff',
  MODERATE: '#ffe066',
  HIGH:     '#ff922b',
  EXTREME:  '#ff3b3b',
};

// =====================================================
// SUPABASE
// =====================================================

const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY,
);

// =====================================================
// MOON TEXTURE
// =====================================================

const textureLoader = new THREE.TextureLoader();
const moonTexture = textureLoader.load(
  'https://threejs.org/examples/textures/planets/moon_1024.jpg',
);

// =====================================================
// UTILITY: lat/lon → XYZ on a sphere
// =====================================================

function latLonToXYZ(lat, lon, radius = MOON_RADIUS) {
  const latRad = (lat * Math.PI) / 180;
  const lonRad = (lon * Math.PI) / 180;
  return new THREE.Vector3(
    radius * Math.cos(latRad) * Math.cos(lonRad),
    radius * Math.sin(latRad),
    radius * Math.cos(latRad) * Math.sin(lonRad),
  );
}

// =====================================================
// HAZARD POINT
// =====================================================

function HazardPoint({ node, onHover, isStart, isGoal, isOnPath, planningMode, onClick }) {
  const position = latLonToXYZ(node.latitude, node.longitude, HAZARD_RADIUS);

  const label = node.hazard || node.hazard_label || 'SAFE';
  let color = HAZARD_COLORS[label] || '#ffffff';

  // Override colour for start/goal markers
  if (isStart) color = '#22c55e';
  if (isGoal)  color = '#ef4444';

  // Path nodes get a slight size boost
  const baseScale = isStart || isGoal ? 0.07
    : isOnPath ? 0.045
    : label === 'EXTREME' ? 0.05
    : label === 'HIGH' ? 0.04
    : label === 'MODERATE' ? 0.03
    : 0.025;

  const emissive = isStart || isGoal || isOnPath ? 3.5 : 1.5;

  return (
    <mesh
      position={position.toArray()}
      onPointerOver={(e) => { e.stopPropagation(); onHover(node); }}
      onPointerOut={() => onHover(null)}
      onClick={(e) => { e.stopPropagation(); if (onClick) onClick(node); }}
    >
      <sphereGeometry args={[baseScale, 14, 14]} />
      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={emissive}
      />
    </mesh>
  );
}

// =====================================================
// ROUTE LINE (TubeGeometry along lunar surface)
// =====================================================

function RouteLine({ pathDetails, mode }) {
  const tubeRef = useRef();

  const tubeGeometry = useMemo(() => {
    if (!pathDetails || pathDetails.length < 2) return null;

    // Project all path nodes onto the moon surface at ROUTE_RADIUS
    const points = pathDetails.map((n) =>
      latLonToXYZ(n.latitude, n.longitude, ROUTE_RADIUS),
    );

    // CatmullRomCurve3 gives a smooth spline through the points
    const curve = new THREE.CatmullRomCurve3(points, false, 'catmullrom', 0.5);
    const segments = Math.max(points.length * 8, 64);

    return new THREE.TubeGeometry(curve, segments, 0.006, 8, false);
  }, [pathDetails]);

  if (!tubeGeometry) return null;

  const color = ROUTE_COLORS[mode] || '#ffffff';

  return (
    <mesh ref={tubeRef} geometry={tubeGeometry}>
      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={4}
        transparent
        opacity={0.92}
      />
    </mesh>
  );
}

// =====================================================
// MOON SCENE
// =====================================================

function MoonScene({
  nodes,
  onHover,
  planningActive,
  startNode,
  goalNode,
  pathNodeIds,
  pathDetails,
  routeMode,
  onNodeClick,
}) {
  const pathSet = useMemo(() => new Set(pathNodeIds || []), [pathNodeIds]);

  return (
    <group>
      {/* Moon globe */}
      <Sphere args={[MOON_RADIUS, 128, 128]}>
        <meshStandardMaterial map={moonTexture} />
      </Sphere>

      {/* Route line */}
      {pathDetails && pathDetails.length >= 2 && (
        <RouteLine pathDetails={pathDetails} mode={routeMode} />
      )}

      {/* Hazard / navigation nodes */}
      {nodes.map((node) => (
        <HazardPoint
          key={node.id ?? node.node_id}
          node={node}
          onHover={onHover}
          isStart={startNode?.node_id === (node.id ?? node.node_id)}
          isGoal={goalNode?.node_id === (node.id ?? node.node_id)}
          isOnPath={pathSet.has(node.id ?? node.node_id)}
          planningMode={planningActive}
          onClick={planningActive ? onNodeClick : null}
        />
      ))}
    </group>
  );
}

// =====================================================
// MISSION PLANNING PANEL
// =====================================================

function MissionPanel({
  planningActive,
  onTogglePlanning,
  startNode,
  goalNode,
  mode,
  onModeChange,
  onGenerate,
  onClear,
  computing,
  routeStatus,
  statusType,
}) {
  const canGenerate = startNode && goalNode && !computing;

  return (
    <div className="panel mission-panel">
      <div className="panel-title">Mission Planner</div>

      {/* Toggle planning mode */}
      <button
        className={`mode-toggle-btn ${planningActive ? 'active' : ''}`}
        onClick={onTogglePlanning}
        id="toggle-planning-btn"
      >
        {planningActive ? '✓ Route Planning Active' : 'Enable Route Planning'}
      </button>

      {/* Start / Goal indicators */}
      <div className="selection-row">
        <div className={`selection-indicator start ${startNode ? 'set' : ''}`}>
          <span className="dot" />
          {startNode
            ? `Start: Node #${startNode.node_id}`
            : planningActive
            ? 'Click a node to set Start'
            : 'Enable planning to select'}
        </div>
        <div className={`selection-indicator goal ${goalNode ? 'set' : ''}`}>
          <span className="dot" />
          {goalNode
            ? `Goal: Node #${goalNode.node_id}`
            : planningActive && startNode
            ? 'Click a node to set Goal'
            : '—'}
        </div>
      </div>

      {/* Mode selector */}
      <div className="mode-selector">
        {['shortest', 'safest', 'balanced'].map((m) => (
          <button
            key={m}
            className={`mode-btn ${mode === m ? `active ${m}` : ''}`}
            onClick={() => onModeChange(m)}
            id={`mode-btn-${m}`}
          >
            {m}
          </button>
        ))}
      </div>

      {/* Action buttons */}
      <div className="route-actions">
        <button
          className="route-btn generate"
          disabled={!canGenerate}
          onClick={onGenerate}
          id="generate-route-btn"
        >
          {computing ? 'Computing…' : 'Generate Route'}
        </button>
        <button
          className="route-btn clear"
          onClick={onClear}
          id="clear-route-btn"
        >
          Clear
        </button>
      </div>

      {/* Status */}
      {routeStatus && (
        <div className={`route-status ${statusType}`}>
          {routeStatus}
        </div>
      )}
    </div>
  );
}

// =====================================================
// ROUTE ANALYTICS PANEL
// =====================================================

function RouteAnalyticsPanel({ routeResult, mode }) {
  if (!routeResult) return null;

  return (
    <div className="panel route-analytics-panel">
      <div className="panel-title">
        Route Analytics
        <span className={`route-badge ${mode}`}>{mode}</span>
      </div>

      <div className="analytics-stat">
        <span className="label">Total Distance</span>
        <span className="value">{routeResult.distance_km.toFixed(1)} km</span>
      </div>
      <div className="analytics-stat">
        <span className="label">Hazard Exposure</span>
        <span className="value">{routeResult.risk_score.toFixed(1)}</span>
      </div>
      <div className="analytics-stat">
        <span className="label">Nodes Traversed</span>
        <span className="value">{routeResult.node_count}</span>
      </div>
      <div className="analytics-stat">
        <span className="label">Avg Hazard Score</span>
        <span className="value">{routeResult.avg_hazard_score.toFixed(2)}</span>
      </div>
      <div className="analytics-stat">
        <span className="label">Nodes Expanded</span>
        <span className="value">{routeResult.nodes_visited.toLocaleString()}</span>
      </div>
      <div className="analytics-stat">
        <span className="label">Est. Cost</span>
        <span className="value">{routeResult.estimated_cost.toFixed(1)}</span>
      </div>
    </div>
  );
}

// =====================================================
// HOVER TOOLTIP
// =====================================================

function HoverTooltip({ hovered }) {
  if (!hovered) return null;

  const label = hovered.hazard || hovered.hazard_label || 'SAFE';
  const score = typeof hovered.hazard_score === 'number'
    ? hovered.hazard_score.toFixed(4)
    : (hovered.hazard_score ?? '—');
  const conf = typeof hovered.confidence === 'number'
    ? hovered.confidence.toFixed(3)
    : typeof hovered.prediction_confidence === 'number'
    ? hovered.prediction_confidence.toFixed(3)
    : '—';

  return (
    <div className="panel tooltip-panel">
      <div className="tooltip-title">Hazard Node</div>
      <div className="panel-row">
        <span>Hazard Class</span>
        <span className={`hazard-chip ${label}`}>{label}</span>
      </div>
      <div className="panel-row">
        <span>Hazard Score</span>
        <span>{score}</span>
      </div>
      <div className="panel-row">
        <span>Latitude</span>
        <span>{(hovered.latitude ?? 0).toFixed(4)}°</span>
      </div>
      <div className="panel-row">
        <span>Longitude</span>
        <span>{(hovered.longitude ?? 0).toFixed(4)}°</span>
      </div>
      <div className="panel-row">
        <span>Confidence</span>
        <span>{conf}</span>
      </div>
      {hovered.solarWind !== undefined && (
        <div className="panel-row">
          <span>Solar Wind</span>
          <span>{hovered.solarWind.toFixed(1)} km/s</span>
        </div>
      )}
      {hovered.plasma !== undefined && (
        <div className="panel-row">
          <span>Plasma Density</span>
          <span>{hovered.plasma.toFixed(2)}</span>
        </div>
      )}
      {hovered.magnetic !== undefined && (
        <div className="panel-row">
          <span>Magnetic Field</span>
          <span>{hovered.magnetic.toFixed(2)} nT</span>
        </div>
      )}
    </div>
  );
}

// =====================================================
// HAZARD COUNTS PANEL (existing, preserved)
// =====================================================

function HazardCountsPanel({ counts, totalRendered }) {
  return (
    <div className="panel analytics-panel">
      <div className="panel-title">LunaGraph AI</div>
      <div className="panel-grid">
        <div className="stat-card safe">SAFE</div>
        <div className="stat-value">{counts.SAFE}</div>
        <div className="stat-card moderate">MODERATE</div>
        <div className="stat-value">{counts.MODERATE}</div>
        <div className="stat-card high">HIGH</div>
        <div className="stat-value">{counts.HIGH}</div>
        <div className="stat-card extreme">EXTREME</div>
        <div className="stat-value">{counts.EXTREME}</div>
      </div>
      <div style={{ marginTop: '0.75rem', fontSize: '0.75rem', opacity: 0.45, textAlign: 'center' }}>
        Rendering {totalRendered.toLocaleString()} nodes
      </div>
    </div>
  );
}

// =====================================================
// MAIN APP
// =====================================================

export default function App() {
  // -- Hazard node state (existing) --
  const [nodes, setNodes] = useState([]);
  const [hovered, setHovered] = useState(null);
  const [loading, setLoading] = useState(true);

  // -- Mission planning state --
  const [planningActive, setPlanningActive] = useState(false);
  const [startNode, setStartNode] = useState(null);
  const [goalNode, setGoalNode] = useState(null);
  const [routeMode, setRouteMode] = useState('balanced');
  const [computing, setComputing] = useState(false);
  const [routeResult, setRouteResult] = useState(null);   // full API response
  const [pathDetails, setPathDetails] = useState([]);     // [{lat, lon, …}]
  const [routeStatus, setRouteStatus] = useState('');
  const [statusType, setStatusType] = useState('');       // '' | 'error' | 'computing'

  // ===================================================
  // FETCH HAZARD NODES FROM SUPABASE (existing logic)
  // ===================================================

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const PAGE_SIZE = 1000;
      let allRows = [];
      let from = 0;

      while (true) {
        const { data, error } = await supabase
          .from('lunar_hazard_nodes')
          .select(`
            node_id,
            latitude,
            longitude,
            hazard_label,
            hazard_score,
            solar_wind_speed,
            plasma_density,
            magnetic_field_bt
          `)
          .range(from, from + PAGE_SIZE - 1);

        if (error || !data || data.length === 0) break;
        allRows = [...allRows, ...data];
        from += PAGE_SIZE;
        if (data.length < PAGE_SIZE) break;
      }

      // Format nodes for the 3D scene
      const formatted = allRows.map((row) => ({
        id: row.node_id,
        node_id: row.node_id,
        latitude: Number(row.latitude),
        longitude: Number(row.longitude),
        hazard: row.hazard_label || 'SAFE',
        hazard_label: row.hazard_label || 'SAFE',
        hazard_score: Number(row.hazard_score || 0),
        confidence: 0,
        prediction_confidence: 0,
        solarWind: Number(row.solar_wind_speed || 0),
        plasma: Number(row.plasma_density || 0),
        magnetic: Number(row.magnetic_field_bt || 0),
      }));

      // Random sample up to 3000 for performance
      const MAX_RENDER = 3000;
      const sampled = [];
      const used = new Set();
      while (sampled.length < MAX_RENDER && sampled.length < formatted.length) {
        const idx = Math.floor(Math.random() * formatted.length);
        if (!used.has(idx)) {
          used.add(idx);
          sampled.push(formatted[idx]);
        }
      }

      setNodes(sampled);
    } catch (err) {
      console.error('fetchData error:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 60_000);
    return () => clearInterval(iv);
  }, [fetchData]);

  // ===================================================
  // HAZARD COUNTS (existing)
  // ===================================================

  const counts = useMemo(() => {
    const c = { SAFE: 0, MODERATE: 0, HIGH: 0, EXTREME: 0 };
    nodes.forEach((n) => { if (c[n.hazard] !== undefined) c[n.hazard]++; });
    return c;
  }, [nodes]);

  // ===================================================
  // PATH NODE ID SET
  // ===================================================

  const pathNodeIds = useMemo(
    () => routeResult?.path || [],
    [routeResult],
  );

  // ===================================================
  // PLANNING MODE: NODE CLICK HANDLER
  // ===================================================

  const handleNodeClick = useCallback((node) => {
    if (!planningActive) return;

    const nid = node.id ?? node.node_id;
    const clickedNode = { ...node, node_id: nid };

    if (!startNode) {
      setStartNode(clickedNode);
      setRouteStatus('Start set. Click a destination node.');
      setStatusType('');
    } else if (!goalNode && nid !== startNode.node_id) {
      setGoalNode(clickedNode);
      setRouteStatus('Goal set. Click "Generate Route".');
      setStatusType('');
    } else if (nid === startNode.node_id) {
      // Re-click start clears start
      setStartNode(null);
      setGoalNode(null);
      setRouteStatus('Start cleared. Click a node to set start.');
      setStatusType('');
    } else {
      // Replace goal
      setGoalNode(clickedNode);
      setRouteStatus('Goal updated. Click "Generate Route".');
      setStatusType('');
    }
  }, [planningActive, startNode, goalNode]);

  // ===================================================
  // TOGGLE PLANNING
  // ===================================================

  const handleTogglePlanning = useCallback(() => {
    setPlanningActive((v) => {
      if (v) {
        // Deactivating — clear selection but keep route
        setStartNode(null);
        setGoalNode(null);
        setRouteStatus('');
        setStatusType('');
      } else {
        setRouteStatus('Click a node on the globe to set Start.');
        setStatusType('');
      }
      return !v;
    });
  }, []);

  // ===================================================
  // GENERATE ROUTE (A* API CALL)
  // ===================================================

  const handleGenerateRoute = useCallback(async () => {
    if (!startNode || !goalNode) return;

    setComputing(true);
    setRouteStatus('Computing optimal route…');
    setStatusType('computing');
    setRouteResult(null);
    setPathDetails([]);

    try {
      const resp = await fetch(`${API_BASE}/route`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          start_node_id: startNode.node_id,
          goal_node_id: goalNode.node_id,
          mode: routeMode,
        }),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }

      const data = await resp.json();
      setRouteResult(data);
      setPathDetails(data.path_details || []);
      setRouteStatus(
        `Route found: ${data.node_count} nodes, ${data.distance_km.toFixed(1)} km.`,
      );
      setStatusType('');
    } catch (err) {
      console.error('Route error:', err);
      setRouteStatus(`Error: ${err.message}`);
      setStatusType('error');
    } finally {
      setComputing(false);
    }
  }, [startNode, goalNode, routeMode]);

  // ===================================================
  // CLEAR ROUTE
  // ===================================================

  const handleClear = useCallback(() => {
    setStartNode(null);
    setGoalNode(null);
    setRouteResult(null);
    setPathDetails([]);
    setRouteStatus('');
    setStatusType('');
  }, []);

  // ===================================================
  // RENDER
  // ===================================================

  return (
    <div style={{ width: '100vw', height: '100vh', background: '#05070d', overflow: 'hidden', position: 'relative' }}>

      {/* 3D Canvas */}
      <Canvas camera={{ position: [0, 0, 5] }}>
        <ambientLight intensity={0.6} />
        <directionalLight position={[5, 5, 5]} intensity={2} />

        <Stars radius={100} depth={50} count={5000} factor={4} saturation={0} fade />

        <Suspense fallback={null}>
          <MoonScene
            nodes={nodes}
            onHover={setHovered}
            planningActive={planningActive}
            startNode={startNode}
            goalNode={goalNode}
            pathNodeIds={pathNodeIds}
            pathDetails={pathDetails}
            routeMode={routeMode}
            onNodeClick={handleNodeClick}
          />
        </Suspense>

        <OrbitControls enablePan={false} minDistance={3} maxDistance={10} />
      </Canvas>

      {/* Hazard counts panel (existing) */}
      <HazardCountsPanel counts={counts} totalRendered={nodes.length} />

      {/* Hover tooltip (enhanced) */}
      <HoverTooltip hovered={hovered} />

      {/* Mission planning panel */}
      <MissionPanel
        planningActive={planningActive}
        onTogglePlanning={handleTogglePlanning}
        startNode={startNode}
        goalNode={goalNode}
        mode={routeMode}
        onModeChange={setRouteMode}
        onGenerate={handleGenerateRoute}
        onClear={handleClear}
        computing={computing}
        routeStatus={routeStatus}
        statusType={statusType}
      />

      {/* Route analytics panel (shown when route exists) */}
      {routeResult && (
        <RouteAnalyticsPanel routeResult={routeResult} mode={routeMode} />
      )}

      {/* Loading overlay */}
      {loading && (
        <div className="loading-overlay">
          <div className="loader" />
          <div className="loading-message">Loading Lunar Intelligence…</div>
        </div>
      )}
    </div>
  );
}
