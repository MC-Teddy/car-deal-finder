"""
Pydantic models for the Used Car Deal Finder API.

These models serve as both response schemas and OpenAPI documentation.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class CarListing(BaseModel):
    """A single used car listing with deal-scoring metadata."""

    id: int = Field(..., description="Auto-generated primary key.")
    source: str = Field(..., description="Source site: haraj | syarah | motory.")
    title: Optional[str] = Field(None, description="Raw listing title (may be in Arabic).")
    make: Optional[str] = Field(None, description="Car manufacturer / brand.")
    model: Optional[str] = Field(None, description="Car model name.")
    year: Optional[int] = Field(None, ge=1990, le=2030, description="Model year.")
    price_sar: Optional[float] = Field(None, description="Asking price in Saudi Riyals.")
    mileage_km: Optional[int] = Field(None, ge=0, description="Odometer reading in km.")
    city: Optional[str] = Field(None, description="Listing city / region.")
    listed_at: datetime = Field(..., description="When the listing was posted.")
    url: str = Field(..., description="Direct link to the original listing.")
    seller_type: str = Field(
        "unknown", description="Seller type: private | dealer | unknown."
    )
    # Deal-scoring fields
    deal_score: Optional[float] = Field(
        None,
        description=(
            "Percentage below market median price for comparable vehicles. "
            "Positive = underpriced, negative = overpriced."
        ),
    )
    deal_tier: Optional[str] = Field(
        None,
        description="excellent | good | fair | overpriced | unscored",
    )
    market_median_price: Optional[float] = Field(
        None, description="Median price of comparable listings used for scoring."
    )
    sample_size: Optional[int] = Field(
        None, description="Number of comparable listings used for scoring."
    )
    created_at: datetime = Field(..., description="Row creation timestamp.")
    updated_at: datetime = Field(..., description="Row last-updated timestamp.")

    class Config:
        from_attributes = True


class PaginatedListings(BaseModel):
    """Paginated response wrapper for listing queries."""

    items: list[CarListing]
    total: int = Field(..., description="Total number of matching listings.")
    page: int = Field(..., ge=1, description="Current page number (1-indexed).")
    page_size: int = Field(..., description="Number of items per page.")
    pages: int = Field(..., description="Total number of pages.")


class MarketStatGroup(BaseModel):
    """Price statistics for a (make, model, year, mileage_band) group."""

    make: str
    model: str
    year: int
    mileage_band: Optional[int] = Field(
        None, description="Lower bound of 20,000-km mileage band."
    )
    listing_count: int
    median_price: float
    mean_price: float
    std_dev_price: Optional[float]
    min_price: float
    max_price: float


class MarketStatsMeta(BaseModel):
    """Summary metadata for the market stats endpoint."""

    total_listings: int
    last_refreshed: str


class MarketStatsResponse(BaseModel):
    """Response model for the /listings/stats endpoint."""

    meta: MarketStatsMeta
    top_makes: list[dict] = Field(
        ...,
        description="Top 10 makes by listing count with average deal score.",
    )
    deal_tier_counts: dict[str, int] = Field(
        ..., description="Count of listings per deal tier."
    )


class MakeEntry(BaseModel):
    """A make with its listing count."""

    make: str
    listing_count: int


class ModelEntry(BaseModel):
    """A model (for a given make) with its listing count."""

    make: str
    model: str
    listing_count: int


