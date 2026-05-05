"""
Supabase client wrapper for the Used Car Deal Finder scraper.

Uses direct HTTP requests to the Supabase PostgREST API to avoid
supabase-py / gotrue / httpx version conflicts.

Environment variables required:
    SUPABASE_URL  - your Supabase project URL
    SUPABASE_KEY  - your Supabase service-role API key
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

LISTING_COLUMNS = [
    "source", "title", "make", "model", "year",
    "price_sar", "mileage_km", "city", "listed_at", "url",
    "seller_type", "deal_score", "deal_tier",
    "market_median_price", "sample_size",
]


class SupabaseClient:
    """
    Thin REST wrapper exposing domain-specific operations for the
    Used Car Deal Finder scraper.
    """

    TABLE = "car_listings"

    def __init__(self):
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_KEY must be set in environment variables."
            )
        self._rest = url.rstrip("/") + "/rest/v1"
        self._headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        self._session = requests.Session()
        self._session.headers.update(self._headers)
        logger.info("Supabase REST client initialised. Project: %s", url)

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def upsert_listings(self, listings: list[dict]) -> int:
        """Upsert a batch of listing dicts using the url column as conflict key."""
        if not listings:
            logger.warning("upsert_listings called with empty list - nothing to do.")
            return 0

        clean = []
        for listing in listings:
            row = {k: listing.get(k) for k in LISTING_COLUMNS if listing.get(k) is not None}
            row["url"] = listing.get("url")
            if not row.get("url"):
                logger.debug("Skipping listing without URL: %s", listing.get("title"))
                continue
            clean.append(row)

        if not clean:
            return 0

        batch_size = 500
        upserted = 0
        for i in range(0, len(clean), batch_size):
            batch = clean[i : i + batch_size]
            try:
                resp = self._session.post(
                    f"{self._rest}/{self.TABLE}",
                    json=batch,
                    headers={
                        "Prefer": "resolution=merge-duplicates,return=minimal",
                        "on_conflict": "url",
                    },
                )
                resp.raise_for_status()
                upserted += len(batch)
                logger.debug("Upserted batch %d-%d.", i, i + len(batch))
            except Exception as exc:
                logger.error("Failed to upsert batch %d: %s", i, exc)

        logger.info("Upserted %d listings into %s.", upserted, self.TABLE)
        return upserted

    def delete_old_listings(self, days: int = 30) -> int:
        """Delete listings older than `days` days."""
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
        logger.info("Deleting listings older than %d days (cutoff: %s).", days, cutoff)
        try:
            resp = self._session.delete(
                f"{self._rest}/{self.TABLE}",
                params={"listed_at": f"lt.{cutoff}"},
                headers={"Prefer": "return=minimal"},
            )
            resp.raise_for_status()
            logger.info("Deleted stale listings older than %s.", cutoff)
            return 0  # minimal return doesn't give count
        except Exception as exc:
            logger.error("Failed to delete old listings: %s", exc)
            return 0

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_market_stats(self) -> dict:
        """Fetch market stats from the materialized view."""
        try:
            resp = self._session.get(f"{self._rest}/market_stats")
            resp.raise_for_status()
            groups = resp.json() or []

            count_resp = self._session.get(
                f"{self._rest}/{self.TABLE}",
                params={"select": "count"},
                headers={"Prefer": "count=exact"},
            )
            # Content-Range: 0-0/42
            cr = count_resp.headers.get("Content-Range", "0/0")
            total = int(cr.split("/")[-1]) if "/" in cr else 0

            return {
                "groups": groups,
                "meta": {
                    "total_listings": total,
                    "last_refreshed": datetime.utcnow().isoformat(),
                },
            }
        except Exception as exc:
            logger.error("Failed to fetch market stats: %s", exc)
            return {"groups": [], "meta": {"total_listings": 0}}

    def get_top_deals(self, limit: int = 50, filters: Optional[dict] = None) -> list[dict]:
        """Fetch top deals sorted by deal_score descending."""
        try:
            params = {
                "select": "*",
                "deal_score": "gt.0",
                "order": "deal_score.desc",
                "limit": limit,
            }
            if filters:
                for col, val in filters.items():
                    if val is not None:
                        params[col] = f"eq.{val}"

            resp = self._session.get(f"{self._rest}/{self.TABLE}", params=params)
            resp.raise_for_status()
            return resp.json() or []
        except Exception as exc:
            logger.error("Failed to fetch top deals: %s", exc)
            return []