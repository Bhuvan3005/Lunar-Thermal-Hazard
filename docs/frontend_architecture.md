# Frontend Architecture

## Overview

The frontend is a single-page React application (Vite) that renders an interactive 3-D Moon globe using Three.js and communicates with:

- **Supabase** — direct PostgREST queries for hazard node data (paginated, 1000 rows/page)
- **Backend FastAPI** — A\* route planning via `POST /route`

---

## Component Hierarchy

```
main.jsx
└── App.jsx
    └── MoonViewer.jsx  (default export)
        ├── <Canvas>  (React Three Fiber)
        │   ├── <MoonScene>
        │   │   ├── <Sphere>         Moon globe with LOLA texture
        │   │   ├── <RouteLine>      TubeGeometry along surface
        │   │   └── <HazardPoint>×N  Clickable coloured spheres
        │   ├── <Stars>              Starfield background
        │   └── <OrbitControls>      Mouse orbit/zoom
        │
        ├── <HazardCountsPanel>    SAFE/MODERATE/HIGH/EXTREME counts
        ├── <HoverTooltip>         On-hover node detail
        ├── <MissionPanel>         Start/goal selection + mode picker
        └── <RouteAnalyticsPanel>  Distance, risk, node count
```

---

## State Management

All state lives in the `App` function component (no external store).

| State | Type | Purpose |
|---|---|---|
| `nodes` | Node[] | Sampled hazard nodes for rendering |
| `hovered` | Node \| null | Currently hovered node |
| `loading` | boolean | Shows loading overlay |
| `planningActive` | boolean | Enables click-to-select mode |
| `startNode` / `goalNode` | Node \| null | Route endpoints |
| `routeMode` | string | `shortest` / `safest` / `balanced` |
| `routeResult` | RouteResponse \| null | Full A\* API response |
| `pathDetails` | Node[] | Per-node path detail for route tube |
| `routeStatus` | string | User-facing status message |

---

## Data Flow

```
Supabase PostgREST
    │  paginated SELECT (1000 rows/page)
    │  repeat every 60 s
    ▼
nodes[]  (random sample ≤ 3000 for GPU performance)
    │
    ▼
<HazardPoint> meshes on Moon surface
    │
User clicks two nodes (planning mode)
    │
    ▼
POST /route → FastAPI → A*
    │
    ▼
routeResult → <RouteLine> (CatmullRomCurve3 TubeGeometry)
           → <RouteAnalyticsPanel>
```

---

## 3D Coordinate Conversion

Latitude/longitude to Three.js XYZ on a unit sphere of radius `r`:

```js
function latLonToXYZ(lat, lon, r) {
  const φ = lat * π / 180;   // latitude in radians
  const λ = lon * π / 180;   // longitude in radians
  return new THREE.Vector3(
    r * cos(φ) * cos(λ),     // X
    r * sin(φ),              // Y
    r * cos(φ) * sin(λ),     // Z
  );
}
```

Hazard nodes sit at `r = 2.06`, route tube at `r = 2.055` (both slightly above the Moon surface at `r = 2.0`) to prevent z-fighting.

---

## Performance

- Maximum 3000 nodes rendered simultaneously (random sample of DB nodes)
- Node data refreshed every 60 seconds from Supabase
- `useMemo` gates all expensive geometry recomputation (edge_index, TubeGeometry)
- `useCallback` prevents unnecessary re-renders of event handlers
