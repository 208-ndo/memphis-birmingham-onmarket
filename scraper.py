"""
scraper.py — Apify-powered Zillow scraper
Replaces Playwright scraper. Calls maxcopell/zillow-scraper via Apify API.
Output format unchanged — same lead dicts fed into main.py pipeline.
"""

import os
import time
import logging
import re
from apify_client import ApifyClient
from config import MARKETS, DISTRESSED_KEYWORDS, MAX_VIEWS_DAY, OF_MIN_PRICE, OF_MAX_PRICE

logger = logging.getLogger(__name__)

APIFY_TOKEN = os.environ.get("APIFY_API_TOKEN")
ACTOR_ID    = "maxcopell/zillow-scraper"

MAX_RESULTS_PER_BAND = 100

# Price bands to scrape — matches OF and Cash Lowball ranges
PRICE_BANDS = [
    {"min": 30000,  "max": 55000},
    {"min": 55001,  "max": 80000},
    {"min": 80001,  "max": 150000},
    {"min": 150001, "max": 300000},
]


def build_zillow_url(city: str, state: str, price_min: int, price_max: int) -> str:
    """Build a Zillow for-sale search URL filtered by price band and agent-listed only."""
    city_slug   = city.lower().replace(" ", "-")
    state_lower = state.lower()
    return (
        f"https://www.zillow.com/homes/for_sale/"
        f"?searchQueryState=%7B%22isMapVisible%22%3Atrue%2C"
        f"%22filterState%22%3A%7B"
        f"%22price%22%3A%7B%22min%22%3A{price_min}%2C%22max%22%3A{price_max}%7D%2C"
        f"%22beds%22%3A%7B%22min%22%3A1%7D%2C"
        f"%22sqft%22%3A%7B%22min%22%3A750%7D%2C"
        f"%22isForSaleByAgent%22%3A%7B%22value%22%3Atrue%7D%2C"
        f"%22isForSaleByOwner%22%3A%7B%22value%22%3Afalse%7D%2C"
        f"%22isNewConstruction%22%3A%7B%22value%22%3Afalse%7D%2C"
        f"%22isAuction%22%3A%7B%22value%22%3Afalse%7D%2C"
        f"%22isMakeMeMove%22%3A%7B%22value%22%3Afalse%7D%7D%2C"
        f"%22isListVisible%22%3Atrue%2C"
        f"%22regionSelection%22%3A%5B%7B%22regionId%22%3A0%2C%22regionType%22%3A6%7D%5D%7D"
        f"&searchTerm={city_slug}%2C+{state_lower}"
    )


def is_distressed(listing: dict) -> bool:
    """Check listing text for distressed keywords."""
    text = " ".join([
        listing.get("description", "") or "",
        listing.get("statusText", "") or "",
        listing.get("brokerName", "") or "",
        listing.get("listingSubType", "") or "",
    ]).lower()
    return any(kw.lower() in text for kw in DISTRESSED_KEYWORDS)


def passes_views_gate(listing: dict) -> bool:
    """Skip listings with more than MAX_VIEWS_DAY views/day."""
    try:
        views = int(listing.get("pageViewCount") or listing.get("totalViews") or 0)
        days  = listing.get("daysOnZillow") or listing.get("timeOnZillow") or 1
        if isinstance(days, str):
            days = int(re.sub(r"[^\d]", "", days) or 1)
        days = max(int(days), 1)
        return (views / days) <= MAX_VIEWS_DAY
    except Exception:
        return True


def extract_lead(listing: dict, market: dict) -> dict | None:
    """Map Apify listing → pipeline lead dict. Returns None if required fields missing."""
    try:
        address  = listing.get("address") or listing.get("streetAddress") or ""
        city     = listing.get("city")    or market.get("city", "")
        state    = listing.get("state")   or market.get("state", "")
        zipcode  = listing.get("zipcode") or listing.get("zip", "")
        price    = listing.get("price")   or listing.get("unformattedPrice") or 0
        zpid     = str(listing.get("zpid") or "")

        url = listing.get("detailUrl") or listing.get("hdpUrl") or ""
        if url and not url.startswith("http"):
            url = "https://www.zillow.com" + url
        if not url and zpid:
            url = f"https://www.zillow.com/homedetails/{zpid}_zpid/"

        agent_name  = listing.get("brokerName")       or listing.get("agentName", "")
        agent_email = listing.get("agentEmail", "")
        agent_phone = listing.get("agentPhoneNumber") or listing.get("brokerPhoneNumber", "")

        days_on_market = listing.get("daysOnZillow") or listing.get("timeOnZillow") or 0
        if isinstance(days_on_market, str):
            days_on_market = int(re.sub(r"[^\d]", "", days_on_market) or 0)

        bedrooms  = listing.get("beds")  or listing.get("bedrooms", 0)
        bathrooms = listing.get("baths") or listing.get("bathrooms", 0)
        sqft      = listing.get("area")  or listing.get("livingArea", 0)

        photo_url = ""
        imgs = listing.get("imgSrc") or listing.get("images") or []
        if isinstance(imgs, str):
            photo_url = imgs
        elif isinstance(imgs, list) and imgs:
            photo_url = imgs[0]

        if not address or not price:
            return None

        return {
            "address":        address,
            "city":           city,
            "state":          state,
            "zip":            zipcode,
            "price":          int(price),
            "zpid":           zpid,
            "url":            url,
            "agent_name":     agent_name,
            "agent_email":    agent_email,
            "agent_phone":    agent_phone,
            "days_on_market": int(days_on_market),
            "bedrooms":       int(bedrooms),
            "bathrooms":      float(bathrooms),
            "sqft":           int(sqft),
            "photo_url":      photo_url,
            "market":         market.get("name", city),
        }
    except Exception as e:
        logger.warning(f"Failed to extract lead: {e}")
        return None


def scrape_market(market: dict) -> list[dict]:
    """Run Apify actor across all price bands for a market."""
    if not APIFY_TOKEN:
        logger.error("APIFY_API_TOKEN not set — cannot scrape")
        return []

    client     = ApifyClient(APIFY_TOKEN)
    city       = market["city"]
    state      = market["state"]
    leads      = []
    seen_zpids = set()

    for band in PRICE_BANDS:
        price_min  = band["min"]
        price_max  = band["max"]
        band_label = f"${price_min:,}-${price_max:,}"
        logger.info(f"Scraping band: {band_label}")

        search_url = build_zillow_url(city, state, price_min, price_max)
        logger.info(f"URL: {search_url[:120]}...")

        try:
            run_input = {
                "searchUrls": [{"url": search_url}],
                "maxItems":   MAX_RESULTS_PER_BAND,
            }
            run   = client.actor(ACTOR_ID).call(run_input=run_input, timeout_secs=180)
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            logger.info(f"Band {band_label}: {len(items)} raw results")

            band_leads = []
            for item in items:
                # Active listings only
                status = (item.get("homeStatus") or item.get("statusType") or "").upper()
                if status and status not in ("FOR_SALE", "ACTIVE", ""):
                    continue

                # Dedup within this run
                zpid = str(item.get("zpid") or "")
                if zpid and zpid in seen_zpids:
                    continue
                if zpid:
                    seen_zpids.add(zpid)

                # Distressed filter
                if not is_distressed(item):
                    continue

                # Views/day gate
                if not passes_views_gate(item):
                    continue

                lead = extract_lead(item, market)
                if lead:
                    band_leads.append(lead)

            logger.info(f"Band {band_label}: {len(band_leads)} leads passed screening")
            leads.extend(band_leads)
            time.sleep(5)

        except Exception as e:
            logger.error(f"Apify run failed for band {band_label}: {e}")
            continue

    logger.info(f"Scrape complete: {city} | {len(leads)} leads passed all screening gates")
    return leads


def scrape(market: dict) -> list[dict]:
    """Public entry point called by main.py — same signature as old scraper."""
    logger.info(f"Starting scrape: {market['city']}, {market['state']} | Source: Zillow via Apify")
    return scrape_market(market)
