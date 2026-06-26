"""
229 Holdings LLC — Pipeline Config
Flip Man KISS Method
"""

# Markets
MARKETS = {
    "memphis": {
        "city": "Memphis",
        "state": "TN",
        "zip_codes": [],
        "price_min": 30000,
        "price_max": 500000,
    },
    "birmingham": {
        "city": "Birmingham",
        "state": "AL",
        "zip_codes": [],
        "price_min": 30000,
        "price_max": 500000,
    },
}

# Owner Finance band
OF_MIN_PRICE = 30000
OF_MAX_PRICE = 80000

# Owner Finance structure (Flip Man KISS)
# 5% down = agent commission (no separate % or flat fee)
OF_DOWN_PCT        = 0.05   # 5% down = goes to agent at closing
OF_NUM_PAYMENTS    = 100    # 100 monthly payments
OF_SELLER_RATE     = 0.0    # 0% interest to seller
OF_BUYER_DOWN_PCT  = 0.12   # charge end buyer 12% down
OF_BUYER_RATE      = 0.12   # 12% interest to end buyer
OF_BUYER_TERM_YRS  = 10     # 10 year term to end buyer
OF_EARNEST         = 500
OF_CLOSE_DAYS      = 21
OF_DD_DAYS         = 10

# Cash Lowball tiers (% of list price)
KISS_TIERS = {
    75000:   20,   # sub-$75k = 20% (should be OF, fallback only)
    150000:  40,   # $80k–$150k = 40%
    300000:  50,   # $150k–$300k = 50%
    750000:  60,   # $300k–$750k = 60%
    1500000: 65,   # $750k–$1.5M = 65%
}

# Cash Lowball agent commission (different from OF)
CL_AGENT_COMM_PCT = 0.06   # 6% of cash offer
CL_FLAT_FEE       = 1000   # $1,000 flat fee
ASSIGNMENT_FEE    = 10000  # $10k assignment fee

# Pitch check baseline
AT_LIST_PCT = 0.03   # agent must net >= 3% of list price

# Scraper
DISTRESSED_KEYWORDS = [
    "as is", "as-is", "fixer", "investor special", "tlc", "needs work",
    "handyman", "cash only", "price reduced", "motivated", "sold as-is",
    "rehab", "investor", "opportunity", "potential", "sweat equity",
]
MIN_SQFT      = 750
MAX_VIEWS_DAY = 25
MIN_DOM       = 30

# Dedup
AGENT_COOLDOWN_DAYS  = 7
AGENT_LIFETIME_CAP   = 3
BUSINESS_HOURS_START = 8
BUSINESS_HOURS_END   = 16
# Playwright browser settings
SCREEN = {
    "width": 1920,
    "height": 1080,
}
