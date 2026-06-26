"""
229 Holdings LLC — Pipeline Config
Flip Man KISS Method
"""
import os

# ─── Markets ───────────────────────────────────────────────────────────────────
MARKETS = {
    "memphis": {
        "city": "Memphis",
        "state": "TN",
        "zip_codes": [],
        "price_min": 30000,
        "price_max": 500000,
        "gmail_user": os.environ.get("GMAIL_USER_MEMPHIS", ""),
        "gmail_app_password": os.environ.get("GMAIL_APP_PASSWORD_MEMPHIS", ""),
        "ghl_phone_number": os.environ.get("GHL_PHONE_MEMPHIS", ""),
    },
    "birmingham": {
        "city": "Birmingham",
        "state": "AL",
        "zip_codes": [],
        "price_min": 30000,
        "price_max": 500000,
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
    "log_file":          "data/dedup_log.json",
    "cooldown_days":     7,
    "lifetime_cap":      3,
    "business_hours_start": 8,
    "business_hours_end":   16,
}

# ─── Owner Finance (Flip Man KISS) ─────────────────────────────────────────────
# 5% down = agent commission — nothing else
OF_MIN_PRICE      = 30000
OF_MAX_PRICE      = 80000
OF_DOWN_PCT       = 0.05   # 5% down = agent commission at closing
OF_NUM_PAYMENTS   = 100    # 100 monthly payments to seller
OF_SELLER_RATE    = 0.0    # 0% interest to seller
OF_BUYER_DOWN_PCT = 0.12   # charge end buyer 12% down
OF_BUYER_RATE     = 0.12   # 12% interest charged to end buyer
OF_BUYER_TERM_YRS = 10     # 10 year term for end buyer
OF_EARNEST        = 500
OF_CLOSE_DAYS     = 21
OF_DD_DAYS        = 10

# ─── Cash Lowball KISS Tiers ───────────────────────────────────────────────────
KISS_TIERS = {
    75000:   20,   # sub-$75k fallback (should be OF)
    150000:  40,   # $80k–$150k
    300000:  50,   # $150k–$300k
    750000:  60,   # $300k–$750k
    1500000: 65,   # $750k–$1.5M
}

# Cash lowball agent commission (different from OF — OF is just 5% down)
CL_AGENT_COMM_PCT = 0.06
CL_FLAT_FEE       = 1000
ASSIGNMENT_FEE    = 10000
AT_LIST_PCT       = 0.03

# ─── Scraper ───────────────────────────────────────────────────────────────────
DISTRESSED_KEYWORDS = [
    "as is", "as-is", "fixer", "investor special", "tlc", "needs work",
    "handyman", "cash only", "price reduced", "motivated", "sold as-is",
    "rehab", "investor", "opportunity", "potential", "sweat equity",
]
MIN_SQFT      = 750
MAX_VIEWS_DAY = 25
MIN_DOM       = 30

# Keep legacy flat names for backwards compat
AGENT_COOLDOWN_DAYS  = 7
AGENT_LIFETIME_CAP   = 3
BUSINESS_HOURS_START = 8
BUSINESS_HOURS_END   = 16

# ─── Playwright ────────────────────────────────────────────────────────────────
SCREEN = {
    "width":  1920,
    "height": 1080,
}
