"""
Supabase client wrapper for the Used Car Deal Finder scraper.

Provides high-level methods for upserting listings, deleting stale rows,
querying market stats, and fetching top deals.

Environment variables required:
    SUPABASE_URL  — your Supabase project URL
    SUPABASE_KEY  — your Supabase service-role (or anon) API key
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column names that must exist in the car_listings table
# ---------------------------------------------------------------------------
LISTING_COLUMNS = [
    "source",
    "title",
    "make",
    "model",
    "year",
    "price_sar",
    "mileage_km",
    "city",
    "listed_at",
    "url",
    "seller_type",
    "deal_score",
    "deal_tier",
    "market_median_price",
    "sample_size",
]


class SupabaseClient:
    """
    Thin wrapper around the supabase-py client exposing domain-specific
    operations for the Used Car Deal Finder.
    """

    TABLE = "car_listings"

    def __init__(self):
        """
        Initialise the Supabase client using environment variables.

        Raises:
            RuntimeError: If SUPABASE_URL or SUPABASE_KEY are not set.
        """
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_KEY must be set in environment variables."
            )
        self._client: Client = create_client(url, key)
        logger.info("Supabase client initialised. Project: %s", url)

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def upsert_listings(self, listings: list[dict]) -> int:
        """
        Upsert a batch of listing dicts into the car_listings table.

        Uses the 'url' column as the unique conflict target so that
        re-scraping the same URL updates the existing row rather than
        inserting a duplicate.

        Args:
            listings: List of normalised (and scored) listing dicts.

        Returns:
            Number of rows successfully upserted.
        """
        if not listings:
            logger.warning("upsert_listings called with empty list — nothing to do.")
            return 0

        # Strip any extra keys not in the DB schema
        clean = []
        for listing in listings:
            row = {k: listing.get(k) for k in LISTING_COLUMNS if k in listing or listing.get(k) is not None}
            # Ensure url is always present (it's the upsert key)
            row["url"] = listing.get("url")
            if not row["url"]:
                logger.debug("Skipping listing without URL: %s", listing.get("title"))
                continue
            clean.append(row)

        if not clean:
            return 0

        try:
            # Supabase upsert in batches of 500 to avoid payload limits
            batch_size = 500
            upserted = 0
            for i in range(0, len(clean), batch_size):
                batch = clean[i : i + batch_size]
                resp = (
                    self._client.table(self.TABLE)
                    .upsert(batch, on_conflict="url")
                    .execute()
                )
                upserted += len(resp.data) if resp.data else len(batch)
                logger.debug("Upserted batch %d–%d.", i, i + len(batch))

            logger.info("Upserted %d listings into %s.", upserted, self.TABLE)
            return upserted

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to upsert listings: %s", exc)
            return 0

    def delete_old_listings(self, days: int = 30) -> int:
        """
        Delete listings whose listed_at timestamp is older than `days` days.

        Args:
            days: Retention window in days. Rows older than this are removed.

        Returns:
            Number of rows deleted (estimated from response).
        """
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
        logger.info(
            "Deleting listings older than %d days (cutoff: %s).", days, cutoff
        )

        try:
            resp = (
                self._client.table(self.TABLE)
                .delete()
                .lt("listed_at", cutoff)
                .execute()
            )
            count = len(resp.data) if resp.data else 0
            logger.info("Deleted %d stale listings.", count)
            return count

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to delete old listings: %s", exc)
            return 0

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_market_stats(self) -> dict:
        """
        Fetch aggregated market statistics from the materialized view.

        Queries the market_stats view (defined in schema.sql) which
        pre-computes group-level price aggregates.

        Returns:
            Dict with keys 'groups' (list of group stat rows) and
            'meta' (total_listings, last_refreshed).
        """
        try:
            # Fetch from the materialized view
            resp = self._client.table("market_stats").select("*").execute()
            groups = resp.data or []

            # Also grab a quick count of total active listings
            count_resp = (
                self._client.table(self.TABLE)
                .select("id", count="exact")
                .execute()
            )
            total = count_resp.count or 0

            return {
                "groups": groups,
                "meta": {
                    "total_listings": total,
                    "last_refreshed": datetime.utcnow().isoformat(),
                },
            }

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch market stats: %s", exc)
            return {"groups": [], "meta": {"total_listings": 0}}

    def get_top_deals(
        self,
        limit: int = 50,
        filters: Optional[dict] = None,
    ) -> list[dict]:
        """
        Fetch top deals sorted by deal_score descending.

        Args:
            limit: Maximum number of rows to return.
            filters: Optional dict of column → value equality filters, e.g.
                     {"make": "Toyota", "city": "Riyadh"}.

        Returns:
            List of listing dicts ordered by deal_score descending.
        """
        try:
            query = (
                self._client.table(self.TABLE)
                .select("*")
                .gt("deal_score", 0)  # Only listings below market median
                .order("deal_score", desc=True)
                .limit(limit)
            )

            if filters:
                for column, value in filters.items():
                    if value is not None:
                        query = query.eq(column, value)

            resp = query.execute()
            return resp.data or []

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch top deals: %s", exc)
            return []
