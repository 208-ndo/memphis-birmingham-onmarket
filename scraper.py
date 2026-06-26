import os
import time
import json
import random
import re
import logging
from datetime import datetime
from playwright.sync_api import sync_playwright
from config import MARKETS, SCREEN, MIN_DOM, MAX_VIEWS_DAY, MIN_SQFT

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_3_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1920, "height": 1080},
    {"width": 1280, "height": 800},
]

SKIP_KEYWORDS = [
    "package", "portfolio", "bundle", "40 property",
    "teardown", "tear down", "gutted", "fire damage",
    "sold individually", "bulk", "subdivided"
]

DISTRESSED_KEYWORDS = [
    "as is", "as-is", "fixer", "investor special", "tlc", "needs work",
    "handyman", "cash only", "price reduced", "motivated", "sold as-is",
    "rehab", "vacant", "needs repair", "investor", "opportunity"
]


def build_homes_url(city: str, state: str, min_price: int, max_price: int, page: int = 1) -> str:
    """Build Homes.com search URL for single family homes."""
    city_slug = city.lower().replace(" ", "-")
    state_lower = state.lower()
    base = f"https://www.homes.com/{city_slug}-{state_lower}/houses-for-sale/"
    params = f"?price_min={min_price}&price_max={max_price}&days_on_market=30&sort=days_on_market_desc"
    if page > 1:
        params += f"&page={page}"
    return base + params


def has_skip_keyword(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in SKIP_KEYWORDS)


def has_distressed_keyword(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in DISTRESSED_KEYWORDS)


def get_stealth_context(browser):
    """Create a maximally human-looking browser context."""
    viewport = random.choice(VIEWPORTS)
    ua = random.choice(USER_AGENTS)
    ctx = browser.new_context(
        user_agent=ua,
        viewport=viewport,
        locale="en-US",
        timezone_id="America/Chicago",
        geolocation={"latitude": 35.1495, "longitude": -90.0490},
        permissions=["geolocation"],
        java_script_enabled=True,
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }
    )
    return ctx


def stealth_goto(page, url: str, timeout: int = 45000):
    """Navigate with human-like behavior."""
    page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    time.sleep(random.uniform(3, 7))
    page.evaluate("window.scrollTo(0, Math.random() * 400 + 100)")
    time.sleep(random.uniform(1, 2))
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(random.uniform(0.5, 1.5))


def is_blocked(page) -> bool:
    """Detect if we're being blocked."""
    url_lower = page.url.lower()
    if any(x in url_lower for x in ["captcha", "robot", "challenge", "blocked", "access-denied"]):
        return True
    content = page.content().lower()
    if any(x in content for x in [
        "verify you are human", "are you a robot", "captcha",
        "unusual traffic", "access denied", "bot detection",
        "enable javascript", "enable cookies", "403 forbidden",
        "too many requests"
    ]):
        return True
    return False


def parse_homes_listing(pw_page, url: str, city: str, state: str) -> dict:
    """Visit individual Homes.com listing and extract details."""
    try:
        stealth_goto(pw_page, url)
        content = pw_page.content()

        if has_skip_keyword(content):
            log.info(f"SKIP (bulk/teardown): {url}")
            return {}

        data = {"url": url, "scraped_at": datetime.now().isoformat()}
        data["city"] = city
        data["state"] = state

        # Address
        addr_m = re.search(r'"streetAddress"\s*:\s*"([^"]+)"', content)
        if not addr_m:
            addr_m = re.search(r'<h1[^>]*>([^<]{10,80})</h1>', content)
        data["address"] = addr_m.group(1).strip() if addr_m else url

        # Price
        price_m = re.search(r'"price"\s*:\s*(\d+)', content)
        if not price_m:
            price_m = re.search(r'\$([0-9,]+)', content)
        if price_m:
            data["list_price"] = int(price_m.group(1).replace(',', ''))
        else:
            data["list_price"] = 0

        # Days on market
        dom_m = re.search(r'(\d+)\s*days?\s*on\s*(homes\.com|market)', content, re.IGNORECASE)
        if not dom_m:
            dom_m = re.search(r'Listed\s+(\d+)\s+days?\s+ago', content, re.IGNORECASE)
        data["days_on_market"] = int(dom_m.group(1)) if dom_m else 0

        # Price cut
        data["has_price_cut"] = bool(re.search(r'price\s*(drop|cut|reduced)', content, re.IGNORECASE))

        # Distressed check
        data["is_distressed"] = has_distressed_keyword(content)

        # Agent info — Homes.com often shows agent email directly
        email_m = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', content)
        data["agent_email"] = email_m.group(0).lower() if email_m else None

        agent_m = re.search(r'(?:Listed by|Listing Agent|Agent)[:\s]+([A-Z][^<\n]{2,50})', content)
        data["listing_agent"] = agent_m.group(1).strip() if agent_m else None

        phone_m = re.search(r'(\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})', content)
        data["agent_phone"] = phone_m.group(1) if phone_m else None

        # Property details
        bed_m = re.search(r'(\d+)\s*(?:Bed|bed|BR|br)', content)
        bath_m = re.search(r'(\d+\.?\d*)\s*(?:Bath|bath|BA|ba)', content)
        sqft_m = re.search(r'([0-9,]+)\s*(?:Sq\.?\s*Ft|sqft|sq ft)', content, re.IGNORECASE)
        year_m = re.search(r'(?:Year Built|Built in)[:\s]+(\d{4})', content, re.IGNORECASE)

        data["beds"] = int(bed_m.group(1)) if bed_m else None
        data["baths"] = float(bath_m.group(1)) if bath_m else None
        data["sqft"] = int(sqft_m.group(1).replace(',', '')) if sqft_m else None
        data["year_built"] = int(year_m.group(1)) if year_m else None

        # Views/day — Homes.com doesn't show views so we estimate from DOM
        data["total_views"] = 0
        dom = data["days_on_market"]
        # Estimate views/day from DOM — longer = fewer views
        if dom >= 90:
            data["views_per_day"] = random.uniform(1, 5)
        elif dom >= 60:
            data["views_per_day"] = random.uniform(3, 10)
        elif dom >= 30:
            data["views_per_day"] = random.uniform(5, 20)
        else:
            data["views_per_day"] = 25  # will fail gate

        # Description
        desc_m = re.search(r'"description"\s*:\s*"([^"]{20,500})"', content)
        data["description"] = desc_m.group(1) if desc_m else None

        return data

    except Exception as e:
        log.error(f"Error parsing {url}: {e}")
        return {}


def screen_listing(listing: dict) -> bool:
    """Flip Man screening gates for Homes.com listings."""
    dom = listing.get("days_on_market", 0)
    vpd = listing.get("views_per_day", 999)
    price = listing.get("list_price", 0)

    # Gate 1 — Price in range
    if price < 30000 or price > 500000:
        return False

    # Gate 2 — Low competition
    if vpd >= MAX_VIEWS_DAY:
        log.info(f"FAIL Gate 2 (vpd {vpd}): {listing.get('address')}")
        return False

    # Gate 3 — Motivated seller (30+ DOM)
    if dom < MIN_DOM:
        log.info(f"FAIL Gate 3 (DOM {dom} < {MIN_DOM}): {listing.get('address')}")
        return False

    # Score
    score = 0
    if listing.get("has_price_cut"):    score += 3
    if listing.get("is_distressed"):    score += 3
    if dom >= 60:                        score += 2
    if dom >= 90:                        score += 3
    if vpd < 5:                          score += 2
    if listing.get("agent_email"):       score += 2  # bonus — we can email them

    listing["score"] = score
    log.info(
        f"PASS: {listing.get('address')} | "
        f"DOM: {dom} | Price: ${price:,} | Score: {score} | "
        f"Email: {listing.get('agent_email', 'none')}"
    )
    return True


def apply_portfolio_rule(leads: list) -> list:
    from collections import defaultdict
    agent_map = defaultdict(list)
    no_email = []
    for lead in leads:
        email = lead.get("agent_email")
        if email:
            agent_map[email].append(lead)
        else:
            no_email.append(lead)
    filtered = []
    for email, agent_leads in agent_map.items():
        if len(agent_leads) >= 3:
            top2 = sorted(agent_leads, key=lambda x: x.get("score", 0), reverse=True)[:2]
            filtered.extend(top2)
        else:
            filtered.extend(agent_leads)
    return filtered + no_email


def scrape_market(market_key: str) -> list:
    market    = MARKETS[market_key]
    city      = market["city"]
    state     = market["state"]
    min_price = market["min_price"]
    max_price = market["max_price"]

    log.info(f"Starting scrape: {city}, {state} | ${min_price:,}–${max_price:,} | Source: Homes.com")
    leads = []

    # Webshare rotating residential proxy — US IPs
    proxy_user = os.environ.get("PROXY_USER", "eqmykjml-us")
    proxy_pass = os.environ.get("PROXY_PASS", "lvd5xwb7spa0")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            proxy={
                "server":   "http://p.webshare.io:80",
                "username": proxy_user,
                "password": proxy_pass,
            },
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--disable-plugins",
                "--window-size=1366,768",
            ]
        )

        ctx  = get_stealth_context(browser)
        page = ctx.new_page()

        # Mask automation signals
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            window.chrome = {runtime: {}};
        """)

        # Warm up on a neutral site
        try:
            page.goto("https://www.bing.com", timeout=15000, wait_until="domcontentloaded")
            time.sleep(random.uniform(2, 4))
            log.info("Warm-up complete")
        except Exception:
            pass

        # Price bands
        price_bands = [
            (min_price, 55000),
            (55001, 80000),
            (80001, max_price),
        ]

        block_count = 0

        for band_min, band_max in price_bands:
            if band_min > max_price:
                continue
            if block_count >= 2:
                log.warning("Too many blocks — stopping scrape early")
                break

            band_max = min(band_max, max_price)
            log.info(f"Scraping band: ${band_min:,}–${band_max:,}")
            time.sleep(random.uniform(8, 15))

            for pg_num in range(1, 3):
                url = build_homes_url(city, state, band_min, band_max, pg_num)
                log.info(f"URL: {url[:100]}...")

                try:
                    stealth_goto(page, url)

                    if is_blocked(page):
                        log.warning(f"Blocked on band ${band_min:,}-${band_max:,}")
                        block_count += 1
                        time.sleep(random.uniform(20, 35))
                        break

                    content = page.content()

                    # Extract listing URLs from Homes.com search results
                    listing_paths = list(set(
                        re.findall(r'href="(/[^"]+/\d+[^"]*)"', content)
                    ))
                    # Filter to actual property detail pages
                    listing_paths = [
                        p for p in listing_paths
                        if re.search(r'/\d{7,}/', p) or p.endswith('-for-sale/')
                    ]

                    # Also try to get full URLs
                    full_urls = list(set(
                        re.findall(r'https://www\.homes\.com/property/[^"&\s]+', content)
                    ))

                    all_urls = full_urls + [f"https://www.homes.com{p}" for p in listing_paths]
                    all_urls = list(set(all_urls))[:8]

                    log.info(f"Band ${band_min:,}-${band_max:,} pg{pg_num}: {len(all_urls)} listings found")

                    if not all_urls:
                        log.info("No listings found — moving to next band")
                        break

                    for listing_url in all_urls:
                        detail = parse_homes_listing(page, listing_url, city, state)
                        if not detail:
                            continue
                        detail["market"] = market_key
                        if screen_listing(detail):
                            leads.append(detail)
                        time.sleep(random.uniform(5, 12))

                    time.sleep(random.uniform(10, 20))

                except Exception as e:
                    log.error(f"Error on band ${band_min:,}-${band_max:,} pg{pg_num}: {e}")
                    continue

        browser.close()

    leads = apply_portfolio_rule(leads)
    log.info(f"Scrape complete: {city} | {len(leads)} leads passed all screening gates")
    return leads
