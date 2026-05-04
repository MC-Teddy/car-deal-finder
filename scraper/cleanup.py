"""
Cleanup script — deletes car listings older than 30 days from Supabase.

Run via GitHub Actions daily at midnight UTC, or manually:
    python scraper/cleanup.py

Environment variables (set in .env or GitHub Secrets):
    SUPABASE_URL
    SUPABASE_KEY
"""

import logging
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("scraper.cleanup")

from db import SupabaseClient  # noqa: E402


def main() -> None:
    """
    Delete listings older than 30 days and log the result.

    Exit codes:
        0 — success (including the case of 0 rows deleted)
        1 — fatal error (e.g. DB connection failure)
    """
    start = datetime.utcnow()
    logger.info(
        "=== Cleanup job started at %s UTC ===", start.isoformat()
    )

    try:
        db = SupabaseClient()
    except RuntimeError as exc:
        logger.critical("Cannot connect to Supabase: %s", exc)
        sys.exit(1)

    retention_days = 30
    deleted = db.delete_old_listings(days=retention_days)

    elapsed = (datetime.utcnow() - start).total_seconds()
    logger.info(
        "=== Cleanup complete in %.1f s — deleted %d listings older than %d days ===",
        elapsed,
        deleted,
        retention_days,
    )


if __name__ == "__main__":
    main()
