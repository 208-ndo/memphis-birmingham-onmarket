"""
scraper.py — Apify-powered Zillow scraper
Calls maxcopell/zillow-scraper via Apify API.
"""

import os
import time
import logging
import re
import json
from apify_client import ApifyClient
from config import DISTRESSED_KEYWORDS, MAX_VIEWS_DAY

logger = logging.getLogger(__name__)

APIFY_TOKEN = os.environ.get("APIFY_API_TOKEN")
ACTOR_ID    = "maxcopell/zillow-scraper"

MAX_RESULTS_PER_BAND = 100

PRICE_BANDS = [
    {"min": 30000,  "max": 55000},
    {"min": 55001,  "max": 80000},
    {"min": 80001,  "max": 150000},
    {"min": 150001, "max": 300000},
]


def build_zillow_url(city: str, state: str, price_min: int, price_max: int) -> str:
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


def get_all_text(listing: dict) -> str:
    """Grab every string field from listing and concat for keyword search."""
    parts = []
    for v in listing.values():
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    for sv in item.values():
                        if isinstance(sv, str):
                            parts.append(sv)
    return " ".join(parts).lower()


def is_distressed(listing: dict) -> bool:
    """Search ALL string fields in the listing for distressed keywords."""
    text = get_all_text(listing)
    matched = [kw for kw in DISTRESSED_KEYWORDS if kw.lower() in text]
    if matched:
        logger.debug(f"Distressed match: {matched} in {listing.get('address','?')}")
    return len(matched) > 0


def passes_views_gate(listing: dict) -> bool:
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

        # Agent fields — check multiple possible keys
        agent_name  = (listing.get("brokerName") or listing.get("agentName") or
                       listing.get("listing_agent") or "")
        agent_email = (listing.get("agentEmail") or listing.get("agent_email") or "")
        agent_phone = (listing.get("agentPhoneNumber") or listing.get("brokerPhoneNumber") or
                       listing.get("agentPhone") or "")

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
            "list_price":     int(price),
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
            "market":         market_key_from(market),
        }
    except Exception as e:
        logger.warning(f"Failed to extract lead: {e}")
        return None


def market_key_from(market: dict) -> str:
    return market.get("name", market.get("city", "unknown")).lower()


def scrape_market(market: dict) -> list[dict]:
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

            # LOG FIRST ITEM KEYS so we can see what Apify returns
            if items:
                first = items[0]
                logger.info(f"APIFY FIELD SAMPLE: {json.dumps({k: str(v)[:80] for k, v in first.items() if v}, indent=2)[:2000]}")

            band_leads = []
            for item in items:
                # Active listings only
                status = (item.get("homeStatus") or item.get("statusType") or "").upper()
                if status and status not in ("FOR_SALE", "ACTIVE", ""):
                    continue

                # Dedup within run
                zpid = str(item.get("zpid") or "")
                if zpid and zpid in seen_zpids:
                    continue
                if zpid:
                    seen_zpids.add(zpid)

                # Distressed filter — now searches ALL fields
                if not is_distressed(item):
                    logger.info(f"NO DISTRESSED MATCH: {item.get('address','?')} | keys: {list(item.keys())}")
                    continue

                # Views gate
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
    logger.info(f"Starting scrape: {market['city']}, {market['state']} | Source: Zillow via Apify")
    return scrape_market(market)
