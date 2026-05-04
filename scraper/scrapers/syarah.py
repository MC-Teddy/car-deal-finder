"""
Syarah.com scraper for used car listings.

Syarah (syarah.com) is a structured Saudi used-car marketplace with
dedicated fields for make, model, year, mileage, and price — making
parsing more reliable than free-text classifieds.

The site renders pages server-side; requests + BeautifulSoup is sufficient.
"""

import logging
import re
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlencode

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class SyarahScraper:
    """
    Scraper for syarah.com used car listings.

    Syarah exposes a structured listing page at /used-cars/ with
    filter parameters. Each card contains labelled fields for make,
    model, year, mileage, city, and price.
    """

    BASE_URL = "https://syarah.com"
    LISTINGS_PATH = "/used-cars/"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ar,en;q=0.9",
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://syarah.com/",
        "Connection": "keep-alive",
    }

    def __init__(self, max_pages: int = 5, delay: float = 2.5, timeout: int = 15):
        """
        Initialise the Syarah scraper.

        Args:
            max_pages: Maximum number of listing pages to fetch.
            delay: Seconds to sleep between requests.
            timeout: HTTP request timeout in seconds.
        """
        self.max_pages = max_pages
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch URL and return BeautifulSoup, or None on error."""
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except requests.exceptions.HTTPError as exc:
            logger.error("HTTP error fetching %s: %s", url, exc)
        except requests.exceptions.ConnectionError as exc:
            logger.error("Connection error fetching %s: %s", url, exc)
        except requests.exceptions.Timeout:
            logger.error("Timeout fetching %s", url)
        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected error fetching %s: %s", url, exc)
        return None

    def _clean_number(self, text: str) -> Optional[float]:
        """Strip non-numeric characters and return a float."""
        if not text:
            return None
        cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None

    def _parse_year(self, text: str) -> Optional[int]:
        """Extract a 4-digit year from text."""
        match = re.search(r"\b(19[89]\d|20[012]\d)\b", text)
        return int(match.group(1)) if match else None

    def _page_url(self, page: int) -> str:
        """Build the URL for a given page number."""
        params = {"page": page} if page > 1 else {}
        base = urljoin(self.BASE_URL, self.LISTINGS_PATH)
        return f"{base}?{urlencode(params)}" if params else base

    def _parse_card(self, card) -> Optional[dict]:
        """
        Extract a normalised listing dict from a Syarah listing card element.

        Syarah card structure (as of 2024):
          - .car-name / h2 / [data-name] — make + model + year
          - .car-price / [data-price]    — price in SAR
          - .car-km / [data-km]          — mileage in km
          - .car-city / [data-city]      — city name
          - <a href>                     — listing detail URL
        """
        try:
            # --- URL ---
            link_el = card.select_one("a[href]")
            if not link_el:
                return None
            href = link_el.get("href", "")
            url = urljoin(self.BASE_URL, href) if href else None
            if not url:
                return None

            # --- Title / make / model / year ---
            title_el = (
                card.select_one("[class*='car-name']")
                or card.select_one("[class*='title']")
                or card.select_one("h2")
                or card.select_one("h3")
            )
            raw_title = title_el.get_text(" ", strip=True) if title_el else ""

            # Syarah often stores make/model/year in separate data attributes
            make = (
                card.get("data-make")
                or card.select_one("[data-make]") and card.select_one("[data-make]").get("data-make")
            )
            model = (
                card.get("data-model")
                or card.select_one("[data-model]") and card.select_one("[data-model]").get("data-model")
            )
            year_attr = card.get("data-year")
            year: Optional[int] = int(year_attr) if year_attr and year_attr.isdigit() else None

            # Fall back to parsing the title text
            if not make or not model or not year:
                year = year or self._parse_year(raw_title)
                # Attempt split: first two words are make/model on Syarah
                parts = raw_title.split()
                if not make and len(parts) >= 1:
                    make = parts[0]
                if not model and len(parts) >= 2:
                    model = parts[1]

            # --- Price ---
            price_el = (
                card.select_one("[class*='price']")
                or card.select_one("[class*='Price']")
                or card.select_one("[data-price]")
            )
            if price_el:
                price_text = price_el.get("data-price") or price_el.get_text(strip=True)
            else:
                price_text = ""
            price_sar = self._clean_number(price_text)

            # --- Mileage ---
            km_el = (
                card.select_one("[class*='km']")
                or card.select_one("[class*='mileage']")
                or card.select_one("[data-km]")
            )
            if km_el:
                km_text = km_el.get("data-km") or km_el.get_text(strip=True)
            else:
                # Search card text for km pattern
                km_text = ""
                m = re.search(r"([\d,]+)\s*(?:km|كم)", card.get_text(" "), re.IGNORECASE)
                km_text = m.group(1) if m else ""
            mileage_km_raw = self._clean_number(km_text)
            mileage_km = int(mileage_km_raw) if mileage_km_raw is not None else None

            # --- City ---
            city_el = (
                card.select_one("[class*='city']")
                or card.select_one("[class*='location']")
                or card.select_one("[data-city]")
            )
            city = (
                city_el.get("data-city") or city_el.get_text(strip=True)
                if city_el
                else None
            )

            # --- Date (Syarah often shows "X days ago") ---
            date_el = card.select_one("time") or card.select_one("[class*='date']")
            listed_at = datetime.utcnow().isoformat()
            if date_el:
                dt_attr = date_el.get("datetime")
                if dt_attr:
                    listed_at = dt_attr
                else:
                    txt = date_el.get_text(strip=True)
                    days_match = re.search(r"(\d+)\s*(?:day|يوم|أيام)", txt, re.IGNORECASE)
                    if days_match:
                        from datetime import timedelta
                        listed_at = (
                            datetime.utcnow() - timedelta(days=int(days_match.group(1)))
                        ).isoformat()

            return {
                "source": "syarah",
                "title": raw_title,
                "make": make or None,
                "model": model or None,
                "year": year,
                "price_sar": price_sar,
                "mileage_km": mileage_km,
                "city": city,
                "listed_at": listed_at,
                "url": url,
                "seller_type": "dealer",  # Syarah is primarily a dealer/certified platform
            }

        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to parse Syarah card: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def scrape(self) -> list[dict]:
        """
        Scrape used car listings from syarah.com.

        Returns:
            List of normalised listing dicts.
        """
        all_listings: list[dict] = []

        for page in range(1, self.max_pages + 1):
            url = self._page_url(page)
            logger.info("Scraping Syarah page %d: %s", page, url)

            soup = self._get(url)
            if soup is None:
                logger.warning("Skipping Syarah page %d — fetch failed.", page)
                continue

            # Syarah listing cards
            cards = (
                soup.select("div.car-card")
                or soup.select("[class*='car-card']")
                or soup.select("[class*='listing-card']")
                or soup.select("[class*='vehicle-card']")
                or soup.select("article.car")
                or soup.select("li[class*='car']")
            )

            if not cards:
                logger.warning(
                    "No Syarah cards found on page %d — layout may have changed.", page
                )
                break

            page_listings: list[dict] = []
            for card in cards:
                listing = self._parse_card(card)
                if listing:
                    page_listings.append(listing)

            logger.info("Syarah page %d: %d valid listings.", page, len(page_listings))
            all_listings.extend(page_listings)

            # Pagination check
            next_btn = soup.select_one("a[rel='next']") or soup.select_one(".pagination .next")
            if not next_btn and page < self.max_pages:
                logger.info("No next page found after Syarah page %d. Stopping.", page)
                break

            if page < self.max_pages:
                time.sleep(self.delay)

        logger.info("Syarah scrape complete. Total: %d listings.", len(all_listings))
        return all_listings
