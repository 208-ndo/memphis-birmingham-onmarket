"""
contact_validation.py

Shared, dependency-free validation for listing-agent contact data.
Imported by scraper.py, agent_email_finder.py, and gmail_send.py — kept
separate so it works even when apify-client isn't installed (tests, no-scrape
runs) and so there are no circular imports.

Why this exists (2026-07-02 Cleveland/Akron dry-run fix):
The Zillow item text-soup parser was producing numeric "agent names" like
"33", "35", "82", "134" (days-on-market / photo-count fragments), which were
then fed into Google email searches as '"33" "brokerage" email' — guaranteed
0/10 enrichment. Nothing validated agent names anywhere.

Skill rules encoded here (listing-agent-contact-finder.skill):
- published business contact info only; verify, do not invent
- live-send only source-verified / snippet-verified / office-fallback emails
- pattern-guessed emails are NEVER sendable unless a future explicit
  setting enables them (ALLOW_PATTERN_GUESS_SENDS env, default off)
"""

import os
import re

# ── Agent name validation ──────────────────────────────────────────────────────

# Things that are never a human/team name
_ALL_NUMERIC_RE   = re.compile(r"^[\d\s\.,#-]+$")
_ID_LIKE_RE       = re.compile(r"^(id|mls|zpid|lot|apn|#)?[\s:#-]*\d{1,12}$", re.IGNORECASE)
_PHONE_FRAG_RE    = re.compile(r"^\(?\d{3}\)?[\s.-]?\d{0,4}[\s.-]?\d{0,4}$")
_HAS_LETTERS_RE   = re.compile(r"[A-Za-z]")
# Counts / UI fragments that leak out of Zillow text soup
_JUNK_PATTERNS = re.compile(
    r"^[\d\s.,#-]*(days?\s+on|photos?|views?|saves?|baths?|beds?|sqft|acres?|price|"
    r"listing|status|active|pending|sold|contingent|new|hot|home|zestimate)\b",
    re.IGNORECASE,
)


def is_valid_agent_name(value) -> bool:
    """
    True only if value plausibly names a real human agent or team.

    Rejects: empty/None, all-numeric strings ("33", "134"), ID/count-like
    values ("MLS 123456", "#82"), phone fragments, strings under 3 chars,
    and UI text fragments ("days on Zillow", "12 photos").
    Accepts: real names ("Jane Smith", "The Smith Team", "J. Smith Realty").
    """
    if not value or not isinstance(value, str):
        return False
    name = re.sub(r"\s+", " ", value).strip(" ,.-:;|")
    if len(name) < 3:
        return False
    if len(name) > 80:  # real names/teams are short; long strings are text-soup leaks
        return False
    if not _HAS_LETTERS_RE.search(name):
        return False
    if _ALL_NUMERIC_RE.match(name):
        return False
    if _ID_LIKE_RE.match(name):
        return False
    if _PHONE_FRAG_RE.match(name):
        return False
    if _JUNK_PATTERNS.match(name):
        return False
    # Mostly-digits strings ("33 1234") are IDs/fragments, not names
    digits = sum(c.isdigit() for c in name)
    if digits and digits / len(name.replace(" ", "")) > 0.5:
        return False
    return True


def clean_agent_name(value) -> str:
    """Return the cleaned name if valid, else '' (never a numeric junk name)."""
    if not is_valid_agent_name(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip(" ,.-:;|")


# ── Email source / confidence taxonomy ─────────────────────────────────────────

SOURCE_TYPES = (
    "zillow_contact",     # email present in the Zillow/Apify item itself
    "listing_contact",    # from live listing / listing-URL contact data
    "zillow_profile",     # agent's Zillow profile page
    "homes_profile",      # agent's Homes.com profile page
    "brokerage_roster",   # official brokerage roster/staff/agent page
    "google_snippet",     # visible in a Google result snippet
    "office_fallback",    # office intake email from official brokerage site
)

CONFIDENCE_LEVELS = (
    "source_verified",    # read directly from listing/profile/roster source
    "snippet_verified",   # visible verbatim in a search snippet
    "office_fallback",    # official office inbox, not the agent directly
    "pattern_guess",      # constructed/guessed — NEVER sendable by default
)

# Live-send is allowed ONLY for these confidence levels.
SENDABLE_CONFIDENCES = frozenset(
    {"source_verified", "snippet_verified", "office_fallback"}
)


def allow_pattern_guess_sends() -> bool:
    """Future explicit opt-in for pattern-guessed emails. Default: OFF."""
    return os.environ.get("ALLOW_PATTERN_GUESS_SENDS", "").lower().strip() == "true"


def email_is_sendable(confidence: str) -> bool:
    if confidence in SENDABLE_CONFIDENCES:
        return True
    if confidence == "pattern_guess" and allow_pattern_guess_sends():
        return True
    return False


# ── Email extraction helpers ───────────────────────────────────────────────────

EMAIL_RE  = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
MAILTO_RE = re.compile(r"mailto:([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})",
                       re.IGNORECASE)

# Domains that are portals/free-mail, never a brokerage business address —
# gmail etc. excluded per existing pipeline policy (business email only).
SKIP_DOMAINS = {
    "zillow.com", "realtor.com", "redfin.com", "homes.com", "trulia.com",
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com",
    "aol.com", "example.com", "sentry.io", "wixpress.com", "godaddy.com",
}


def is_plausible_business_email(email: str) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.split("@")[-1].lower()
    if domain in SKIP_DOMAINS:
        return False
    # image filenames etc. sometimes match the regex ("x@2x.png")
    if domain.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
        return False
    return True


def extract_emails_from_text(text: str) -> list:
    """All plausible business emails visible in text, mailto: links first."""
    if not text:
        return []
    found, seen = [], set()
    for match in MAILTO_RE.findall(text) + EMAIL_RE.findall(text):
        email = match.lower().strip(" .,;:")
        if email not in seen and is_plausible_business_email(email):
            seen.add(email)
            found.append(email)
    return found
