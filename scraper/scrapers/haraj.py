"""
Haraj.com scraper for used car listings.

Haraj (haraj.com) is one of the most popular classifieds platforms in Saudi Arabia.
Car listings appear under the "cars" category. The site renders content server-side,
so requests + BeautifulSoup works without a headless browser.

If Cloudflare or JS challenges are encountered, the scraper logs a warning and
returns whatever partial data was collected.
"""

import logging
import re
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Arabic → English make name mapping (common Saudi listing patterns)
# ---------------------------------------------------------------------------
ARABIC_MAKES: dict[str, str] = {
    "تويوتا": "Toyota",
    "هوندا": "Honda",
    "نيسان": "Nissan",
    "هيونداي": "Hyundai",
    "كيا": "Kia",
    "فورد": "Ford",
    "شيفروليه": "Chevrolet",
    "شفروليه": "Chevrolet",
    "جيب": "Jeep",
    "دودج": "Dodge",
    "بي ام دبليو": "BMW",
    "مرسيدس": "Mercedes-Benz",
    "مرسيدس بنز": "Mercedes-Benz",
    "لكزس": "Lexus",
    "انفينيتي": "Infiniti",
    "أودي": "Audi",
    "اودي": "Audi",
    "فولكس واجن": "Volkswagen",
    "بورش": "Porsche",
    "رنج روفر": "Range Rover",
    "لاند روفر": "Land Rover",
    "ميتسوبيشي": "Mitsubishi",
    "سوزوكي": "Suzuki",
    "مازدا": "Mazda",
    "جاكوار": "Jaguar",
    "فولفو": "Volvo",
    "كاديلاك": "Cadillac",
    "لينكون": "Lincoln",
    "بيجو": "Peugeot",
    "رينو": "Renault",
    "سيتروين": "Citroen",
    "جنسيس": "Genesis",
    "هامر": "Hummer",
    "غي ام سي": "GMC",
    "جي ام سي": "GMC",
    "GMC": "GMC",
    "شانجان": "Changan",
    "هافال": "Haval",
    "JAC": "JAC",
    "BYD": "BYD",
    "MG": "MG",
    "ام جي": "MG",
}

# Common model patterns in Arabic
ARABIC_MODELS: dict[str, str] = {
    "كامري": "Camry",
    "كورولا": "Corolla",
    "راف فور": "RAV4",
    "هايلكس": "Hilux",
    "لاند كروزر": "Land Cruiser",
    "برادو": "Prado",
    "فورتشنر": "Fortuner",
    "افالون": "Avalon",
    "يارس": "Yaris",
    "اكورد": "Accord",
    "سيفيك": "Civic",
    "باسبورت": "Passport",
    "بايلوت": "Pilot",
    "سي ار في": "CR-V",
    "الترا": "Altima",
    "ماكسيما": "Maxima",
    "باترول": "Patrol",
    "اكس تريل": "X-Trail",
    "سنترا": "Sentra",
    "النترا": "Elantra",
    "توسان": "Tucson",
    "سانتافي": "Santa Fe",
    "سوناتا": "Sonata",
    "سبورتاج": "Sportage",
    "سيراتو": "Cerato",
    "ستينجر": "Stinger",
    "تاهو": "Tahoe",
    "سوبربان": "Suburban",
    "ترافيرس": "Traverse",
    "ايكونوس": "Equinox",
    "سيلفرادو": "Silverado",
    "ريبل": "Rebel",
    "رام": "Ram",
    "جراند شيروكي": "Grand Cherokee",
    "رانجلر": "Wrangler",
    "F-150": "F-150",
    "اكسبلورر": "Explorer",
    "إكسبلورر": "Explorer",
    "موستانج": "Mustang",
    "ابتيما": "Optima",
    "سيدان": "Sedan",
}

# ---------------------------------------------------------------------------
# Title parser
# ---------------------------------------------------------------------------

def parse_title(title: str) -> tuple[Optional[str], Optional[str], Optional[int]]:
    """
    Extract (make, model, year) from a raw listing title.

    Handles mixed Arabic/English text such as:
      - "تويوتا كامري 2020 ابيض"
      - "Toyota Camry 2020 White"
      - "لكزس LX 570 2019"
      - "BMW X5 2021 full options"

    Returns:
        Tuple of (make, model, year). Any element may be None if not found.
    """
    if not title:
        return None, None, None

    # ---- Year extraction ------------------------------------------------
    year_match = re.search(r"\b(19[89]\d|20[012]\d)\b", title)
    year = int(year_match.group(1)) if year_match else None

    make: Optional[str] = None
    model: Optional[str] = None

    # ---- Arabic make/model extraction -----------------------------------
    for arabic_make, english_make in ARABIC_MAKES.items():
        if arabic_make in title:
            make = english_make
            break

    for arabic_model, english_model in ARABIC_MODELS.items():
        if arabic_model in title:
            model = english_model
            break

    # ---- English make/model extraction (fallback) -----------------------
    if not make:
        english_make_patterns = [
            r"\b(Toyota|Honda|Nissan|Hyundai|Kia|Ford|Chevrolet|Jeep|Dodge|BMW|"
            r"Mercedes[-\s]?Benz|Mercedes|Lexus|Infiniti|Audi|Volkswagen|Porsche|"
            r"Land\s*Rover|Range\s*Rover|Mitsubishi|Suzuki|Mazda|Jaguar|Volvo|"
            r"Cadillac|Lincoln|Peugeot|Renault|Genesis|Hummer|GMC|Changan|Haval|"
            r"JAC|BYD|MG|Subaru|Acura|Buick|Chrysler|RAM|Isuzu)\b",
        ]
        for pattern in english_make_patterns:
            m = re.search(pattern, title, re.IGNORECASE)
            if m:
                make = m.group(1).title()
                break

    if not model and make:
        # Try to find the word(s) after the make as the model
        if make:
            escaped = re.escape(make)
            model_match = re.search(
                rf"{escaped}\s+([A-Za-z0-9\-]+(?:\s+[A-Za-z0-9\-]+)?)",
                title,
                re.IGNORECASE,
            )
            if model_match:
                candidate = model_match.group(1).strip()
                # Filter out years and common noise words
                noise = {"white", "black", "red", "blue", "silver", "full", "options",
                         "gcc", "clean", "excellent", "good", "condition", "for", "sale"}
                if candidate.lower() not in noise and not re.match(r"^(19|20)\d{2}$", candidate):
                    model = candidate

    return make, model, year


# ---------------------------------------------------------------------------
# Main scraper class
# ---------------------------------------------------------------------------

class HarajScraper:
    """
    Scraper for haraj.com/en/ car listings.

    Uses requests with browser-like headers. Paginates through listing pages,
    parses each listing card, and returns normalized dicts.
    """

    BASE_URL = "https://haraj.com"
    CARS_URL = "https://haraj.com/en/cars/"

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
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "max-age=0",
    }

    def __init__(self, max_pages: int = 5, delay: float = 2.0, timeout: int = 15):
        """
        Initialize the Haraj scraper.

        Args:
            max_pages: Maximum number of listing pages to scrape.
            delay: Seconds to sleep between page requests (rate limiting).
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
        """Fetch a URL and return a BeautifulSoup object, or None on failure."""
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            # Detect JS challenge pages (Cloudflare, etc.)
            if len(resp.text) < 500 and ("challenge" in resp.text.lower() or
                                          "checking your browser" in resp.text.lower()):
                logger.warning("Possible JS challenge detected at %s. Content may be incomplete.", url)
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

    def _parse_price(self, text: str) -> Optional[float]:
        """Extract numeric price from a string, stripping SAR / ريال labels."""
        if not text:
            return None
        cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None

    def _parse_mileage(self, text: str) -> Optional[int]:
        """Extract mileage (km) from a string."""
        if not text:
            return None
        match = re.search(r"([\d,]+)", text.replace(",", ""))
        if match:
            try:
                return int(match.group(1).replace(",", ""))
            except ValueError:
                pass
        return None

    def _parse_date(self, text: str) -> Optional[str]:
        """
        Normalise a listing date string to ISO-8601.
        Haraj shows dates like "2 hours ago", "yesterday", or "2024/04/15".
        Returns best-effort ISO string; falls back to today's date for relative times.
        """
        if not text:
            return None
        text = text.strip()
        now = datetime.utcnow()

        relative_patterns = [
            (r"(\d+)\s*(minute|دقيقة|دقائق)", "minutes"),
            (r"(\d+)\s*(hour|ساعة|ساعات)", "hours"),
        ]
        for pattern, unit in relative_patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return now.isoformat()

        if re.search(r"yesterday|أمس", text, re.IGNORECASE):
            from datetime import timedelta
            return (now - timedelta(days=1)).date().isoformat()

        # Try explicit date formats
        for fmt in ("%Y/%m/%d", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text[:10], fmt).isoformat()
            except ValueError:
                continue

        # Fall back to now
        return now.isoformat()

    def _extract_listing(self, card) -> Optional[dict]:
        """
        Parse a single listing card element into a normalised dict.

        Haraj listing cards typically contain:
          - A title <h2> or <a> element
          - A price element with class containing 'price'
          - City / location text
          - A relative timestamp
        """
        try:
            # Title & URL
            title_el = (
                card.select_one("h2 a")
                or card.select_one("h3 a")
                or card.select_one("a.post-title")
                or card.select_one("[class*='title'] a")
                or card.select_one("a[href*='/cars/']")
            )
            if not title_el:
                return None

            raw_title = title_el.get_text(separator=" ", strip=True)
            href = title_el.get("href", "")
            url = urljoin(self.BASE_URL, href) if href else None
            if not url:
                return None

            # Price
            price_el = (
                card.select_one("[class*='price']")
                or card.select_one("[class*='Price']")
                or card.select_one("span.price")
            )
            price_text = price_el.get_text(strip=True) if price_el else ""
            price_sar = self._parse_price(price_text)

            # Mileage — look for a km / كم pattern anywhere in the card text
            card_text = card.get_text(" ", strip=True)
            mileage_km: Optional[int] = None
            mileage_match = re.search(
                r"([\d,]+)\s*(?:km|كم|كيلومتر|كيلو)", card_text, re.IGNORECASE
            )
            if mileage_match:
                mileage_km = self._parse_mileage(mileage_match.group(1))

            # City / location
            city_el = (
                card.select_one("[class*='city']")
                or card.select_one("[class*='location']")
                or card.select_one("[class*='region']")
            )
            city = city_el.get_text(strip=True) if city_el else None

            # Date
            date_el = (
                card.select_one("time")
                or card.select_one("[class*='date']")
                or card.select_one("[class*='time']")
            )
            raw_date = (
                date_el.get("datetime") or date_el.get_text(strip=True)
                if date_el
                else None
            )
            listed_at = self._parse_date(raw_date)

            # Seller type heuristic: "dealer" / "تاجر" in description → dealer
            seller_type = "unknown"
            if re.search(r"\bdealer\b|تاجر|معرض", card_text, re.IGNORECASE):
                seller_type = "dealer"
            elif re.search(r"\bprivate\b|شخصي|مالك", card_text, re.IGNORECASE):
                seller_type = "private"

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
                "listed_at": listed_at or datetime.utcnow().isoformat(),
                "url": url,
                "seller_type": seller_type,
            }

        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to parse listing card: %s", exc)
            return None

    def _get_page_url(self, page: int) -> str:
        """Build paginated URL for haraj.com car listings."""
        if page == 1:
            return self.CARS_URL
        return f"{self.CARS_URL}?page={page}"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def scrape(self) -> list[dict]:
        """
        Scrape car listings from haraj.com across multiple pages.

        Returns:
            List of normalised listing dicts. Empty list on total failure.
        """
        all_listings: list[dict] = []

        for page in range(1, self.max_pages + 1):
            url = self._get_page_url(page)
            logger.info("Scraping Haraj page %d: %s", page, url)

            soup = self._get(url)
            if soup is None:
                logger.warning("Skipping page %d — failed to fetch.", page)
                continue

            # Haraj uses various card selectors depending on layout version
            cards = (
                soup.select("div.post-item")
                or soup.select("article.post")
                or soup.select("[class*='listing-card']")
                or soup.select("[class*='post-card']")
                or soup.select("li.post")
                or soup.select("div[data-id]")
            )

            if not cards:
                logger.warning(
                    "No listing cards found on page %d. "
                    "Site layout may have changed or JS rendering may be required.",
                    page,
                )
                # Attempt a broader fallback: any <a> inside a repeated container
                # that links to a car listing
                cards = soup.select("a[href*='/cars/']")
                if not cards:
                    logger.warning("Fallback selector also failed on page %d. Stopping.", page)
                    break

            page_listings: list[dict] = []
            for card in cards:
                listing = self._extract_listing(card)
                if listing:
                    page_listings.append(listing)

            logger.info("Page %d: found %d valid listings.", page, len(page_listings))
            all_listings.extend(page_listings)

            # Check if there's a next page
            next_btn = soup.select_one("a[rel='next']") or soup.select_one(".pagination .next")
            if not next_btn and page < self.max_pages:
                logger.info("No next-page link found after page %d. Stopping pagination.", page)
                break

            if page < self.max_pages:
                logger.debug("Sleeping %.1f s before next page.", self.delay)
                time.sleep(self.delay)

        logger.info(
            "Haraj scrape complete. Total listings collected: %d", len(all_listings)
        )
        return all_listings
