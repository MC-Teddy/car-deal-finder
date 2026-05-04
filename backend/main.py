"""
FastAPI application for the Used Car Deal Finder backend.

Provides a REST API consumed by the frontend to browse car listings,
filter by various attributes, and surface the best deals.

Environment variables required:
    SUPABASE_URL  — Supabase project URL
    SUPABASE_KEY  — Supabase anon or service-role key
"""

import logging
import os
import sys

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client

from routes import listings_router

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("backend.main")

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Used Car Deal Finder API",
    description=(
        "REST API for browsing and filtering used car listings scraped from "
        "haraj.com, syarah.com, and motory.com in Saudi Arabia. "
        "Listings are scored for deal quality against market benchmarks."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# CORS — allow all origins in development; restrict in production via env
# ---------------------------------------------------------------------------
allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Supabase client — attached to app state for use in route dependencies
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event() -> None:
    """
    Connect to Supabase on application startup and attach the client
    to app.state so routes can access it via request.app.state.db.
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        logger.critical(
            "SUPABASE_URL and SUPABASE_KEY must be set. Shutting down."
        )
        sys.exit(1)

    app.state.db: Client = create_client(url, key)
    logger.info("Supabase client connected. Project: %s", url)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Clean up on application shutdown."""
    logger.info("Backend shutting down.")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Meta"])
async def health() -> dict:
    """Return a simple health check response."""
    return {"status": "ok", "service": "used-car-deal-finder-api"}


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(listings_router, prefix="/listings", tags=["Listings"])
