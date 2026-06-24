import os

# ─── MARKETS ──────────────────────────────────────────────────────────────────
MARKETS = {
    "memphis": {
        "city": "Memphis",
        "state": "TN",
        "zip_codes": [
            "38103","38104","38105","38106","38107","38108","38109",
            "38111","38112","38114","38115","38116","38117","38118",
            "38119","38120","38122","38125","38126","38127","38128",
            "38132","38134","38135","38138","38139","38141"
        ],
        "gmail_user":         os.environ.get("GMAIL_USER_MEMPHIS"),
        "gmail_app_password": os.environ.get("GMAIL_APP_PASSWORD_MEMPHIS"),
        "ghl_phone_number":   os.environ.get("GHL_PHONE_MEMPHIS"),
        "min_price": 30000,
        "max_price": 250000,
    },
    "birmingham": {
        "city": "Birmingham",
        "state": "AL",
        "zip_codes": [
            "35203","35204","35205","35206","35207","35208","35209",
            "35210","35211","35212","35213","35214","35215","35216",
            "35217","35218","35221","35222","35223","35224","35226",
            "35228","35233","35234","35235","35242","35244"
        ],
        "gmail_user":         os.environ.get("GMAIL_USER_BIRMINGHAM"),
        "gmail_app_password": os.environ.get("GMAIL_APP_PASSWORD_BIRMINGHAM"),
        "ghl_phone_number":   os.environ.get("GHL_PHONE_BIRMINGHAM"),
        "min_price": 30000,
        "max_price": 250000,
    },
}

# ─── SCREENING (Flip Man / Zompz method) ──────────────────────────────────────
SCREEN = {
    "min_dom": 30,
    "max_views_per_day": 20,
    "skip_keywords": [
        "package", "portfolio", "bundle", "auction", "foreclosure",
        "subdivided", "teardown", "tear down", "gutted", "burned",
        "fire damage", "sold individually", "40 property", "bulk"
    ],
    "target_keywords": [
        "as is", "fixer", "investor special", "tlc", "needs work",
        "handyman", "cash only", "price reduced", "motivated",
        "sold as-is", "rehab", "vacant"
    ],
}

# ─── OFFER LOGIC (Flip Man KISS Method) ───────────────────────────────────────
OFFER = {
    # Owner Finance band: $30k-$80k
    "owner_finance_band_max":  80000,
    "owner_finance_down_pct":  0.05,    # 5% down covers agent commission
    "owner_finance_payments":  100,     # 100 monthly payments
    "owner_finance_interest":  0.0,     # 0% interest free

    # Cash band: $80k+ KISS tiers
    "cash_offer_pcts": {
        150000:  0.40,   # $80k-$150k  -> 40%
        300000:  0.50,   # $150k-$300k -> 50%
        750000:  0.60,   # $300k-$750k -> 60%
        1500000: 0.65,   # $750k-$1.5M -> 65%
    },

    # Agent flat fee , ensures pitch holds (total to agent >= 3% at-list)
    "agent_flat_fee_sub50k":   1000,    # sub-$50k listings
    "agent_flat_fee_50_150k":  1500,    # $50k-$150k listings

    # End buyer / assignment
    "buyer_down_pct":          0.12,    # charge end buyer 12% down
    "assignment_fee_target":   10000,   # cash deal target fee

    # Closing terms
    "earnest_money":           500,
    "due_diligence_days":      10,
    "close_days":              21,
}

# ─── EMAIL SETTINGS ───────────────────────────────────────────────────────────
EMAIL = {
    "daily_limit_per_account":   15,
    "send_hour_am":               8,
    "send_hour_pm":              14,
    "delay_between_sends_sec":   90,

    # Subject lines , NO em dashes anywhere (Flip Man hard rule)
    # Owner finance subjects must be neutral , never mention seller/owner financing
    # Cash subjects can reference offer type
    "subject_lines": [
        "Quick question about {address}",
        "Interested in {address}, cash offer",    # FIX: was 'em dash cash offer', now comma
        "Offer for your listing at {address}",
        "{address}, can we close in 14 days?",    # FIX: was em dash, now comma
        "Still available? {address}",
        "{address}, your seller might like this", # FIX: was em dash, now comma
        "We can close {address} this month",
        "Your listing at {address}, have a minute?", # FIX: was em dash, now comma
    ],
}

# ─── GHL ──────────────────────────────────────────────────────────────────────
GHL = {
    "api_key":           os.environ.get("GHL_API_KEY"),
    "location_id":       os.environ.get("GHL_LOCATION_ID"),
    "text_delay_minutes": 5,            # kept for reference; sleep removed from ghl_push.py
    "pipeline_name":     "On-Market Wholesale",
    "stage_name":        "Offer Sent",
}

# ─── ANTHROPIC ────────────────────────────────────────────────────────────────
ANTHROPIC = {
    "api_key":           os.environ.get("ANTHROPIC_API_KEY"),
    "model":             "claude-sonnet-4-6",
    "max_tokens":        1500,          # FIX: was 1000, bumped to 1500 to prevent 4th email truncation
    "email_variations":  4,
}

# ─── DEDUP ────────────────────────────────────────────────────────────────────
DEDUP = {
    "log_file": "data/sent_leads.json",
}
