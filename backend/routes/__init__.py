"""
Routes package for the Used Car Deal Finder API.
"""

from .listings import router as listings_router

__all__ = ["listings_router"]
