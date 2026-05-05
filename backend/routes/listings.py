"""
Listings routes for the Used Car Deal Finder API.

Endpoints:
    GET /listings              — paginated, filterable listing browse
    GET /listings/top-deals    — top 50 deals (deal_score > 10%)
    GET /listings/stats        — market summary statistics
    GET /listings/makes        — distinct car makes for filter dropdown
    GET /listings/models       — distinct models for a given make
"""

import logging
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from postgrest import SyncPostgrestClient

from models import (
    CarListing,
    MakeEntry,
    MarketStatsMeta,
    MarketStatsResponse,
    ModelEntry,
    PaginatedListings,
)

logger = logging.getLogger("backend.routes.listings")

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency: Supabase client from app state
# ---------------------------------------------------------------------------

def get_db(request: Request) -> SyncPostgrestClient:
    """Retrieve the Supabase client attached to app.state at startup."""
    return request.app.state.db


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TABLE = "car_listings"
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


# ---------------------------------------------------------------------------
# Helper: apply common listing filters to a Supabase query
# ---------------------------------------------------------------------------

def _apply_filters(query, make, model, year, city, min_deal_score, source):
    """Chain equality/range filters onto a Supabase query object."""
    if make:
        query = query.ilike("make", f"%{make}%")
    if model:
        query = query.ilike("model", f"%{model}%")
    if year:
        query = query.eq("year", year)
    if city:
        query = query.ilike("city", f"%{city}%")
    if min_deal_score is not None:
        query = query.gte("deal_score", min_deal_score)
    if source:
        query = query.eq("source", source)
    return query


# ---------------------------------------------------------------------------
# GET /listings
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=PaginatedListings,
    summary="Browse listings",
    description=(
        "Return a paginated list of car listings. "
        "Supports filtering by make, model, year, city, minimum deal score, "
        "and source site. Supports sorting by price, deal_score, mileage, or listed_at."
    ),
)
async def get_listings(
    db: Client = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number (1-indexed)."),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page."),
    make: Optional[str] = Query(None, description="Filter by make (case-insensitive partial match)."),
    model: Optional[str] = Query(None, description="Filter by model (case-insensitive partial match)."),
    year: Optional[int] = Query(None, ge=1990, le=2030, description="Filter by exact model year."),
    city: Optional[str] = Query(None, description="Filter by city (case-insensitive partial match)."),
    min_deal_score: Optional[float] = Query(None, description="Minimum deal score (e.g. 10 = at least 10% below median)."),
    source: Optional[str] = Query(None, description="Filter by source: haraj | syarah | motory."),
    sort_by: str = Query("deal_score", description="Sort field: deal_score | price_sar | mileage_km | listed_at."),
    sort_order: str = Query("desc", description="Sort direction: asc | desc."),
) -> PaginatedListings:
    """
    Browse paginated car listings with optional filters and sorting.
    """
    valid_sort_fields = {"deal_score", "price_sar", "mileage_km", "listed_at", "year"}
    if sort_by not in valid_sort_fields:
        raise HTTPException(
            status_code=422,
            detail=f"sort_by must be one of: {', '.join(sorted(valid_sort_fields))}",
        )
    if sort_order not in {"asc", "desc"}:
        raise HTTPException(status_code=422, detail="sort_order must be 'asc' or 'desc'.")

    desc = sort_order == "desc"
    offset = (page - 1) * page_size

    try:
        # Count query (no pagination)
        count_query = db.table(TABLE).select("id", count="exact")
        count_query = _apply_filters(count_query, make, model, year, city, min_deal_score, source)
        count_resp = count_query.execute()
        total = count_resp.count or 0

        # Data query
        data_query = (
            db.table(TABLE)
            .select("*")
            .order(sort_by, desc=desc)
            .range(offset, offset + page_size - 1)
        )
        data_query = _apply_filters(data_query, make, model, year, city, min_deal_score, source)
        data_resp = data_query.execute()
        items = data_resp.data or []

    except Exception as exc:
        logger.error("Error fetching listings: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch listings from database.")

    return PaginatedListings(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)),
    )


# ---------------------------------------------------------------------------
# GET /listings/top-deals
# ---------------------------------------------------------------------------

@router.get(
    "/top-deals",
    response_model=list[CarListing],
    summary="Top deals",
    description="Return up to 50 listings with a deal_score greater than 10% (good or excellent tier).",
)
async def get_top_deals(
    db: Client = Depends(get_db),
    limit: int = Query(50, ge=1, le=100, description="Maximum results to return."),
    make: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
) -> list[dict]:
    """Return the best deals, optionally filtered by make, model, or city."""
    try:
        query = (
            db.table(TABLE)
            .select("*")
            .gt("deal_score", 10)
            .order("deal_score", desc=True)
            .limit(limit)
        )
        if make:
            query = query.ilike("make", f"%{make}%")
        if model:
            query = query.ilike("model", f"%{model}%")
        if city:
            query = query.ilike("city", f"%{city}%")

        resp = query.execute()
        return resp.data or []

    except Exception as exc:
        logger.error("Error fetching top deals: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch top deals.")


# ---------------------------------------------------------------------------
# GET /listings/stats
# ---------------------------------------------------------------------------

@router.get(
    "/stats",
    response_model=MarketStatsResponse,
    summary="Market statistics",
    description=(
        "Return a market summary: total listing count, deal tier distribution, "
        "and top 10 makes by listing count with their average deal score."
    ),
)
async def get_stats(db: Client = Depends(get_db)) -> MarketStatsResponse:
    """Aggregate market statistics for dashboard display."""
    try:
        # Total listings
        total_resp = db.table(TABLE).select("id", count="exact").execute()
        total = total_resp.count or 0

        # Deal tier counts
        tier_rows = (
            db.table(TABLE)
            .select("deal_tier")
            .not_.is_("deal_tier", "null")
            .execute()
        ).data or []

        tier_counts: dict[str, int] = {}
        for row in tier_rows:
            t = row.get("deal_tier", "unscored")
            tier_counts[t] = tier_counts.get(t, 0) + 1

        # Top makes: aggregate via rpc or fetch all makes and count in Python
        makes_resp = (
            db.table(TABLE)
            .select("make, deal_score")
            .not_.is_("make", "null")
            .execute()
        ).data or []

        make_agg: dict[str, dict] = {}
        for row in makes_resp:
            m = row.get("make")
            if not m:
                continue
            if m not in make_agg:
                make_agg[m] = {"count": 0, "deal_score_sum": 0.0, "deal_score_n": 0}
            make_agg[m]["count"] += 1
            ds = row.get("deal_score")
            if ds is not None:
                make_agg[m]["deal_score_sum"] += ds
                make_agg[m]["deal_score_n"] += 1

        top_makes = sorted(make_agg.items(), key=lambda x: x[1]["count"], reverse=True)[:10]
        top_makes_list = [
            {
                "make": name,
                "listing_count": agg["count"],
                "avg_deal_score": (
                    round(agg["deal_score_sum"] / agg["deal_score_n"], 2)
                    if agg["deal_score_n"] > 0
                    else None
                ),
            }
            for name, agg in top_makes
        ]

        return MarketStatsResponse(
            meta=MarketStatsMeta(
                total_listings=total,
                last_refreshed="now",
            ),
            top_makes=top_makes_list,
            deal_tier_counts=tier_counts,
        )

    except Exception as exc:
        logger.error("Error fetching stats: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch market statistics.")


# ---------------------------------------------------------------------------
# GET /listings/makes
# ---------------------------------------------------------------------------

@router.get(
    "/makes",
    response_model=list[MakeEntry],
    summary="Distinct makes",
    description="Return a list of distinct car makes available in the database, sorted by listing count.",
)
async def get_makes(db: Client = Depends(get_db)) -> list[dict]:
    """Return distinct makes for populating filter dropdowns."""
    try:
        resp = db.table("distinct_makes").select("*").execute()
        return resp.data or []
    except Exception:
        # Fallback if the view doesn't exist: query the table directly
        try:
            resp = (
                db.table(TABLE)
                .select("make")
                .not_.is_("make", "null")
                .execute()
            )
            rows = resp.data or []
            counts: dict[str, int] = {}
            for row in rows:
                m = row.get("make")
                if m:
                    counts[m] = counts.get(m, 0) + 1
            return [
                {"make": k, "listing_count": v}
                for k, v in sorted(counts.items(), key=lambda x: -x[1])
            ]
        except Exception as exc2:
            logger.error("Error fetching makes: %s", exc2)
            raise HTTPException(status_code=500, detail="Failed to fetch makes.")


# ---------------------------------------------------------------------------
# GET /listings/models
# ---------------------------------------------------------------------------

@router.get(
    "/models",
    response_model=list[ModelEntry],
    summary="Distinct models",
    description="Return distinct models for a given make, sorted by listing count.",
)
async def get_models(
    db: Client = Depends(get_db),
    make: str = Query(..., description="The make to filter models by."),
) -> list[dict]:
    """Return distinct models for a given make."""
    try:
        resp = (
            db.table("distinct_models")
            .select("*")
            .ilike("make", f"%{make}%")
            .execute()
        )
        return resp.data or []
    except Exception:
        try:
            resp = (
                db.table(TABLE)
                .select("make, model")
                .ilike("make", f"%{make}%")
                .not_.is_("model", "null")
                .execute()
            )
            rows = resp.data or []
            counts: dict[tuple, int] = {}
            for row in rows:
                key = (row.get("make"), row.get("model"))
                if key[0] and key[1]:
                    counts[key] = counts.get(key, 0) + 1
            return [
                {"make": mk, "model": mdl, "listing_count": cnt}
                for (mk, mdl), cnt in sorted(counts.items(), key=lambda x: -x[1])
            ]
        except Exception as exc2:
            logger.error("Error fetching models for make=%s: %s", make, exc2)
            raise HTTPException(status_code=500, detail="Failed to fetch models.")
