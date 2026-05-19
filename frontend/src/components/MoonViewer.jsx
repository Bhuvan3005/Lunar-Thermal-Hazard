
// @ts-nocheck

import React, {
  Suspense,
  useEffect,
  useMemo,
  useState,
} from 'react';

import { Canvas } from '@react-three/fiber';

import {
  OrbitControls,
  Sphere,
  Stars,
  Html,
} from '@react-three/drei';

import * as THREE from 'three';

import { createClient } from '@supabase/supabase-js';

// =====================================================
// SUPABASE
// =====================================================

const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY
);

// =====================================================
// MOON TEXTURE
// =====================================================

const textureLoader = new THREE.TextureLoader();

const moonTexture = textureLoader.load(
  'https://threejs.org/examples/textures/planets/moon_1024.jpg'
);

// =====================================================
// COLORS
// =====================================================

const hazardColors = {
  SAFE: '#00d9ff',
  MODERATE: '#ffe066',
  HIGH: '#ff922b',
  EXTREME: '#ff3b3b',
};

// =====================================================
// LAT/LON → XYZ
// =====================================================

function latLonToXYZ(
  lat,
  lon,
  radius = 2.12
) {

  const latRad =
    (lat * Math.PI) / 180;

  const lonRad =
    (lon * Math.PI) / 180;

  const x =
    radius *
    Math.cos(latRad) *
    Math.cos(lonRad);

  const y =
    radius *
    Math.sin(latRad);

  const z =
    radius *
    Math.cos(latRad) *
    Math.sin(lonRad);

  return [x, y, z];
}

// =====================================================
// HAZARD POINT
// =====================================================

function HazardPoint({ node, onHover }) {

  const position = latLonToXYZ(
    node.latitude,
    node.longitude,
    2.05
  );

  const color =
    hazardColors[node.hazard] || '#ffffff';

  const scale =
    node.hazard === 'EXTREME'
      ? 0.05
      : node.hazard === 'HIGH'
      ? 0.04
      : node.hazard === 'MODERATE'
      ? 0.03
      : 0.025;

  return (
    <mesh
      position={position}
      onPointerOver={() => onHover(node)}
      onPointerOut={() => onHover(null)}
    >
      <sphereGeometry args={[scale, 16, 16]} />

      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={2}
      />
    </mesh>
  );
}

// =====================================================
// MOON
// =====================================================

function Moon({ nodes, onHover }) {

  return (
    <group>

      {/* MOON */}

      <Sphere args={[2, 128, 128]}>

        <meshStandardMaterial
          map={moonTexture}
        />

      </Sphere>

      {/* AI OVERLAYS */}

      {nodes.map((node) => (

        <HazardPoint
          key={node.id}
          node={node}
          onHover={onHover}
        />

      ))}

    </group>
  );
}

// =====================================================
// MAIN APP
// =====================================================

export default function App() {

  const [nodes, setNodes] = useState([]);

  const [hovered, setHovered] = useState(null);

  const [loading, setLoading] = useState(true);

  // ===================================================
  // FETCH DATA
  // ===================================================

  const fetchData = async () => {

  try {

    setLoading(true);

    // ===========================================
    // FETCH ALL ROWS USING PAGINATION
    // ===========================================

    const PAGE_SIZE = 1000;

    let allRows = [];

    let from = 0;

    while (true) {

      const { data, error } =
        await supabase

          .from('lunar_hazard_nodes')

          .select(`
            node_id,
            latitude,
            longitude,
            gnn_prediction,
            prediction_confidence,
            solar_wind_speed,
            plasma_density,
            magnetic_field_bt
          `)

          .range(
            from,
            from + PAGE_SIZE - 1
          );

      if (error) {

        console.error(error);

        break;
      }

      if (!data || data.length === 0) {
        break;
      }

      allRows = [
        ...allRows,
        ...data
      ];

      from += PAGE_SIZE;

      if (data.length < PAGE_SIZE) {
        break;
      }
    }

    console.log(
      'TOTAL DB ROWS:',
      allRows.length
    );

    // ===========================================
    // FORMAT
    // ===========================================

    const formatted =
      allRows.map((row) => ({

        id: row.node_id,

        latitude:
          Number(row.latitude),

        longitude:
          Number(row.longitude),

        hazard:
          row.gnn_prediction || 'SAFE',

        confidence:
          Number(
            row.prediction_confidence || 0
          ),

        solarWind:
          Number(
            row.solar_wind_speed || 0
          ),

        plasma:
          Number(
            row.plasma_density || 0
          ),

        magnetic:
          Number(
            row.magnetic_field_bt || 0
          ),

      }));

    // ===========================================
    // RANDOM SAMPLING
    // ===========================================

    const MAX_RENDER_NODES = 3000;

    const sampled = [];

    const used = new Set();

    while (

      sampled.length <
        MAX_RENDER_NODES &&

      sampled.length <
        formatted.length

    ) {

      const idx = Math.floor(

        Math.random() *
          formatted.length

      );

      if (!used.has(idx)) {

        used.add(idx);

        sampled.push(
          formatted[idx]
        );
      }
    }

    console.log(
      'RENDERING:',
      sampled.length
    );

    // ===========================================
    // UPDATE UI
    // ===========================================

    setNodes(sampled);

    setLoading(false);

  } catch (err) {

    console.error(err);

    setLoading(false);
  }
};

  // ===================================================
  // INITIAL LOAD
  // ===================================================

  useEffect(() => {

    fetchData();

    const interval = setInterval(() => {
      fetchData();
    }, 60000);

    return () => clearInterval(interval);

  }, []);

  // ===================================================
  // COUNTS
  // ===================================================

  const counts = useMemo(() => {

    const c = {
      SAFE: 0,
      MODERATE: 0,
      HIGH: 0,
      EXTREME: 0,
    };

    nodes.forEach((n) => {

      if (c[n.hazard] !== undefined) {
        c[n.hazard] += 1;
      }

    });

    return c;

  }, [nodes]);

  // ===================================================
  // RENDER
  // ===================================================

  return (

    <div
      style={{
        width: '100vw',
        height: '100vh',
        background: 'black',
        overflow: 'hidden',
        position: 'relative',
      }}
    >

      {/* =========================================== */}
      {/* CANVAS */}
      {/* =========================================== */}

      <Canvas camera={{ position: [0, 0, 5] }}>

        {/* LIGHTS */}

        <ambientLight intensity={0.6} />

        <directionalLight
          position={[5, 5, 5]}
          intensity={2}
        />

        {/* STARS */}

        <Stars
          radius={100}
          depth={50}
          count={5000}
          factor={4}
          saturation={0}
          fade
        />

        {/* MOON */}

        <Suspense fallback={null}>

          <Moon
            nodes={nodes}
            onHover={setHovered}
          />

        </Suspense>

        {/* CONTROLS */}

        <OrbitControls
          enablePan={false}
          minDistance={3}
          maxDistance={10}
        />

      </Canvas>

      {/* =========================================== */}
      {/* ANALYTICS PANEL */}
      {/* =========================================== */}

      <div
        style={{
          position: 'absolute',
          top: 20,
          left: 20,
          zIndex: 100,
          background: 'rgba(0,0,0,0.7)',
          color: 'white',
          padding: 20,
          borderRadius: 16,
          backdropFilter: 'blur(10px)',
          minWidth: 240,
          fontFamily: 'sans-serif',
        }}
      >

        <h2>LunaGraph AI</h2>

        <div>
          SAFE: {counts.SAFE}
        </div>

        <div>
          MODERATE: {counts.MODERATE}
        </div>

        <div>
          HIGH: {counts.HIGH}
        </div>

        <div>
          EXTREME: {counts.EXTREME}
        </div>

      </div>

      {/* =========================================== */}
      {/* TOOLTIP */}
      {/* =========================================== */}

      {hovered && (

        <div
          style={{
            position: 'absolute',
            top: 20,
            right: 20,
            zIndex: 100,
            background: 'rgba(0,0,0,0.75)',
            color: 'white',
            padding: 20,
            borderRadius: 16,
            minWidth: 260,
            fontFamily: 'sans-serif',
            backdropFilter: 'blur(10px)',
          }}
        >

          <h3>Hazard Node</h3>

          <div>
            Hazard: {hovered.hazard}
          </div>

          <div>
            Confidence:
            {' '}
            {hovered.confidence.toFixed(2)}
          </div>

          <div>
            Solar Wind:
            {' '}
            {hovered.solarWind.toFixed(2)}
          </div>

          <div>
            Plasma Density:
            {' '}
            {hovered.plasma.toFixed(2)}
          </div>

          <div>
            Magnetic Field:
            {' '}
            {hovered.magnetic.toFixed(2)}
          </div>

        </div>

      )}

      {/* =========================================== */}
      {/* LOADING */}
      {/* =========================================== */}

      {loading && (

        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            color: 'white',
            background: 'rgba(0,0,0,0.5)',
            fontSize: 24,
            zIndex: 200,
          }}
        >
          Loading Lunar Intelligence...
        </div>

      )}

    </div>
  );
}
