import os

# ─── MARKETS ───────────────────────────────────────────────────────────────────
MARKETS = {
      "memphis": {
                "city": "Memphis",
                "state": "TN",
                "zip_codes": ["38103","38104","38105","38106","38107","38108","38109","38111","38112","38114","38115","38116","38117","38118","38119","38120","38122","38125","38126","38127","38128","38132","38134","38135","38138","38139","38141"],
                "gmail_user": os.environ.get("GMAIL_USER_MEMPHIS"),
                "gmail_app_password": os.environ.get("GMAIL_APP_PASSWORD_MEMPHIS"),
                "ghl_phone_number": os.environ.get("GHL_PHONE_MEMPHIS"),  # 901 number
                "min_price": 50000,
                "max_price": 250000,
      },
      "birmingham": {
                "city": "Birmingham",
                "state": "AL",
                "zip_codes": ["35203","35204","35205","35206","35207","35208","35209","35210","35211","35212","35213","35214","35215","35216","35217","35218","35221","35222","35223","35224","35226","35228","35233","35234","35235","35242","35244"],
                "gmail_user": os.environ.get("GMAIL_USER_BIRMINGHAM"),
                "gmail_app_password": os.environ.get("GMAIL_APP_PASSWORD_BIRMINGHAM"),
                "ghl_phone_number": os.environ.get("GHL_PHONE_BIRMINGHAM"),  # 205 number
                "min_price": 40000,
                "max_price": 200000,
      },
}

# ─── SCREENING CRITERIA (Zompz Deal Finder logic) ──────────────────────────────
SCREEN = {
      "min_dom": 30,               # Minimum days on market
      "max_views_per_day": 5,      # Max Zillow views/day (low = motivated)
      "max_price_cuts": 99,        # Any price cut is a signal
      "min_price_cut_pct": 2.0,    # Minimum % price reduction
      "conditions": ["Fair", "Poor"],  # Target distressed conditions
      "skip_keywords": ["auction", "foreclosure", "hoa", "short sale"],
}

# ─── OFFER LOGIC (KISS Formula) ───────────────────────────────────────────────
OFFER = {
      "owner_finance_arv_pct": 0.90,   # Owner finance: offer 90% of list
      "cash_arv_pct": 0.65,            # Cash: offer 65% of ARV
      "assignment_fee": 10000,          # Target assignment fee
      "repair_estimate_per_sqft": 25,   # Rough repair estimate
}

# ─── EMAIL SETTINGS ────────────────────────────────────────────────────────────
EMAIL = {
      "daily_limit_per_account": 15,   # Max emails per Gmail account per day
      "send_hour_am": 8,               # AM batch send hour
      "send_hour_pm": 14,              # PM batch send hour
      "delay_between_sends_sec": 90,   # Seconds between each email
      "subject_lines": [
                "Quick question about {address}",
                "Interested in {address} — cash offer",
                "Offer for your listing at {address}",
                "{address} — can we close in 14 days?",
      ],
}

# ─── GHL SETTINGS ──────────────────────────────────────────────────────────────
GHL = {
      "api_key": os.environ.get("GHL_API_KEY"),
      "location_id": os.environ.get("GHL_LOCATION_ID"),
      "text_delay_minutes": 30,        # Send text 30 min after email
      "pipeline_name": "On-Market Wholesale",
      "stage_name": "Offer Sent",
}

# ─── ANTHROPIC ─────────────────────────────────────────────────────────────────
ANTHROPIC = {
      "api_key": os.environ.get("ANTHROPIC_API_KEY"),
      "model": "claude-sonnet-4-6",
      "max_tokens": 1000,
      "email_variations": 4,
}

# ─── DEDUP ─────────────────────────────────────────────────────────────────────
DEDUP = {
      "log_file": "data/sent_leads.json",  # Local dedup log
}
