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


def build_zillow_url(city, state, min_price, max_price, page=1):
    city_slug = city.lower().replace(" ", "-")
    return (
        f"https://www.zillow.com/{city_slug}-{state.lower()}/"
        f"?searchQueryState={{\"pagination\":{{\"currentPage\":{page}}},"
        f"\"filterState\":{{\"price\":{{\"min\":{min_price},\"max\":{max_price}}},"
        f"\"doz\":{{\"value\":\"30d\"}},"
        f"\"sort\":{{\"value\":\"days\"}}}}}}"
    )


def parse_listing_detail(pw_page, url):
    try:
        pw_page.goto(url, timeout=30000)
        time.sleep(random.uniform(2, 4))
        content = pw_page.content()
        data = {"url": url, "scraped_at": datetime.now().isoformat()}

        dom_m = re.search(r'(\d+) days on Zillow', content)
        data["days_on_market"] = int(dom_m.group(1)) if dom_m else 0

        views_m = re.search(r'(\d+,?\d*) views', content)
        data["total_views"] = int(views_m.group(1).replace(',', '')) if views_m else 0
        data["views_per_day"] = round(data["total_views"] / max(data["days_on_market"], 1), 2)

        price_cut_m = re.search(r'Price cut', content, re.IGNORECASE)
        data["has_price_cut"] = price_cut_m is not None

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
        data["beds"] = int(bed_m.group(1)) if bed_m else None
        data["baths"] = float(bath_m.group(1)) if bath_m else None
        data["sqft"] = int(sqft_m.group(1).replace(',', '')) if sqft_m else None

        return data
    except Exception as e:
        log.error(f"Error parsing {url}: {e}")
        return {}


def screen_listing(listing):
    dom = listing.get("days_on_market", 0)
    vpd = listing.get("views_per_day", 999)
    if dom < SCREEN["min_dom"]:
        return False
    if vpd > SCREEN["max_views_per_day"]:
        return False
    score = 0
    if listing.get("has_price_cut"):
        score += 3
    if dom > 60:
        score += 2
    if dom > 90:
        score += 3
    if vpd < 2:
        score += 2
    if listing.get("agent_email"):
        score += 1  # Bonus: we have a direct email
    listing["score"] = score
    return True


def apply_portfolio_rule(leads):
    """If same agent has 3+ listings, keep only top 2 by score (portfolio seller rule)."""
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


def scrape_market(market_key):
    market = MARKETS[market_key]
    city, state = market["city"], market["state"]
    min_price, max_price = market["min_price"], market["max_price"]
    log.info(f"Scraping {city}, {state}")
    leads = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"]
        )
        ctx = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1366, "height": 768},
            locale="en-US"
        )
        page = ctx.new_page()

        for pg_num in range(1, 4):
            url = build_zillow_url(city, state, min_price, max_price, pg_num)
            try:
                page.goto(url, timeout=45000)
                time.sleep(random.uniform(3, 6))
                if "captcha" in page.url.lower():
                    log.warning("CAPTCHA hit — stopping")
                    break
                content = page.content()
                listing_paths = list(set(re.findall(r'href="(/homedetails/[^"]+/\d+_zpid/)"', content)))
                log.info(f"Page {pg_num}: {len(listing_paths)} listings found")

                for path in listing_paths[:10]:
                    detail = parse_listing_detail(page, f"https://www.zillow.com{path}")
                    if not detail:
                        continue
                    detail["market"] = market_key
                    detail["city"] = city
                    detail["state"] = state
                    if screen_listing(detail):
                        leads.append(detail)
                    time.sleep(random.uniform(4, 8))

                time.sleep(random.uniform(5, 10))
            except Exception as e:
                log.error(f"Page {pg_num} error: {e}")

        browser.close()

    leads = apply_portfolio_rule(leads)
    log.info(f"{city}: {len(leads)} leads after screening + portfolio rule")
    return leads
