"""
Email generator — 229 Holdings LLC
Emails are agent-facing only. No strategy, percentages, or assignment fees exposed.
"""

import re
import json
import random
import logging

log = logging.getLogger(__name__)


def generate_emails(listing: dict, offer: dict) -> list[dict]:
    offer_type = offer.get("offer_type")
    if offer_type == "owner_finance":
        return _gen_of_emails(listing, offer)
    else:
        return _gen_cl_emails(listing, offer)


def _gen_of_emails(listing: dict, offer: dict) -> list[dict]:
    address    = listing.get("address", "the property")
    price      = offer.get("owner_finance_offer", 0)
    dp         = offer.get("down_payment", 0)
    monthly    = offer.get("monthly_payment", 0)
    payments   = offer.get("num_payments", 100)
    agent_comm = offer.get("total_to_agent", 0)
    at_list    = offer.get("at_list_commission", 0)

    prompt = f"""You are a real estate investor writing to a listing agent about their listing.

PROPERTY: {address}
OFFER: Full asking price of ${price:,.0f}
STRUCTURE: ${dp:,.0f} down at closing, ${monthly:,.0f}/month over {payments} months to seller at 0% interest
AGENT GETS: ${agent_comm:,.0f} paid at closing from buyer's down payment
THAT IS: ${agent_comm - at_list:,.0f} MORE than the agent would net on a standard full-price sale

RULES — follow every one:
1. NO em dashes anywhere. Periods and commas only.
2. 3-5 sentences MAX. Short, handwritten feel.
3. NEVER say "seller financing", "owner financing", "creative financing", or any financing type in subject or body.
4. NEVER mention percentages, assignment fees, or wholesaling.
5. Mention exact agent commission: ${agent_comm:,.0f} paid at closing.
6. Mention seller gets full asking price.
7. Soft CTA only: ask where to send written offer.
8. Sign off EXACTLY: Torian Wallace | 901-290-8408
9. Write 4 variations: V1=direct, V2=empathetic, V3=curiosity hook, V4=ultra short (2 sentences max).
10. Each variation must have a DIFFERENT subject line and DIFFERENT opening line.
11. Subject line must be neutral. Example: "Offer on {address}" or "Quick question on {address}". Never hint at the structure.

Return ONLY a JSON array, no markdown, no extra text:
[
  {{"variation": 1, "subject": "...", "body": "..."}},
  {{"variation": 2, "subject": "...", "body": "..."}},
  {{"variation": 3, "subject": "...", "body": "..."}},
  {{"variation": 4, "subject": "...", "body": "..."}}
]"""

    return _call_claude(prompt)


def _gen_cl_emails(listing: dict, offer: dict) -> list[dict]:
    address     = listing.get("address", "the property")
    list_price  = listing.get("list_price", 0) or listing.get("price", 0)
    cash_offer  = offer.get("cash_offer", 0)
    agent_total = offer.get("total_to_agent", 0)
    at_list     = offer.get("at_list_commission", 0)

    prompt = f"""You are a real estate investor writing to a listing agent about their listing.

PROPERTY: {address}
LIST PRICE: ${list_price:,.0f}
CASH OFFER: ${cash_offer:,.0f}
CLOSE: 7-14 days, as-is, no repairs, no contingencies, cash, $500 earnest
AGENT GETS: ${agent_total:,.0f} paid at closing
THAT IS: ${agent_total - at_list:,.0f} MORE than the agent would net on a standard at-list commission

RULES — follow every one:
1. NO em dashes anywhere. Periods and commas only.
2. 3-5 sentences MAX. Short, handwritten feel.
3. Lead with speed and certainty: cash, as-is, close in 14 days.
4. NEVER mention percentages, assignment fees, or wholesaling.
5. Mention exact agent commission: ${agent_total:,.0f} paid at closing.
6. Soft CTA only: ask where to send written offer.
7. Sign off EXACTLY: Torian Wallace | 901-290-8408
8. Write 4 variations: V1=direct, V2=empathetic, V3=curiosity hook, V4=ultra short (2 sentences max).
9. Each variation must have a DIFFERENT subject line and DIFFERENT opening line.

Return ONLY a JSON array, no markdown, no extra text:
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
