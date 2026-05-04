"""
Scrapers package for the Used Car Deal Finder.
Aggregates scraper modules for haraj.com, syarah.com, and motory.com.
"""

from .haraj import HarajScraper
from .syarah import SyarahScraper
from .motory import MotoryScraper

__all__ = ["HarajScraper", "SyarahScraper", "MotoryScraper"]
