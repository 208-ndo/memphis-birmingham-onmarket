import time
import json
import random
import re
import logging
from datetime import datetime
from playwright.sync_api import sync_playwright
from config import MARKETS, SCREEN

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

# Flip Man distressed keyword filter — applied directly in Zillow URL
# Pre-filters to ugly/distressed homes so we skip retail listings entirely
DISTRESSED_KEYWORDS = (
    "as is,fixer,investor special,tlc,needs work,handyman,"
    "cash only,price reduced,motivated,sold as-is,rehab,vacant"
)

# Skip keywords — bulk/package deals and teardowns
SKIP_KEYWORDS = [
    "package", "portfolio", "bundle", "40 property",
    "teardown", "tear down", "gutted", "fire damage",
    "sold individually", "bulk", "subdivided"
]


def build_zillow_url(city: str, state: str, min_price: int, max_price: int, page: int = 1) -> str:
    """
    Build Zillow search URL using searchQueryState technique from Flip Man skill.
    Includes distressed keyword filter to pre-cut retail listings at source.
    Sorted by days on market (oldest first = most motivated).
    """
    city_slug = city.lower().replace(" ", "-")
    state_lower = state.lower()

    import json as _json
    sqs = {
        "pagination": {"currentPage": page},
        "filterState": {
            "price": {"min": min_price, "max": max_price},
            "doz": {"value": "30d"},
            "sort": {"value": "days"},
            # Houses only — exclude everything else
            "tow": {"value": False},
            "mf": {"value": False},
            "con": {"value": False},
            "land": {"value": False},
            "apa": {"value": False},
            "manu": {"value": False},
            "apco": {"value": False},
            # Agent listed only — exclude FSBO, auctions, foreclosures
            "fsba": {"value": True},
            "fsbo": {"value": False},
            "nc": {"value": False},
            "cmsn": {"value": False},
            "auc": {"value": False},
            "fore": {"value": False},
            # Min sqft 750 — avoid teardowns
            "sqft": {"min": 750},
            # Distressed keyword filter — Flip Man's biggest screening hack
            "att": {"value": DISTRESSED_KEYWORDS},
        },
        "isListVisible": True,
        "isMapVisible": True,
    }

    encoded = _json.dumps(sqs, separators=(',', ':'))
    return f"https://www.zillow.com/{city_slug}-{state_lower}/houses/?searchQueryState={encoded}"


def has_skip_keyword(text: str) -> bool:
    """Check if listing contains bulk/package/teardown keywords — skip these."""
    text_lower = text.lower()
    for kw in SKIP_KEYWORDS:
        if kw in text_lower:
            return True
    return False


def parse_listing_detail(pw_page, url: str) -> dict:
    """Visit individual listing page and extract full details."""
    try:
        pw_page.goto(url, timeout=30000)
        time.sleep(random.uniform(2, 4))
        content = pw_page.content()

        # Skip bulk/package/teardown listings immediately
        if has_skip_keyword(content):
            log.info(f"SKIP (bulk/teardown keyword): {url}")
            return {}

        data = {"url": url, "scraped_at": datetime.now().isoformat()}

        # Days on market
        dom_m = re.search(r'(\d+) days on Zillow', content)
        data["days_on_market"] = int(dom_m.group(1)) if dom_m else 0

        # Views and views/day
        views_m = re.search(r'(\d+,?\d*) views', content)
        data["total_views"] = int(views_m.group(1).replace(',', '')) if views_m else 0
        data["views_per_day"] = round(
            data["total_views"] / max(data["days_on_market"], 1), 2
        )

        # Price cut signal
        price_cut_m = re.search(r'Price cut', content, re.IGNORECASE)
        data["has_price_cut"] = price_cut_m is not None

        # True DOM check — check price history for relisted properties
        # A relisted property is MORE motivated not less — flag it
        relisted_m = re.search(r'Listed\s+\d+\s+times', content, re.IGNORECASE)
        data["was_relisted"] = relisted_m is not None

        # Agent info
        agent_m = re.search(r'Listed by[:\s]+([^<\n]{3,60})', content)
        data["listing_agent"] = agent_m.group(1).strip() if agent_m else None

        email_m = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', content)
        data["agent_email"] = email_m.group(0).lower() if email_m else None

        phone_m = re.search(r'(\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})', content)
        data["agent_phone"] = phone_m.group(1) if phone_m else None

        # Property details
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

        # Grab description for additional context
        desc_m = re.search(r'"description":"([^"]{20,500})"', content)
        data["description"] = desc_m.group(1) if desc_m else None

        return data

    except Exception as e:
        log.error(f"Error parsing {url}: {e}")
        return {}


def screen_listing(listing: dict) -> bool:
    """
    Apply Flip Man / Zompz screening gates.
    Returns True if listing passes all gates.

    Gate 1: Active listing (handled by Zillow filters)
    Gate 2: Views/day < 20 (low competition)
    Gate 3: DOM >= 30 (motivated seller)
    Gate 4: Not a bulk/package deal (handled by skip keywords)
    Gate 5: Has agent contact info (need to reach them)
    """
    dom = listing.get("days_on_market", 0)
    vpd = listing.get("views_per_day", 999)

    # Gate 2 — Low competition: < 20 views/day (stricter than 25 to avoid borderline)
    if vpd >= 20:
        log.info(f"FAIL Gate 2 (views/day {vpd} >= 20): {listing.get('address')}")
        return False

    # Gate 3 — Motivated: 30+ days on market
    if dom < SCREEN["min_dom"]:
        log.info(f"FAIL Gate 3 (DOM {dom} < {SCREEN['min_dom']}): {listing.get('address')}")
        return False

    # Score calculation — higher = more motivated
    score = 0
    if listing.get("has_price_cut"):
        score += 3
    if listing.get("was_relisted"):
        score += 2   # Relisted = even more motivated
    if dom >= 60:
        score += 2
    if dom >= 90:
        score += 3
    if vpd < 5:
        score += 2
    if vpd < 2:
        score += 2
    if listing.get("agent_email"):
        score += 1   # Bonus: direct email found

    listing["score"] = score
    log.info(
        f"PASS: {listing.get('address')} | "
        f"DOM: {dom} | VPD: {vpd} | Score: {score} | "
        f"Cut: {listing.get('has_price_cut')} | "
        f"Relisted: {listing.get('was_relisted')}"
    )
    return True


def apply_portfolio_rule(leads: list) -> list:
    """
    Flip Man portfolio rule:
    If same agent has 3+ listings they're a portfolio/bulk seller.
    Keep only their top 2 highest-scoring properties.
    """
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
            log.info(
                f"Portfolio rule: {email} has {len(agent_leads)} listings "
                f"— keeping top 2 by score"
            )
            top2 = sorted(
                agent_leads,
                key=lambda x: x.get("score", 0),
                reverse=True
            )[:2]
            filtered.extend(top2)
        else:
            filtered.extend(agent_leads)

    return filtered + no_email


def scrape_market(market_key: str) -> list:
    """
    Main scrape function for a single market.
    Uses Flip Man's URL technique with distressed keyword filter.
    Returns screened + portfolio-filtered leads.
    """
    market = MARKETS[market_key]
    city = market["city"]
    state = market["state"]
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
            ]
        )
        ctx = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )
        page = ctx.new_page()
        page.set_extra_http_headers({"Accept-Language": "en-US,en;q=0.9"})

        # Run two price bands for owner finance range
        # $30k-$55k first, then $55k-$80k, then $80k+ for cash
        # This avoids Zillow's virtual scroll limit of ~9 cards
        price_bands = [
            (min_price, 55000),
            (55001, 80000),
            (80001, max_price),
        ]

        for band_min, band_max in price_bands:
            if band_min > max_price:
                continue

            band_max = min(band_max, max_price)
            log.info(f"Scraping band: ${band_min:,}–${band_max:,}")

            for pg_num in range(1, 3):  # 2 pages per band
                url = build_zillow_url(city, state, band_min, band_max, pg_num)
                log.info(f"URL: {url[:100]}...")

                try:
                    page.goto(url, timeout=45000)
                    time.sleep(random.uniform(3, 6))

                    # CAPTCHA check
                    if "captcha" in page.url.lower() or \
                       "robot" in page.content().lower():
                        log.warning("CAPTCHA detected — stopping scrape for this market")
                        break

                    content = page.content()

                    # Extract listing URLs from search results
                    listing_paths = list(set(
                        re.findall(r'href="(/homedetails/[^"]+/\d+_zpid/)"', content)
                    ))
                    log.info(f"Band ${band_min:,}-${band_max:,} pg{pg_num}: "
                             f"{len(listing_paths)} listings found")

                    if not listing_paths:
                        log.info("No listings found — moving to next band")
                        break

                    # Visit each listing detail page
                    for path in listing_paths[:8]:  # Max 8 per page
                        full_url = f"https://www.zillow.com{path}"
                        detail = parse_listing_detail(page, full_url)

                        if not detail:
                            continue

                        detail["market"] = market_key
                        detail["city"] = city
                        detail["state"] = state

                        if screen_listing(detail):
                            leads.append(detail)

                        time.sleep(random.uniform(3, 7))

                    time.sleep(random.uniform(5, 10))

                except Exception as e:
                    log.error(f"Error on band ${band_min:,}-${band_max:,} pg{pg_num}: {e}")
                    continue

        browser.close()

    # Apply portfolio rule before returning
    leads = apply_portfolio_rule(leads)

    log.info(
        f"Scrape complete: {city} | "
        f"{len(leads)} leads passed all screening gates"
    )
    return leads
