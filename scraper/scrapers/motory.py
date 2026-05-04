"""
Motory.com scraper for used car listings.

Motory (motory.com) is a Saudi automotive marketplace covering both new
and used cars. The used-cars section is available at /used-cars/ and
provides structured listing cards with make, model, year, mileage, city,
and price.
"""

import logging
import re
import time
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin, urlencode

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class MotoryScraper:
    """
    Scraper for motory.com used car listings.

    Fetches paginated HTML listing pages and extracts normalised
    car listing data from structured card elements.
    """

    BASE_URL = "https://motory.com"
    LISTINGS_PATH = "/used-cars/"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ar,en;q=0.9",
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://motory.com/",
        "Connection": "keep-alive",
    }

    def __init__(self, max_pages: int = 5, delay: float = 2.5, timeout: int = 15):
        """
        Initialise the Motory scraper.

        Args:
            max_pages: Maximum pages to scrape.
            delay: Sleep duration between requests (seconds).
            timeout: HTTP timeout in seconds.
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
        """GET a URL and return parsed HTML, or None on error."""
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

    def _to_float(self, text: str) -> Optional[float]:
        """Strip formatting and return numeric value."""
        if not text:
            return None
        cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None

    def _parse_year(self, text: str) -> Optional[int]:
        """Find a 4-digit model year in text."""
        m = re.search(r"\b(19[89]\d|20[012]\d)\b", text)
        return int(m.group(1)) if m else None

    def _parse_relative_date(self, text: str) -> str:
        """
        Convert relative date strings like '3 days ago' or 'منذ يومين'
        into an ISO-8601 string. Falls back to now.
        """
        now = datetime.utcnow()
        if not text:
            return now.isoformat()

        patterns = [
            (r"(\d+)\s*(?:minute|دقيقة|دقائق)", "minutes"),
            (r"(\d+)\s*(?:hour|ساعة|ساعات)", "hours"),
            (r"(\d+)\s*(?:day|يوم|أيام)", "days"),
            (r"(\d+)\s*(?:week|أسبوع|أسابيع)", "weeks"),
        ]
        for pattern, unit in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                n = int(m.group(1))
                delta = {unit: n}
                return (now - timedelta(**delta)).isoformat()

        if re.search(r"yesterday|أمس", text, re.IGNORECASE):
            return (now - timedelta(days=1)).isoformat()

        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(text[:10], fmt).isoformat()
            except ValueError:
                continue

        return now.isoformat()

    def _page_url(self, page: int) -> str:
        """Construct a paginated listing URL."""
        base = urljoin(self.BASE_URL, self.LISTINGS_PATH)
        if page > 1:
            return f"{base}?{urlencode({'page': page})}"
        return base

    def _parse_card(self, card) -> Optional[dict]:
        """
        Parse a Motory listing card into a normalised dict.

        Motory card structure (as of 2024):
          - car title link:  <a class="car-title"> or <h2>
          - price:           element with class containing 'price'
          - specs row:       year, mileage, city as labelled spans
          - listing time:    <time> or a relative text node
        """
        try:
            # --- URL ---
            link_el = card.select_one("a[href]")
            if not link_el:
                return None
            href = link_el.get("href", "")
            url = urljoin(self.BASE_URL, href)

            # --- Title ---
            title_el = (
                card.select_one("[class*='car-title']")
                or card.select_one("[class*='title']")
                or card.select_one("h2")
                or card.select_one("h3")
                or link_el
            )
            raw_title = title_el.get_text(" ", strip=True) if title_el else ""

            # --- Make / Model from data attributes or text ---
            make = card.get("data-make") or card.get("data-brand")
            model = card.get("data-model")
            year_attr = card.get("data-year")
            year: Optional[int] = (
                int(year_attr) if year_attr and year_attr.isdigit() else None
            )

            if not make or not model:
                # Try labelled spec items
                for spec in card.select("[class*='spec'], [class*='detail']"):
                    label = spec.get("data-label", "").lower()
                    val = spec.get_text(strip=True)
                    if "make" in label or "brand" in label:
                        make = make or val
                    elif "model" in label:
                        model = model or val
                    elif "year" in label:
                        year = year or (int(val) if val.isdigit() else self._parse_year(val))

            # Final fallback: parse raw title
            year = year or self._parse_year(raw_title)
            parts = raw_title.split()
            if not make and parts:
                make = parts[0]
            if not model and len(parts) > 1:
                model = parts[1]

            # --- Price ---
            price_el = (
                card.select_one("[class*='price']")
                or card.select_one("[data-price]")
            )
            price_text = ""
            if price_el:
                price_text = price_el.get("data-price") or price_el.get_text(strip=True)
            price_sar = self._to_float(price_text)

            # --- Mileage ---
            km_el = (
                card.select_one("[class*='mileage']")
                or card.select_one("[class*='km']")
                or card.select_one("[data-mileage]")
            )
            mileage_km: Optional[int] = None
            if km_el:
                km_text = km_el.get("data-mileage") or km_el.get_text(strip=True)
                raw_km = self._to_float(km_text)
                mileage_km = int(raw_km) if raw_km is not None else None
            else:
                card_text = card.get_text(" ")
                m_km = re.search(r"([\d,]+)\s*(?:km|كم)", card_text, re.IGNORECASE)
                if m_km:
                    raw_km = self._to_float(m_km.group(1))
                    mileage_km = int(raw_km) if raw_km is not None else None

            # --- City ---
            city_el = (
                card.select_one("[class*='city']")
                or card.select_one("[class*='location']")
                or card.select_one("[data-city]")
            )
            city: Optional[str] = None
            if city_el:
                city = city_el.get("data-city") or city_el.get_text(strip=True) or None

            # --- Listed date ---
            date_el = card.select_one("time") or card.select_one("[class*='date']")
            listed_at = datetime.utcnow().isoformat()
            if date_el:
                dt_attr = date_el.get("datetime")
                if dt_attr:
                    listed_at = dt_attr
                else:
                    listed_at = self._parse_relative_date(date_el.get_text(strip=True))

            # --- Seller type ---
            card_text_full = card.get_text(" ", strip=True)
            seller_type = "unknown"
            if re.search(r"\bdealer\b|معرض|تاجر", card_text_full, re.IGNORECASE):
                seller_type = "dealer"
            elif re.search(r"\bprivate\b|شخصي|مالك", card_text_full, re.IGNORECASE):
                seller_type = "private"

            return {
                "source": "motory",
                "title": raw_title,
                "make": make or None,
                "model": model or None,
                "year": year,
                "price_sar": price_sar,
                "mileage_km": mileage_km,
                "city": city,
                "listed_at": listed_at,
                "url": url,
                "seller_type": seller_type,
            }

        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to parse Motory card: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def scrape(self) -> list[dict]:
        """
        Scrape used car listings from motory.com.

        Returns:
            List of normalised listing dicts.
        """
        all_listings: list[dict] = []

        for page in range(1, self.max_pages + 1):
            url = self._page_url(page)
            logger.info("Scraping Motory page %d: %s", page, url)

            soup = self._get(url)
            if soup is None:
                logger.warning("Skipping Motory page %d — fetch failed.", page)
                continue

            cards = (
                soup.select("div.car-card")
                or soup.select("[class*='car-card']")
                or soup.select("[class*='listing']")
                or soup.select("[class*='vehicle']")
                or soup.select("article")
                or soup.select("li[class*='car']")
            )

            if not cards:
                logger.warning(
                    "No listing cards found on Motory page %d — layout may have changed.",
                    page,
                )
                break

            page_listings: list[dict] = []
            for card in cards:
                listing = self._parse_card(card)
                if listing:
                    page_listings.append(listing)

            logger.info("Motory page %d: %d valid listings.", page, len(page_listings))
            all_listings.extend(page_listings)

            next_btn = soup.select_one("a[rel='next']") or soup.select_one(".pagination .next")
            if not next_btn and page < self.max_pages:
                logger.info("No next page found after Motory page %d. Stopping.", page)
                break

            if page < self.max_pages:
                time.sleep(self.delay)

        logger.info("Motory scrape complete. Total: %d listings.", len(all_listings))
        return all_listings
