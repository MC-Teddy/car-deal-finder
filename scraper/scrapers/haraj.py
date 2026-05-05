"""
Haraj.com scraper - v2 with API endpoint discovery.

Haraj is a React SPA — the HTML shell has no listing data and no __NEXT_DATA__.
Strategy: probe known API endpoint patterns and use the first one that returns JSON.
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

# API endpoints to probe in order; first JSON 200 wins
API_PROBES = [
    # Haraj REST v2/v3 (used by mobile app)
    "https://haraj.com/api/v2/posts?want=cars&type=sell&lang=en&city=0&last_id=0&limit=20",
    "https://haraj.com/api/v3/posts?want=cars&type=sell&city=0&last_id=0&limit=20",
    "https://haraj.com/api/posts?want=cars&type=sell&city=0&limit=20",
    "https://haraj.com/en/api/posts?want=cars&city=0&limit=20",
    # Alternative domain
    "https://haraj.com.sa/api/v2/posts?want=cars&city=0&last_id=0&limit=20",
    # GraphQL hint
    "https://haraj.com/graphql",
]

ARABIC_MAKES = {
    "تويوتا": "Toyota", "هوندا": "Honda", "نيسان": "Nissan",
    "هيونداي": "Hyundai", "كيا": "Kia", "فورد": "Ford",
    "شيفروليه": "Chevrolet", "جيب": "Jeep", "دودج": "Dodge",
    "بي ام دبليو": "BMW", "مرسيدس": "Mercedes-Benz", "لكزس": "Lexus",
    "انفينيتي": "Infiniti", "أودي": "Audi", "فولكس واجن": "Volkswagen",
    "بورش": "Porsche", "لاند روفر": "Land Rover", "رنج روفر": "Range Rover",
    "ميتسوبيشي": "Mitsubishi", "سوزوكي": "Suzuki", "مازدا": "Mazda",
    "كاديلاك": "Cadillac", "لينكون": "Lincoln", "جنسيس": "Genesis",
    "غي ام سي": "GMC", "جي ام سي": "GMC", "GMC": "GMC",
    "شانجان": "Changan", "هافال": "Haval", "BYD": "BYD", "MG": "MG",
}


def parse_title(title: str):
    if not title:
        return None, None, None
    yr = re.search(r"\b(19[89]\d|20[012]\d)\b", title)
    year = int(yr.group(1)) if yr else None
    make = None
    for ar, en in ARABIC_MAKES.items():
        if ar in title:
            make = en
            break
    if not make:
        m = re.search(
            r"\b(Toyota|Honda|Nissan|Hyundai|Kia|Ford|Chevrolet|Jeep|Dodge|BMW|"
            r"Mercedes|Lexus|Infiniti|Audi|Volkswagen|Porsche|Land\s*Rover|"
            r"Range\s*Rover|Mitsubishi|Suzuki|Mazda|Cadillac|GMC|BYD|MG)\b",
            title, re.IGNORECASE)
        if m:
            make = m.group(1).title()
    return make, None, year


class HarajScraper:
    BASE_URL = "https://haraj.com"
    CARS_URL = "https://haraj.com/en/cars/"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.6367.82 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
        "sec-ch-ua-mobile": "?0",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "Connection": "keep-alive",
    }

    API_HEADERS = {
        "User-Agent": "HarajApp/4.0 (Android; Saudi Arabia)",
        "Accept": "application/json",
        "Accept-Language": "ar-SA",
    }

    def __init__(self, max_pages: int = 5, delay: float = 2.0, timeout: int = 20):
        self.max_pages = max_pages
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self._api_url = None
        self._api_data_path = None

    # ------------------------------------------------------------------
    # API discovery (primary method)
    # ------------------------------------------------------------------

    def _probe_apis(self) -> Optional[tuple]:
        """
        Try each API endpoint. Return (base_url, sample_item) for the first
        one that returns a JSON array of car-like objects, or None.
        """
        api_session = requests.Session()
        api_session.headers.update(self.API_HEADERS)

        for url in API_PROBES:
            try:
                resp = api_session.get(url, timeout=self.timeout)
                ct = resp.headers.get("content-type", "")
                logger.info("Haraj API probe: %s -> %d [%s]", url, resp.status_code, ct[:60])

                if resp.status_code != 200:
                    continue
                if "json" not in ct and "javascript" not in ct:
                    logger.info("Haraj API probe non-JSON at %s", url)
                    continue

                data = resp.json()
                logger.info("Haraj API probe JSON type=%s len=%s",
                            type(data).__name__,
                            len(data) if isinstance(data, (list, dict)) else "?")

                # Look for a list of car-like objects
                candidates = self._find_post_arrays(data)
                if candidates:
                    logger.info("Haraj API: found %d posts at %s. Sample keys: %s",
                                len(candidates), url, list(candidates[0].keys())[:10])
                    return url, candidates
                else:
                    logger.info("Haraj API JSON at %s has no post arrays. Keys: %s",
                                list(data.keys())[:10] if isinstance(data, dict) else "list")

            except requests.exceptions.ConnectionError:
                logger.info("Haraj API probe: connection error at %s (endpoint may not exist)", url)
            except json.JSONDecodeError:
                logger.info("Haraj API probe: non-JSON response at %s", url)
            except Exception as exc:
                logger.error("Haraj API probe error at %s: %s", url, exc)

        return None

    def _find_post_arrays(self, obj, depth: int = 0) -> list:
        if depth > 6:
            return []
        if isinstance(obj, list) and len(obj) >= 1 and isinstance(obj[0], dict):
            first = obj[0]
            post_keys = {"id", "title", "subject", "price", "city", "url",
                         "make", "model", "year", "want", "type", "slug"}
            if len(set(str(k).lower() for k in first.keys()) & {k.lower() for k in post_keys}) >= 2:
                return obj
        if isinstance(obj, dict):
            for key in ["posts", "data", "items", "results", "cars", "ads",
                        "listings", "list", "content"]:
                if key in obj:
                    r = self._find_post_arrays(obj[key], depth + 1)
                    if r:
                        return r
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    r = self._find_post_arrays(v, depth + 1)
                    if r:
                        return r
        return []

    def _api_post_to_listing(self, post: dict) -> Optional[dict]:
        def pick(d, *keys):
            for k in keys:
                v = d.get(k)
                if v is not None and v != "":
                    return v
            return None

        post_id = pick(post, "id", "post_id", "postId")
        url_raw = pick(post, "url", "link", "slug", "permalink")
        if url_raw and url_raw.startswith("http"):
            url = url_raw
        elif url_raw:
            url = urljoin(self.BASE_URL, "/" + url_raw.lstrip("/"))
        elif post_id:
            url = f"{self.BASE_URL}/en/cars/{post_id}"
        else:
            return None

        title = pick(post, "title", "subject", "body", "name", "ad_title")
        price = pick(post, "price", "priceValue", "sell_price")
        make = pick(post, "make", "brand", "brandName")
        model = pick(post, "model", "modelName")
        year = pick(post, "year", "model_year")
        mileage = pick(post, "mileage", "km", "kilometers")
        city = pick(post, "city", "location", "cityName", "region")

        if title and (not make or not year):
            _make, _, _year = parse_title(str(title))
            make = make or _make
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
            "source": "haraj", "title": str(title) if title else None,
            "make": make, "model": model, "year": year,
            "price_sar": price, "mileage_km": mileage,
            "city": str(city) if city else None,
            "listed_at": datetime.utcnow().isoformat(), "url": url, "seller_type": "unknown",
        }

    # ------------------------------------------------------------------
    # HTML fallback (for future use if API is found)
    # ------------------------------------------------------------------

    def _get_html(self, url: str):
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            return resp, BeautifulSoup(resp.text, "lxml")
        except Exception as exc:
            logger.error("Haraj HTML fetch error %s: %s", url, exc)
        return None, None

    def _log_diag(self, soup, url):
        title = soup.title.string.strip() if soup.title else "NO TITLE"
        logger.info("DIAG[Haraj] title: '%s' | url: %s", title, url)
        classes = set()
        for tag in soup.find_all(True, limit=300):
            for cls in tag.get("class", []):
                classes.add(cls)
        rel = sorted(c for c in classes if any(
            kw in c.lower() for kw in ["car", "post", "card", "item", "vehicle", "ad"]))
        logger.info("DIAG[Haraj] relevant classes: %s", rel[:40])
        logger.info("DIAG[Haraj] all classes: %s", sorted(classes)[:40])
        text = soup.get_text(" ", strip=True)
        logger.info("DIAG[Haraj] text (500): %s", text[:500])
        if len(text) < 300:
            logger.warning("DIAG[Haraj] Short page — SPA shell or bot challenge.")

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def scrape(self) -> list:
        all_listings = []

        # --- Phase 1: Try API endpoints ---
        logger.info("Haraj: probing %d API endpoints...", len(API_PROBES))
        result = self._probe_apis()

        if result:
            api_url, first_page_posts = result
            # Convert first page
            for post in first_page_posts:
                listing = self._api_post_to_listing(post)
                if listing:
                    all_listings.append(listing)
            logger.info("Haraj: API page 1 -> %d listings.", len(all_listings))

            # Try paginating via last_id or page param
            # (Haraj typically uses cursor-based pagination with last_id)
            last_id = None
            for page in range(2, self.max_pages + 1):
                if last_id is None and first_page_posts:
                    ids = [p.get("id") for p in first_page_posts if p.get("id")]
                    last_id = min(ids) if ids else None
                if last_id is None:
                    break
                paginated_url = f"{api_url.split('?')[0]}?want=cars&type=sell&lang=en&city=0&last_id={last_id}&limit=20"
                try:
                    resp = requests.get(paginated_url, headers=self.API_HEADERS, timeout=self.timeout)
                    if resp.status_code != 200:
                        break
                    page_data = resp.json()
                    posts = self._find_post_arrays(page_data)
                    if not posts:
                        break
                    page_listings = [l for l in (self._api_post_to_listing(p) for p in posts) if l]
                    all_listings.extend(page_listings)
                    logger.info("Haraj API page %d -> %d listings.", page, len(page_listings))
                    ids = [p.get("id") for p in posts if p.get("id")]
                    last_id = min(ids) if ids else None
                    if page < self.max_pages:
                        time.sleep(self.delay)
                except Exception as exc:
                    logger.error("Haraj API pagination error: %s", exc)
                    break
        else:
            # --- Phase 2: HTML fallback (diagnostic only for SPA) ---
            logger.warning("Haraj: no working API found. Falling back to HTML (SPA — may return 0).")
            _, soup = self._get_html(self.CARS_URL)
            if soup:
                self._log_diag(soup, self.CARS_URL)

        logger.info("Haraj total: %d listings.", len(all_listings))
        return all_listings
