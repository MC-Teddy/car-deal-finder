"""
Syarah.com scraper - v2 with URL auto-discovery.
/used-cars/ now returns 404; try several candidate paths.
"""
import json
import logging
import re
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# URL candidates in priority order; first 200 response wins
LISTING_URL_CANDIDATES = [
    "https://syarah.com/used-cars/",
    "https://syarah.com/en/used-cars/",
    "https://syarah.com/buy/",
    "https://syarah.com/cars/",
    "https://syarah.com/buy-used-cars/",
    "https://syarah.com/",
]

class SyarahScraper:
    BASE_URL = "https://syarah.com"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }

    def __init__(self, max_pages: int = 5, delay: float = 2.5, timeout: int = 20):
        self.max_pages = min(max_pages, 3)
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self._base_listing_url = None

    # ------------------------------------------------------------------
    # URL discovery
    # ------------------------------------------------------------------

    def _discover_listing_url(self) -> Optional[str]:
        """Try candidate URLs and return the first one that returns HTTP 200."""
        for url in LISTING_URL_CANDIDATES:
            try:
                resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
                logger.info("Syarah URL probe: %s -> %d", url, resp.status_code)
                if resp.status_code == 200:
                    # Check it actually has some content
                    if len(resp.text) > 500:
                        logger.info("Syarah: using listing URL %s", url)
                        return url
            except Exception as exc:
                logger.warning("Syarah URL probe error for %s: %s", url, exc)
        return None

    def _page_url(self, base: str, page: int) -> str:
        if page == 1:
            return base
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}page={page}"

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _get(self, url: str):
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code in (404, 410):
                logger.warning("Syarah %d for %s", resp.status_code, url)
                return None, None
            resp.raise_for_status()
            return resp, BeautifulSoup(resp.text, "lxml")
        except requests.exceptions.HTTPError as exc:
            logger.error("HTTP error %s: %s", url, exc)
        except Exception as exc:
            logger.error("Error %s: %s", url, exc)
        return None, None

    # ------------------------------------------------------------------
    # __NEXT_DATA__ extraction
    # ------------------------------------------------------------------

    def _extract_next_data(self, soup) -> dict:
        script = soup.find("script", id="__NEXT_DATA__")
        if script and script.string:
            try:
                return json.loads(script.string)
            except json.JSONDecodeError:
                pass
        return {}

    def _find_car_arrays(self, obj, depth: int = 0) -> list:
        if depth > 8:
            return []
        if isinstance(obj, list) and len(obj) >= 1 and isinstance(obj[0], dict):
            first = obj[0]
            car_keys = {"price", "year", "make", "model", "mileage", "km",
                        "url", "id", "slug", "title", "name", "brand",
                        "price_sar", "priceValue", "sell_price"}
            if len({str(k).lower() for k in first.keys()} & {k.lower() for k in car_keys}) >= 2:
                return obj
        if isinstance(obj, dict):
            for key in ["cars", "listings", "usedCars", "used_cars", "data",
                        "results", "items", "vehicles", "pageProps", "props"]:
                if key in obj:
                    r = self._find_car_arrays(obj[key], depth + 1)
                    if r:
                        return r
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    r = self._find_car_arrays(v, depth + 1)
                    if r:
                        return r
        return []

    def _json_car_to_listing(self, car: dict) -> Optional[dict]:
        def pick(d, *keys):
            for k in keys:
                v = d.get(k)
                if v is not None and v != "":
                    return v
            return None

        url_raw = pick(car, "url", "link", "slug", "permalink", "path")
        if not url_raw:
            return None
        url = url_raw if url_raw.startswith("http") else urljoin(self.BASE_URL, "/" + url_raw.lstrip("/"))

        make  = pick(car, "make", "brand", "brandName", "make_en", "manufacturer")
        model = pick(car, "model", "modelName", "model_en")
        year  = pick(car, "year", "model_year", "modelYear")
        price = pick(car, "price", "price_sar", "priceValue", "final_price", "sell_price")
        mileage = pick(car, "mileage", "km", "kilometers", "odometer")
        city  = pick(car, "city", "location", "cityName", "region")
        title = pick(car, "title", "name", "car_name", "listing_title")
        if not title and make and model:
            title = f"{make} {model} {year or ''}".strip()

        for field, val in [("price", price), ("year", year), ("mileage", mileage)]:
            try:
                locals()[field] = float(val) if field == "price" else int(float(val)) if val is not None else None
            except (ValueError, TypeError):
                locals()[field] = None

        try:
            price = float(price) if price is not None else None
        except (ValueError, TypeError):
            price = None
        try:
            year = int(year) if year is not None else None
        except (ValueError, TypeError):
            year = None
        try:
            mileage = int(float(mileage)) if mileage is not None else None
        except (ValueError, TypeError):
            mileage = None

        return {
            "source": "syarah", "title": str(title) if title else None,
            "make": str(make) if make else None, "model": str(model) if model else None,
            "year": year, "price_sar": price, "mileage_km": mileage,
            "city": str(city) if city else None,
            "listed_at": datetime.utcnow().isoformat(), "url": url, "seller_type": "dealer",
        }

    def _parse_from_next_data(self, soup) -> list:
        data = self._extract_next_data(soup)
        if not data:
            return []
        cars = self._find_car_arrays(data)
        if not cars:
            pp = data.get("props", {}).get("pageProps", {})
            logger.info("Syarah __NEXT_DATA__ found, no car arrays. pageProps keys: %s", list(pp.keys())[:15])
            return []
        listings = [self._json_car_to_listing(c) for c in cars]
        listings = [l for l in listings if l]
        logger.info("Syarah: %d listings from __NEXT_DATA__.", len(listings))
        return listings

    # ------------------------------------------------------------------
    # HTML fallback
    # ------------------------------------------------------------------

    def _log_diag(self, soup, url):
        title = soup.title.string.strip() if soup.title else "NO TITLE"
        logger.info("DIAG[Syarah] title: '%s' | url: %s", title, url)
        classes = set()
        for tag in soup.find_all(True, limit=300):
            for cls in tag.get("class", []):
                classes.add(cls)
        rel = sorted(c for c in classes if any(
            kw in c.lower() for kw in ["car", "list", "card", "item", "vehicle", "product", "ad"]))
        logger.info("DIAG[Syarah] relevant classes: %s", rel[:40])
        logger.info("DIAG[Syarah] all classes: %s", sorted(classes)[:40])
        logger.info("DIAG[Syarah] text (500): %s", soup.get_text(" ", strip=True)[:500])

    def _parse_from_html(self, soup, url) -> list:
        selectors = [
            "div.car-card", "[class*='car-card']", "[class*='CarCard']",
            "[class*='listing-card']", "[class*='vehicle-card']",
            "[class*='product-card']", "article.car", "li[class*='car']",
        ]
        cards = []
        for sel in selectors:
            cards = soup.select(sel)
            if cards:
                logger.info("Syarah HTML selector '%s' -> %d cards.", sel, len(cards))
                break
        if not cards:
            self._log_diag(soup, url)
            return []
        return [l for l in (self._html_card(c) for c in cards) if l]

    def _html_card(self, card) -> Optional[dict]:
        try:
            link = card.select_one("a[href]")
            if not link:
                return None
            url = urljoin(self.BASE_URL, link.get("href", ""))
            title_el = card.select_one("[class*='title']") or card.select_one("h2") or card.select_one("h3")
            raw_title = title_el.get_text(" ", strip=True) if title_el else ""
            price_el = card.select_one("[class*='price']") or card.select_one("[data-price]")
            price_text = (price_el.get("data-price") or price_el.get_text(strip=True)) if price_el else ""
            price_sar = float(re.sub(r"[^\d.]", "", price_text.replace(",", ""))) if re.sub(r"[^\d.]", "", price_text.replace(",", "")) else None
            m = re.search(r"([\d,]+)\s*(?:km|ÙƒÙ…)", card.get_text(" "), re.IGNORECASE)
            mileage_km = int(re.sub(r"[^\d]", "", m.group(1))) if m else None
            yr = re.search(r"\b(19[89]\d|20[012]\d)\b", raw_title)
            year = int(yr.group(1)) if yr else None
            parts = raw_title.split()
            return {"source": "syarah", "title": raw_title,
                    "make": parts[0] if parts else None, "model": parts[1] if len(parts) > 1 else None,
                    "year": year, "price_sar": price_sar, "mileage_km": mileage_km, "city": None,
                    "listed_at": datetime.utcnow().isoformat(), "url": url, "seller_type": "dealer"}
        except Exception as exc:
            logger.debug("Syarah HTML card parse error: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def scrape(self) -> list:
        all_listings = []

        base_url = self._discover_listing_url()
        if not base_url:
            logger.error("Syarah: no working listing URL found. Tried: %s", LISTING_URL_CANDIDATES)
            return []

        for page in range(1, self.max_pages + 1):
            url = self._page_url(base_url, page)
            logger.info("Syarah: fetching page %d â€” %s", page, url)
            resp, soup = self._get(url)
            if soup is None:
                break

            page_listings = self._parse_from_next_data(soup) or self._parse_from_html(soup, url)
            logger.info("Syarah page %d: %d listings.", page, len(page_listings))
            all_listings.extend(page_listings)

            if not page_listings:
                break
            if page < self.max_pages:
                time.sleep(self.delay)

        logger.info("Syarah total: %d listings.", len(all_listings))
        return all_listings
