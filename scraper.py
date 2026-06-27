"""
scraper.py — Apify Zillow scraper
Fixed: price parsing, distressed filter uses DOM + hdpData instead of keywords only
"""

import os
import time
import logging
import re
import json
import ast
from urllib.parse import quote
from apify_client import ApifyClient
from config import DISTRESSED_KEYWORDS, MAX_VIEWS_DAY

logger = logging.getLogger(__name__)

APIFY_TOKEN = os.environ.get("APIFY_API_TOKEN")
ACTOR_ID    = "maxcopell/zillow-scraper"

MAX_RESULTS_PER_BAND = 50  # Reduced to stay within free plan limits

PRICE_BANDS = [
    {"min": 30000,  "max": 55000},
    {"min": 55001,  "max": 80000},
    {"min": 80001,  "max": 150000},
    {"min": 150001, "max": 300000},
]

MARKET_BOUNDS = {
    "Memphis": {"west": -90.3, "east": -89.7, "south": 35.0, "north": 35.3},
    "Birmingham": {"west": -87.0, "east": -86.6, "south": 33.4, "north": 33.7},
}

MIN_DOM = 30  # Only want listings 30+ days on market


def parse_price(val) -> int:
    """Parse price whether it's int, float, or string like '$44,000'."""
    if not val:
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    cleaned = re.sub(r"[^\d]", "", str(val))
    return int(cleaned) if cleaned else 0


def parse_int(val) -> int:
    if not val:
        return 0
    if isinstance(val, int):
        return val
    cleaned = re.sub(r"[^\d]", "", str(val))
    return int(cleaned) if cleaned else 0


def build_zillow_url(city: str, price_min: int, price_max: int) -> str:
    bounds = MARKET_BOUNDS.get(city, MARKET_BOUNDS["Memphis"])
    state_obj = {
        "isMapVisible": True,
        "mapBounds": bounds,
        "filterState": {
            "price": {"min": price_min, "max": price_max},
            "beds":  {"min": 1},
            "sqft":  {"min": 750},
            "isForSaleByAgent":  {"value": True},
            "isForSaleByOwner":  {"value": False},
            "isNewConstruction": {"value": False},
            "isAuction":         {"value": False},
            "isMakeMeMove":      {"value": False},
            "doz":               {"value": "30"},
            "sort":              {"value": "days"},
        },
        "isListVisible": True,
    }
    encoded = quote(json.dumps(state_obj, separators=(",", ":")))
    return f"https://www.zillow.com/homes/for_sale/?searchQueryState={encoded}"


def get_dom(listing: dict) -> int:
    """Extract days on market from listing. Check multiple fields including hdpData."""
    # Direct fields first
    for key in ["daysOnZillow", "timeOnZillow", "days_on_zillow"]:
        val = listing.get(key)
        if val:
            return parse_int(val)

    # Try hdpData which is a nested dict serialized as string
    hdp_raw = listing.get("hdpData", "")
    if hdp_raw:
        try:
            hdp = ast.literal_eval(hdp_raw) if isinstance(hdp_raw, str) else hdp_raw
            home_info = hdp.get("homeInfo", {})
            for key in ["daysOnZillow", "timeOnZillow"]:
                val = home_info.get(key)
                if val:
                    return parse_int(val)
        except Exception:
            pass

    # Fall back to flexFieldText e.g. "22 hours ago", "3 days ago", "Listed 45 days ago"
    flex = listing.get("flexFieldText", "")
    if flex:
        m = re.search(r"(\d+)\s*day", flex, re.IGNORECASE)
        if m:
            return int(m.group(1))

    return 0


def get_all_text(listing: dict) -> str:
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
    """
    Primary filter: 30+ days on market (stale = motivated seller).
    Secondary: keyword check across all fields.
    Either condition passes the listing through.
    """
    dom = get_dom(listing)
    if dom >= MIN_DOM:
        return True

    # Also pass if distressed keyword found anywhere in the listing
    text = get_all_text(listing)
    return any(kw.lower() in text for kw in DISTRESSED_KEYWORDS)


def passes_views_gate(listing: dict) -> bool:
    try:
        views = int(listing.get("pageViewCount") or listing.get("totalViews") or 0)
        days  = max(get_dom(listing), 1)
        return (views / days) <= MAX_VIEWS_DAY
    except Exception:
        return True


def extract_lead(listing: dict, market: dict) -> dict | None:
    try:
        address  = listing.get("address") or listing.get("streetAddress") or ""
        city     = listing.get("addressCity") or listing.get("city") or market.get("city", "")
        state    = listing.get("addressState") or listing.get("state") or market.get("state", "")
        zipcode  = listing.get("addressZipcode") or listing.get("zipcode") or ""
        price    = parse_price(listing.get("unformattedPrice") or listing.get("price"))
        zpid     = str(listing.get("zpid") or "")

        url = listing.get("detailUrl") or listing.get("hdpUrl") or ""
        if url and not url.startswith("http"):
            url = "https://www.zillow.com" + url
        if not url and zpid:
            url = f"https://www.zillow.com/homedetails/{zpid}_zpid/"

        agent_name  = listing.get("brokerName") or listing.get("agentName") or ""
        agent_email = listing.get("agentEmail") or listing.get("agent_email") or ""
        agent_phone = (listing.get("agentPhoneNumber") or listing.get("brokerPhoneNumber") or
                       listing.get("agentPhone") or "")

        dom       = get_dom(listing)
        bedrooms  = parse_int(listing.get("beds") or listing.get("bedrooms"))
        bathrooms = float(parse_int(listing.get("baths") or listing.get("bathrooms")))
        sqft      = parse_int(listing.get("area") or listing.get("livingArea"))

        photo_url = listing.get("imgSrc") or ""
        if isinstance(photo_url, list):
            photo_url = photo_url[0] if photo_url else ""

        if not address or not price:
            return None

        return {
            "address":        address,
            "city":           city,
            "state":          state,
            "zip":            zipcode,
            "price":          price,
            "list_price":     price,
            "zpid":           zpid,
            "url":            url,
            "agent_name":     agent_name,
            "agent_email":    agent_email,
            "agent_phone":    agent_phone,
            "days_on_market": dom,
            "bedrooms":       bedrooms,
            "bathrooms":      bathrooms,
            "sqft":           sqft,
            "photo_url":      photo_url,
            "market":         market.get("city", "").lower(),
        }
    except Exception as e:
        logger.warning(f"Failed to extract lead: {e}")
        return None


def scrape_market(market: dict) -> list[dict]:
    if not APIFY_TOKEN:
        logger.error("APIFY_API_TOKEN not set — cannot scrape")
        return []

    client     = ApifyClient(APIFY_TOKEN)
    city       = market["city"]
    leads      = []
    seen_zpids = set()

    for band in PRICE_BANDS:
        price_min  = band["min"]
        price_max  = band["max"]
        band_label = f"${price_min:,}-${price_max:,}"
        logger.info(f"Scraping band: {band_label}")

        search_url = build_zillow_url(city, price_min, price_max)
        logger.info(f"URL: {search_url[:150]}...")

        try:
            run_input = {
                "searchUrls": [{"url": search_url}],
                "maxItems":   MAX_RESULTS_PER_BAND,
            }
            run   = client.actor(ACTOR_ID).call(run_input=run_input, timeout_secs=180)
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            logger.info(f"Band {band_label}: {len(items)} raw results")

            real_items = [i for i in items if "error" not in i]
            if not real_items:
                if items:
                    logger.warning(f"Result: {items[0]}")
                continue

            band_leads = []
            for item in real_items:
                # Active only
                status = (item.get("statusType") or item.get("rawHomeStatusCd") or "").upper()
                if status and status not in ("FOR_SALE", "FORSALE", "ACTIVE", ""):
                    continue

                # Dedup
                zpid = str(item.get("zpid") or "")
                if zpid and zpid in seen_zpids:
                    continue
                if zpid:
                    seen_zpids.add(zpid)

                # DOM or distressed keyword filter
                if not is_distressed(item):
                    continue

                # Views gate
                if not passes_views_gate(item):
                    continue

                lead = extract_lead(item, market)
                if lead:
                    dom = lead.get("days_on_market", 0)
                    logger.info(f"LEAD: {lead['address']} | ${lead['price']:,} | DOM: {dom} | Agent: {lead['agent_name']} | Email: {lead['agent_email'] or 'NONE'}")
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
