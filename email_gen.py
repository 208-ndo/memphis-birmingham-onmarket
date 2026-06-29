"""
Email generator — 229 Holdings LLC.
Agent-facing copy must not expose internal underwriting or resale math.
"""

import re
import json
import random
import logging

log = logging.getLogger(__name__)

SIGN_OFF = "Michael B. | 229 Holdings LLC"


def generate_emails(listing: dict, offer: dict) -> list[dict]:
    offer_type = offer.get("offer_type")
    if offer_type == "owner_finance":
        return _gen_of_emails(listing, offer)
    elif offer_type == "cash_lowball":
        return _gen_cl_emails(listing, offer)
    return []


def _gen_of_emails(listing: dict, offer: dict) -> list[dict]:
    address   = listing.get("address", "the property")
    price     = offer.get("owner_finance_offer", 0)
    dp        = offer.get("down_payment", 0)
    monthly   = offer.get("monthly_payment", 0)
    payments  = offer.get("num_payments", 100)

    prompt = f"""You are a real estate investor writing to a listing agent about their listing.

PROPERTY: {address}
OFFER: Full asking price of ${price:,.0f}
STRUCTURE: ${dp:,.0f} down at closing (5%), seller carries ${price-dp:,.0f} balance over {payments} monthly payments at 0% interest
COMMISSION: Seller to pay any listing broker compensation per the existing listing agreement from seller proceeds at closing. Buyer is not offering an agent bonus.
CLOSE: 21-30 days | as-is, no repair requests, subject to standard due diligence | $500 earnest | 10-day due diligence

RULES:
1. NO em dashes. Periods and commas only.
2. 3-5 sentences MAX. Short, conversational, handwritten feel.
3. NEVER say "seller financing" or "owner financing" in subject or body.
4. NEVER mention internal resale math, broker compensation amounts, or methodology.
5. DO NOT pitch the agent on their commission. Keep focus on the seller getting full price.
6. Seller gets FULL asking price of ${price:,.0f}.
7. Soft CTA only: ask where to send written offer.
8. Sign off EXACTLY: {SIGN_OFF}
9. Write 4 variations: V1=direct, V2=empathetic, V3=curiosity hook, V4=ultra short (2 sentences max).
10. Each variation must have a DIFFERENT subject line and DIFFERENT opening line.
11. Subject: neutral only. Example: "Offer on {address}". Never hint at structure.

Return ONLY a JSON array, no markdown:
[
  {{"variation": 1, "subject": "...", "body": "..."}},
  {{"variation": 2, "subject": "...", "body": "..."}},
  {{"variation": 3, "subject": "...", "body": "..."}},
  {{"variation": 4, "subject": "...", "body": "..."}}
]"""

    return _call_claude(prompt)


def _gen_cl_emails(listing: dict, offer: dict) -> list[dict]:
    address    = listing.get("address", "the property")
    list_price = listing.get("list_price", 0) or listing.get("price", 0)
    cash_offer = offer.get("cash_offer", 0)

    prompt = f"""You are a real estate investor writing to a listing agent about their listing.

PROPERTY: {address}
LIST PRICE: ${list_price:,.0f}
CASH OFFER: ${cash_offer:,.0f}
COMMISSION: Seller to pay any listing broker compensation per the existing listing agreement from seller proceeds at closing. Buyer is not offering an agent bonus.
CLOSE: 21-30 days | as-is, no repair requests, subject to standard due diligence | Cash | $500 earnest

RULES:
1. NO em dashes. Periods and commas only.
2. 3-5 sentences MAX. Short, conversational.
3. Lead with speed and certainty: cash, as-is, close in 21-30 days.
4. NEVER mention internal underwriting, broker compensation amounts, resale math, or methodology.
5. DO NOT pitch the agent on their commission.
6. Soft CTA only: ask where to send written offer.
7. Sign off EXACTLY: {SIGN_OFF}
8. Write 4 variations: V1=direct, V2=empathetic, V3=curiosity hook, V4=ultra short (2 sentences max).
9. Each variation must have a DIFFERENT subject line and DIFFERENT opening line.

Return ONLY a JSON array, no markdown:
[
  {{"variation": 1, "subject": "...", "body": "..."}},
  {{"variation": 2, "subject": "...", "body": "..."}},
  {{"variation": 3, "subject": "...", "body": "..."}},
  {{"variation": 4, "subject": "...", "body": "..."}}
]"""

    return _call_claude(prompt)


def _call_claude(prompt: str) -> list[dict]:
    try:
        from anthropic import Anthropic
        client = Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r"```json|```", "", raw).strip()
        emails = json.loads(raw)
        for e in emails:
            e["body"]    = e["body"].replace("\u2014", ",").replace("\u2013", ",")
            e["subject"] = e["subject"].replace("\u2014", ",").replace("\u2013", ",")
        return emails
    except Exception as ex:
        log.error(f"Email generation failed: {ex}")
        return []


def pick_email(emails: list[dict]) -> dict:
    if not emails:
        return {}
    return random.choice(emails)
