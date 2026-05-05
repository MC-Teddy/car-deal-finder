"""
Motory.com scraper for used car listings.

Strategy (in order):
1. Extract embedded __NEXT_DATA__ JSON from the page (Next.js SSR data).
2. Fall back to HTML CSS-selector parsing.
3. Log diagnostic HTML structure so broken selectors can be fixed quickly.
"""

import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class MotoryScraper:
    BASE_URL = "https://motory.com"
    LISTINGS_PATH = "/used-cars/"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ar,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://motory.com/",
        "Connection": "keep-alive",
    }

    def __init__(self, max_pages: int = 5, delay: float = 2.5, timeout: int = 20):
        self.max_pages = max_pages
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _get(self, url: str):
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 404:
                logger.warning("404 for %s — stopping.", url)
                return None, None
            resp.raise_for_status()
            return resp, BeautifulSoup(resp.text, "lxml")
        except requests.exceptions.HTTPError as exc:
            logger.error("HTTP error fetching %s: %s", url, exc)
        except Exception as exc:
            logger.error("Error fetching %s: %s", url, exc)
        return None, None

    def _page_url(self, page: int) -> str:
        base = urljoin(self.BASE_URL, self.LISTINGS_PATH)
        return f"{base}?page={page}" if page > 1 else base

    # ------------------------------------------------------------------
    # __NEXT_DATA__ extraction (primary method)
    # ------------------------------------------------------------------

    def _extract_next_data(self, soup) -> dict:
        script = soup.find("script", id="__NEXT_DATA__")
        if script and script.string:
            try:
                return json.loads(script.string)
            except json.JSONDecodeError as e:
                logger.debug("Could not parse __NEXT_DATA__: %s", e)
        return {}

    def _find_car_arrays(self, obj, depth: int = 0) -> list:
        if depth > 8:
            return []
        if isinstance(obj, list) and len(obj) >= 1 and isinstance(obj[0], dict):
            first = obj[0]
            car_keys = {
                "price", "year", "make", "model", "mileage", "km",
                "url", "id", "slug", "title", "name", "brand",
                "price_sar", "priceValue", "sell_price",
            }
            overlap = {str(k).lower() for k in first.keys()} & {k.lower() for k in car_keys}
            if len(overlap) >= 2:
                return obj
        if isinstance(obj, dict):
            priority = [
                "cars", "listings", "usedCars", "used_cars", "carsList",
                "data", "results", "items", "vehicles", "adverts", "ads",
                "pageProps", "props",
            ]
            for key in priority:
                if key in obj:
                    result = self._find_car_arrays(obj[key], depth + 1)
                    if result:
                        return result
            for value in obj.values():
                if isinstance(value, (dict, list)):
                    result = self._find_car_arrays(value, depth + 1)
                    if result:
                        return result
        return []

    def _json_car_to_listing(self, car: dict) -> Optional[dict]:
        def pick(d, *keys):
            for k in keys:
                v = d.get(k)
                if v is not None and v != "":
                    return v
            return None

        url_raw = pick(car, "url", "link", "slug", "permalink", "detail_url", "path")
        if not url_raw:
            return None
        url = url_raw if url_raw.startswith("http") else urljoin(self.BASE_URL, "/" + url_raw.lstrip("/"))

        make  = pick(car, "make", "brand", "brandName", "make_en", "brand_en", "manufacturer")
        model = pick(car, "model", "modelName", "model_en", "car_model")
        year  = pick(car, "year", "model_year", "modelYear", "manufacture_year")
        price = pick(car, "price", "price_sar", "priceValue", "final_price", "sell_price")
        mileage = pick(car, "mileage", "km", "kilometers", "odometer", "mileage_km")
        city  = pick(car, "city", "location", "cityName", "region", "area", "city_en")
        title = pick(car, "title", "name", "car_name", "listing_title")
        if not title and make and model:
            title = f"{make} {model} {year or ''}".strip()

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
            "source": "motory",
            "title": str(title) if title else None,
            "make": str(make) if make else None,
            "model": str(model) if model else None,
            "year": year,
            "price_sar": price,
            "mileage_km": mileage,
            "city": str(city) if city else None,
            "listed_at": datetime.utcnow().isoformat(),
            "url": url,
            "seller_type": "unknown",
        }

    def _parse_from_next_data(self, soup) -> list:
        data = self._extract_next_data(soup)
        if not data:
            logger.info("Motory: no __NEXT_DATA__ found.")
            return []
        cars = self._find_car_arrays(data)
        if not cars:
            pp = data.get("props", {}).get("pageProps", {})
            logger.info("Motory __NEXT_DATA__ found but no car arrays. pageProps keys: %s",
                        list(pp.keys())[:15])
            return []
        listings = []
        for car in cars:
            listing = self._json_car_to_listing(car)
            if listing:
                listings.append(listing)
        logger.info("Motory: extracted %d listings from __NEXT_DATA__.", len(listings))
        return listings

    # ------------------------------------------------------------------
    # HTML fallback
    # ------------------------------------------------------------------

    def _log_html_diagnostics(self, soup, url: str):
        title = soup.title.string.strip() if soup.title else "NO TITLE"
        logger.info("DIAG[Motory] title: '%s' | url: %s", title, url)
        classes = set()
        for tag in soup.find_all(True, limit=300):
            for cls in tag.get("class", []):
                classes.add(cls)
        relevant = sorted(c for c in classes if any(
            kw in c.lower() for kw in
            ["car", "list", "card", "item", "vehicle", "product", "ad", "post", "result"]
        ))
        logger.info("DIAG[Motory] relevant classes: %s", relevant[:40])
        logger.info("DIAG[Motory] all classes sample: %s", sorted(classes)[:40])
        text = soup.get_text(" ", strip=True)
        logger.info("DIAG[Motory] page text (500 chars): %s", text[:500])
        if len(text) < 300:
            logger.warning("DIAG[Motory] Very short page text — possible bot challenge or JS-only render.")

    def _to_float(self, text: str) -> Optional[float]:
        if not text:
            return None
        cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None

    def _parse_year(self, text: str) -> Optional[int]:
        m = re.search(r"\b(19[89]\d|20[012]\d)\b", text)
        return int(m.group(1)) if m else None

    def _parse_card_html(self, card) -> Optional[dict]:
        try:
            link_el = card.select_one("a[href]")
            if not link_el:
                return None
            href = link_el.get("href", "")
            url = urljoin(self.BASE_URL, href)

            title_el = (
                card.select_one("[class*='car-title']")
                or card.select_one("[class*='title']")
                or card.select_one("[class*='name']")
                or card.select_one("h2") or card.select_one("h3")
                or link_el
            )
            raw_title = title_el.get_text(" ", strip=True) if title_el else ""

            price_el = (
                card.select_one("[class*='price']")
                or card.select_one("[class*='Price']")
                or card.select_one("[data-price]")
            )
            price_text = ""
            if price_el:
                price_text = price_el.get("data-price") or price_el.get_text(strip=True)
            price_sar = self._to_float(price_text)

            card_text = card.get_text(" ")
            mileage_km = None
            km_match = re.search(r"([\d,]+)\s*(?:km|كم)", card_text, re.IGNORECASE)
            if km_match:
                raw = self._to_float(km_match.group(1))
                mileage_km = int(raw) if raw is not None else None

            city_el = (
                card.select_one("[class*='city']")
                or card.select_one("[class*='location']")
                or card.select_one("[data-city]")
            )
            city = city_el.get_text(strip=True) if city_el else None

            year = self._parse_year(raw_title)
            parts = raw_title.split()
            make = parts[0] if parts else None
            model = parts[1] if len(parts) > 1 else None

            return {
                "source": "motory",
                "title": raw_title,
                "make": make,
                "model": model,
                "year": year,
                "price_sar": price_sar,
                "mileage_km": mileage_km,
                "city": city,
                "listed_at": datetime.utcnow().isoformat(),
                "url": url,
                "seller_type": "unknown",
            }
        except Exception as exc:
            logger.debug("Failed to parse Motory HTML card: %s", exc)
            return None

    def _parse_from_html(self, soup, url: str) -> list:
        selectors = [
            "div.car-card", "[class*='car-card']", "[class*='CarCard']",
            "[class*='listing-card']", "[class*='ListingCard']",
            "[class*='vehicle-card']", "[class*='VehicleCard']",
            "[class*='product-card']", "[class*='ProductCard']",
            "[class*='car-item']", "[class*='CarItem']",
            "[class*='ad-card']", "article",
            "li[class*='car']",
        ]
        cards = []
        for sel in selectors:
            cards = soup.select(sel)
            if cards:
                logger.info("Motory HTML: matched selector '%s' -> %d cards.", sel, len(cards))
                break

        if not cards:
            self._log_html_diagnostics(soup, url)
            return []

        listings = []
        for card in cards:
            listing = self._parse_card_html(card)
            if listing:
                listings.append(listing)
        return listings

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def scrape(self) -> list:
        all_listings = []

        for page in range(1, self.max_pages + 1):
            url = self._page_url(page)
            logger.info("Motory: fetching page %d — %s", page, url)

            resp, soup = self._get(url)
            if soup is None:
                logger.warning("Motory: stopping at page %d — fetch failed.", page)
                break

            page_listings = self._parse_from_next_data(soup)
            if not page_listings:
                page_listings = self._parse_from_html(soup, url)

            logger.info("Motory page %d: %d valid listings.", page, len(page_listings))
            all_listings.extend(page_listings)

            if not page_listings:
                logger.info("Motory: no listings on page %d, stopping.", page)
                break

            next_btn = soup.select_one("a[rel='next']") or soup.select_one(".pagination .next")
            if not next_btn and page < self.max_pages:
                logger.info("Motory: no next-page link after page %d, stopping.", page)
                break

            if page < self.max_pages:
                time.sleep(self.delay)

        logger.info("Motory scrape complete. Total: %d listings.", len(all_listings))
        return all_listings
