"""
Haraj.com scraper for used car listings.

Haraj is a Saudi classifieds platform. As of 2025 it renders via
React/JS — simple requests returns a near-empty HTML shell.

Strategy (in order):
1. Extract __NEXT_DATA__ JSON (if Next.js SSR is active).
2. Extract any embedded JSON from <script> tags containing listing data.
3. Fall back to HTML CSS-selector parsing.
4. Log detailed diagnostics so selectors can be fixed from the CI logs.
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

# ---------------------------------------------------------------------------
# Arabic -> English make/model maps (kept for HTML fallback)
# ---------------------------------------------------------------------------
ARABIC_MAKES = {
    "تويوتا": "Toyota", "هوندا": "Honda", "نيسان": "Nissan",
    "هيونداي": "Hyundai", "كيا": "Kia", "فورد": "Ford",
    "شيفروليه": "Chevrolet", "شفروليه": "Chevrolet", "جيب": "Jeep",
    "دودج": "Dodge", "بي ام دبليو": "BMW", "مرسيدس": "Mercedes-Benz",
    "لكزس": "Lexus", "انفينيتي": "Infiniti", "أودي": "Audi",
    "فولكس واجن": "Volkswagen", "بورش": "Porsche",
    "رنج روفر": "Range Rover", "لاند روفر": "Land Rover",
    "ميتسوبيشي": "Mitsubishi", "سوزوكي": "Suzuki", "مازدا": "Mazda",
    "كاديلاك": "Cadillac", "لينكون": "Lincoln", "جنسيس": "Genesis",
    "هامر": "Hummer", "غي ام سي": "GMC", "جي ام سي": "GMC",
    "GMC": "GMC", "شانجان": "Changan", "هافال": "Haval",
    "JAC": "JAC", "BYD": "BYD", "MG": "MG", "ام جي": "MG",
}

ARABIC_MODELS = {
    "كامري": "Camry", "كورولا": "Corolla", "راف فور": "RAV4",
    "هايلكس": "Hilux", "لاند كروزر": "Land Cruiser", "برادو": "Prado",
    "فورتشنر": "Fortuner", "افالون": "Avalon", "يارس": "Yaris",
    "اكورد": "Accord", "سيفيك": "Civic", "باترول": "Patrol",
    "اكس تريل": "X-Trail", "سنترا": "Sentra", "النترا": "Elantra",
    "توسان": "Tucson", "سانتافي": "Santa Fe", "سوناتا": "Sonata",
    "سبورتاج": "Sportage", "تاهو": "Tahoe", "سوبربان": "Suburban",
    "جراند شيروكي": "Grand Cherokee", "رانجلر": "Wrangler",
    "اكسبلورر": "Explorer", "موستانج": "Mustang",
}


def parse_title(title: str):
    """Extract (make, model, year) from raw listing title."""
    if not title:
        return None, None, None
    year_match = re.search(r"\b(19[89]\d|20[012]\d)\b", title)
    year = int(year_match.group(1)) if year_match else None
    make = None
    model = None
    for ar, en in ARABIC_MAKES.items():
        if ar in title:
            make = en
            break
    for ar, en in ARABIC_MODELS.items():
        if ar in title:
            model = en
            break
    if not make:
        m = re.search(
            r"\b(Toyota|Honda|Nissan|Hyundai|Kia|Ford|Chevrolet|Jeep|Dodge|BMW|"
            r"Mercedes[-\s]?Benz|Mercedes|Lexus|Infiniti|Audi|Volkswagen|Porsche|"
            r"Land\s*Rover|Range\s*Rover|Mitsubishi|Suzuki|Mazda|Cadillac|Lincoln|"
            r"Genesis|Hummer|GMC|Changan|Haval|JAC|BYD|MG|Subaru|Acura|Buick|RAM)\b",
            title, re.IGNORECASE,
        )
        if m:
            make = m.group(1).title()
    return make, model, year


class HarajScraper:
    BASE_URL = "https://haraj.com"
    CARS_URL = "https://haraj.com/en/cars/"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ar,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "max-age=0",
    }

    def __init__(self, max_pages: int = 5, delay: float = 2.0, timeout: int = 20):
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
            resp.raise_for_status()
            return resp, BeautifulSoup(resp.text, "lxml")
        except requests.exceptions.HTTPError as exc:
            logger.error("HTTP error fetching %s: %s", url, exc)
        except Exception as exc:
            logger.error("Error fetching %s: %s", url, exc)
        return None, None

    def _get_page_url(self, page: int) -> str:
        if page == 1:
            return self.CARS_URL
        return f"{self.CARS_URL}?page={page}"

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
            car_keys = {
                "price", "year", "make", "model", "mileage", "km",
                "url", "id", "slug", "title", "name", "brand",
                "subject", "body", "post_type",
            }
            overlap = {str(k).lower() for k in first.keys()} & {k.lower() for k in car_keys}
            if len(overlap) >= 2:
                return obj
        if isinstance(obj, dict):
            priority = [
                "posts", "items", "listings", "cars", "data", "results",
                "adverts", "ads", "vehicles", "pageProps", "props",
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

    def _find_embedded_json(self, soup) -> list:
        """Try to extract listing data from any <script> tags containing JSON arrays."""
        for script in soup.find_all("script"):
            txt = script.string or ""
            if not txt or len(txt) < 100:
                continue
            # Look for a JSON array of objects
            match = re.search(r'\[(\{.*?"(?:url|id|price|title)".*?\})+\]', txt, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(0))
                    if isinstance(data, list) and data and isinstance(data[0], dict):
                        return data
                except json.JSONDecodeError:
                    pass
        return []

    def _json_post_to_listing(self, post: dict) -> Optional[dict]:
        def pick(d, *keys):
            for k in keys:
                v = d.get(k)
                if v is not None and v != "":
                    return v
            return None

        url_raw = pick(post, "url", "link", "slug", "permalink", "path", "id")
        if not url_raw:
            return None
        if str(url_raw).isdigit():
            url = f"{self.BASE_URL}/en/cars/{url_raw}"
        elif str(url_raw).startswith("http"):
            url = str(url_raw)
        else:
            url = urljoin(self.BASE_URL, "/" + str(url_raw).lstrip("/"))

        title = pick(post, "title", "subject", "name", "ad_title", "description")
        price = pick(post, "price", "priceValue", "sell_price", "listed_price")
        make = pick(post, "make", "brand", "brandName", "car_make")
        model = pick(post, "model", "modelName", "car_model")
        year = pick(post, "year", "model_year", "modelYear")
        mileage = pick(post, "mileage", "km", "kilometers", "odometer")
        city = pick(post, "city", "location", "cityName", "region", "area")

        # Fall back to parsing the title
        if title and (not make or not model or not year):
            _make, _model, _year = parse_title(str(title))
            make = make or _make
            model = model or _model
            year = year or _year

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
            "source": "haraj",
            "title": str(title) if title else None,
            "make": make,
            "model": model,
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
            return []
        posts = self._find_car_arrays(data)
        if not posts:
            pp = data.get("props", {}).get("pageProps", {})
            logger.info("Haraj __NEXT_DATA__ found but no post arrays. pageProps keys: %s",
                        list(pp.keys())[:15])
            return []
        listings = []
        for post in posts:
            listing = self._json_post_to_listing(post)
            if listing:
                listings.append(listing)
        logger.info("Haraj: extracted %d listings from __NEXT_DATA__.", len(listings))
        return listings

    # ------------------------------------------------------------------
    # HTML fallback
    # ------------------------------------------------------------------

    def _log_html_diagnostics(self, soup, url: str):
        title = soup.title.string.strip() if soup.title else "NO TITLE"
        logger.info("DIAG[Haraj] title: '%s' | url: %s", title, url)
        classes = set()
        for tag in soup.find_all(True, limit=300):
            for cls in tag.get("class", []):
                classes.add(cls)
        relevant = sorted(c for c in classes if any(
            kw in c.lower() for kw in
            ["car", "post", "list", "card", "item", "vehicle", "product", "ad", "result"]
        ))
        logger.info("DIAG[Haraj] relevant classes: %s", relevant[:40])
        logger.info("DIAG[Haraj] all classes sample: %s", sorted(classes)[:40])
        text = soup.get_text(" ", strip=True)
        logger.info("DIAG[Haraj] page text (500 chars): %s", text[:500])
        # Also check if this might be a Cloudflare/bot challenge
        if len(text) < 300:
            logger.warning("DIAG[Haraj] Very short page text — possible bot challenge or empty shell.")

    def _parse_price(self, text: str) -> Optional[float]:
        if not text:
            return None
        cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None

    def _extract_listing_html(self, card) -> Optional[dict]:
        try:
            title_el = (
                card.select_one("h2 a") or card.select_one("h3 a")
                or card.select_one("a.post-title")
                or card.select_one("[class*='title'] a")
                or card.select_one("[class*='subject'] a")
                or card.select_one("a[href*='/cars/']")
            )
            if not title_el:
                return None

            raw_title = title_el.get_text(separator=" ", strip=True)
            href = title_el.get("href", "")
            url = urljoin(self.BASE_URL, href) if href else None
            if not url:
                return None

            price_el = (
                card.select_one("[class*='price']")
                or card.select_one("[class*='Price']")
            )
            price_sar = self._parse_price(price_el.get_text(strip=True) if price_el else "")

            card_text = card.get_text(" ", strip=True)
            mileage_km = None
            km_match = re.search(r"([\d,]+)\s*(?:km|كم|كيلومتر)", card_text, re.IGNORECASE)
            if km_match:
                raw = re.sub(r"[^\d]", "", km_match.group(1))
                mileage_km = int(raw) if raw else None

            city_el = (
                card.select_one("[class*='city']") or card.select_one("[class*='location']")
                or card.select_one("[class*='region']")
            )
            city = city_el.get_text(strip=True) if city_el else None

            make, model, year = parse_title(raw_title)

            return {
                "source": "haraj",
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
            logger.debug("Failed to parse Haraj HTML card: %s", exc)
            return None

    def _parse_from_html(self, soup, url: str) -> list:
        selectors = [
            "div.post-item", "article.post", "li.post",
            "[class*='post-card']", "[class*='PostCard']",
            "[class*='listing-card']", "[class*='ListingCard']",
            "[class*='ad-card']", "[class*='AdCard']",
            "div[data-id]", "[class*='car-card']",
            "[class*='item-card']", "[class*='ItemCard']",
        ]
        cards = []
        for sel in selectors:
            cards = soup.select(sel)
            if cards:
                logger.info("Haraj HTML: matched selector '%s' -> %d cards.", sel, len(cards))
                break

        if not cards:
            # Broad fallback: any <a> linking to a car post
            cards = soup.select("a[href*='/cars/']")
            if cards:
                logger.info("Haraj HTML: broad link fallback -> %d links.", len(cards))

        if not cards:
            self._log_html_diagnostics(soup, url)
            return []

        listings = []
        for card in cards:
            listing = self._extract_listing_html(card)
            if listing:
                listings.append(listing)
        return listings

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def scrape(self) -> list:
        all_listings = []

        for page in range(1, self.max_pages + 1):
            url = self._get_page_url(page)
            logger.info("Haraj: fetching page %d — %s", page, url)

            resp, soup = self._get(url)
            if soup is None:
                logger.warning("Haraj: skipping page %d — failed to fetch.", page)
                continue

            # 1. Try __NEXT_DATA__ JSON
            page_listings = self._parse_from_next_data(soup)
            # 2. Try embedded JSON in script tags
            if not page_listings:
                embedded = self._find_embedded_json(soup)
                if embedded:
                    logger.info("Haraj: found %d items in embedded script JSON.", len(embedded))
                    for post in embedded:
                        listing = self._json_post_to_listing(post)
                        if listing:
                            page_listings.append(listing)
            # 3. Fall back to HTML selectors
            if not page_listings:
                page_listings = self._parse_from_html(soup, url)

            logger.info("Haraj page %d: %d valid listings.", page, len(page_listings))
            all_listings.extend(page_listings)

            if not page_listings:
                break

            next_btn = soup.select_one("a[rel='next']") or soup.select_one(".pagination .next")
            if not next_btn and page < self.max_pages:
                logger.info("Haraj: no next-page link after page %d, stopping.", page)
                break

            if page < self.max_pages:
                time.sleep(self.delay)

        logger.info("Haraj scrape complete. Total: %d listings.", len(all_listings))
        return all_listings
