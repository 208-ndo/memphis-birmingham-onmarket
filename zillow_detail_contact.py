"""
zillow_detail_contact.py

Extract listing-agent contact info from a Zillow listing DETAIL page's
"Listed by" block — the block that actually shows the agent email, which
the search-results Apify feed does NOT include (it only gives
brokerName/detailUrl/zpid).

Two layers:
  1. parse_listed_by_block(text)  — PURE, no network. Parses the visible
     "Listed by:" text into agent_name/agent_email/agent_phone/brokerage.
     Handles the real formats seen in production (see tests):
       "Listed by: Sonja Halstead 330-388-0566 sonjahalstead@kw.com, Keller Williams Elevate"
       "Listed by: Seth B Task jeannet@taskteamcle.com, Berkshire ..., Jeannet Wright 216-269-3467"  (multi-agent)
       email without phone, phone without email, brokerage after comma.
  2. fetch_detail_contact(url, ...) — opens the detail page (via the Apify
     Zillow-detail actor if a client is provided, else a plain HTTP GET)
     and runs parse_listed_by_block on the visible text.

RULES (match the pipeline's published-contact policy):
  - Only emails ACTUALLY VISIBLE on the page are used. Never guessed or
    pattern-constructed. If no email is visible, email stays "".
  - A visible listing email is source_verified / sendable (it's the
    published listing contact, the strongest rung).
  - This runs BEFORE Google enrichment so we don't spend Google/Apify
    calls when the email is already on the listing.
"""

import os
import re
import logging

from contact_validation import (
    is_valid_agent_name, clean_agent_name, is_plausible_business_email,
    EMAIL_RE, extract_emails_from_text,
)

logger = logging.getLogger(__name__)

ZILLOW_DETAIL_ACTOR_ID = os.environ.get(
    "ZILLOW_DETAIL_ACTOR_ID", "maxcopell/zillow-detail-scraper")

# Phone: matches 330-388-0566, (216) 269-3467, 216.375.4486, etc.
PHONE_RE = re.compile(r"\(?\b\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}\b")
_LISTED_BY_RE = re.compile(r"(?i)listed\s+by\s*:?\s*")
_WS_RE = re.compile(r"\s+")


def _clean_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
    return ""


def _looks_like_brokerage(segment: str) -> bool:
    """A comma segment with letters, no email, no long phone → brokerage."""
    seg = segment.strip()
    if not seg or EMAIL_RE.search(seg):
        return False
    # If it's basically just a phone, it's not a brokerage
    digits = sum(c.isdigit() for c in seg)
    if digits >= 7:
        return False
    return bool(re.search(r"[A-Za-z]", seg)) and is_valid_agent_name(seg)


def parse_listed_by_block(text: str) -> dict:
    """
    Parse a visible "Listed by" block. Returns:
      {agent_name, agent_email, agent_phone, brokerage, all_agents}
    Only data literally present in the text is returned; nothing is guessed.
    all_agents is a list of {name, email, phone} for multi-agent listings.
    """
    empty = {"agent_name": "", "agent_email": "", "agent_phone": "",
             "brokerage": "", "all_agents": []}
    if not text:
        return empty

    text = _WS_RE.sub(" ", text).strip()
    m = _LISTED_BY_RE.search(text)
    if not m:
        return empty
    block = text[m.end():].strip()

    # Cut the block off at obvious end markers if present (kept lenient).
    block = re.split(r"(?i)\b(?:source|mls#|listing provided|©|zillow group)\b", block)[0].strip()

    # First visible email anywhere in the block is THE listing email.
    emails = [e for e in extract_emails_from_text(block)]
    # extract_emails_from_text filters portal/free domains; for a listing
    # page we also accept the raw first visible email if it's plausible.
    if not emails:
        raw = EMAIL_RE.findall(block)
        emails = [e.lower() for e in raw if is_plausible_business_email(e.lower())]
    primary_email = emails[0] if emails else ""

    # Split on commas: segments are agents, brokerage, or agent+contact.
    segments = [s.strip() for s in block.split(",") if s.strip()]

    all_agents = []
    brokerage = ""
    for seg in segments:
        seg_email = ""
        seg_raw_emails = EMAIL_RE.findall(seg)
        if seg_raw_emails and is_plausible_business_email(seg_raw_emails[0].lower()):
            seg_email = seg_raw_emails[0].lower()
        seg_phone_match = PHONE_RE.search(seg)
        seg_phone = _clean_phone(seg_phone_match.group(0)) if seg_phone_match else ""

        # Name = the segment with email/phone/IDs stripped out.
        name_part = seg
        if seg_email:
            name_part = name_part.replace(seg_raw_emails[0], " ")
        if seg_phone_match:
            name_part = name_part.replace(seg_phone_match.group(0), " ")
        name_part = _WS_RE.sub(" ", name_part).strip(" ,.-")
        name = clean_agent_name(name_part)

        if seg_email or seg_phone or name:
            if name or seg_email or seg_phone:
                # Segment carries agent/contact info
                if not name and not seg_email and not seg_phone:
                    pass
                else:
                    # Distinguish "brokerage only" from "agent (+contact)".
                    if name and not seg_email and not seg_phone and _looks_like_brokerage(seg):
                        if not brokerage:
                            brokerage = name
                    else:
                        all_agents.append({"name": name, "email": seg_email,
                                           "phone": seg_phone})
                    continue
        # Pure brokerage segment (letters, no contact detail)
        if _looks_like_brokerage(seg) and not brokerage:
            brokerage = clean_agent_name(seg)

    # Choose the primary agent: prefer one carrying the primary email, else
    # one with a phone, else the first named agent.
    primary = None
    if primary_email:
        primary = next((a for a in all_agents if a["email"] == primary_email), None)
    if primary is None:
        primary = next((a for a in all_agents if a["phone"]), None)
    if primary is None and all_agents:
        primary = all_agents[0]
    primary = primary or {"name": "", "email": "", "phone": ""}

    # Primary email falls back to any visible email in the block.
    agent_email = primary["email"] or primary_email
    # Primary phone falls back to any visible phone in the block.
    agent_phone = primary["phone"]
    if not agent_phone:
        pm = PHONE_RE.search(block)
        agent_phone = _clean_phone(pm.group(0)) if pm else ""

    return {
        "agent_name":  primary["name"],
        "agent_email": agent_email,
        "agent_phone": agent_phone,
        "brokerage":   brokerage,
        "all_agents":  all_agents,
    }


def _fetch_detail_text(url: str, client=None) -> str:
    """
    Return visible text of the Zillow detail page, or "" on failure.
    Uses the Apify Zillow-detail actor when a client is provided (keeps us
    on the same infra/proxying as the rest of the pipeline); otherwise a
    plain HTTP GET as a best-effort fallback.
    """
    if not url:
        return ""
    if client is not None:
        try:
            run = client.actor(ZILLOW_DETAIL_ACTOR_ID).call(
                run_input={"startUrls": [{"url": url}], "maxItems": 1},
                timeout_secs=90,
            )
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            parts = []
            for item in items:
                for key in ("attributionInfo", "listed_by", "listedBy",
                            "contact_recipients", "description", "text",
                            "rawText", "pageText"):
                    val = item.get(key)
                    if isinstance(val, dict):
                        parts.append(" ".join(str(v) for v in val.values()))
                    elif isinstance(val, list):
                        for v in val:
                            parts.append(str(v) if not isinstance(v, dict)
                                         else " ".join(str(x) for x in v.values()))
                    elif val:
                        parts.append(str(val))
            return " ".join(parts)
        except Exception as e:
            logger.debug("Zillow detail actor fetch failed for %s: %s", url, e)
            return ""
    # Fallback: plain GET (best effort; may be bot-blocked, that's fine —
    # we simply fall through to Google enrichment when this returns "").
    try:
        import requests
        resp = requests.get(url, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (compatible; contact-lookup/1.0)"})
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        logger.debug("Zillow detail HTTP fetch failed for %s: %s", url, e)
    return ""


def fetch_detail_contact(url: str, client=None) -> dict:
    """
    Fetch the detail page and parse its "Listed by" block.
    Returns a contact dict with source metadata, or {} if nothing usable.
    Only ever returns an email that was literally visible on the page.
    """
    text = _fetch_detail_text(url, client=client)
    if not text:
        return {}
    parsed = parse_listed_by_block(text)
    if not (parsed["agent_email"] or parsed["agent_phone"] or parsed["agent_name"]):
        return {}

    contact = {
        "agent_name":        parsed["agent_name"],
        "brokerage_name":    parsed["brokerage"],
        "agent_phone":       parsed["agent_phone"],
        "contact_source_url": url,
    }
    if parsed["agent_email"]:
        contact.update({
            "agent_email":        parsed["agent_email"],
            "email":              parsed["agent_email"],
            "email_source_url":   url,
            "email_source_type":  "zillow_detail_listed_by",
            "email_confidence":   "source_verified",
            "email_is_sendable":  True,
            "contact_source_type": "zillow_detail_listed_by",
        })
        logger.info(
            "Zillow detail contact found: email=%s, phone=%s, source=zillow_detail_listed_by",
            parsed["agent_email"], parsed["agent_phone"] or "none")
    else:
        logger.info(
            "Zillow detail contact found (no email): name=%s, phone=%s, source=zillow_detail_listed_by",
            parsed["agent_name"] or "unknown", parsed["agent_phone"] or "none")
    return contact
