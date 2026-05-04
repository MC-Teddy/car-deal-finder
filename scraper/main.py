"""
Scraper entry point — runs all three scrapers, scores listings, saves to Supabase.

Usage:
    python scraper/main.py

Environment variables (set in .env or GitHub Secrets):
    SUPABASE_URL
    SUPABASE_KEY
"""

import logging
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Bootstrap: load env vars and configure logging before importing submodules
# ---------------------------------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("scraper.main")

# ---------------------------------------------------------------------------
# Local imports (after env is loaded)
# ---------------------------------------------------------------------------
from scrapers import HarajScraper, SyarahScraper, MotoryScraper  # noqa: E402
from processors import process_listings  # noqa: E402
from db import SupabaseClient  # noqa: E402


def run_scrapers(max_pages: int = 5) -> list[dict]:
    """
    Execute all three scrapers and merge results.

    Args:
        max_pages: Pages to fetch per scraper (passed to each scraper).

    Returns:
        Combined list of raw listing dicts from all sources.
    """
    all_listings: list[dict] = []

    scrapers = [
        ("Haraj",   HarajScraper(max_pages=max_pages)),
        ("Syarah",  SyarahScraper(max_pages=max_pages)),
        ("Motory",  MotoryScraper(max_pages=max_pages)),
    ]

    for name, scraper in scrapers:
        logger.info("Starting %s scraper…", name)
        try:
            listings = scraper.scrape()
            logger.info("%s returned %d listings.", name, len(listings))
            all_listings.extend(listings)
        except Exception as exc:  # noqa: BLE001
            logger.error("%s scraper raised an unexpected exception: %s", name, exc)

    return all_listings


def deduplicate(listings: list[dict]) -> list[dict]:
    """
    Remove duplicate listings by URL, keeping the first occurrence.

    Args:
        listings: Combined raw listings from all scrapers.

    Returns:
        Deduplicated list.
    """
    seen: set[str] = set()
    unique: list[dict] = []
    for listing in listings:
        url = listing.get("url")
        if url and url not in seen:
            seen.add(url)
            unique.append(listing)
        elif not url:
            unique.append(listing)  # Keep URL-less listings; they'll be filtered later
    dropped = len(listings) - len(unique)
    if dropped:
        logger.info("Deduplicated %d duplicate listings.", dropped)
    return unique


def main() -> None:
    """
    Orchestrate the full scrape → score → save pipeline.

    Exit codes:
        0 — success
        1 — fatal error (DB connection failed, no listings at all)
    """
    start = datetime.utcnow()
    logger.info("=== Used Car Deal Finder — scrape run started at %s UTC ===", start.isoformat())

    # -- 1. Connect to Supabase ------------------------------------------
    try:
        db = SupabaseClient()
    except RuntimeError as exc:
        logger.critical("Cannot connect to Supabase: %s", exc)
        sys.exit(1)

    # -- 2. Run scrapers --------------------------------------------------
    max_pages = int(os.environ.get("SCRAPER_MAX_PAGES", "5"))
    raw_listings = run_scrapers(max_pages=max_pages)

    if not raw_listings:
        logger.warning("All scrapers returned zero listings. Nothing to save.")
        sys.exit(0)

    logger.info("Total raw listings collected: %d", len(raw_listings))

    # -- 3. Deduplicate ---------------------------------------------------
    listings = deduplicate(raw_listings)
    logger.info("Listings after deduplication: %d", len(listings))

    # -- 4. Score listings -----------------------------------------------
    scored_listings = process_listings(listings)
    logger.info("Listings scored: %d", len(scored_listings))

    # -- 5. Save to Supabase ---------------------------------------------
    upserted = db.upsert_listings(scored_listings)

    # -- 6. Summary log --------------------------------------------------
    excellent = sum(1 for l in scored_listings if l.get("deal_tier") == "excellent")
    good      = sum(1 for l in scored_listings if l.get("deal_tier") == "good")
    deals_found = excellent + good

    elapsed = (datetime.utcnow() - start).total_seconds()
    logger.info(
        "=== Run complete in %.1f s — "
        "scraped: %d, upserted: %d, deals found (excellent+good): %d ===",
        elapsed,
        len(scored_listings),
        upserted,
        deals_found,
    )


if __name__ == "__main__":
    main()
