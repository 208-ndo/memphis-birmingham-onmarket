"""
229 Holdings LLC — Pipeline Config
Two offer lanes: Owner Finance + Cash Lowball (MAO + Visible Spread)

Phase 2: Little Rock + Oklahoma City are the active production markets.
Memphis and Birmingham are inactive (weak $30k-$80k DOM 30+ inventory per
market_audit.py findings) but their Gmail/GHL secrets are reused as the
sending inboxes for the new markets — no new GitHub Secrets required.
"""
import os

# ─── Active / Inactive Markets ──────────────────────────────────────────────────
# Only markets listed in ACTIVE_MARKETS are processed by main.py's market loop.
ACTIVE_MARKETS = ["little_rock", "oklahoma_city"]

# Kept for reference / dashboard / audit reporting only — not read by main.py's
# send loop. Documents why these markets are currently sidelined.
INACTIVE_MARKETS = {
    "memphis": "Weak $30k-$80k DOM 30+ inventory per market_audit.py — 0 useful OF candidates in low-price bands",
    "birmingham": "Weak $30k-$80k DOM 30+ inventory per market_audit.py — 0 useful OF candidates in low-price bands",
    "cleveland": "Prepared as next email-first test market; inactive until a dry-run Cleveland/Akron-only scrape is approved",
    "akron": "Prepared as next email-first test market; inactive until a dry-run Cleveland/Akron-only scrape is approved",
}

# ─── Send Caps ──────────────────────────────────────────────────────────────────
GLOBAL_DAILY_CAP = 30   # total emails across all inboxes, all markets, per day
PER_INBOX_CAP    = 15   # max emails per Gmail inbox per run

# ─── Markets ───────────────────────────────────────────────────────────────────
# little_rock and oklahoma_city deliberately reuse the existing Memphis/Birmingham
# Gmail + GHL secrets as their sending inboxes (inbox #1 = Memphis secret,
# inbox #2 = Birmingham secret) so no new GitHub Secrets need to be created.
MARKETS = {
    "memphis": {
        "city": "Memphis", "state": "TN", "zip_codes": [],
        "price_min": 30000, "price_max": 500000,
        "min_price": 30000, "max_price": 500000,
        "gmail_user": os.environ.get("GMAIL_USER_MEMPHIS", ""),
        "gmail_app_password": os.environ.get("GMAIL_APP_PASSWORD_MEMPHIS", ""),
        "ghl_phone_number": os.environ.get("GHL_PHONE_MEMPHIS", ""),
    },
    "birmingham": {
        "city": "Birmingham", "state": "AL", "zip_codes": [],
        "price_min": 30000, "price_max": 500000,
        "min_price": 30000, "max_price": 500000,
        "gmail_user": os.environ.get("GMAIL_USER_BIRMINGHAM", ""),
        "gmail_app_password": os.environ.get("GMAIL_APP_PASSWORD_BIRMINGHAM", ""),
        "ghl_phone_number": os.environ.get("GHL_PHONE_BIRMINGHAM", ""),
    },
    "little_rock": {
        "city": "Little Rock", "state": "AR", "zip_codes": [],
        "price_min": 30000, "price_max": 500000,
        "min_price": 30000, "max_price": 500000,
        # Inbox #1 — reuses Memphis Gmail/GHL secrets
        "gmail_user": os.environ.get("GMAIL_USER_MEMPHIS", ""),
        "gmail_app_password": os.environ.get("GMAIL_APP_PASSWORD_MEMPHIS", ""),
        "ghl_phone_number": os.environ.get("GHL_PHONE_MEMPHIS", ""),
        "bounds": {"west": -92.5, "east": -92.0, "south": 34.6, "north": 35.0},
    },
    "oklahoma_city": {
        "city": "Oklahoma City", "state": "OK", "zip_codes": [],
        "price_min": 30000, "price_max": 500000,
        "min_price": 30000, "max_price": 500000,
        # Inbox #2 — reuses Birmingham Gmail/GHL secrets
        "gmail_user": os.environ.get("GMAIL_USER_BIRMINGHAM", ""),
        "gmail_app_password": os.environ.get("GMAIL_APP_PASSWORD_BIRMINGHAM", ""),
        "ghl_phone_number": os.environ.get("GHL_PHONE_BIRMINGHAM", ""),
        "bounds": {"west": -97.7, "east": -97.2, "south": 35.3, "north": 35.7},
    },
    "cleveland": {
        "city": "Cleveland", "state": "OH", "zip_codes": [],
        "price_min": 30000, "price_max": 125000,
        "min_price": 30000, "max_price": 125000,
        "min_dom": 30,
        "email_first_test_market": True,
        "live_send_enabled": False,
        "gmail_user": "",
        "gmail_app_password": "",
        "ghl_phone_number": "",
        "bounds": {"west": -81.95, "east": -81.45, "south": 41.35, "north": 41.65},
    },
    "akron": {
        "city": "Akron", "state": "OH", "zip_codes": [],
        "price_min": 30000, "price_max": 125000,
        "min_price": 30000, "max_price": 125000,
        "min_dom": 30,
        "email_first_test_market": True,
        "live_send_enabled": False,
        "gmail_user": "",
        "gmail_app_password": "",
        "ghl_phone_number": "",
        "bounds": {"west": -81.65, "east": -81.35, "south": 40.95, "north": 41.2},
    },
}

# ─── GHL ───────────────────────────────────────────────────────────────────────
GHL = {
    "api_key":     os.environ.get("GHL_API_KEY", ""),
    "location_id": os.environ.get("GHL_LOCATION_ID", ""),
}

# ─── Email ─────────────────────────────────────────────────────────────────────
EMAIL = {
    "daily_limit":      PER_INBOX_CAP,
    "stagger_min_secs": 60,
    "stagger_max_secs": 180,
}

# ─── Dedup ─────────────────────────────────────────────────────────────────────
DEDUP = {
    "log_file":             "data/dedup_log.json",
    "cooldown_days":        7,
    "lifetime_cap":         3,
    "business_hours_start": 8,
    "business_hours_end":   16,
}

# ─── Owner Finance ─────────────────────────────────────────────────────────────
# Production band stays $30k-$80k. $80k-$100k is audit-only — never auto-sent.
OF_MIN_PRICE       = 30000
OF_MAX_PRICE       = 80000
OF_AUDIT_MIN_PRICE = 80000
OF_AUDIT_MAX_PRICE = 100000   # audit-only band, not production OF
OF_DOWN_PCT        = 0.05
OF_NUM_PAYMENTS    = 100
OF_SELLER_RATE     = 0.0
OF_BUYER_DOWN_PCT  = 0.12
OF_BUYER_RATE      = 0.08
OF_BUYER_TERM_YRS  = 30
OF_EARNEST         = 500
OF_CLOSE_DAYS      = 21
OF_DD_DAYS         = 10

# ─── Cash Lowball — Buyer MAO ──────────────────────────────────────────────────
# Cash offers require ARV. No-ARV cash leads remain manual review / no-send — unchanged.
BUYER_MAO_MULTIPLIER = 0.90          # Buyer MAO = ARV * 0.90
REPAIR_MULTIPLIER    = 2.0           # effective_repairs * 2 in buyer MAO
ASSIGNMENT_FEE_MIN        = 7_500
ASSIGNMENT_FEE_MIN_SMALL = 5_000   # small deal: buyer_mao < 50k
ASSIGNMENT_FEE_MAX_SMALL = 7_500
ASSIGNMENT_FEE_MAX   = 30_000
ASSIGNMENT_FEE_PCT   = 0.08          # ARV * 8%, clamped to min/max
CLOSING_BUFFER_MIN   = 2_500
CLOSING_BUFFER_PCT   = 0.02          # max(2500, buyer_mao * 2%)
INITIAL_OFFER_LOW    = 0.85          # initial offer = final_contract_mao * 85%
INITIAL_OFFER_HIGH   = 0.90   # max counter
TRUE_WALKAWAY_PCT    = 1.00   # internal only — do not share with agent
CASH_MAX_AUTO        = 500_000       # above this: manual review

# ─── Visible Spread Requirements ───────────────────────────────────────────────
# visible_spread = list_price - (contract_price + assignment_fee)
SPREAD_RULES = [
    # (min_price, max_price, flat_min, pct_of_list)
    (0,       80_000,  15_000, 0.25),
    (80_000,  150_000, 25_000, 0.20),
    (150_000, 300_000, 30_000, 0.15),
    (300_000, 500_000, 40_000, 0.12),
]

# ─── Commission (public-facing) ────────────────────────────────────────────────
COMMISSION_LANGUAGE = (
    "Seller to pay any listing broker compensation per the existing listing agreement "
    "from seller proceeds at closing. Buyer is not offering an agent bonus."
)

# ─── Scraper ───────────────────────────────────────────────────────────────────
DISTRESSED_KEYWORDS = [
    "as is", "as-is", "fixer", "investor special", "tlc", "needs work",
    "handyman", "cash only", "price reduced", "motivated", "sold as-is",
    "rehab", "investor", "opportunity", "potential", "sweat equity",
]
MIN_SQFT      = 750
MAX_VIEWS_DAY = 25
MIN_DOM       = 30   # hard rule — never lowered, never made 7-29 auto-send eligible

def _int_env_override(env_name: str, default: int) -> int:
    """Read an optional integer override from a workflow input env var.
    Falls back to the given default if unset, blank, or unparsable."""
    raw = os.environ.get(env_name, "")
    try:
        return int(raw) if raw.strip() else default
    except ValueError:
        return default


# ─── Apify Safety ──────────────────────────────────────────────────────────────
# BUDGETS ARE NOW SPLIT (2026-07-02 fix): the old single shared cap let
# Cleveland's email enrichment eat Akron's Zillow band budget (Cleveland used
# 3 Zillow + 5 Google = 8 of 10, Akron got 2 Zillow calls and band 3 was
# skipped). Zillow scraping and email enrichment now have independent caps so
# they cannot starve each other. MAX_APIFY_RUNS_PER_WORKFLOW remains as a
# pure EMERGENCY global hard stop across all actors combined.

# Zillow scrape calls: 3 bands x 2 markets = 6 minimum for the standard
# Cleveland/Akron (or Memphis/Birmingham) 2-market run.
MAX_ZILLOW_CALLS_PER_WORKFLOW = _int_env_override(
    "MAX_ZILLOW_CALLS_OVERRIDE", 6
)

# Emergency global hard stop — every actor call (Zillow + Google + future)
# still counts against this. Must be >= zillow cap + email cap for a normal
# run to complete (6 + 10 = 16); 20 leaves headroom without allowing runaway.
MAX_APIFY_RUNS_PER_WORKFLOW = _int_env_override(
    "MAX_APIFY_RUNS_OVERRIDE", 20
)

# ─── Price-Reduced OF Variant ───────────────────────────────────────────────────
# When True: $30k-$80k OF bands get a second Apify pass with isReducedPrice=True.
# This surfaces listings with at least one price cut — a motivated-seller signal.
# Cost: adds 2 extra actor calls per market (one per OF band pair), so 4 extra
#       calls total for 2 active markets, pushing budget from ~10 to ~14/run.
# Default: False — base search only, budget stays within MAX_APIFY_RUNS_PER_WORKFLOW.
# Enable only after confirming base search produces sufficient leads.
ENABLE_PRICE_REDUCED_OF_VARIANT = False


# ─── Email Enrichment Budget ────────────────────────────────────────────────────
# Separate, lower sub-cap on Google email-search Apify calls specifically.
# This is IN ADDITION TO MAX_APIFY_RUNS_PER_WORKFLOW above — a Google call must
# pass BOTH checks (shared total budget AND this email-specific cap) before
# it is allowed to run. Overridable per-run via the max_email_enrichment_calls
# workflow input (passed through as MAX_EMAIL_ENRICHMENT_CALLS_OVERRIDE).
MAX_EMAIL_ENRICHMENT_CALLS_PER_WORKFLOW = _int_env_override(
    "MAX_EMAIL_ENRICHMENT_CALLS_OVERRIDE", 10
)

# Per-market slice of the email budget (2026-07-02 fix) so market #1 cannot
# consume the whole email budget before market #2 runs. 5 per market x 2
# markets = the 10-call workflow cap above.
MAX_EMAIL_ENRICHMENT_CALLS_PER_MARKET = _int_env_override(
    "MAX_EMAIL_ENRICHMENT_CALLS_PER_MARKET_OVERRIDE", 5
)

# ─── Lead Shortlist Before Enrichment ───────────────────────────────────────────
# Leads are scored (KISS/Zompz-style signals — price band, DOM, views/day,
# photo count, distress keywords, etc.) and ranked BEFORE any Google email
# call is made. Only the top N scored leads per market are ever sent to email
# enrichment; the rest are kept for the dashboard/log with Email: NONE unless
# Zillow itself already supplied an email. Overridable via the
# max_leads_to_enrich workflow input (MAX_LEADS_TO_ENRICH_OVERRIDE).
MAX_LEADS_TO_ENRICH_PER_WORKFLOW = _int_env_override(
    "MAX_LEADS_TO_ENRICH_OVERRIDE", 10
)


AGENT_COOLDOWN_DAYS  = 7
AGENT_LIFETIME_CAP   = 3
BUSINESS_HOURS_START = 8
BUSINESS_HOURS_END   = 16
SCREEN = {"width": 1920, "height": 1080}
