"""
Database package for the Used Car Deal Finder.
Provides a Supabase client wrapper for all DB operations.
"""

from .supabase_client import SupabaseClient

__all__ = ["SupabaseClient"]
