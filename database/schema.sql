-- =============================================================================
-- Used Car Deal Finder — Supabase PostgreSQL Schema
-- Run this in the Supabase SQL Editor to set up your project.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Enable required extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- trigram similarity for text search
CREATE EXTENSION IF NOT EXISTS btree_gin; -- GIN indexes on composite types

-- ---------------------------------------------------------------------------
-- car_listings table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS car_listings (
    id                   BIGSERIAL PRIMARY KEY,
    source               TEXT        NOT NULL CHECK (source IN ('haraj', 'syarah', 'motory')),
    title                TEXT,
    make                 TEXT,
    model                TEXT,
    year                 SMALLINT    CHECK (year BETWEEN 1990 AND 2030),
    price_sar            NUMERIC(12, 2),
    mileage_km           INTEGER     CHECK (mileage_km >= 0),
    city                 TEXT,
    listed_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    url                  TEXT        NOT NULL UNIQUE,
    seller_type          TEXT        DEFAULT 'unknown' CHECK (seller_type IN ('private', 'dealer', 'unknown')),
    -- Pricing engine fields
    deal_score           NUMERIC(6, 2),       -- % below market median; positive = underpriced
    deal_tier            TEXT        CHECK (deal_tier IN ('excellent', 'good', 'fair', 'overpriced', 'unscored')),
    market_median_price  NUMERIC(12, 2),
    sample_size          INTEGER     DEFAULT 0,
    -- Audit timestamps
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE car_listings IS
    'Used car listings aggregated from haraj.com, syarah.com, and motory.com with deal-scoring fields.';

COMMENT ON COLUMN car_listings.deal_score IS
    'Percentage below market median price for comparable vehicles. Positive = underpriced.';

COMMENT ON COLUMN car_listings.deal_tier IS
    'excellent: >20% below median | good: 10-20% | fair: 0-10% | overpriced: above median';

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_listings_make       ON car_listings (make);
CREATE INDEX IF NOT EXISTS idx_listings_model      ON car_listings (model);
CREATE INDEX IF NOT EXISTS idx_listings_year       ON car_listings (year);
CREATE INDEX IF NOT EXISTS idx_listings_price      ON car_listings (price_sar);
CREATE INDEX IF NOT EXISTS idx_listings_deal_score ON car_listings (deal_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_listings_deal_tier  ON car_listings (deal_tier);
CREATE INDEX IF NOT EXISTS idx_listings_city       ON car_listings (city);
CREATE INDEX IF NOT EXISTS idx_listings_source     ON car_listings (source);
CREATE INDEX IF NOT EXISTS idx_listings_listed_at  ON car_listings (listed_at DESC);
CREATE INDEX IF NOT EXISTS idx_listings_make_model ON car_listings (make, model);
CREATE INDEX IF NOT EXISTS idx_listings_make_model_year ON car_listings (make, model, year);

-- Full-text search index on title
CREATE INDEX IF NOT EXISTS idx_listings_title_trgm
    ON car_listings USING GIN (title gin_trgm_ops);

-- ---------------------------------------------------------------------------
-- Auto-update updated_at on row modification
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_listings_updated_at ON car_listings;
CREATE TRIGGER trg_listings_updated_at
    BEFORE UPDATE ON car_listings
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- market_stats materialized view
-- Groups listings by (make, model, year, mileage_band) and computes
-- aggregate price statistics. Refreshed by a function called on each upsert.
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS market_stats AS
SELECT
    make,
    model,
    year,
    (FLOOR(mileage_km / 20000.0) * 20000)::INTEGER AS mileage_band,
    COUNT(*)                                         AS listing_count,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_sar) AS median_price,
    AVG(price_sar)                                   AS mean_price,
    STDDEV_POP(price_sar)                            AS std_dev_price,
    MIN(price_sar)                                   AS min_price,
    MAX(price_sar)                                   AS max_price,
    MAX(updated_at)                                  AS last_seen
FROM car_listings
WHERE
    price_sar  IS NOT NULL
    AND price_sar  > 0
    AND make       IS NOT NULL
    AND model      IS NOT NULL
    AND year       IS NOT NULL
GROUP BY make, model, year, mileage_band
WITH DATA;

COMMENT ON MATERIALIZED VIEW market_stats IS
    'Pre-computed price statistics per (make, model, year, mileage_band) group.';

CREATE UNIQUE INDEX IF NOT EXISTS idx_market_stats_key
    ON market_stats (make, model, year, mileage_band);

CREATE INDEX IF NOT EXISTS idx_market_stats_make_model
    ON market_stats (make, model);

-- ---------------------------------------------------------------------------
-- Function to refresh the materialized view (called post-upsert)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION refresh_market_stats()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY market_stats;
END;
$$;

COMMENT ON FUNCTION refresh_market_stats IS
    'Refresh the market_stats materialized view concurrently. Safe to call frequently.';

-- ---------------------------------------------------------------------------
-- Row-Level Security (RLS)
-- ---------------------------------------------------------------------------
ALTER TABLE car_listings ENABLE ROW LEVEL SECURITY;

-- Public read access — anyone can read listings (for the frontend)
CREATE POLICY listings_public_read
    ON car_listings
    FOR SELECT
    USING (true);

-- Service role write access — only authenticated service (scraper) can write
-- In practice this is enforced by using the service-role key in the scraper
-- and the anon key in the frontend.
CREATE POLICY listings_service_write
    ON car_listings
    FOR ALL
    USING (auth.role() = 'service_role');

-- Allow the scraper to insert/update via supabase-py with service key:
-- The service_role key bypasses RLS by default, so the above policies
-- primarily govern anon/authenticated clients (i.e. the public frontend).

-- ---------------------------------------------------------------------------
-- Helpful views for the API
-- ---------------------------------------------------------------------------

-- Top deals view: listings at least 10% below market median
CREATE OR REPLACE VIEW top_deals AS
SELECT *
FROM car_listings
WHERE deal_score > 10
ORDER BY deal_score DESC;

-- Distinct makes (for filter dropdowns)
CREATE OR REPLACE VIEW distinct_makes AS
SELECT DISTINCT make, COUNT(*) AS listing_count
FROM car_listings
WHERE make IS NOT NULL
GROUP BY make
ORDER BY listing_count DESC;

-- Distinct models per make (for filter dropdowns)
CREATE OR REPLACE VIEW distinct_models AS
SELECT DISTINCT make, model, COUNT(*) AS listing_count
FROM car_listings
WHERE make IS NOT NULL AND model IS NOT NULL
GROUP BY make, model
ORDER BY make, listing_count DESC;

-- ---------------------------------------------------------------------------
-- Optional: scheduled refresh via pg_cron (if enabled on your Supabase plan)
-- Uncomment the lines below if pg_cron is available.
-- ---------------------------------------------------------------------------
-- SELECT cron.schedule(
--     'refresh-market-stats',
--     '*/30 * * * *',   -- every 30 minutes
--     'SELECT refresh_market_stats()'
-- );
