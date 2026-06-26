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

DISTRESSED_KEYWORDS = (
    "as is,fixer,investor special,tlc,needs work,handyman,"
    "cash only,price reduced,motivated,sold as-is,rehab,vacant"
)

SKIP_KEYWORDS = [
    "package", "portfolio", "bundle", "40 property",
    "teardown", "tear down", "gutted", "fire damage",
    "sold individually", "bulk", "subdivided"
]

# Randomized viewports to avoid fingerprinting
VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1920, "height": 1080},
    {"width": 1280, "height": 800},
]


def build_zillow_url(city: str, state: str, min_price: int, max_price: int, page: int = 1) -> str:
    city_slug = city.lower().replace(" ", "-")
    state_lower = state.lower()
    sqs = {
        "pagination": {"currentPage": page},
        "filterState": {
            "price": {"min": min_price, "max": max_price},
            "doz": {"value": "30d"},
            "sort": {"value": "days"},
            "tow": {"value": False},
            "mf": {"value": False},
            "con": {"value": False},
            "land": {"value": False},
            "apa": {"value": False},
            "manu": {"value": False},
            "apco": {"value": False},
            "fsba": {"value": True},
            "fsbo": {"value": False},
            "nc": {"value": False},
            "cmsn": {"value": False},
            "auc": {"value": False},
            "fore": {"value": False},
            "sqft": {"min": MIN_SQFT},
            "att": {"value": DISTRESSED_KEYWORDS},
        },
        "isListVisible": True,
        "isMapVisible": True,
    }
    encoded = json.dumps(sqs, separators=(',', ':'))
    return f"https://www.zillow.com/{city_slug}-{state_lower}/houses/?searchQueryState={encoded}"


def has_skip_keyword(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in SKIP_KEYWORDS)


def get_stealth_context(browser):
    """Create a browser context that looks as human as possible."""
    viewport = random.choice(VIEWPORTS)
    ua = random.choice(USER_AGENTS)
    ctx = browser.new_context(
        user_agent=ua,
        viewport=viewport,
        locale="en-US",
        timezone_id="America/Chicago",
        geolocation={"latitude": 35.1495, "longitude": -90.0490},  # Memphis coords
        permissions=["geolocation"],
        java_script_enabled=True,
        accept_downloads=False,
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
    # Random human-like delay
    time.sleep(random.uniform(4, 8))
    # Simulate light scrolling
    page.evaluate("window.scrollTo(0, Math.random() * 300 + 100)")
    time.sleep(random.uniform(1, 2))
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(random.uniform(0.5, 1.5))


def is_captcha(page) -> bool:
    """Detect CAPTCHA or bot detection pages."""
    url_lower = page.url.lower()
    if any(x in url_lower for x in ["captcha", "robot", "challenge", "blocked"]):
        return True
    content = page.content().lower()
    if any(x in content for x in [
        "verify you are human", "are you a robot", "captcha",
        "unusual traffic", "access denied", "bot detection",
        "please enable javascript", "enable cookies"
    ]):
        return True
    return False


def parse_listing_detail(pw_page, url: str) -> dict:
    try:
        stealth_goto(pw_page, url)
        content = pw_page.content()

        if has_skip_keyword(content):
            log.info(f"SKIP (bulk/teardown): {url}")
            return {}

        data = {"url": url, "scraped_at": datetime.now().isoformat()}

        dom_m = re.search(r'(\d+) days on Zillow', content)
        data["days_on_market"] = int(dom_m.group(1)) if dom_m else 0

        views_m = re.search(r'(\d+,?\d*) views', content)
        data["total_views"] = int(views_m.group(1).replace(',', '')) if views_m else 0
        data["views_per_day"] = round(
            data["total_views"] / max(data["days_on_market"], 1), 2
        )

        price_cut_m = re.search(r'Price cut', content, re.IGNORECASE)
        data["has_price_cut"] = price_cut_m is not None

        relisted_m = re.search(r'Listed\s+\d+\s+times', content, re.IGNORECASE)
        data["was_relisted"] = relisted_m is not None

        agent_m = re.search(r'Listed by[:\s]+([^<\n]{3,60})', content)
        data["listing_agent"] = agent_m.group(1).strip() if agent_m else None

        email_m = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', content)
        data["agent_email"] = email_m.group(0).lower() if email_m else None

        phone_m = re.search(r'(\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})', content)
        data["agent_phone"] = phone_m.group(1) if phone_m else None

        addr_m = re.search(r'"streetAddress":"([^"]+)"', content)
        data["address"] = addr_m.group(1) if addr_m else url

        price_m = re.search(r'"price":(\d+)', content)
        data["list_price"] = int(price_m.group(1)) if price_m else 0

        bed_m = re.search(r'(\d+)\s*bd', content)
        bath_m = re.search(r'(\d+\.?\d*)\s*ba', content)
        sqft_m = re.search(r'(\d+,?\d*)\s*sqft', content)
        year_m = re.search(r'Built in (\d{4})', content)

        data["beds"] = int(bed_m.group(1)) if bed_m else None
        data["baths"] = float(bath_m.group(1)) if bath_m else None
        data["sqft"] = int(sqft_m.group(1).replace(',', '')) if sqft_m else None
        data["year_built"] = int(year_m.group(1)) if year_m else None

        desc_m = re.search(r'"description":"([^"]{20,500})"', content)
        data["description"] = desc_m.group(1) if desc_m else None

        return data

    except Exception as e:
        log.error(f"Error parsing {url}: {e}")
        return {}


def screen_listing(listing: dict) -> bool:
    """Flip Man screening gates."""
    dom = listing.get("days_on_market", 0)
    vpd = listing.get("views_per_day", 999)

    if vpd >= MAX_VIEWS_DAY:
        log.info(f"FAIL Gate 2 (views/day {vpd} >= {MAX_VIEWS_DAY}): {listing.get('address')}")
        return False

    if dom < MIN_DOM:
        log.info(f"FAIL Gate 3 (DOM {dom} < {MIN_DOM}): {listing.get('address')}")
        return False

    score = 0
    if listing.get("has_price_cut"):  score += 3
    if listing.get("was_relisted"):   score += 2
    if dom >= 60:                     score += 2
    if dom >= 90:                     score += 3
    if vpd < 5:                       score += 2
    if vpd < 2:                       score += 2
    if listing.get("agent_email"):    score += 1

    listing["score"] = score
    log.info(
        f"PASS: {listing.get('address')} | "
        f"DOM: {dom} | VPD: {vpd} | Score: {score}"
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
            log.info(f"Portfolio rule: {email} has {len(agent_leads)} listings — keeping top 2")
            top2 = sorted(agent_leads, key=lambda x: x.get("score", 0), reverse=True)[:2]
            filtered.extend(top2)
        else:
            filtered.extend(agent_leads)

    return filtered + no_email


def scrape_market(market_key: str) -> list:
    market = MARKETS[market_key]
    city      = market["city"]
    state     = market["state"]
    min_price = market["min_price"]
    max_price = market["max_price"]

    log.info(f"Starting scrape: {city}, {state} | ${min_price:,}–${max_price:,}")
    leads = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--disable-plugins",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-features=TranslateUI",
                "--disable-ipc-flooding-protection",
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
            Object.defineProperty(navigator, 'permissions', {
                get: () => ({query: () => Promise.resolve({state: 'granted'})})
            });
        """)

        # Warm up — visit Google first to look like a real browser session
        try:
            page.goto("https://www.google.com", timeout=15000, wait_until="domcontentloaded")
            time.sleep(random.uniform(2, 4))
            log.info("Warm-up complete")
        except Exception:
            pass

        price_bands = [
            (min_price, 55000),
            (55001, 80000),
            (80001, max_price),
        ]

        captcha_count = 0

        for band_min, band_max in price_bands:
            if band_min > max_price:
                continue
            if captcha_count >= 2:
                log.warning("Too many CAPTCHAs — stopping scrape early")
                break

            band_max = min(band_max, max_price)
            log.info(f"Scraping band: ${band_min:,}–${band_max:,}")

            # Random delay between bands — looks human
            time.sleep(random.uniform(8, 15))

            for pg_num in range(1, 3):
                url = build_zillow_url(city, state, band_min, band_max, pg_num)
                log.info(f"URL: {url[:100]}...")

                try:
                    stealth_goto(page, url)

                    if is_captcha(page):
                        log.warning(f"CAPTCHA detected on band ${band_min:,}-${band_max:,}")
                        captcha_count += 1
                        # Wait longer before next attempt
                        time.sleep(random.uniform(20, 35))
                        break

                    content = page.content()
                    listing_paths = list(set(
                        re.findall(r'href="(/homedetails/[^"]+/\d+_zpid/)"', content)
                    ))
                    log.info(f"Band ${band_min:,}-${band_max:,} pg{pg_num}: {len(listing_paths)} listings found")

                    if not listing_paths:
                        break

                    for path in listing_paths[:8]:
                        full_url = f"https://www.zillow.com{path}"
                        detail   = parse_listing_detail(page, full_url)

                        if not detail:
                            continue

                        detail["market"] = market_key
                        detail["city"]   = city
                        detail["state"]  = state

                        if screen_listing(detail):
                            leads.append(detail)

                        # Human-like delay between listings
                        time.sleep(random.uniform(5, 12))

                    # Delay between pages
                    time.sleep(random.uniform(10, 20))

                except Exception as e:
                    log.error(f"Error on band ${band_min:,}-${band_max:,} pg{pg_num}: {e}")
                    continue

        browser.close()

    leads = apply_portfolio_rule(leads)
    log.info(f"Scrape complete: {city} | {len(leads)} leads passed all screening gates")
    return leads
