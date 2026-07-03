"""
agent_email_finder.py

Deterministic published-contact ladder for listing agents
(listing-agent-contact-finder.skill + zompz-deal-finder rules).

Ladder implemented by find_published_agent_contact(), in strict order:
  1. zillow_contact    — email already present in the Zillow/Apify item
  2. listing_contact   — contact data tied to the live listing URL (searched
                         via the listing URL / exact address, since direct
                         Zillow page fetches are bot-blocked in this pipeline)
  3. google_snippet    — exact property address + brokerage (+ agent if valid)
  4. google_snippet    — agent name + brokerage + city + email (valid names only)
  5. zillow_profile / homes_profile / brokerage_roster — profile & roster pages
                         discovered through Google (site: queries)
  6. mailto:/visible-email extraction from every snippet/url examined above
  7. office_fallback   — office intake email from the official brokerage site
  8. phone-only        — ONLY after every rung above has failed

Every found email is stored with source URL, source type, confidence, and a
sendable flag. Live sending only ever allows source_verified /
snippet_verified / office_fallback (see contact_validation.py). Numeric junk
agent names ("33", "82") are never used in queries — invalid names fall back
to property-address + brokerage + listing-URL queries.

Budget safety: every client.actor() call is gated by can_make_call() and
reported via register_call(), passed in by scraper.py. Per-market and
per-workflow email caps plus the global emergency Apify cap all apply there.
"""

import os
import time
import logging

try:
    from apify_client import ApifyClient
except Exception:            # pragma: no cover - allows import without apify
    ApifyClient = None

from contact_validation import (
    is_valid_agent_name, clean_agent_name, extract_emails_from_text,
    is_plausible_business_email, email_is_sendable, EMAIL_RE, SKIP_DOMAINS,
)

try:
    from zillow_detail_contact import fetch_detail_contact
except Exception:  # pragma: no cover - keep enrichment importable without it
    fetch_detail_contact = None

logger = logging.getLogger(__name__)

APIFY_TOKEN     = os.environ.get("APIFY_API_TOKEN")
GOOGLE_ACTOR_ID = "apify/google-search-scraper"

# Kept for backward compatibility with existing imports/tests
def is_valid_agent_email(email: str) -> bool:
    return is_plausible_business_email(email)


def _default_can_make_call() -> bool:
    return True


def _default_register_call():
    return None


def _sanitize_query_for_log(query: str) -> str:
    """Queries contain only public listing data, but keep logs tidy/safe."""
    return query[:160]


def _run_google_query(query, client, can_make_call, register_call,
                      results_per_page=5):
    """
    One budget-gated Google actor call. Returns list of result dicts:
    {title, description, url}. Empty list on budget stop or failure.
    """
    if not can_make_call():
        logger.warning("EMAIL ENRICHMENT BUDGET REACHED — skipping query: %s",
                       _sanitize_query_for_log(query))
        return []
    try:
        register_call()
        logger.info("Google query: %s", _sanitize_query_for_log(query))
        run = client.actor(GOOGLE_ACTOR_ID).call(
            run_input={
                "queries":          query,
                "maxPagesPerQuery": 1,
                "resultsPerPage":   results_per_page,
                "languageCode":     "en",
                "countryCode":      "us",
            },
            timeout_secs=60,
        )
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        results = []
        for item in items:
            for result in item.get("organicResults", []):
                results.append({
                    "title":       result.get("title", "") or "",
                    "description": result.get("description", "") or "",
                    "url":         result.get("url", "") or "",
                })
        time.sleep(1)
        return results
    except Exception as e:
        logger.debug("Google search failed for '%s': %s",
                     _sanitize_query_for_log(query), e)
        return []


def _classify_result_source(url: str) -> str:
    u = (url or "").lower()
    if "zillow.com/profile" in u:
        return "zillow_profile"
    if "homes.com" in u:
        return "homes_profile"
    return "google_snippet"


def _emails_from_results(results, source_type_hint=None):
    """
    Yield (email, source_url, source_type) from snippets + mailto links.
    Confidence for all of these is snippet-derived (visible, not invented).
    """
    for r in results:
        text = " ".join([r["title"], r["description"], r["url"]])
        for email in extract_emails_from_text(text):
            source_type = source_type_hint or _classify_result_source(r["url"])
            yield email, r["url"], source_type


def _contact_dict(email="", source_url="", source_type="", confidence="",
                  phone=""):
    return {
        "email":             email,
        "email_source_url":  source_url,
        "email_source_type": source_type,
        "email_confidence":  confidence,
        "email_is_sendable": email_is_sendable(confidence) if email else False,
        "agent_phone":       phone,
    }


def find_published_agent_contact(lead, client, can_make_call=None,
                                 register_call=None):
    """
    Deterministic published-contact ladder. Returns a contact dict (see
    _contact_dict). Never invents/pattern-guesses an email. Uses property
    address + brokerage + listing URL when the agent name is invalid/missing.
    """
    can_make_call = can_make_call or _default_can_make_call
    register_call = register_call or _default_register_call

    agent_name = clean_agent_name(
        lead.get("listing_agent_name") or lead.get("agent_name") or "")
    brokerage  = (lead.get("brokerage_name") or lead.get("brokerName") or "").strip()
    # Guard: brokerName historically fell back to agent_name — never let a
    # junk numeric value through as a brokerage either.
    if brokerage and not is_valid_agent_name(brokerage):
        brokerage = ""
    address     = (lead.get("address") or "").strip()
    city        = (lead.get("city") or lead.get("market") or "").strip()
    listing_url = (lead.get("listing_url") or lead.get("url") or "").strip()
    phone       = (lead.get("listing_agent_phone") or lead.get("agent_phone") or "").strip()

    # ── Rung 1: contact data already present in the Zillow/Apify item ──────
    existing = (lead.get("agent_email") or "").strip().lower()
    if existing and is_plausible_business_email(existing):
        return _contact_dict(existing, listing_url or "zillow_item",
                             "zillow_contact", "source_verified", phone)

    # ── Rung 1.5: Zillow DETAIL page "Listed by" block (2026-07-02) ─────────
    # The search-results feed omits the agent email; the detail page's
    # "Listed by" block has it. Run this BEFORE any Google call so we never
    # spend Google/Apify email-search budget when the email is already
    # published on the listing. Only uses emails literally visible on the
    # page — never guessed. This is the strongest rung after a direct item
    # email, so it short-circuits the whole Google ladder on success.
    if fetch_detail_contact is not None and listing_url:
        try:
            detail = fetch_detail_contact(listing_url, client=client)
        except Exception as e:
            logger.debug("Zillow detail extraction failed for %s: %s", listing_url, e)
            detail = {}
        if detail.get("email"):
            result = _contact_dict(
                detail["email"], detail["email_source_url"],
                "zillow_detail_listed_by", "source_verified",
                detail.get("agent_phone") or phone)
            # Carry through detail-page name/brokerage when the item lacked them
            if detail.get("agent_name"):
                result["agent_name"] = detail["agent_name"]
            if detail.get("brokerage_name"):
                result["brokerage_name"] = detail["brokerage_name"]
            return result
        # If the detail page gave a better phone/name but no email, keep them
        # for the phone-only fallback and for the Google queries below.
        if detail.get("agent_phone") and not phone:
            phone = detail["agent_phone"]
        if detail.get("agent_name") and not agent_name:
            agent_name = clean_agent_name(detail["agent_name"])
        if detail.get("brokerage_name") and not brokerage:
            brokerage = detail["brokerage_name"]

    # ── Rung 2: contact data tied to the live listing (listing URL query) ──
    if listing_url:
        results = _run_google_query(f'"{address}" listing agent contact {listing_url}',
                                    client, can_make_call, register_call, 3)
        for email, src_url, _ in _emails_from_results(results, "listing_contact"):
            return _contact_dict(email, src_url, "listing_contact",
                                 "snippet_verified", phone)

    # ── Rung 3: exact property address + brokerage (+ agent if valid) ──────
    if address and brokerage:
        q = f'"{address}" "{brokerage}"'
        if agent_name:
            q += f' "{agent_name}"'
        q += " email"
        results = _run_google_query(q, client, can_make_call, register_call)
        for email, src_url, source_type in _emails_from_results(results):
            return _contact_dict(email, src_url, source_type,
                                 "snippet_verified", phone)

    # ── Rung 4: agent name + brokerage + city + email (valid names ONLY) ───
    if agent_name:
        pieces = [f'"{agent_name}"']
        if brokerage:
            pieces.append(f'"{brokerage}"')
        if city:
            pieces.append(city)
        pieces.append("email")
        results = _run_google_query(" ".join(pieces), client,
                                    can_make_call, register_call)
        for email, src_url, source_type in _emails_from_results(results):
            return _contact_dict(email, src_url, source_type,
                                 "snippet_verified", phone)

    # ── Rung 5: Zillow / Homes.com profiles + brokerage roster via Google ──
    profile_queries = []
    if agent_name:
        profile_queries.append(
            f'site:zillow.com/profile OR site:homes.com "{agent_name}"'
            + (f' "{brokerage}"' if brokerage else ""))
    if brokerage:
        profile_queries.append(
            f'"{brokerage}" {city} agent roster staff directory'
            + (f' "{agent_name}"' if agent_name else ""))
    for q in profile_queries:
        results = _run_google_query(q, client, can_make_call, register_call)
        # Rung 6 (mailto/visible emails) is applied to every page examined
        for email, src_url, source_type in _emails_from_results(results):
            if source_type == "google_snippet" and brokerage:
                source_type = "brokerage_roster"
            return _contact_dict(email, src_url, source_type,
                                 "snippet_verified", phone)

    # ── Rung 7: office intake email from the official brokerage site ───────
    if brokerage:
        q = f'"{brokerage}" {city} office email contact'
        results = _run_google_query(q, client, can_make_call, register_call, 3)
        for email, src_url, _ in _emails_from_results(results, "office_fallback"):
            logger.info("Office-fallback email for %s: %s", brokerage, email)
            return _contact_dict(email, src_url, "office_fallback",
                                 "office_fallback", phone)

    # ── Rung 8: phone-only, all email rungs exhausted ───────────────────────
    if phone:
        logger.info("Phone-only lead (all email rungs exhausted): %s | %s",
                    agent_name or address, brokerage or "no brokerage")
    return _contact_dict(phone=phone)


# ── Backward-compatible wrapper used by older tests/tools ──────────────────────

def search_agent_email(agent_name, brokerage, city, client,
                       can_make_call=None, register_call=None) -> str:
    lead = {"agent_name": agent_name, "brokerage_name": brokerage,
            "city": city, "address": ""}
    contact = find_published_agent_contact(lead, client,
                                           can_make_call, register_call)
    return contact["email"]


def enrich_leads_with_emails(leads, market, client,
                             can_make_call=None, register_call=None) -> list:
    """
    For each lead missing an agent email, walk the published-contact ladder.
    Stores email + source/confidence/sendable fields on the lead. Stops
    cleanly once budget is exhausted; remaining leads keep agent_email="".
    """
    can_make_call = can_make_call or _default_can_make_call
    register_call = register_call or _default_register_call

    city        = market.get("city", "")
    needs_email = [l for l in leads if not l.get("agent_email")]
    has_email   = [l for l in leads if l.get("agent_email")]

    # Leads whose email came straight from the Zillow item get source fields too
    for lead in has_email:
        if not lead.get("email_source_type"):
            lead.update(_contact_dict(
                lead["agent_email"],
                lead.get("listing_url") or lead.get("url") or "zillow_item",
                "zillow_contact", "source_verified",
                lead.get("agent_phone", "")))
            lead["agent_email"] = lead["email"]

    logger.info("Email lookup: %s leads need emails, %s already have one",
                len(needs_email), len(has_email))

    brokerage_cache = {}
    for idx, lead in enumerate(needs_email):
        if not lead.get("city"):
            lead["city"] = city
        brokerage = (lead.get("brokerage_name") or lead.get("brokerName") or "").strip()

        cache_key = brokerage.lower()
        if cache_key and cache_key in brokerage_cache:
            cached = brokerage_cache[cache_key]
            if cached["email"]:
                lead.update(cached)
                lead["agent_email"] = cached["email"]
                logger.info("Reused cached %s email for %s: %s",
                            cached["email_source_type"], brokerage, cached["email"])
            continue

        # find_published_agent_contact() runs the Zillow detail-page "Listed
        # by" rung FIRST (before any Google call), so call it even when the
        # Google budget is exhausted — the detail rung doesn't use Google
        # budget. can_make_call is still passed through so the Google rungs
        # inside it self-gate and make zero Google calls once the cap is hit.
        if not can_make_call():
            logger.info(
                "Google email budget exhausted — running Zillow detail-page "
                "step only for remaining %s leads (no Google calls)",
                len(needs_email) - idx)

        contact = find_published_agent_contact(
            lead, client, can_make_call=can_make_call,
            register_call=register_call)
        lead.update(contact)
        lead["agent_email"] = contact["email"]
        if cache_key:
            brokerage_cache[cache_key] = contact
        if not contact["email"]:
            logger.info("No published email found: %s / %s (%s)",
                        lead.get("agent_name") or "no-name", brokerage or "no-brokerage",
                        "phone-only" if contact["agent_phone"] else "no contact")

    found = sum(1 for l in needs_email if l.get("agent_email"))
    logger.info("Email enrichment complete: found %s/%s emails",
                found, len(needs_email))
    return has_email + needs_email
