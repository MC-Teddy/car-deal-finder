"""
Motory.com scraper - v2 with anti-403 headers.
Motory returns 403 to basic scrapers; full browser header set + Google Referer.
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


class MotoryScraper:
    BASE_URL = "https://motory.com"
    LISTINGS_PATH = "/used-cars/"

    # Full desktop Chrome browser fingerprint to bypass 403
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.6367.82 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ar-SA,ar;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.google.com/search?q=used+cars+saudi+arabia+motory",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "cross-site",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "Connection": "keep-alive",
        "Cache-Control": "max-age=0",
    }

    # Mobile fallback headers if desktop gets 403
    MOBILE_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive",
    }

    def __init__(self, max_pages: int = 5, delay: float = 2.5, timeout: int = 20):
        self.max_pages = max_pages
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def _get(self, url: str):
        """Try desktop headers first; fall back to mobile headers on 403."""
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 403:
                logger.warning("Motory: desktop 403 on %s, trying mobile UA.", url)
                mobile_session = requests.Session()
                mobile_session.headers.update(self.MOBILE_HEADERS)
                resp = mobile_session.get(url, timeout=self.timeout)
                logger.info("Motory: mobile UA -> %d on %s", resp.status_code, url)
            if resp.status_code in (404, 410):
                logger.warning("Motory %d for %s", resp.status_code, url)
                return None, None
            resp.raise_for_status()
            return resp, BeautifulSoup(resp.text, "lxml")
        except requests.exceptions.HTTPError as exc:
            logger.error("Motory HTTP error %s: %s", url, exc)
        except Exception as exc:
            logger.error("Motory error %s: %s", url, exc)
        return None, None

    def _page_url(self, page: int) -> str:
        base = urljoin(self.BASE_URL, self.LISTINGS_PATH)
        return f"{base}?page={page}" if page > 1 else base

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
                        "url", "id", "slug", "title", "name", "brand", "priceValue"}
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

        make  = pick(car, "make", "brand", "brandName", "manufacturer")
        model = pick(car, "model", "modelName")
        year  = pick(car, "year", "model_year", "modelYear")
        price = pick(car, "price", "priceValue", "final_price", "sell_price")
        mileage = pick(car, "mileage", "km", "kilometers", "odometer")
        city  = pick(car, "city", "location", "cityName", "region")
        title = pick(car, "title", "name", "car_name")
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
            "source": "motory", "title": str(title) if title else None,
            "make": str(make) if make else None, "model": str(model) if model else None,
            "year": year, "price_sar": price, "mileage_km": mileage,
            "city": str(city) if city else None,
            "listed_at": datetime.utcnow().isoformat(), "url": url, "seller_type": "unknown",
        }

    def _parse_from_next_data(self, soup) -> list:
        data = self._extract_next_data(soup)
        if not data:
            return []
        cars = self._find_car_arrays(data)
        if not cars:
            pp = data.get("props", {}).get("pageProps", {})
            logger.info("Motory __NEXT_DATA__ found, no car arrays. pageProps keys: %s", list(pp.keys())[:15])
            return []
        listings = [self._json_car_to_listing(c) for c in cars]
        listings = [l for l in listings if l]
        logger.info("Motory: %d listings from __NEXT_DATA__.", len(listings))
        return listings

    # ------------------------------------------------------------------
    # HTML fallback
    # ------------------------------------------------------------------

    def _log_diag(self, soup, url):
        title = soup.title.string.strip() if soup.title else "NO TITLE"
        logger.info("DIAG[Motory] title: '%s' | url: %s", title, url)
        classes = set()
        for tag in soup.find_all(True, limit=300):
            for cls in tag.get("class", []):
                classes.add(cls)
        rel = sorted(c for c in classes if any(
            kw in c.lower() for kw in ["car", "list", "card", "item", "vehicle", "product"]))
        logger.info("DIAG[Motory] relevant classes: %s", rel[:40])
        logger.info("DIAG[Motory] all classes: %s", sorted(classes)[:40])
        logger.info("DIAG[Motory] text (500): %s", soup.get_text(" ", strip=True)[:500])
        if len(soup.get_text(" ", strip=True)) < 300:
            logger.warning("DIAG[Motory] Very short text — possible JS-only or bot block.")

    def _parse_from_html(self, soup, url) -> list:
        selectors = [
            "div.car-card", "[class*='car-card']", "[class*='CarCard']",
            "[class*='listing-card']", "[class*='vehicle-card']",
            "[class*='product-card']", "article",
        ]
        cards = []
        for sel in selectors:
            cards = soup.select(sel)
            if cards:
                logger.info("Motory HTML selector '%s' -> %d cards.", sel, len(cards))
                break
        if not cards:
            self._log_diag(soup, url)
            return []
        listings = []
        for card in cards:
            try:
                link = card.select_one("a[href]")
                if not link:
                    continue
                url_c = urljoin(self.BASE_URL, link.get("href", ""))
                title_el = card.select_one("[class*='title']") or card.select_one("h2") or card.select_one("h3")
                raw_title = title_el.get_text(" ", strip=True) if title_el else ""
                price_el = card.select_one("[class*='price']")
                price_text = price_el.get_text(strip=True) if price_el else ""
                price_clean = re.sub(r"[^\d.]", "", price_text.replace(",", ""))
                price_sar = float(price_clean) if price_clean else None
                m = re.search(r"([\d,]+)\s*(?:km|كم)", card.get_text(" "), re.IGNORECASE)
                mileage_km = int(re.sub(r"[^\d]", "", m.group(1))) if m else None
                yr = re.search(r"\b(19[89]\d|20[012]\d)\b", raw_title)
                year = int(yr.group(1)) if yr else None
                parts = raw_title.split()
                listings.append({
                    "source": "motory", "title": raw_title,
                    "make": parts[0] if parts else None, "model": parts[1] if len(parts) > 1 else None,
                    "year": year, "price_sar": price_sar, "mileage_km": mileage_km, "city": None,
                    "listed_at": datetime.utcnow().isoformat(), "url": url_c, "seller_type": "unknown",
                })
            except Exception as exc:
                logger.debug("Motory HTML card error: %s", exc)
        return listings

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def scrape(self) -> list:
        all_listings = []
        for page in range(1, self.max_pages + 1):
            url = self._page_url(page)
            logger.info("Motory: fetching page %d — %s", page, url)
            resp, soup = self._get(url)
            if soup is None:
                break
            page_listings = self._parse_from_next_data(soup) or self._parse_from_html(soup, url)
            logger.info("Motory page %d: %d listings.", page, len(page_listings))
            all_listings.extend(page_listings)
            if not page_listings:
                break
            next_btn = soup.select_one("a[rel='next']") or soup.select_one(".pagination .next")
            if not next_btn and page < self.max_pages:
                break
            if page < self.max_pages:
                time.sleep(self.delay)
        logger.info("Motory total: %d listings.", len(all_listings))
        return all_listings
