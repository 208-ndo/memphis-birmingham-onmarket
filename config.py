"""
229 Holdings LLC — Pipeline Config
Two offer lanes: Owner Finance + Cash Lowball (MAO + Visible Spread)
"""
import os

# ─── Markets ───────────────────────────────────────────────────────────────────
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
}

# ─── GHL ───────────────────────────────────────────────────────────────────────
GHL = {
    "api_key":     os.environ.get("GHL_API_KEY", ""),
    "location_id": os.environ.get("GHL_LOCATION_ID", ""),
}

# ─── Email ─────────────────────────────────────────────────────────────────────
EMAIL = {
    "daily_limit":      15,
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
OF_MIN_PRICE      = 30000
OF_MAX_PRICE      = 80000
OF_DOWN_PCT       = 0.05
OF_NUM_PAYMENTS   = 100
OF_SELLER_RATE    = 0.0
OF_BUYER_DOWN_PCT = 0.12
OF_BUYER_RATE     = 0.08
OF_BUYER_TERM_YRS = 30
OF_EARNEST        = 500
OF_CLOSE_DAYS     = 21
OF_DD_DAYS        = 10

# ─── Cash Lowball — Buyer MAO ──────────────────────────────────────────────────
BUYER_MAO_MULTIPLIER = 0.90          # Buyer MAO = ARV * 0.90
REPAIR_MULTIPLIER    = 2.0           # effective_repairs * 2 in buyer MAO
ASSIGNMENT_FEE_MIN        = 7_500
ASSIGNMENT_FEE_MIN_SMALL = 5_000   # small deal: buyer_mao < 50k
ASSIGNMENT_FEE_MAX_SMALL = 7_500
ASSIGNMENT_FEE_MAX   = 30_000
ASSIGNMENT_FEE_PCT   = 0.08          # ARV * 8%, clamped to min/max
CLOSING_BUFFER_MIN   = 2_500
CLOSING_BUFFER_PCT   = 0.02          # max(2500, buyer_mao * 2%)
INITIAL_OFFER_LOW    = 0.85          # initial = final_contract_mao * 85–92%
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
MIN_DOM       = 30

AGENT_COOLDOWN_DAYS  = 7
AGENT_LIFETIME_CAP   = 3
BUSINESS_HOURS_START = 8
BUSINESS_HOURS_END   = 16
SCREEN = {"width": 1920, "height": 1080}
