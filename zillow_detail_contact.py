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
    is_valid_agent_name, clean_agent_name, EMAIL_RE,
)

logger = logging.getLogger(__name__)

ZILLOW_DETAIL_ACTOR_ID = os.environ.get(
    "ZILLOW_DETAIL_ACTOR_ID", "maxcopell/zillow-detail-scraper")

# Optional Playwright fallback (2026-07-02) — OFF by default, and only ever
# used for a small number of TOP shortlisted detail pages, never every lead.
USE_PLAYWRIGHT_ZILLOW_DETAIL = (
    os.environ.get("USE_PLAYWRIGHT_ZILLOW_DETAIL", "").lower().strip() == "true")


def _max_detail_fetches() -> int:
    raw = os.environ.get("MAX_ZILLOW_DETAIL_FETCHES_PER_WORKFLOW", "")
    try:
        return int(raw) if raw.strip() else 10
    except ValueError:
        return 10


# Workflow-level counter so Playwright (the expensive path) is hard-capped.
_playwright_fetch_count = 0

# ── Zillow-detail email acceptance (2026-07-02 fix) ─────────────────────────────
# Zillow's own listing detail page publishes the agent's real email in the
# "Listed by" block — and that email is frequently a gmail/yahoo/outlook
# address (e.g. frefrederickteam@gmail.com on 19806 Shawnee Ave). The general
# contact_validation skip-list rejects those free-mail domains GLOBALLY, which
# is correct for Google snippets (where a gmail hit is usually noise) but WRONG
# for an email literally printed on Zillow's own listing page. So detail-page
# extraction uses its OWN acceptance rule that only rejects obvious junk /
# image-filename domains, never free-mail providers. Google/snippet extraction
# in contact_validation.py is left completely unchanged.

# Only these are ever rejected for a Zillow-detail email: parser artifacts and
# image/asset filenames that happen to match the email regex.
_ZILLOW_DETAIL_JUNK_DOMAINS = {
    "sentry.io", "wixpress.com", "example.com", "email.com", "domain.com",
    "sentry-next.wixpress.com", "schema.org", "w3.org",
}
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico")

# Zillow-detail email regex per spec (letters/digits/._%+- @ domain . tld{2,}).
ZILLOW_DETAIL_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def is_valid_zillow_detail_email(email: str) -> bool:
    """
    Accept ANY normal email visibly published on a Zillow detail page,
    INCLUDING gmail/yahoo/outlook/etc. Reject only empty values, obvious
    parser junk domains, and image/asset filenames. This deliberately does
    NOT call the general business-email skip list (which drops free-mail),
    because these emails are literally printed on Zillow's own listing.
    """
    if not email or "@" not in email:
        return False
    email = email.strip().lower()
    if not ZILLOW_DETAIL_EMAIL_RE.fullmatch(email):
        return False
    domain = email.split("@")[-1]
    if domain in _ZILLOW_DETAIL_JUNK_DOMAINS:
        return False
    if domain.endswith(_IMAGE_EXTS):
        return False
    # "2x.png"-style local parts / obvious asset refs
    local = email.split("@")[0]
    if local.endswith(_IMAGE_EXTS):
        return False
    return True


def extract_zillow_detail_emails(text: str) -> list:
    """All Zillow-detail-acceptable emails in text, mailto links first, in
    order of first appearance. Free-mail domains ARE kept (see rationale)."""
    if not text:
        return []
    found, seen = [], set()
    mailtos = re.findall(r"(?i)mailto:([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})", text)
    for raw in mailtos + ZILLOW_DETAIL_EMAIL_RE.findall(text):
        email = raw.lower().strip(" .,;:")
        if email not in seen and is_valid_zillow_detail_email(email):
            seen.add(email)
            found.append(email)
    return found

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
    # Uses Zillow-detail acceptance (accepts gmail/yahoo/outlook etc. because
    # these are literally published on Zillow's own listing page).
    emails = extract_zillow_detail_emails(block)
    primary_email = emails[0] if emails else ""

    # Split on commas: segments are agents, brokerage, or agent+contact.
    segments = [s.strip() for s in block.split(",") if s.strip()]

    all_agents = []
    brokerage = ""
    for seg in segments:
        seg_email = ""
        seg_raw_emails = ZILLOW_DETAIL_EMAIL_RE.findall(seg)
        if seg_raw_emails and is_valid_zillow_detail_email(seg_raw_emails[0].lower()):
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


def _flatten_json(obj) -> str:
    """
    Recursively walk ANY dict/list/str/scalar and join every string value
    into one text blob. This is the key fix (2026-07-02): the Zillow detail
    actor nests the "Listed by" contact data under keys we can't guess, so
    instead of probing guessed keys we flatten the ENTIRE item and parse the
    whole thing. Order is preserved so "Listed by:" + following contact text
    stay adjacent.
    """
    parts = []

    def walk(node):
        if node is None:
            return
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            if node.strip():
                parts.append(node)
        else:
            parts.append(str(node))

    walk(obj)
    return " ".join(parts)


def _mask_email(email: str) -> str:
    if "@" not in email:
        return email
    user, _, domain = email.partition("@")
    return f"{user[:2]}***@{domain}"


def _mask_emails_in_text(text: str) -> str:
    return EMAIL_RE.sub(lambda m: _mask_email(m.group(0)), text or "")


def _log_detail_diagnostics(url, actor_id, items, flat_text):
    """INFO-level diagnostics so a failed detail fetch is debuggable from logs."""
    logger.info("Zillow detail attempt: url=%s | actor=%s | items_returned=%s",
                url, actor_id, len(items) if items is not None else 0)
    if items:
        top_keys = set()
        for item in items:
            if isinstance(item, dict):
                top_keys.update(item.keys())
        logger.info("Zillow detail item top-level keys: %s", sorted(top_keys)[:40])
    has_email = bool(EMAIL_RE.search(flat_text or ""))
    has_listed_by = bool(re.search(r"(?i)listed\s+by", flat_text or ""))
    logger.info("Zillow detail flattened: len=%s | any_email=%s | has_'Listed by'=%s",
                len(flat_text or ""), has_email, has_listed_by)
    if flat_text:
        snippet = _mask_emails_in_text(flat_text.strip())[:500]
        logger.info("Zillow detail first 500 chars (emails masked): %s", snippet)


def _fetch_via_actor(url, client):
    """Return (items, flattened_text) from the Apify detail actor, or ([], '')."""
    try:
        run = client.actor(ZILLOW_DETAIL_ACTOR_ID).call(
            run_input={"startUrls": [{"url": url}], "maxItems": 1},
            timeout_secs=90,
        )
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        flat = _flatten_json(items)
        return items, flat
    except Exception as e:
        logger.info("Zillow detail actor fetch failed for %s: %s", url, e)
        return [], ""


def _fetch_via_http(url):
    """
    Direct HTML fallback. Unescapes entities + decodes safe unicode escapes,
    then returns the whole HTML/script text so parse_listed_by_block and the
    email regex can find contacts literally present in the page. Only emails
    actually in the HTML are ever used — nothing is guessed.
    """
    try:
        import requests
    except Exception:
        logger.info("Zillow detail HTTP fallback unavailable: requests not installed")
        return ""
    try:
        import html as _html
        resp = requests.get(url, timeout=20, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0 Safari/537.36"),
            "Accept-Language": "en-US,en;q=0.9",
        })
        if resp.status_code != 200:
            logger.info("Zillow detail HTTP fallback for %s returned status %s",
                        url, resp.status_code)
            return ""
        text = resp.text
        text = _html.unescape(text)
        # Decode \u00XX / \/ style escapes that appear inside embedded JSON.
        try:
            text = text.encode("utf-8").decode("unicode_escape", "ignore")
        except Exception:
            pass
        text = text.replace("\\/", "/")
        return text
    except Exception as e:
        logger.info("Zillow detail HTTP fallback failed for %s: %s", url, e)
        return ""


def _fetch_via_playwright(url):
    """
    Optional Playwright fallback for TOP shortlisted pages only. OFF unless
    USE_PLAYWRIGHT_ZILLOW_DETAIL=true AND playwright is importable. Hard
    capped by MAX_ZILLOW_DETAIL_FETCHES_PER_WORKFLOW.
    """
    global _playwright_fetch_count
    if not USE_PLAYWRIGHT_ZILLOW_DETAIL:
        return ""
    if _playwright_fetch_count >= _max_detail_fetches():
        logger.info("Zillow detail Playwright cap reached (%s) — skipping %s",
                    _max_detail_fetches(), url)
        return ""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        logger.info("Zillow detail Playwright fallback requested but Playwright "
                    "is not installed — skipping")
        return ""
    try:
        _playwright_fetch_count += 1
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"))
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            text = page.inner_text("body")
            browser.close()
            return text or ""
    except Exception as e:
        logger.info("Zillow detail Playwright fetch failed for %s: %s", url, e)
        return ""


def _fetch_detail_text(url: str, client=None) -> str:
    """
    Return flattened detail-page text for parsing, or "" on failure.
    Tries, in order: Apify detail actor (recursively flattened) → direct
    HTML GET → optional Playwright (top pages only). Emits INFO diagnostics
    at each step so empty results are debuggable.
    """
    if not url:
        return ""

    # 1) Apify detail actor, fully flattened.
    if client is not None:
        items, flat = _fetch_via_actor(url, client)
        _log_detail_diagnostics(url, ZILLOW_DETAIL_ACTOR_ID, items, flat)
        if flat and (re.search(r"(?i)listed\s+by", flat) or EMAIL_RE.search(flat)):
            return flat

    # 2) Direct HTML fallback.
    html_text = _fetch_via_http(url)
    if html_text:
        _log_detail_diagnostics(url, "http_get", None, html_text)
        if re.search(r"(?i)listed\s+by", html_text) or EMAIL_RE.search(html_text):
            return html_text

    # 3) Optional Playwright fallback (top shortlisted pages only).
    pw_text = _fetch_via_playwright(url)
    if pw_text:
        _log_detail_diagnostics(url, "playwright", None, pw_text)
        if re.search(r"(?i)listed\s+by", pw_text) or EMAIL_RE.search(pw_text):
            return pw_text

    return ""


def extract_contact_from_flat_text(flat_text: str) -> dict:
    """
    For actor output that carries the contact as STRUCTURED JSON (email +
    phone + name present, but no literal "Listed by:" marker), pull the
    contact directly from the flattened blob. Only accepts an email that is
    literally present in the text. Never guesses.

    Strategy: prefer an email that sits near a Zillow contact key
    (attributionInfo/contactFormRenderData/agentEmail/brokerEmail/email),
    else the first Zillow-detail-acceptable email; then look for a phone and
    a human name in a nearby window. Accepts free-mail domains (gmail etc.)
    because these are literally published on the Zillow listing.
    """
    if not flat_text:
        return {}

    # Prefer an email that appears right after a known contact key.
    key_email = ""
    for key in ("agentEmail", "brokerEmail", "contactEmail",
                "contactFormRenderData", "attributionInfo", "listedBy",
                "email"):
        km = re.search(re.escape(key), flat_text)
        if not km:
            continue
        near = flat_text[km.start(): km.start() + 300]
        cand = ZILLOW_DETAIL_EMAIL_RE.search(near)
        if cand and is_valid_zillow_detail_email(cand.group(0).lower()):
            key_email = cand.group(0).lower()
            break

    email = key_email
    if not email:
        for cand in ZILLOW_DETAIL_EMAIL_RE.finditer(flat_text):
            c = cand.group(0).lower()
            if is_valid_zillow_detail_email(c):
                email = c
                break
    if not email:
        return {}

    idx = flat_text.lower().find(email)
    window = flat_text[max(0, idx - 200): idx + 200]

    phone = ""
    pm = PHONE_RE.search(window)
    if pm:
        phone = _clean_phone(pm.group(0))

    # Name: look for a "First Last" style token sequence in the window that
    # validates as an agent name and isn't part of the email/phone.
    name = ""
    for cand in re.findall(r"[A-Z][a-zA-Z'’.-]+(?:\s+[A-Z][a-zA-Z'’.-]+){1,3}", window):
        if email.split("@")[0] in cand.lower().replace(" ", ""):
            continue
        if is_valid_agent_name(cand):
            name = clean_agent_name(cand)
            break

    return {"agent_name": name, "agent_email": email, "agent_phone": phone,
            "brokerage": ""}


def fetch_detail_contact(url: str, client=None) -> dict:
    """
    Fetch the detail page and parse its "Listed by" block.
    Returns a contact dict with source metadata, or {} if nothing usable.
    Only ever returns an email that was literally visible on the page.
    """
    text = _fetch_detail_text(url, client=client)
    if not text:
        return {}

    # Parsing order (per spec):
    #   1. exact "Listed by" window from flattened text
    #   2. structured attributionInfo/contactFormRenderData/agentEmail/etc
    #   3. any Zillow-detail email near phone/name/brokerage in the text
    #   (Google is the LAST resort, handled by the enrichment ladder, not here)
    parsed = parse_listed_by_block(text)
    # If the Listed-by block produced a name/phone but NO email, still try the
    # structured/near-email extractor so a published email elsewhere in the
    # flattened detail data isn't missed (this was the "no email" bug).
    if not parsed.get("agent_email"):
        structured = extract_contact_from_flat_text(text)
        if structured.get("agent_email"):
            # Keep the richer name/brokerage from the Listed-by block if present.
            parsed = {
                "agent_email": structured["agent_email"],
                "agent_phone": parsed.get("agent_phone") or structured.get("agent_phone", ""),
                "agent_name":  parsed.get("agent_name") or structured.get("agent_name", ""),
                "brokerage":   parsed.get("brokerage", ""),
            }
    if not (parsed.get("agent_email") or parsed.get("agent_phone") or parsed.get("agent_name")):
        return {}

    contact = {
        "agent_name":        parsed.get("agent_name", ""),
        "brokerage_name":    parsed.get("brokerage", ""),
        "agent_phone":       parsed.get("agent_phone", ""),
        "contact_source_url": url,
    }
    if parsed.get("agent_email"):
        parsed_email = parsed["agent_email"]
        contact.update({
            "agent_email":        parsed_email,
            "email":              parsed_email,
            "email_source_url":   url,
            "email_source_type":  "zillow_detail_listed_by",
            "email_confidence":   "source_verified",
            "email_is_sendable":  True,
            "contact_source_type": "zillow_detail_listed_by",
        })
        logger.info(
            "Zillow detail contact found: email=%s, phone=%s, source=zillow_detail_listed_by",
            parsed_email, parsed.get("agent_phone") or "none")
    else:
        logger.info(
            "Zillow detail contact found (no email): name=%s, phone=%s, source=zillow_detail_listed_by",
            parsed.get("agent_name") or "unknown", parsed.get("agent_phone") or "none")
    return contact
