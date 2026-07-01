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
try:
    from apify_client import ApifyClient
except ModuleNotFoundError:
    ApifyClient = None
from config import (
    DISTRESSED_KEYWORDS, MAX_VIEWS_DAY, MAX_APIFY_RUNS_PER_WORKFLOW,
    ENABLE_PRICE_REDUCED_OF_VARIANT, MAX_EMAIL_ENRICHMENT_CALLS_PER_WORKFLOW,
    MAX_LEADS_TO_ENRICH_PER_WORKFLOW,
)
try:
    from agent_email_finder import enrich_leads_with_emails
except ModuleNotFoundError:
    enrich_leads_with_emails = None

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

# Fallback bounds used only if a market dict doesn't define its own "bounds".
# Little Rock + Oklahoma City added for Phase 2; market["bounds"] in config.py
# takes precedence over these when present.
MARKET_BOUNDS = {
    "Memphis":       {"west": -90.3, "east": -89.7, "south": 35.0, "north": 35.3},
    "Birmingham":    {"west": -87.0, "east": -86.6, "south": 33.4, "north": 33.7},
    "Little Rock":   {"west": -92.5, "east": -92.1, "south": 34.6, "north": 34.85},
    "Oklahoma City": {"west": -97.7, "east": -97.3, "south": 35.35, "north": 35.65},
    "Cleveland":     {"west": -81.95, "east": -81.45, "south": 41.35, "north": 41.65},
    "Akron":         {"west": -81.65, "east": -81.35, "south": 40.95, "north": 41.2},
}

# ── Shared Apify Budget (covers ALL Apify actors: Zillow + Google email) ─────
# Module-level counters, shared across all scrape_market() calls within the
# same process (one pipeline run = one process, per market sequentially).
# MAX_APIFY_RUNS_PER_WORKFLOW is a HARD CEILING across every actor call —
# Zillow scraper AND Google email search both draw from this same budget.
# MAX_EMAIL_ENRICHMENT_CALLS_PER_WORKFLOW is an additional, lower sub-cap
# applied only to Google email enrichment calls.
_apify_call_count             = 0  # total across ALL actors (Zillow + Google + any future actor)
_zillow_call_count            = 0  # subset of the above, Zillow actor only
_email_enrichment_call_count  = 0  # subset of the above, Google actor only


class ApifyQuotaError(RuntimeError):
    """Raised when Apify rejects a run due to monthly quota or hard limit."""


def is_apify_quota_error(exc: Exception) -> bool:
    text_parts = [str(exc), repr(exc)]
    for attr in ("message", "status_code", "status", "code"):
        value = getattr(exc, attr, None)
        if value is not None:
            text_parts.append(str(value))
    text = " ".join(text_parts).lower()

    quota_phrases = (
        "monthly usage hard limit exceeded",
        "usage hard limit exceeded",
        "quota exceeded",
    )
    if any(phrase in text for phrase in quota_phrases):
        return True

    return "403" in text and ("hard limit" in text or "quota" in text)


def can_make_apify_call() -> bool:
    """True if any actor (Zillow or otherwise) may still be called this workflow."""
    return _apify_call_count < MAX_APIFY_RUNS_PER_WORKFLOW


def register_zillow_call() -> int:
    """Record one Zillow actor call against the shared budget. Returns new shared total."""
    global _apify_call_count, _zillow_call_count
    _apify_call_count  += 1
    _zillow_call_count += 1
    return _apify_call_count


def register_apify_call() -> int:
    """Generic alias retained for any other future actor that isn't Zillow or Google."""
    global _apify_call_count
    _apify_call_count += 1
    return _apify_call_count


def can_make_email_enrichment_call() -> bool:
    """
    True only if BOTH the shared total budget AND the email-specific sub-cap
    still have room. Checked before every Google email actor call.
    """
    if _apify_call_count >= MAX_APIFY_RUNS_PER_WORKFLOW:
        return False
    if _email_enrichment_call_count >= MAX_EMAIL_ENRICHMENT_CALLS_PER_WORKFLOW:
        return False
    return True


def register_email_enrichment_call() -> tuple:
    """Record one Google email actor call against both the shared and email counters."""
    global _apify_call_count, _email_enrichment_call_count
    _apify_call_count            += 1
    _email_enrichment_call_count += 1
    return _apify_call_count, _email_enrichment_call_count


def get_apify_budget_status() -> dict:
    return {
        "total_calls_used":  _apify_call_count,
        "total_calls_max":   MAX_APIFY_RUNS_PER_WORKFLOW,
        "zillow_calls_used": _zillow_call_count,
        "google_calls_used": _email_enrichment_call_count,
        "google_calls_max":  MAX_EMAIL_ENRICHMENT_CALLS_PER_WORKFLOW,
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


def resolve_bounds(market: dict) -> dict:
    """
    Bounds resolution order:
      1. market["bounds"] from config.py, if present
      2. MARKET_BOUNDS[market["city"]] fallback
      3. MARKET_BOUNDS["Memphis"] as last resort
    """
    if market.get("bounds"):
        return market["bounds"]
    city = market.get("city", "")
    return MARKET_BOUNDS.get(city, MARKET_BOUNDS["Memphis"])


def build_zillow_url(market: dict, price_min: int, price_max: int,
                     price_reduced: bool = False) -> str:
    """
    Build a Zillow search URL for a given market, price band, and optional
    price-reduced variant.

    NOTE: doz (days-on-Zillow) is intentionally OMITTED.
    doz=30 means "listed in the last 30 days" — the opposite of our goal.
    We want stale DOM>=30 inventory. screen_listing() enforces DOM>=30 in
    Python after Apify returns results, so no pre-filter is needed here.
    """
    bounds = resolve_bounds(market)
    filter_state = {
        "price": {"min": price_min, "max": price_max},
        "beds":  {"min": 1},
        "sqft":  {"min": 750},
        "isForSaleByAgent":  {"value": True},
        "isForSaleByOwner":  {"value": False},
        "isNewConstruction": {"value": False},
        "isAuction":         {"value": False},
        "isMakeMeMove":      {"value": False},
        "sort":              {"value": "days"},
    }
    if price_reduced:
        # Adds isReducedPrice filter — surfaces listings with at least one price cut.
        # Only used when ENABLE_PRICE_REDUCED_OF_VARIANT=True in config.py.
        filter_state["isReducedPrice"] = {"value": True}

    state_obj = {
        "isMapVisible":  True,
        "mapBounds":     bounds,
        "filterState":   filter_state,
        "isListVisible": True,
    }
    encoded = quote(json.dumps(state_obj, separators=(",", ":")))
    return f"https://www.zillow.com/homes/for_sale/?searchQueryState={encoded}"


def get_market_price_bands(market: dict) -> list[dict]:
    """Return global price bands clipped to a market's configured min/max."""
    market_min = parse_price(market.get("min_price") or market.get("price_min")) or PRICE_BANDS[0]["min"]
    market_max = parse_price(market.get("max_price") or market.get("price_max")) or PRICE_BANDS[-1]["max"]
    bands = []
    for band in PRICE_BANDS:
        band_min = max(band["min"], market_min)
        band_max = min(band["max"], market_max)
        if band_min <= band_max:
            bands.append({"min": band_min, "max": band_max})
    return bands


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


def get_all_visible_text(listing: dict) -> str:
    parts = []

    def collect(value):
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)

    collect(listing)
    return " ".join(parts)


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}")


def clean_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return (value or "").strip()


def parse_listed_by_text(text: str) -> dict:
    """
    Extract only contact details visibly present in Zillow-style Listed By text.
    This never guesses an email from a name or brokerage domain.
    """
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return {}
    listed_by_match = re.search(r"(?i)\blisted\s+by\s*:?", text)
    if listed_by_match:
        text = text[listed_by_match.start():]

    email_match = EMAIL_RE.search(text)
    phone_match = PHONE_RE.search(text)
    email = email_match.group(0) if email_match else ""
    phone = clean_phone(phone_match.group(0)) if phone_match else ""

    agent_name = ""
    brokerage_name = ""
    before_contact = text
    contact_positions = [m.start() for m in (email_match, phone_match) if m]
    if contact_positions:
        before_contact = text[:min(contact_positions)]
    before_contact = re.sub(r"(?i)\blisted\s+by\s*:?", "", before_contact).strip(" ,.-")
    if before_contact:
        agent_name = before_contact

    if email_match:
        after_email = text[email_match.end():].strip(" ,.-")
        if after_email:
            brokerage_name = after_email.split(". ")[0].strip(" ,.-")

    return {
        "agent_name": agent_name,
        "agent_email": email,
        "agent_phone": phone,
        "brokerage_name": brokerage_name,
    }


def get_nested_value(data: dict, *keys):
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return current or ""


def extract_contact_info(listing: dict) -> dict:
    visible = get_all_visible_text(listing)
    parsed = parse_listed_by_text(visible)
    agent_name = (
        listing.get("agentName")
        or listing.get("listingAgentName")
        or get_nested_value(listing, "attributionInfo", "agentName")
        or parsed.get("agent_name")
        or ""
    )
    brokerage_name = (
        listing.get("brokerName")
        or listing.get("brokerageName")
        or get_nested_value(listing, "attributionInfo", "brokerName")
        or parsed.get("brokerage_name")
        or ""
    )
    agent_email = (
        listing.get("agentEmail")
        or listing.get("agent_email")
        or get_nested_value(listing, "attributionInfo", "agentEmail")
        or get_nested_value(listing, "attributionInfo", "email")
        or parsed.get("agent_email")
        or ""
    )
    agent_phone = (
        listing.get("agentPhoneNumber")
        or listing.get("agent_phone")
        or get_nested_value(listing, "attributionInfo", "agentPhoneNumber")
        or get_nested_value(listing, "attributionInfo", "phoneNumber")
        or parsed.get("agent_phone")
        or listing.get("brokerPhoneNumber")
        or ""
    )
    return {
        "agent_name": agent_name,
        "brokerage_name": brokerage_name,
        "agent_email": agent_email,
        "agent_phone": clean_phone(agent_phone),
    }


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


def compute_views_per_day(listing: dict):
    """Return views/day as float, or None if it can't be computed."""
    try:
        views = int(listing.get("pageViewCount") or listing.get("totalViews") or 0)
        dom   = get_dom(listing)
        days  = max(dom if dom is not None else 30, 1)
        return views / days
    except Exception:
        return None


def passes_views_gate(listing: dict) -> bool:
    vpd = compute_views_per_day(listing)
    if vpd is None:
        return True
    return vpd <= MAX_VIEWS_DAY


def get_photo_count(listing: dict):
    """
    Best-effort photo count from common Apify zillow-scraper fields.
    Returns None if no photo data is present (treated as neutral in scoring).
    """
    for key in ["photoCount", "photo_count", "numPhotos"]:
        val = listing.get(key)
        if isinstance(val, (int, float)) and val >= 0:
            return int(val)

    for key in ["photos", "carouselPhotos", "responsivePhotos", "imgSrc"]:
        val = listing.get(key)
        if isinstance(val, list):
            return len(val)

    return None


def get_description_text(listing: dict) -> str:
    for key in ["description", "homeDescription", "publicRemarks", "remarks"]:
        val = listing.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def normalize_address(address: str) -> str:
    """Lowercase, strip punctuation/whitespace for dedup comparison."""
    if not address:
        return ""
    return re.sub(r"[^a-z0-9]", "", address.lower())


def dedup_leads(leads: list[dict]) -> list[dict]:
    """
    Final dedup pass across the full market lead list by zpid, URL, and
    normalized address. zpid dedup already happens during band scraping via
    seen_zpids, but URL/address dedup is applied here as a safety net before
    scoring — catches cases where the same property surfaced under a
    different zpid (re-listed) or via the price-reduced variant.
    """
    seen_zpid = set()
    seen_url  = set()
    seen_addr = set()
    deduped   = []

    for lead in leads:
        zpid = lead.get("zpid", "")
        url  = lead.get("url", "")
        addr = normalize_address(lead.get("address", ""))

        if zpid and zpid in seen_zpid:
            continue
        if url and url in seen_url:
            continue
        if addr and addr in seen_addr:
            continue

        if zpid:
            seen_zpid.add(zpid)
        if url:
            seen_url.add(url)
        if addr:
            seen_addr.add(addr)

        deduped.append(lead)

    return deduped


# ── KISS/Zompz-style lead scoring ────────────────────────────────────────────
# Scores what data exists; no single signal is required. Higher = more
# promising for the OF lane (cheap, stale, low-competition, motivated-seller
# signals). Used only to RANK leads before email enrichment — does not
# replace or loosen any existing screen_listing()/DOM/price gates.
OF_BAND_MIN = 30000
OF_BAND_MAX = 80000
MIN_SQFT_FOR_SCORING = 750


def score_lead(lead: dict) -> dict:
    """
    Returns {"score": float, "breakdown": {signal: points}}.
    All inputs are read from the already-extracted lead dict — no extra
    Apify calls. Missing signals simply contribute 0, never penalize.
    """
    breakdown: dict[str, float] = {}

    price = lead.get("price", 0)
    dom   = lead.get("days_on_market", -1)
    views_per_day = lead.get("views_per_day")
    photo_count   = lead.get("photo_count")
    has_keyword   = lead.get("has_distress_keyword", False)
    sqft          = lead.get("sqft", 0)
    status        = (lead.get("status") or "").upper()
    desc_len      = lead.get("description_length", 0)

    # Active / for-sale only (no pending/contingent/backup) — bonus if confirmed
    if status in ("FOR_SALE", "FORSALE", "ACTIVE"):
        breakdown["active_status"] = 10
    elif status in ("PENDING", "CONTINGENT", "ACTIVE_UNDER_CONTRACT", "BACKUP"):
        breakdown["active_status"] = -50  # should already be filtered out upstream, but defensive
    else:
        breakdown["active_status"] = 0  # unknown — neutral

    # OF production band ($30k-$80k) strongly preferred
    if OF_BAND_MIN <= price <= OF_BAND_MAX:
        breakdown["of_band_price"] = 25
        # Prefer lower price within the band (cheaper = more margin room)
        band_position = (price - OF_BAND_MIN) / (OF_BAND_MAX - OF_BAND_MIN)
        breakdown["lower_price_in_band"] = round(10 * (1 - band_position), 1)
    else:
        breakdown["of_band_price"] = 5
        breakdown["lower_price_in_band"] = 0

    # Older / truer DOM preferred (diminishing returns past 120 days)
    if dom and dom >= 30:
        breakdown["dom_age"] = round(min(dom, 120) / 120 * 20, 1)
    else:
        breakdown["dom_age"] = 0

    # Low views/day preferred (<=25 ideal)
    if views_per_day is not None:
        if views_per_day <= MAX_VIEWS_DAY:
            breakdown["low_views"] = 15
        else:
            breakdown["low_views"] = max(0, round(15 - (views_per_day - MAX_VIEWS_DAY) * 0.5, 1))
    else:
        breakdown["low_views"] = 0

    # Few photos preferred (1-10 = lazy/weak listing signal)
    if photo_count is not None:
        if 1 <= photo_count <= 10:
            breakdown["few_photos"] = 15
        elif photo_count == 0:
            breakdown["few_photos"] = 5  # no photo data — mildly positive, could be weak listing
        else:
            breakdown["few_photos"] = max(0, 15 - (photo_count - 10))
    else:
        breakdown["few_photos"] = 0

    # Weak description (short or missing) — lazy listing signal
    if desc_len == 0:
        breakdown["weak_description"] = 8
    elif desc_len < 100:
        breakdown["weak_description"] = 5
    else:
        breakdown["weak_description"] = 0

    # Distressed / motivated-seller keyword match
    breakdown["distress_keyword"] = 20 if has_keyword else 0

    # Square footage >= 750 (already gated upstream by URL filter, confirm if known)
    if sqft:
        breakdown["sqft_ok"] = 10 if sqft >= MIN_SQFT_FOR_SCORING else 0
    else:
        breakdown["sqft_ok"] = 0

    # Agent-listed only — URL always filters isForSaleByAgent=true, constant small bonus
    breakdown["agent_listed"] = 5

    total = round(sum(breakdown.values()), 1)
    return {"score": total, "breakdown": breakdown}


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

        contact = extract_contact_info(listing)
        agent_name = contact["agent_name"]
        brokerage_name = contact["brokerage_name"]
        agent_email = contact["agent_email"]
        agent_phone = contact["agent_phone"]

        dom       = get_dom(listing)
        bedrooms  = parse_int(listing.get("beds") or listing.get("bedrooms"))
        bathrooms = float(parse_int(listing.get("baths") or listing.get("bathrooms")))
        sqft      = parse_int(listing.get("area") or listing.get("livingArea"))
        photo_url = listing.get("imgSrc") or ""
        if isinstance(photo_url, list):
            photo_url = photo_url[0] if photo_url else ""

        # ── Scoring inputs (no extra Apify calls — all derived from this item) ──
        status            = (listing.get("statusType") or listing.get("rawHomeStatusCd") or "").upper()
        photo_count       = get_photo_count(listing)
        views_per_day     = compute_views_per_day(listing)
        has_keyword       = has_distress_keyword(listing)
        description_text  = get_description_text(listing)

        if not address or not price:
            return None

        return {
            "address":             address,
            "city":                city,
            "state":               state,
            "zip":                 zipcode,
            "price":               price,
            "list_price":          price,
            "zpid":                zpid,
            "url":                 url,
            "agent_name":          agent_name,
            "agent_email":         agent_email,
            "agent_phone":         agent_phone,
            "brokerName":          brokerage_name or agent_name,
            "brokerage_name":      brokerage_name,
            "days_on_market":      dom if dom is not None else -1,
            "bedrooms":            bedrooms,
            "bathrooms":           bathrooms,
            "sqft":                sqft,
            "photo_url":           photo_url,
            "market":              market.get("city", "").lower(),
            "candidate_reason":    candidate_reason,
            # Scoring-only fields — not consumed by offer.py/email_gen.py
            "status":              status,
            "photo_count":         photo_count,
            "views_per_day":       views_per_day,
            "has_distress_keyword": has_keyword,
            "description_length":  len(description_text),
        }
    except Exception as e:
        logger.warning(f"Failed to extract lead: {e}")
        return None


def scrape_market(market: dict) -> list[dict]:
    city = market["city"]

    # ── APIFY_ENABLED guard ──────────────────────────────────────────────────
    # Set APIFY_ENABLED=false in the workflow to run a no-scrape test.
    # No-scrape mode returns [] immediately — no Zillow, no Google email enrichment.
    apify_enabled_raw = os.environ.get("APIFY_ENABLED", "true").lower().strip()
    apify_enabled = (apify_enabled_raw == "true")

    # ── EMAIL_ENRICHMENT_ENABLED guard ───────────────────────────────────────
    # Set EMAIL_ENRICHMENT_ENABLED=false to scrape Zillow but skip the Google
    # email-search actor entirely. Leads keep agent_email="" (displayed as NONE).
    email_enrichment_enabled_raw = os.environ.get("EMAIL_ENRICHMENT_ENABLED", "true").lower().strip()
    email_enrichment_enabled = (email_enrichment_enabled_raw == "true")

    market_price_bands = get_market_price_bands(market)
    planned_bands    = len(market_price_bands)
    of_bands         = sum(1 for b in market_price_bands if b["max"] <= 80000)
    pr_extra_calls   = of_bands if ENABLE_PRICE_REDUCED_OF_VARIANT else 0
    planned_zillow_calls = planned_bands + pr_extra_calls
    planned_email_calls  = MAX_EMAIL_ENRICHMENT_CALLS_PER_WORKFLOW if email_enrichment_enabled else 0
    est_actor_calls  = planned_zillow_calls + planned_email_calls

    logger.info("=" * 60)
    logger.info(f"SCRAPER: {city}")
    logger.info(f"  APIFY_ENABLED                       : {apify_enabled} (raw='{apify_enabled_raw}')")
    logger.info(f"  EMAIL_ENRICHMENT_ENABLED            : {email_enrichment_enabled} (raw='{email_enrichment_enabled_raw}')")
    logger.info(f"  MAX_APIFY_RUNS_PER_WORKFLOW         : {MAX_APIFY_RUNS_PER_WORKFLOW} (shared — Zillow + Google + any future actor)")
    logger.info(f"  MAX_EMAIL_ENRICHMENT_CALLS_PER_WORKFLOW: {MAX_EMAIL_ENRICHMENT_CALLS_PER_WORKFLOW}")
    logger.info(f"  MAX_LEADS_TO_ENRICH_PER_WORKFLOW    : {MAX_LEADS_TO_ENRICH_PER_WORKFLOW} (top-scored leads sent to enrichment)")
    logger.info(f"  ENABLE_PRICE_REDUCED_OF_VARIANT     : {ENABLE_PRICE_REDUCED_OF_VARIANT}")
    logger.info(f"  Apify calls used so far — total     : {_apify_call_count}")
    logger.info(f"  Apify calls used so far — zillow    : {_zillow_call_count}")
    logger.info(f"  Apify calls used so far — google    : {_email_enrichment_call_count}")
    band_labels = " | ".join(f"${b['min']:,}-${b['max']:,}" for b in market_price_bands)
    logger.info(f"  Planned bands                       : {planned_bands} ({band_labels})")
    if ENABLE_PRICE_REDUCED_OF_VARIANT:
        logger.info(f"  Price-reduced OF extra calls        : {pr_extra_calls} ($30k-$80k bands only)")
    logger.info(f"  Planned Zillow calls this market    : {planned_zillow_calls}")
    logger.info(f"  Planned max Google email calls      : {planned_email_calls} (only for top {MAX_LEADS_TO_ENRICH_PER_WORKFLOW} scored leads)")
    logger.info(f"  Estimated actor calls this market   : {est_actor_calls} (Zillow + Google, capped)")
    logger.info(f"  Remaining shared budget              : {max(0, MAX_APIFY_RUNS_PER_WORKFLOW - _apify_call_count)} calls")
    logger.info("=" * 60)

    if not apify_enabled:
        logger.info(f"APIFY_ENABLED=false — skipping all Apify + Google scraping for {city}. Returning 0 leads.")
        return []

    if ApifyClient is None:
        logger.error("apify-client is not installed — cannot scrape")
        return []

    if not APIFY_TOKEN:
        logger.error("APIFY_API_TOKEN not set — cannot scrape")
        return []

    client     = ApifyClient(APIFY_TOKEN)
    leads      = []
    seen_zpids = set()

    for band in market_price_bands:
        price_min  = band["min"]
        price_max  = band["max"]
        band_label = f"${price_min:,}-${price_max:,}"
        is_of_band = (price_max <= 80000)

        # Decide which variants to run for this band.
        # Price-reduced variant only fires on OF bands when explicitly enabled.
        variants = ["base"]
        if is_of_band and ENABLE_PRICE_REDUCED_OF_VARIANT:
            variants.append("price_reduced")

        band_leads_all: list[dict] = []

        for variant in variants:
            is_price_reduced = (variant == "price_reduced")
            search_url = build_zillow_url(market, price_min, price_max,
                                          price_reduced=is_price_reduced)
            logger.info(f"Scraping band: {band_label} [variant={variant}]")
            logger.info(f"URL: {search_url[:120]}...")

            try:
                # ── Shared Apify budget check (Zillow draws from the same pool) ──
                if not can_make_apify_call():
                    logger.warning(
                        f"MAX_APIFY_RUNS_PER_WORKFLOW={MAX_APIFY_RUNS_PER_WORKFLOW} reached "
                        f"after {_apify_call_count} calls — stopping scrape for {city}"
                    )
                    break

                max_results = MAX_RESULTS_OF_BAND if is_of_band else MAX_RESULTS_CL_BAND
                logger.info(
                    f"Band {band_label} [{variant}]: maxResults={max_results} "
                    f"| actor call #{_apify_call_count + 1} (zillow call #{_zillow_call_count + 1})"
                )
                register_zillow_call()
                run   = client.actor(ACTOR_ID).call(
                    run_input={"searchUrls": [{"url": search_url}], "maxResults": max_results},
                    timeout_secs=180
                )
                items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
                logger.info(f"Band {band_label} [{variant}]: {len(items)} raw results")

                real_items = [i for i in items if "error" not in i]
                if not real_items:
                    if items:
                        logger.warning(f"Result: {items[0]}")
                    continue

                # ── Per-variant rejection diagnostics ────────────────────────
                reason_counts: dict[str, int] = {}
                variant_leads: list[dict] = []

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

                    lead = extract_lead(item, market,
                                        candidate_reason=f"{reason}|{variant}")
                    if lead:
                        variant_leads.append(lead)
                    else:
                        reason_counts["reject_missing_address_or_price"] = reason_counts.get("reject_missing_address_or_price", 0) + 1

                dom30_count = sum(
                    1 for lead in variant_leads
                    if lead.get("days_on_market", -1) >= 30
                )
                reason_str = " | ".join(f"{k}={v}" for k, v in sorted(reason_counts.items()))
                logger.info(
                    f"Band {band_label} [{variant}]: "
                    f"raw={len(real_items)} | dom30+={dom30_count} | "
                    f"candidates={len(variant_leads)} | reasons: {reason_str}"
                )

                band_leads_all.extend(variant_leads)
                time.sleep(5)

            except Exception as e:
                if is_apify_quota_error(e):
                    logger.error(
                        "APIFY QUOTA BLOCKED — preserving previous dashboard data and stopping workflow."
                    )
                    raise ApifyQuotaError(str(e)) from e
                logger.error(f"Apify run failed for band {band_label} [{variant}]: {e}")
                continue

        # Log combined unique count per band (seen_zpids dedup already applied above)
        logger.info(
            f"Band {band_label} combined: {len(band_leads_all)} unique candidates "
            f"across {len(variants)} variant(s)"
        )
        leads.extend(band_leads_all)

    # ── Final dedup safety net (zpid + URL + normalized address) ─────────────
    pre_dedup_count = len(leads)
    leads = dedup_leads(leads)
    if len(leads) != pre_dedup_count:
        logger.info(f"Final dedup: {pre_dedup_count} -> {len(leads)} after URL/address dedup")

    # ── KISS/Zompz-style scoring + ranking (no Apify calls — pure Python) ────
    for lead in leads:
        scored = score_lead(lead)
        lead["score"] = scored["score"]
        lead["score_breakdown"] = scored["breakdown"]

    leads.sort(key=lambda l: l.get("score", 0), reverse=True)

    if leads:
        logger.info("=" * 60)
        logger.info(f"TOP SCORED LEADS — {city} ({min(len(leads), MAX_LEADS_TO_ENRICH_PER_WORKFLOW)} of {len(leads)} shown)")
        for i, lead in enumerate(leads[:MAX_LEADS_TO_ENRICH_PER_WORKFLOW], start=1):
            logger.info(
                f"  #{i} score={lead['score']:>5.1f} | {lead['address']} | "
                f"${lead['price']:,} | DOM={lead['days_on_market']} | "
                f"breakdown={lead['score_breakdown']}"
            )
        logger.info("=" * 60)

    # ── Shortlist: only the top N proceed to email enrichment ────────────────
    shortlist = leads[:MAX_LEADS_TO_ENRICH_PER_WORKFLOW]
    remainder = leads[MAX_LEADS_TO_ENRICH_PER_WORKFLOW:]
    if remainder:
        logger.info(
            f"{len(remainder)} lower-scored leads will NOT be sent to email "
            f"enrichment this run (MAX_LEADS_TO_ENRICH_PER_WORKFLOW={MAX_LEADS_TO_ENRICH_PER_WORKFLOW}). "
            f"They are still kept for the dashboard/log with Email: NONE unless "
            f"Zillow itself already supplied an email."
        )

    # ── Email enrichment — gated by EMAIL_ENRICHMENT_ENABLED + shared budget ──
    # Only the shortlist (top N by score) is ever passed to the Google actor.
    if not shortlist:
        pass
    elif not email_enrichment_enabled:
        logger.info(
            f"EMAIL_ENRICHMENT_ENABLED=false — skipping Google email enrichment "
            f"for {city}. {len(shortlist)} shortlisted leads keep agent_email=NONE where missing."
        )
    elif enrich_leads_with_emails is None:
        logger.warning(
            "agent_email_finder dependencies are not installed — keeping shortlisted leads without email enrichment"
        )
    elif not can_make_email_enrichment_call():
        logger.warning(
            "EMAIL ENRICHMENT BUDGET REACHED — keeping remaining leads without email "
            f"(shared: {_apify_call_count}/{MAX_APIFY_RUNS_PER_WORKFLOW}, "
            f"google: {_email_enrichment_call_count}/{MAX_EMAIL_ENRICHMENT_CALLS_PER_WORKFLOW})"
        )
    else:
        logger.info(
            f"Starting email enrichment for {len(shortlist)} shortlisted leads "
            f"(google cap: {MAX_EMAIL_ENRICHMENT_CALLS_PER_WORKFLOW} calls, "
            f"shared budget remaining: {max(0, MAX_APIFY_RUNS_PER_WORKFLOW - _apify_call_count)})..."
        )
        shortlist = enrich_leads_with_emails(
            shortlist, market, client,
            can_make_call=can_make_email_enrichment_call,
            register_call=register_email_enrichment_call,
        )

    leads = shortlist + remainder

    for lead in leads:
        dom_display = lead["days_on_market"] if lead["days_on_market"] >= 0 else "unknown"
        logger.info(
            f"LEAD: {lead['address']} | ${lead['price']:,} | "
            f"DOM: {dom_display} | score={lead.get('score', 0):.1f} | "
            f"reason: {lead.get('candidate_reason', '')} | "
            f"Agent: {lead['agent_name']} | "
            f"Email: {lead.get('agent_email') or 'NONE'}"
        )

    logger.info(
        f"Scrape complete: {city} | {len(leads)} leads passed all screening gates | "
        f"Apify totals — total={_apify_call_count} zillow={_zillow_call_count} "
        f"google={_email_enrichment_call_count}"
    )
    return leads


def scrape(market: dict) -> list[dict]:
    logger.info(f"Starting scrape: {market['city']}, {market['state']} | Source: Zillow via Apify")
    return scrape_market(market)
