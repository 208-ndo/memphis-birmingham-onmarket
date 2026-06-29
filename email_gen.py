"""
Deterministic agent email templates for 229 Holdings LLC.
Emails are public-facing and only include the offer terms intended for agents.
"""

import random

SIGN_OFF = "Michael B. | 229 Holdings LLC"
BROKER_COMP_LINE = (
    "Seller to handle any listing broker compensation per the existing listing "
    "agreement from seller proceeds at closing."
)
INVESTMENT_PURPOSE_LINE = "Buyer is purchasing for investment purposes."


def generate_emails(listing: dict, offer: dict) -> list[dict]:
    offer_type = offer.get("offer_type")
    if offer_type == "owner_finance":
        return [_gen_of_email(listing, offer)]
    if offer_type == "cash_lowball":
        return [_gen_cl_email(listing, offer)]
    return []


def _agent_greeting(listing: dict) -> str:
    name = (
        listing.get("agent_name")
        or listing.get("listing_agent")
        or listing.get("agent")
        or ""
    )
    name = str(name).strip()
    return f"Hi {name}," if name else "Hi,"


def _address(listing: dict) -> str:
    return str(listing.get("address") or "the property").strip()


def _money(value) -> str:
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return "$0"


def _number(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _gen_cl_email(listing: dict, offer: dict) -> dict:
    address = _address(listing)
    cash_offer = (
        offer.get("initial_offer")
        or offer.get("cash_offer")
        or offer.get("offer")
        or 0
    )

    body = "\n\n".join(
        [
            _agent_greeting(listing),
            (
                f"I saw the listing at {address}. I can offer {_money(cash_offer)} "
                "cash, as-is, closing in 21-30 days with $500 earnest money and "
                "a 10-day due diligence period."
            ),
            (
                "No repair requests and no financing contingency. "
                f"{INVESTMENT_PURPOSE_LINE}"
            ),
            BROKER_COMP_LINE,
            "If that is worth showing the seller, where should I send the written offer?",
            SIGN_OFF,
        ]
    )

    return {
        "variation": 1,
        "subject": f"Cash offer for {address}",
        "body": body,
    }


def _gen_of_email(listing: dict, offer: dict) -> dict:
    address = _address(listing)
    purchase_price = (
        offer.get("purchase_price")
        or offer.get("owner_finance_offer")
        or offer.get("offer")
        or listing.get("list_price")
        or listing.get("price")
        or 0
    )
    down_payment = offer.get("down_payment") or (_number(purchase_price) * 0.05)
    financed_balance = (
        offer.get("financed_balance")
        or (_number(purchase_price) - _number(down_payment))
    )
    monthly_payment = offer.get("monthly_payment") or 0
    term = offer.get("term") or offer.get("num_payments") or 100
    interest_rate = offer.get("interest_rate", 0)

    body = "\n\n".join(
        [
            _agent_greeting(listing),
            (
                f"I saw the listing at {address}. I can offer {_money(purchase_price)} "
                f"with {_money(down_payment)} down, seller-financed balance of "
                f"{_money(financed_balance)}, {_money(monthly_payment)}/mo for "
                f"{term} months at {_number(interest_rate):g}% interest."
            ),
            (
                "Terms would be as-is with no repair requests, $500 earnest money, "
                "10-day due diligence, and closing in 21-30 days. "
                f"{INVESTMENT_PURPOSE_LINE}"
            ),
            BROKER_COMP_LINE,
            "If that is worth showing the seller, where should I send the written offer?",
            SIGN_OFF,
        ]
    )

    return {
        "variation": 1,
        "subject": f"Seller-financed offer for {address}",
        "body": body,
    }


def pick_email(emails: list[dict]) -> dict:
    if not emails:
        return {}
    return random.choice(emails)
