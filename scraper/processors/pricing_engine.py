"""
Pricing Engine — core deal-scoring logic for the Used Car Deal Finder.

This module computes market statistics for each (make, model, year, mileage_band)
group and then scores individual listings against those benchmarks to identify
underpriced ("deal") cars.

Mileage banding:
    mileage_band = floor(mileage_km / 20_000) * 20_000
    e.g. 45,000 km → band 40,000

Deal tiers:
    - excellent : price is >20% below the group median
    - good       : price is 10–20% below median
    - fair       : price is 0–10% below median
    - overpriced : price is above median
"""

import logging
import math
import statistics
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Listing = dict
MarketStats = dict  # keyed by (make, model, year, mileage_band) tuples


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mileage_band(mileage_km: Optional[int]) -> Optional[int]:
    """
    Return the lower bound of the 20,000-km band for a given mileage.

    Returns None if mileage_km is None or negative.
    """
    if mileage_km is None or mileage_km < 0:
        return None
    return (mileage_km // 20_000) * 20_000


def _group_key(listing: Listing) -> Optional[tuple]:
    """
    Construct the grouping key for a listing.

    All four components must be present; returns None for incomplete listings.
    """
    make = listing.get("make")
    model = listing.get("model")
    year = listing.get("year")
    mileage_km = listing.get("mileage_km")

    if not make or not model or not year:
        return None

    band = _mileage_band(mileage_km)
    # Allow band to be None — group by (make, model, year, None) when mileage missing
    return (
        str(make).strip().lower(),
        str(model).strip().lower(),
        int(year),
        band,
    )


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def compute_market_stats(listings: list[Listing]) -> MarketStats:
    """
    Compute market price statistics grouped by (make, model, year, mileage_band).

    For each group the following statistics are calculated:
        - median_price  : median asking price in SAR
        - mean_price    : mean asking price in SAR
        - count         : number of listings in the group
        - std_dev       : population standard deviation of prices

    Args:
        listings: Raw listing dicts (may include listings without prices).

    Returns:
        Dict mapping group-key tuples to stat dicts.
        Example key: ("toyota", "camry", 2020, 40000)
        Example value: {"median_price": 72000, "mean_price": 73500,
                        "count": 12, "std_dev": 4200.0}
    """
    groups: dict[tuple, list[float]] = {}

    for listing in listings:
        price = listing.get("price_sar")
        if price is None or price <= 0:
            continue  # Cannot use listings without a price for market stats

        key = _group_key(listing)
        if key is None:
            continue

        groups.setdefault(key, []).append(float(price))

    stats: MarketStats = {}
    for key, prices in groups.items():
        if len(prices) < 1:
            continue
        try:
            med = statistics.median(prices)
            mean = statistics.mean(prices)
            count = len(prices)
            std = statistics.pstdev(prices) if count > 1 else 0.0
            stats[key] = {
                "median_price": med,
                "mean_price": mean,
                "count": count,
                "std_dev": std,
            }
        except statistics.StatisticsError as exc:
            logger.warning("Stats error for group %s: %s", key, exc)

    logger.info(
        "Market stats computed for %d distinct (make, model, year, mileage_band) groups.",
        len(stats),
    )
    return stats


def score_listing(listing: Listing, market_stats: MarketStats) -> Listing:
    """
    Enrich a single listing with deal-scoring fields.

    Added fields:
        deal_score          (float) : percentage below market median, e.g. 15.3
                                      Negative means overpriced.
        deal_tier           (str)   : "excellent" | "good" | "fair" | "overpriced" | "unscored"
        market_median_price (float | None) : median of the comparison group
        sample_size         (int)   : number of comparable listings used

    Args:
        listing: A single listing dict (will NOT be mutated; a copy is returned).
        market_stats: Output of :func:`compute_market_stats`.

    Returns:
        New dict with scoring fields appended.
    """
    result = dict(listing)  # shallow copy — we append new keys only

    result["deal_score"] = None
    result["deal_tier"] = "unscored"
    result["market_median_price"] = None
    result["sample_size"] = 0

    price = listing.get("price_sar")
    if price is None or price <= 0:
        return result

    key = _group_key(listing)
    if key is None:
        return result

    group_stat = market_stats.get(key)
    if group_stat is None:
        # No comparable listings found — try a relaxed key (ignore mileage band)
        make, model, year, _ = key
        relaxed_key = (make, model, year, None)
        group_stat = market_stats.get(relaxed_key)

    if group_stat is None:
        return result  # No market data available

    median = group_stat["median_price"]
    if median <= 0:
        return result

    deal_score = ((median - float(price)) / median) * 100  # positive = below market

    if deal_score > 20:
        tier = "excellent"
    elif deal_score > 10:
        tier = "good"
    elif deal_score >= 0:
        tier = "fair"
    else:
        tier = "overpriced"

    result["deal_score"] = round(deal_score, 2)
    result["deal_tier"] = tier
    result["market_median_price"] = round(median, 2)
    result["sample_size"] = group_stat["count"]

    return result


def process_listings(listings: list[Listing]) -> list[Listing]:
    """
    Full pipeline: compute market stats, score every listing, sort by deal quality.

    Listings that cannot be scored (missing price / make / model / year) are
    included in the output but sorted to the bottom.

    Args:
        listings: Raw listing dicts from one or more scrapers.

    Returns:
        Enriched listing dicts sorted by deal_score descending
        (best deals first; unscored listings at the end).
    """
    if not listings:
        logger.warning("process_listings called with an empty list.")
        return []

    logger.info("Processing %d listings through the pricing engine.", len(listings))

    stats = compute_market_stats(listings)

    scored: list[Listing] = []
    for listing in listings:
        enriched = score_listing(listing, stats)
        scored.append(enriched)

    # Sort: scored listings first (descending deal_score), then unscored
    def sort_key(lst: Listing) -> tuple:
        ds = lst.get("deal_score")
        if ds is None:
            return (1, 0.0)  # unscored last
        return (0, -ds)  # best deal first

    scored.sort(key=sort_key)

    excellent = sum(1 for l in scored if l.get("deal_tier") == "excellent")
    good = sum(1 for l in scored if l.get("deal_tier") == "good")
    fair = sum(1 for l in scored if l.get("deal_tier") == "fair")
    overpriced = sum(1 for l in scored if l.get("deal_tier") == "overpriced")
    unscored = sum(1 for l in scored if l.get("deal_tier") == "unscored")

    logger.info(
        "Scoring complete — excellent: %d, good: %d, fair: %d, "
        "overpriced: %d, unscored: %d",
        excellent, good, fair, overpriced, unscored,
    )

    return scored
