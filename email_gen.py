"""
Email generator — Flip Man KISS Method
Owner Finance: 5% down = agent commission (no 6% + flat fee)
Cash Lowball: 6% of offer + $1,000 flat fee
"""

import os
import re
import json
import random
import logging

log = logging.getLogger(__name__)

SUBJECTS_OF = [
    "Offer on {address}",
    "Quick offer for you — {address}",
    "Your listing at {address}",
    "Interested in {address}",
]

SUBJECTS_CL = [
    "Cash offer on {address}",
    "Quick cash offer — {address}",
    "Cash offer ready — {address}",
    "Can we close {address} in 14 days?",
]


def generate_emails(listing: dict, offer: dict) -> list[dict]:
    offer_type = offer.get("offer_type")
    if offer_type == "owner_finance":
        return _gen_of_emails(listing, offer)
    else:
        return _gen_cl_emails(listing, offer)


def _gen_of_emails(listing: dict, offer: dict) -> list[dict]:
    address     = listing.get("address", "the property")
    price       = offer.get("owner_finance_offer", 0)
    dp          = offer.get("down_payment", 0)
    dp_pct      = offer.get("down_pct", 5)
    monthly     = offer.get("monthly_payment", 0)
    payments    = offer.get("num_payments", 100)
    agent_comm  = offer.get("total_to_agent", 0)
    at_list     = offer.get("at_list_commission", 0)

    prompt = f"""You are a real estate wholesaler writing to a listing agent about their stale listing.

OFFER TYPE: Creative / Seller Financed
Property: {address}
List Price: ${price:,.0f}
Offer: FULL asking price (${price:,.0f})
Down Payment: ${dp:,.0f} ({dp_pct:.0f}% — this covers the agent commission at closing)
Monthly Payment to Seller: ${monthly:,.0f}/mo over {payments} payments at 0% interest
Agent Commission: ${agent_comm:,.0f} — paid from buyer's down payment at closing
At-list comparison (3% of list): ${at_list:,.0f}
Agent nets ${agent_comm - at_list:,.0f} MORE than a traditional full-price sale

HARD RULES:
1. NO em dashes anywhere. Periods and commas only.
2. 3-5 sentences MAX. Short, punchy, handwritten feel.
3. NEVER say "seller financing" or "owner financing" in subject line or body.
4. Call out exact agent commission: ${agent_comm:,.0f} paid from buyer's down payment at closing.
5. Emphasize seller gets FULL asking price of ${price:,.0f}.
6. Soft CTA only: ask where to send written offer.
7. Sign off EXACTLY: Torian Wallace | 901-290-8408
8. V1=direct/confident, V2=empathetic/personal, V3=curiosity hook, V4=ultra short 2-3 sentences only.
9. Each variation must have a different subject line and different opening line.
10. Subject line: neutral only. Example: "Offer on {address}". Never mention financing type.

Return ONLY a JSON array with no markdown:
[
  {{"variation": 1, "subject": "...", "body": "..."}},
  {{"variation": 2, "subject": "...", "body": "..."}},
  {{"variation": 3, "subject": "...", "body": "..."}},
  {{"variation": 4, "subject": "...", "body": "..."}}
]"""

    return _call_claude(prompt)


def _gen_cl_emails(listing: dict, offer: dict) -> list[dict]:
    address      = listing.get("address", "the property")
    list_price   = listing.get("list_price", 0) or listing.get("price", 0)
    cash_offer   = offer.get("cash_offer", 0)
    tier_pct     = offer.get("kiss_tier_pct", 40)
    assign_price = offer.get("assign_price", 0)
    agent_total  = offer.get("total_to_agent", 0)
    at_list      = offer.get("at_list_commission", 0)

    prompt = f"""You are a real estate wholesaler writing to a listing agent about their stale listing.

OFFER TYPE: Cash As-Is
Property: {address}
List Price: ${list_price:,.0f}
Cash Offer: ${cash_offer:,.0f} ({tier_pct}% of list price)
Plan to Sell / Assign Price: ${assign_price:,.0f}
Agent Commission: ${agent_total:,.0f} (6% of cash offer + $1,000 flat fee, paid at closing)
At-list comparison (3% of list): ${at_list:,.0f}
Agent nets ${agent_total - at_list:,.0f} MORE than at-list
Close: 7-14 days | No repairs | No contingencies | Cash | Earnest $500

HARD RULES:
1. NO em dashes. Periods and commas only.
2. 3-5 sentences MAX. Short, punchy, handwritten.
3. Lead with speed and certainty: cash, as-is, close in 14 days.
4. Call out exact commission: ${agent_total:,.0f} paid at closing.
5. Compare to at-list ${at_list:,.0f} — agent wins with your offer.
6. Soft CTA: ask where to send written offer.
7. Sign off EXACTLY: Torian Wallace | 901-290-8408
8. V1=direct/confident, V2=empathetic, V3=curiosity hook, V4=ultra short 2-3 sentences.
9. Each variation must have different subject and different opening line.

Return ONLY a JSON array with no markdown:
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
        # Strip em dashes just in case
        for e in emails:
            e["body"]    = e["body"].replace("\u2014", ",").replace("\u2013", ",")
            e["subject"] = e["subject"].replace("\u2014", ",").replace("\u2013", ",")
        return emails
    except Exception as ex:
        log.error(f"Email generation failed: {ex}")
        return []


def pick_email(emails: list[dict]) -> dict:
    """Pick one email variation for sending."""
    if not emails:
        return {}
    return random.choice(emails)
