-- Run this in Supabase SQL Editor to create / migrate the lunar_regions table.
-- Safe to run on an existing table: uses ADD COLUMN IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS lunar_regions (
    id              BIGSERIAL PRIMARY KEY,
    zoom            INTEGER        NOT NULL,
    tile_x          INTEGER        NOT NULL,
    tile_y          INTEGER        NOT NULL,
    patch_row       INTEGER        NOT NULL,
    patch_col       INTEGER        NOT NULL,
    latitude        DOUBLE PRECISION NOT NULL,
    longitude       DOUBLE PRECISION NOT NULL,
    elevation       DOUBLE PRECISION,
    slope           DOUBLE PRECISION,
    roughness       DOUBLE PRECISION,
    crater_density  DOUBLE PRECISION,
    shadow_score    DOUBLE PRECISION,
    created_at      TIMESTAMPTZ    DEFAULT NOW(),
    UNIQUE (zoom, tile_x, tile_y, patch_row, patch_col)
);

-- If the table already exists, add any missing columns:
ALTER TABLE lunar_regions ADD COLUMN IF NOT EXISTS elevation       DOUBLE PRECISION;
ALTER TABLE lunar_regions ADD COLUMN IF NOT EXISTS slope           DOUBLE PRECISION;
ALTER TABLE lunar_regions ADD COLUMN IF NOT EXISTS roughness       DOUBLE PRECISION;
ALTER TABLE lunar_regions ADD COLUMN IF NOT EXISTS crater_density  DOUBLE PRECISION;
ALTER TABLE lunar_regions ADD COLUMN IF NOT EXISTS shadow_score    DOUBLE PRECISION;
ALTER TABLE lunar_regions ADD COLUMN IF NOT EXISTS latitude        DOUBLE PRECISION;
ALTER TABLE lunar_regions ADD COLUMN IF NOT EXISTS longitude       DOUBLE PRECISION;
ALTER TABLE lunar_regions ADD COLUMN IF NOT EXISTS zoom            INTEGER;
ALTER TABLE lunar_regions ADD COLUMN IF NOT EXISTS tile_x          INTEGER;
ALTER TABLE lunar_regions ADD COLUMN IF NOT EXISTS tile_y          INTEGER;
ALTER TABLE lunar_regions ADD COLUMN IF NOT EXISTS patch_row       INTEGER;
ALTER TABLE lunar_regions ADD COLUMN IF NOT EXISTS patch_col       INTEGER;

-- Refresh PostgREST schema cache so new columns are visible immediately:
NOTIFY pgrst, 'reload schema';
