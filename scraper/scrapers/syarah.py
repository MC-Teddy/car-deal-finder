"""
Syarah.com scraper — v5 (internal JSON API)

Discovery (May 2026):
  API:     https://syarah.com/api/syarah_v1/ar/search/index
  Auth:    `token` header (static app-level key stored in encrypted UUID cookie)
  Data:    data.products[]  →  g4_data_layer sub-object holds clean English fields
  Total:   ~3 600 listings, 230 pages @ 16 per page

Auth notes:
  The token is derived by the page JS from an AES-encrypted UUID cookie.
  We expose it as the env-var / GitHub Secret  SYARAH_TOKEN.
  If the scraper starts returning 401, refresh the token by opening
  syarah.com/autos in a browser and capturing the XHR `token` header.
"""

import json
import logging
import os
import time
import uuid
import re

import requests

logger = logging.getLogger(__name__)

_TOKEN = os.getenv("SYARAH_TOKEN", "JR4iENSB52eTFYnRgmNgtpZXVBf3wHue")
_USER_ID = f"uid-{int(time.time() * 1000)}-{int(uuid.uuid4().int % 100000)}"
_GBUUID = str(uuid.uuid4())

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "token": _TOKEN,
    "user-id": _USER_ID,
    "gbuuid": _GBUUID,
    "device": "web",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://syarah.com/autos",
    "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
}

BASE_URL = "https://syarah.com/api/syarah_v1/ar/search/index"
PAGE_LINK = "/autos"
PAGE_SIZE = 16
MAX_PAGES = 15   # cap at 240 listings per run to stay within free-tier limits


def _parse_int(val) -> int:
    """'76,509' → 76509 ;  None / '' → 0"""
    if val is None:
        return 0
    cleaned = re.sub(r"[^\d]", "", str(val))
    return int(cleaned) if cleaned else 0


def _fetch_page(session: requests.Session, page: int) -> list:
    search_data = json.dumps(
        {
            "filters": {"text": ""},
            "link": PAGE_LINK,
            "page": page,
            "sort": "",
            "size": PAGE_SIZE,
            "new_path": True,
        }
    )
    params = {
        "ps": f"{page}-{PAGE_SIZE}",
        "includes": "meta_tags,seo_data,quality_section",
        "search_data": search_data,
    }
    try:
        resp = session.get(BASE_URL, params=params, headers=HEADERS, timeout=20)
    except requests.RequestException as exc:
        logger.warning("Syarah page %d request error: %s", page, exc)
        return []

    if resp.status_code == 401:
        logger.error(
            "Syarah: 401 Unauthorized — SYARAH_TOKEN has expired. "
            "Update the GitHub Secret and re-run."
        )
        return []

    if resp.status_code != 200:
        logger.warning("Syarah page %d: HTTP %s", page, resp.status_code)
        return []

    try:
        body = resp.json()
    except ValueError:
        logger.warning("Syarah page %d: non-JSON response", page)
        return []

    if not body.get("success"):
        logger.warning(
            "Syarah page %d: API error %s — %s",
            page, body.get("code"), body.get("message"),
        )
        return []

    return body.get("data", {}).get("products", [])


def _product_to_listing(product: dict) -> dict | None:
    """Extract a normalised listing dict from a Syarah API product entry."""
    gl = product.get("g4_data_layer") or {}

    condition = gl.get("post_condition", "")
    if condition.lower() not in ("used", ""):
        return None   # skip brand-new cars

    post_id = str(product.get("id", ""))
    if not post_id:
        return None

    # Price — prefer g4 numeric field, fallback to sellingprice string
    price = gl.get("post_price") or _parse_int(product.get("sellingprice", ""))
    if not price:
        return None

    mileage = _parse_int(gl.get("post_mileage"))
    year = int(gl.get("post_year") or product.get("year") or 0)

    url_path = product.get("product_url", f"/cardetail/{post_id}")
    listing_url = f"https://syarah.com{url_path}"

    return {
        "source": "syarah",
        "listing_id": f"syarah-{post_id}",
        "url": listing_url,
        "title": (product.get("title_en") or product.get("title") or "").strip(),
        "make": gl.get("post_make", ""),
        "model": gl.get("post_model", ""),
        "year": year,
        "price": price,
        "mileage": mileage,
        "city": gl.get("post_city") or product.get("city_name", ""),
        "fuel_type": gl.get("post_fuel", ""),
        "transmission": gl.get("post_transmission", ""),
        "color": gl.get("post_exterior_color_id", ""),
        "image_url": product.get("image_url", ""),
        "condition": condition or "Used",
    }


def scrape() -> list:
    logger.info("Syarah: starting scrape (token=%s…)", _TOKEN[:8])
    session = requests.Session()

    # --- page 1 to discover total pages ---
    first_page_products = _fetch_page(session, 1)
    if not first_page_products:
        logger.warning("Syarah: page 1 returned 0 products — check token / API")
        return []

    # Discover total pages from a lightweight metadata call (same endpoint)
    search_data = json.dumps(
        {"filters": {"text": ""}, "link": PAGE_LINK, "page": 1, "sort": "", "size": PAGE_SIZE, "new_path": True}
    )
    params = {"ps": f"1-{PAGE_SIZE}", "includes": "meta_tags,seo_data,quality_section", "search_data": search_data}
    try:
        meta_resp = session.get(BASE_URL, params=params, headers=HEADERS, timeout=20)
        meta = meta_resp.json()
        total_pages = int(meta.get("data", {}).get("total_pages") or 1)
        total_count = int(meta.get("data", {}).get("products_count") or 0)
        logger.info("Syarah: %d listings across %d pages", total_count, total_pages)
    except Exception:
        total_pages = 1

    pages_to_fetch = min(total_pages, MAX_PAGES)
    logger.info("Syarah: fetching %d pages (cap=%d)", pages_to_fetch, MAX_PAGES)

    all_listings: list[dict] = []

    # Process page 1 results already fetched
    for product in first_page_products:
        listing = _product_to_listing(product)
        if listing:
            all_listings.append(listing)

    logger.info("Syarah page 1: %d used-car listings", len(all_listings))

    # Fetch remaining pages
    for page in range(2, pages_to_fetch + 1):
        products = _fetch_page(session, page)
        page_listings = []
        for product in products:
            listing = _product_to_listing(product)
            if listing:
                page_listings.append(listing)

        logger.info("Syarah page %d: %d listings", page, len(page_listings))
        all_listings.extend(page_listings)

        # Polite delay
        time.sleep(0.5)

    logger.info("Syarah total: %d listings", len(all_listings))
    return all_listings
