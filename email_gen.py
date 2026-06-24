import anthropic
import logging
import random
from config import ANTHROPIC, EMAIL

log = logging.getLogger(__name__)


def calculate_agent_commission(list_price: float, rate: float = 0.05) -> float:
    """Estimate agent commission — typically 5% split 2.5/2.5."""
    return round(list_price * rate)


def generate_emails(listing: dict, offer: dict) -> list:
    """
    Use Claude API to generate 4 unique email variations per property.
    Includes explicit agent commission callout — proven conversion driver.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC["api_key"])

    address = listing.get("address", "the property")
    agent_name = listing.get("listing_agent", "there")
    city = listing.get("city", "")
    state = listing.get("state", "")
    dom = listing.get("days_on_market", 0)
    list_price = offer.get("list_price", 0)
    owner_finance_offer = offer.get("owner_finance_offer", 0)
    cash_offer = offer.get("cash_offer", 0)
    monthly_payment = offer.get("monthly_payment_estimate", 0)
    offer_type = offer.get("offer_type", "owner_finance")

    # Agent commission calculation
    agent_commission = calculate_agent_commission(list_price)
    agent_commission_fmt = f"${agent_commission:,}"

    # Clean agent name to first name only
    first_name = agent_name.split()[0] if agent_name and agent_name != "there" else "there"

    prompt = f"""You are a real estate wholesaler writing to a listing agent about their stale listing.

Property: {address}, {city}, {state}
List Price: ${list_price:,}
Days on Market: {dom}
Agent First Name: {first_name}
Estimated Agent Commission: {agent_commission_fmt}

Our Owner Finance Offer: ${owner_finance_offer:,} (seller gets near full price)
Our Cash Offer: ${cash_offer:,} (fast close, as-is, no repairs)
Monthly Payment if Owner Finance: ~${monthly_payment:,}/mo
Primary Offer Type: {offer_type}

Write {ANTHROPIC["email_variations"]} completely different email variations to this listing agent.

Each email MUST:
1. Be 3-5 sentences max — short, punchy, human
2. Feel handwritten — NOT like a template or mass email
3. Lead with the agent's pain (stale listing, seller frustrated, commission at risk)
4. Explicitly mention the agent commission is PROTECTED and PAID IN FULL
   - Use the exact amount: {agent_commission_fmt}
   - Frame it as: their {agent_commission_fmt} commission is covered/protected/guaranteed
5. Mention we close in 14 days or less, as-is, no contingencies
6. For owner finance: seller gets NEAR FULL LIST PRICE
7. For cash: emphasize speed and certainty
8. Soft CTA — just asking if they're open to a conversation
9. NO subject line — body only
10. Sign off: Michael | 229 Holdings LLC | 229homebuyers.com

Vary tone across 4 emails:
- Email 1: Direct and confident — lead with commission protection
- Email 2: Empathetic — acknowledge the frustration of a stale listing
- Email 3: Curiosity-driven — open with a question
- Email 4: Ultra short — 2-3 sentences max, still mention commission

Return ONLY a JSON array with 4 objects, each with keys "variation" (1-4) and "body".
No markdown, no explanation, just the raw JSON array."""

    try:
        response = client.messages.create(
            model=ANTHROPIC["model"],
            max_tokens=ANTHROPIC["max_tokens"],
            messages=[{"role": "user", "content": prompt}]
        )

        raw = response.content[0].text.strip()

        # Clean JSON if needed
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        import json
        emails = json.loads(raw)

        # Add subject lines and metadata
        subjects = EMAIL["subject_lines"]
        for i, email in enumerate(emails):
            subject = subjects[i % len(subjects)]
            email["subject"] = subject.replace("{address}", address)
            email["address"] = address
            email["agent_email"] = listing.get("agent_email")
            email["agent_phone"] = listing.get("agent_phone")
            email["market"] = listing.get("market")
            email["agent_commission"] = agent_commission

        log.info(f"Generated {len(emails)} email variations for {address}")
        return emails

    except Exception as e:
        log.error(f"Email generation failed for {address}: {e}")
        return []


def pick_email(emails: list) -> dict:
    """Randomly pick one of the 4 generated email variations to send."""
    if not emails:
        return {}
    return random.choice(emails)
