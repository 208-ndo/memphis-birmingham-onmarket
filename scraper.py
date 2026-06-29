"""
scraper.py — Apify Zillow scraper + Google email enrichment
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
from agent_email_finder import enrich_leads_with_emails

logger = logging.getLogger(__name__)

APIFY_TOKEN = os.environ.get("APIFY_API_TOKEN")
ACTOR_ID    = "maxcopell/zillow-scraper"

MAX_RESULTS_OF_BAND = 200  # sub-$80k owner-finance bands — deeper fetch for stale leads
MAX_RESULTS_CL_BAND = 50   # $80k+ cash bands — no ARV available, no auto-send benefit
MIN_DOM = 30

# Owner-finance price ceiling — below this, dom-unknown leads get OF fallback
OF_PRICE_CEILING = 80000

PRICE_BANDS = [
    {"min": 30000,  "max": 55000},
    {"min": 55001,  "max": 80000},
    {"min": 80001,  "max": 150000},
    {"min": 150001, "max": 300000},
]

MARKET_BOUNDS = {
    "Memphis":    {"west": -90.3, "east": -89.7, "south": 35.0, "north": 35.3},
    "Birmingham": {"west": -87.0, "east": -86.6, "south": 33.4, "north": 33.7},
}


def parse_price(val) -> int:
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


def get_dom(listing: dict):
    """
    Return DOM as int if found, or None if the field is missing/unreliable.
    Returns 0 if listing appears to be newly listed (hours).
    Never returns a millisecond timestamp (> 10000 is rejected).
    """
    for key in ["daysOnZillow", "timeOnZillow", "days_on_zillow"]:
        val = listing.get(key)
        if val and isinstance(val, int) and val < 10000:
            return val

    hdp_raw = listing.get("hdpData", "")
    if hdp_raw:
        try:
            hdp = ast.literal_eval(hdp_raw) if isinstance(hdp_raw, str) else hdp_raw
            home_info = hdp.get("homeInfo", {})
            for key in ["daysOnZillow", "timeOnZillow"]:
                val = home_info.get(key)
                if val and isinstance(val, (int, float)) and val < 10000:
                    return int(val)
        except Exception:
            pass

    flex = str(listing.get("flexFieldText", ""))
    day_match = re.search(r"(\d+)\s*day", flex, re.IGNORECASE)
    if day_match:
        return int(day_match.group(1))
    if re.search(r"\d+\s*hour", flex, re.IGNORECASE):
        return 0

    return None  # explicitly missing — caller decides how to handle


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


def has_distress_keyword(listing: dict) -> bool:
    text = get_all_text(listing)
    return any(kw.lower() in text for kw in DISTRESSED_KEYWORDS)


def screen_listing(item: dict, band_min: int, band_max: int) -> tuple[bool, str]:
    """
    Evaluate a raw Zillow item and return (passes: bool, reason: str).

    Reason codes:
      passed_by_dom               — DOM >= 30 confirmed
      passed_by_keyword           — distressed keyword found
      passed_by_low_price_of_dom_unknown_fallback — OF band, DOM unknown, URL already filtered
      reject_dom_missing_no_keyword — DOM unknown, no keyword, not in OF band
      reject_dom_too_low          — DOM known but < 30
      reject_dom_zero_fresh       — DOM=0 (newly listed)
      reject_views_too_high       — views/day > MAX_VIEWS_DAY
    """
    dom = get_dom(item)

    # DOM known and >= 30 — definitively passes
    if dom is not None and dom >= MIN_DOM:
        return True, "passed_by_dom"

    # DOM known and too low — definitively reject
    if dom is not None and dom == 0:
        return False, "reject_dom_zero_fresh"

    if dom is not None and dom < MIN_DOM:
        return False, "reject_dom_too_low"

    # DOM is None (missing from Apify) — check keyword first
    if has_distress_keyword(item):
        return True, "passed_by_keyword"

    # DOM missing, no keyword — apply OF fallback only for sub-$80k price band
    price = parse_price(item.get("unformattedPrice") or item.get("price"))
    if price and band_min >= 30000 and band_max <= OF_PRICE_CEILING:
        # Safe: Zillow URL already applied doz=30 filter before Apify ran.
        # offer.py routes sub-$80k to owner_finance — no ARV needed.
        return True, "passed_by_low_price_of_dom_unknown_fallback"

    return False, "reject_dom_missing_no_keyword"


def passes_views_gate(listing: dict) -> bool:
    try:
        views = int(listing.get("pageViewCount") or listing.get("totalViews") or 0)
        dom   = get_dom(listing)
        days  = max(dom if dom is not None else 30, 1)
        return (views / days) <= MAX_VIEWS_DAY
    except Exception:
        return True


def extract_lead(listing: dict, market: dict, candidate_reason: str = "") -> dict | None:
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
        agent_phone = listing.get("agentPhoneNumber") or listing.get("brokerPhoneNumber") or ""

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
            "address":          address,
            "city":             city,
            "state":            state,
            "zip":              zipcode,
            "price":            price,
            "list_price":       price,
            "zpid":             zpid,
            "url":              url,
            "agent_name":       agent_name,
            "agent_email":      agent_email,
            "agent_phone":      agent_phone,
            "brokerName":       agent_name,
            "days_on_market":   dom if dom is not None else -1,
            "bedrooms":         bedrooms,
            "bathrooms":        bathrooms,
            "sqft":             sqft,
            "photo_url":        photo_url,
            "market":           market.get("city", "").lower(),
            "candidate_reason": candidate_reason,
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
        logger.info(f"URL: {search_url[:120]}...")

        try:
            max_results = MAX_RESULTS_OF_BAND if price_max <= 80000 else MAX_RESULTS_CL_BAND
            logger.info(f"Band {band_label}: maxResults={max_results}")
            run   = client.actor(ACTOR_ID).call(
                run_input={"searchUrls": [{"url": search_url}], "maxResults": max_results},
                timeout_secs=180
            )
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            logger.info(f"Band {band_label}: {len(items)} raw results")

            real_items = [i for i in items if "error" not in i]
            if not real_items:
                if items:
                    logger.warning(f"Result: {items[0]}")
                continue

            # ── Per-band rejection diagnostics ─────────────────────────────
            reason_counts: dict[str, int] = {}
            band_leads = []

            for item in real_items:
                status = (item.get("statusType") or item.get("rawHomeStatusCd") or "").upper()
                if status and status not in ("FOR_SALE", "FORSALE", "ACTIVE", ""):
                    reason_counts["reject_wrong_status"] = reason_counts.get("reject_wrong_status", 0) + 1
                    continue

                zpid = str(item.get("zpid") or "")
                if zpid and zpid in seen_zpids:
                    reason_counts["reject_duplicate_zpid"] = reason_counts.get("reject_duplicate_zpid", 0) + 1
                    continue
                if zpid:
                    seen_zpids.add(zpid)

                passes, reason = screen_listing(item, price_min, price_max)
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

                if not passes:
                    continue

                if not passes_views_gate(item):
                    reason_counts["reject_views_too_high"] = reason_counts.get("reject_views_too_high", 0) + 1
                    continue

                lead = extract_lead(item, market, candidate_reason=reason)
                if lead:
                    band_leads.append(lead)
                else:
                    reason_counts["reject_missing_address_or_price"] = reason_counts.get("reject_missing_address_or_price", 0) + 1

            # Log diagnostics
            reason_str = " | ".join(f"{k}={v}" for k, v in sorted(reason_counts.items()))
            logger.info(
                f"Band {band_label}: raw={len(real_items)} | candidates={len(band_leads)} | "
                f"reasons: {reason_str}"
            )

            leads.extend(band_leads)
            time.sleep(5)

        except Exception as e:
            logger.error(f"Apify run failed for band {band_label}: {e}")
            continue

    # Enrich ALL leads with emails via Google search
    if leads:
        logger.info(f"Starting email enrichment for {len(leads)} leads...")
        leads = enrich_leads_with_emails(leads, market, client)

    for lead in leads:
        dom_display = lead["days_on_market"] if lead["days_on_market"] >= 0 else "unknown"
        logger.info(
            f"LEAD: {lead['address']} | ${lead['price']:,} | "
            f"DOM: {dom_display} | "
            f"reason: {lead.get('candidate_reason', '')} | "
            f"Agent: {lead['agent_name']} | "
            f"Email: {lead.get('agent_email') or 'NONE'}"
        )

    logger.info(f"Scrape complete: {city} | {len(leads)} leads passed all screening gates")
    return leads


def scrape(market: dict) -> list[dict]:
    logger.info(f"Starting scrape: {market['city']}, {market['state']} | Source: Zillow via Apify")
    return scrape_market(market)
