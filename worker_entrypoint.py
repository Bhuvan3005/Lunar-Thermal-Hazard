"""
worker_entrypoint.py
====================
APScheduler-based worker for the Lunar Thermal Hazard system.

Scheduled jobs (all run sequentially to avoid DB race conditions):
  1. noaa_solar_wind_fetch    — fetch latest NOAA solar wind data
  2. generate_lunar_hazard_dataset — regenerate hazard dataset from terrain data
  3. infer_live_hazards       — run GNN inference and write predictions to DB

Schedule (configurable via environment variables):
  NOAA_FETCH_INTERVAL_HOURS   (default: 6)
  DATASET_INTERVAL_HOURS      (default: 24)
  INFERENCE_INTERVAL_HOURS    (default: 6)

The GNN model is NEVER retrained here — only inference is performed.
All output is sent to stdout for Docker log capture.
"""

import logging
import os
import signal
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv

# ── Environment ──────────────────────────────────────────────────────────────
load_dotenv()

# ── Logging — stdout, no buffering (PYTHONUNBUFFERED=1 handles flushing) ──────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WORKER] %(levelname)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ── Schedule intervals (env-configurable) ─────────────────────────────────────
NOAA_HOURS      = int(os.getenv("NOAA_FETCH_INTERVAL_HOURS", "6"))
DATASET_HOURS   = int(os.getenv("DATASET_INTERVAL_HOURS",    "24"))
INFERENCE_HOURS = int(os.getenv("INFERENCE_INTERVAL_HOURS",  "6"))


# ── Job functions ─────────────────────────────────────────────────────────────

def job_noaa_fetch():
    """Fetch latest NOAA solar wind plasma and magnetic field data."""
    logger.info("▶ [NOAA] Starting solar wind data fetch…")
    try:
        import noaa_solar_wind_fetch as noaa
        noaa.main()
        logger.info("✔ [NOAA] Solar wind data fetch completed successfully.")
    except Exception as exc:
        logger.error("✘ [NOAA] Solar wind fetch failed: %s", exc, exc_info=True)


def job_generate_dataset():
    """Regenerate the lunar hazard dataset from terrain/NOAA data."""
    logger.info("▶ [DATASET] Starting lunar hazard dataset generation…")
    try:
        import generate_lunar_hazard_dataset as gen
        gen.main()
        logger.info("✔ [DATASET] Lunar hazard dataset generation completed.")
    except Exception as exc:
        logger.error("✘ [DATASET] Dataset generation failed: %s", exc, exc_info=True)


def job_infer_hazards():
    """Run GNN inference and persist updated hazard predictions to DB."""
    logger.info("▶ [INFER] Starting live hazard inference…")
    try:
        import infer_live_hazards as infer
        infer.main()
        logger.info("✔ [INFER] Live hazard inference completed.")
    except Exception as exc:
        logger.error("✘ [INFER] Live hazard inference failed: %s", exc, exc_info=True)


# ── Graceful shutdown ─────────────────────────────────────────────────────────

scheduler: BlockingScheduler | None = None


def _shutdown(signum, frame):
    logger.info("Received signal %s — shutting down scheduler gracefully…", signum)
    if scheduler:
        scheduler.shutdown(wait=True)
    sys.exit(0)


signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT,  _shutdown)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("Lunar Thermal Hazard — Worker starting")
    logger.info("  NOAA fetch interval     : every %d h", NOAA_HOURS)
    logger.info("  Dataset regen interval  : every %d h", DATASET_HOURS)
    logger.info("  Inference interval      : every %d h", INFERENCE_HOURS)
    logger.info("=" * 60)

    global scheduler
    scheduler = BlockingScheduler(timezone="UTC")

    # ── Job 1: NOAA fetch ────────────────────────────────────────────────────
    scheduler.add_job(
        job_noaa_fetch,
        trigger=IntervalTrigger(hours=NOAA_HOURS),
        id="noaa_fetch",
        name="NOAA Solar Wind Fetch",
        next_run_time=None,   # first run immediately below
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    # ── Job 2: Dataset generation ────────────────────────────────────────────
    scheduler.add_job(
        job_generate_dataset,
        trigger=IntervalTrigger(hours=DATASET_HOURS),
        id="generate_dataset",
        name="Lunar Hazard Dataset Generation",
        next_run_time=None,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    # ── Job 3: Live inference ─────────────────────────────────────────────────
    scheduler.add_job(
        job_infer_hazards,
        trigger=IntervalTrigger(hours=INFERENCE_HOURS),
        id="infer_hazards",
        name="Live Hazard Inference",
        next_run_time=None,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    # ── Run all jobs once immediately at startup ──────────────────────────────
    logger.info("Running initial job pass at startup…")
    job_noaa_fetch()
    job_generate_dataset()
    job_infer_hazards()
    logger.info("Initial job pass complete. Scheduler starting…")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
