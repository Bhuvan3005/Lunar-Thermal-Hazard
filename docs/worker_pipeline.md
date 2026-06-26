# Worker Pipeline

## Overview

The worker container runs `worker_entrypoint.py` — an APScheduler `BlockingScheduler` that executes three background jobs on configurable intervals.

The GNN model is **never retrained** by the worker. Only inference is performed.

---

## Jobs

| Job | Script | Default interval |
|---|---|---|
| NOAA solar wind fetch | `noaa_solar_wind_fetch.py` | Every 6 h |
| Hazard dataset regeneration | `generate_lunar_hazard_dataset.py` | Every 24 h |
| Live GNN inference | `infer_live_hazards.py` | Every 6 h |

---

## Execution Order

All three jobs run **sequentially at container startup**, then each repeats on its own interval:

```
Container start
    │
    ▼
job_noaa_fetch()
    │
    ▼
job_generate_dataset()
    │
    ▼
job_infer_hazards()
    │
    ▼
BlockingScheduler starts
    ├── every 6 h  → job_noaa_fetch()
    ├── every 24 h → job_generate_dataset()
    └── every 6 h  → job_infer_hazards()
```

---

## Configuration

Override intervals via environment variables in `.env` or `docker-compose.yml`:

```
NOAA_FETCH_INTERVAL_HOURS=6
DATASET_INTERVAL_HOURS=24
INFERENCE_INTERVAL_HOURS=6
```

---

## Graceful Shutdown

SIGTERM and SIGINT are caught. The scheduler calls `scheduler.shutdown(wait=True)` so in-progress jobs complete before the container stops.

---

## Logs

All output goes to stdout (captured by Docker). View with:

```bash
docker compose logs -f worker
```
