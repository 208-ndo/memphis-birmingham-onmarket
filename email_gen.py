import anthropic
import logging
import random
from config import ANTHROPIC, EMAIL

log = logging.getLogger(__name__)


def generate_emails(listing: dict, offer: dict) -> list:
    """
    Use Claude API to generate 4 unique email variations per property.
    Based on Zompz listing agent contact skill — each email must feel
    handwritten, unique, and lead with solving the agent's problem.
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

    # Clean agent name to first name only
    first_name = agent_name.split()[0] if agent_name and agent_name != "there" else "there"

    prompt = f"""You are a real estate wholesaler writing to a listing agent about their stale listing.

Property: {address}, {city}, {state}
List Price: ${list_price:,}
Days on Market: {dom}
Our Owner Finance Offer: ${owner_finance_offer:,} (seller gets near full price, we pay over time)
Our Cash Offer: ${cash_offer:,} (fast close, as-is, no repairs)
Monthly Payment if Owner Finance: ~${monthly_payment:,}/mo
Agent First Name: {first_name}
Primary Offer Type: {offer_type}

Write {ANTHROPIC["email_variations"]} completely different email variations to this listing agent.
Each email must:
1. Be 3-5 sentences max — short and punchy
2. Feel handwritten and personal, NOT like a template
3. Lead with the agent's pain point (stale listing, seller frustrated, commission at risk)
4. Mention we can close in 14 days or less, as-is, no contingencies
5. For owner finance: emphasize seller gets NEAR FULL LIST PRICE
6. For cash: emphasize speed and certainty
7. End with a simple soft call to action — just asking if they're open to a conversation
8. NO subject line — body only
9. Sign off as: Michael | 229 Holdings LLC | 229homebuyers.com

Vary the tone across the 4 emails:
- Email 1: Direct and confident
- Email 2: Empathetic and understanding  
- Email 3: Curiosity-driven, ask a question
- Email 4: Ultra short, 2-3 sentences max

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

        # Add subject lines from config
        subjects = EMAIL["subject_lines"]
        for i, email in enumerate(emails):
            subject = subjects[i % len(subjects)]
            email["subject"] = subject.replace("{address}", address)
            email["address"] = address
            email["agent_email"] = listing.get("agent_email")
            email["agent_phone"] = listing.get("agent_phone")
            email["market"] = listing.get("market")

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
