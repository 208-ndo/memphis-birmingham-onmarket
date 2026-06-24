import os

# ─── MARKETS ──────────────────────────────────────────────────────────────────
MARKETS = {
    "memphis": {
        "city": "Memphis",
        "state": "TN",
        "zip_codes": ["38103","38104","38105","38106","38107","38108","38109","38111","38112","38114","38115","38116","38117","38118","38119","38120","38122","38125","38126","38127","38128","38132","38134","38135","38138","38139","38141"],
        "gmail_user": os.environ.get("GMAIL_USER_MEMPHIS"),
        "gmail_app_password": os.environ.get("GMAIL_APP_PASSWORD_MEMPHIS"),
        "ghl_phone_number": os.environ.get("GHL_PHONE_MEMPHIS"),
        "min_price": 30000,
        "max_price": 250000,
    },
    "birmingham": {
        "city": "Birmingham",
        "state": "AL",
        "zip_codes": ["35203","35204","35205","35206","35207","35208","35209","35210","35211","35212","35213","35214","35215","35216","35217","35218","35221","35222","35223","35224","35226","35228","35233","35234","35235","35242","35244"],
        "gmail_user": os.environ.get("GMAIL_USER_BIRMINGHAM"),
        "gmail_app_password": os.environ.get("GMAIL_APP_PASSWORD_BIRMINGHAM"),
        "ghl_phone_number": os.environ.get("GHL_PHONE_BIRMINGHAM"),
        "min_price": 30000,
        "max_price": 250000,
    },
}

# ─── SCREENING CRITERIA (Zompz / Flip Man method) ─────────────────────────────
SCREEN = {
    "min_dom": 30,
    "max_views_per_day": 25,
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
    # Owner Finance band: $30k–$80k — offer FULL list price
    "owner_finance_band_max": 80000,
    "owner_finance_down_pct": 0.05,      # 5% down covers agent commission
    "owner_finance_payments": 100,        # 100 monthly payments
    "owner_finance_interest": 0.0,        # 0% interest free

    # Cash band: $80k+ — aggressive lowball by price tier
    "cash_offer_pcts": {
        150000: 0.40,    # $80k–$150k  → 40% of value
        300000: 0.50,    # $150k–$300k → 50% of value
        750000: 0.60,    # $300k–$750k → 60% of value
        1500000: 0.65,   # $750k–$1.5M → 65% of value
    },

    # Agent flat fee — must be added so agent nets >= at-list commission
    "agent_flat_fee_sub50k": 1000,
    "agent_flat_fee_50_150k": 1500,

    # End buyer targets for assignment spread
    "buyer_down_pct": 0.12,              # Charge end buyer 12% down
    "assignment_fee_target": 10000,       # Cash deal assignment fee target

    # Closing terms
    "earnest_money": 500,
    "due_diligence_days": 10,
    "close_days": 21,
}

# ─── EMAIL SETTINGS ───────────────────────────────────────────────────────────
EMAIL = {
    "daily_limit_per_account": 15,
    "send_hour_am": 8,
    "send_hour_pm": 14,
    "delay_between_sends_sec": 90,
    "subject_lines": [
        "Quick question about {address}",
        "Interested in {address} — cash offer",
        "Offer for your listing at {address}",
        "{address} — can we close in 14 days?",
    ],
}

# ─── GHL SETTINGS ─────────────────────────────────────────────────────────────
GHL = {
    "api_key": os.environ.get("GHL_API_KEY"),
    "location_id": os.environ.get("GHL_LOCATION_ID"),
    "text_delay_minutes": 5,
    "pipeline_name": "On-Market Wholesale",
    "stage_name": "Offer Sent",
}

# ─── ANTHROPIC ────────────────────────────────────────────────────────────────
ANTHROPIC = {
    "api_key": os.environ.get("ANTHROPIC_API_KEY"),
    "model": "claude-sonnet-4-6",
    "max_tokens": 1000,
    "email_variations": 4,
}

# ─── DEDUP ────────────────────────────────────────────────────────────────────
DEDUP = {
    "log_file": "data/sent_leads.json",
}
