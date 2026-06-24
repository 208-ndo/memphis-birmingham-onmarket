import anthropic
import logging
import random
from config import ANTHROPIC, EMAIL

log = logging.getLogger(__name__)

def calculate_agent_commission(list_price: float, rate: float = 0.06) -> float:
    """
    Agent commission — 6% of list price.
    (Was incorrectly set to 5% — corrected to match offer.py and Flip Man method.)
    """
    return round(list_price * rate)

def generate_emails(listing: dict, offer: dict) -> list:
    """
    Use Claude API to generate 4 unique email variations per property.
    Follows Flip Man / Zompz skill rules exactly:
    - Every email unique — rotate skeletons, subjects, hooks
    - Agent commission explicitly called out with exact dollar amount
    - No em dashes anywhere — periods and commas only
    - Never "seller financing" in subject line for owner finance deals
    - Short punchy 3-5 sentences max
    - Soft CTA only — just asking where to send the offer
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC["api_key"])

    address      = listing.get("address", "the property")
    agent_name   = listing.get("listing_agent", "there")
    city         = listing.get("city", "")
    state        = listing.get("state", "")
    dom          = listing.get("days_on_market", 0)
    list_price   = offer.get("list_price", 0)
    owner_finance_offer = offer.get("owner_finance_offer", 0)
    cash_offer   = offer.get("cash_offer", 0)
    monthly_payment = offer.get("monthly_payment", 0) or offer.get("monthly_payment_estimate", 0)
    offer_type   = offer.get("offer_type", "owner_finance")
    total_to_agent   = offer.get("total_to_agent", 0)
    at_list_commission = offer.get("at_list_commission", 0)
    down_payment = offer.get("down_payment", 0)
    agent_flat_fee = offer.get("agent_flat_fee", 1000)

    # ── Agent commission callout — 6% per Flip Man method ──
    agent_commission   = calculate_agent_commission(list_price)  # 6%
    total_agent_payout = total_to_agent or (agent_commission + agent_flat_fee)
    agent_payout_fmt   = f"${int(total_agent_payout):,}"
    at_list_fmt        = f"${int(at_list_commission):,}"

    # Clean agent name to first name only
    first_name = agent_name.split()[0] if agent_name and agent_name != "there" else "there"

    # Subject line rules per Flip Man skill:
    # - Owner finance = NEUTRAL subject — just address, NEVER "seller financing"
    # - Cash = can mention offer type
    if offer_type == "owner_finance":
        subject_options = [
            f"Offer on {address}",
            f"Quick offer on {address}",
            f"Offer for your listing at {address}",
            f"{address} — offer",
            f"Your listing at {address}",
            f"Interested in {address}",
        ]
    else:
        subject_options = [
            f"Cash offer on {address}",
            f"Quick cash offer on {address}",
            f"{address} — cash offer",
            f"Offer on {address}",
            f"Cash offer for {address}",
            f"{address} — can we close in 14 days?",
        ]

    prompt = f"""You are a real estate wholesaler writing to a listing agent about their stale listing.

Property: {address}, {city}, {state}
List Price: ${list_price:,}
Days on Market: {dom}
Agent First Name: {first_name}
Offer Type: {offer_type}

OFFER DETAILS:
- Owner Finance Offer: ${owner_finance_offer:,} (FULL list price — seller gets full asking price)
- Down Payment: ${down_payment:,} (5% down — covers agent commission at closing)
- Monthly Payment: ${monthly_payment:,}/mo for 100 months at 0% interest
- Cash Offer (if applicable): ${cash_offer:,}
- Total Agent Payout: {agent_payout_fmt} (6% commission + flat fee)
- Agent Commission at Full-Price Sale (buyer side only, 3%): {at_list_fmt}
- NOTE: Agent gets MORE from our offer than from a traditional full-price sale

Write {ANTHROPIC["email_variations"]} completely UNIQUE email variations to this listing agent.

HARD RULES — NEVER break these:
1. NO em dashes anywhere. Use periods and commas ONLY. Never use — or –
2. NEVER mention "seller financing" or "owner financing" in the subject line
3. Each email must be 3-5 sentences MAX. Short and punchy.
4. Feel completely handwritten — NOT like a template or mass email
5. Lead with the agent's pain — stale listing, commission at risk, seller frustrated
6. Explicitly say agent will be paid {agent_payout_fmt} — more than the {at_list_fmt} they'd net from a full-price sale
7. For owner finance: seller gets FULL LIST PRICE — emphasize this. The seller wins.
8. For cash: emphasize speed, as-is, no contingencies, certainty of close
9. CTA = soft. Just asking where to send the written offer. Nothing pushy.
10. NO subject line in the body — body only
11. Sign off EXACTLY as: Michael | 229 Holdings LLC | 229homebuyers.com
12. Inject 1 real listing fact as a personal hook (days on market, price, condition language)
13. Never reveal internal signals (views/day, your spread, the word "motivated")
14. Sound like a real person texting from their phone — not a corporation

Vary tone and structure across 4 emails:
- Email 1: Direct and confident — lead with commission protection. Agent made whole, seller made whole.
- Email 2: Empathetic — acknowledge the frustration of {dom} days sitting. You have a solution.
- Email 3: Curiosity hook — open with a question. Pull them in before revealing the offer.
- Email 4: Ultra short — 2-3 sentences MAX. Still mention commission and where to send the offer.

Return ONLY a JSON array with 4 objects, each with keys "variation" (1-4) and "body".
No markdown, no explanation, just the raw JSON array."""

    try:
        response = client.messages.create(
            model=ANTHROPIC["model"],
            max_tokens=ANTHROPIC["max_tokens"],
            messages=[{"role": "user", "content": prompt}]
        )

        raw = response.content[0].text.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        import json
        emails = json.loads(raw)

        # Assign subject lines — rotate from subject options
        for i, email in enumerate(emails):
            email["subject"]     = subject_options[i % len(subject_options)]
            email["address"]     = address
            email["agent_email"] = listing.get("agent_email")
            email["agent_phone"] = listing.get("agent_phone")
            email["market"]      = listing.get("market")
            email["offer_type"]  = offer_type
            email["total_to_agent"] = total_agent_payout

        # Final check — strip any em dashes that slipped through
        for email in emails:
            body = email.get("body", "")
            body = body.replace("\u2014", "-").replace("\u2013", "-")
            email["body"] = body

        log.info(f"Generated {len(emails)} email variations for {address} ({offer_type})")
        return emails

    except Exception as e:
        log.error(f"Email generation failed for {address}: {e}")
        return []


def pick_email(emails: list) -> dict:
    """Randomly pick one of the 4 generated email variations to send."""
    if not emails:
        return {}
    return random.choice(emails)
