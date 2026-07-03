"""
Deterministic agent email templates for 229 Holdings LLC.
Emails are public-facing and only include the offer terms intended for agents.

Wording-only update: all public-facing copy now uses the shared hardwired
lines (buyer-purpose, broker-compensation, review, closing-CTA) and the
labeled-line offer format. No offer math, field sources, or function
signatures were changed — only how the existing values are presented.
"""

import random
import re

SIGN_OFF = "Michael B. | 229 Holdings LLC"
COMPANY_NAME_INDICATORS = (
    "realty",
    "real estate",
    "home",
    "homes",
    "properties",
    "group",
    "appraisals",
    "llc",
    "inc",
    "brokerage",
    "associates",
    "re/max",
    "century 21",
    "coldwell",
    "keller",
    "exp",
    "vylla",
    "real broker",
)

# ─── Shared public-facing language (source of truth) ────────────────────────
# These exact lines must be reused everywhere public-facing — email, PDF,
# dashboard LOI generator — rather than re-typed with slightly different
# wording in each place.
INVESTMENT_PURPOSE_LINE = (
    "Buyer is purchasing for investment/business purposes and not as an "
    "owner-occupant."
)
BROKER_COMP_LINE = (
    "Seller to handle any listing broker compensation per the existing "
    "listing agreement from seller proceeds, down payment/closing "
    "funds, or as otherwise agreed in writing by the seller and broker."
)
REVIEW_LINE = (
    "This offer is subject to buyer final walkthrough, title review, and "
    "standard closing review."
)
CLOSING_CTA_LINE = (
    "Please let me know if the seller would like this submitted on a state "
    "contract or preferred offer form."
)

# Standard terms used across the pipeline (unchanged business defaults —
# wording presentation only, not new numbers).
EARNEST_AMOUNT = 500
CLOSE_DAYS = 21
DUE_DILIGENCE_DAYS = 10


def generate_emails(listing: dict, offer: dict) -> list[dict]:
    offer_type = offer.get("offer_type")
    if offer_type == "seller_finance_counter":
        return [_gen_seller_finance_counter_email(listing, offer)]
    if offer_type in ("owner_finance", "owner_finance_rent_check", "owner_finance_manual_review"):
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
    if _looks_like_invalid_agent_name(name):
        return "Hi,"
    if _looks_like_company_name(name):
        return "Hi,"
    return f"Hi {name}," if name else "Hi,"


def _looks_like_invalid_agent_name(name: str) -> bool:
    if not name:
        return True
    normalized = re.sub(r"\s+", " ", name.lower()).strip()
    if normalized in {"unknown", "n/a", "na", "none", "null", "false", "true"}:
        return True
    tokens = normalized.split()
    if tokens and all(token in {"true", "false", "unknown", "none", "null"} for token in tokens):
        return True
    if not re.search(r"[a-z]", normalized):
        return True
    return False


def _looks_like_company_name(name: str) -> bool:
    if not name:
        return False
    normalized = re.sub(r"\s+", " ", name.lower()).strip()
    padded = f" {normalized} "
    for indicator in COMPANY_NAME_INDICATORS:
        needle = indicator.lower()
        if " " in needle or "/" in needle:
            if needle in normalized:
                return True
        elif re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", padded):
            return True
    return False


def _address(listing: dict) -> str:
    return str(listing.get("address") or "the property").strip()


def _money(value) -> str:
    try:
        amount = round(float(value), 2)
        if amount.is_integer():
            return f"${amount:,.0f}"
        return f"${amount:,.2f}"
    except (TypeError, ValueError):
        return "$0"


def _number(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _earnest_line() -> str:
    return (
        f"Earnest Money: {_money(EARNEST_AMOUNT)} to be deposited with "
        "title/escrow upon completion or waiver of buyer's "
        "inspection/walkthrough period, unless otherwise agreed in writing."
    )


def _gen_cl_email(listing: dict, offer: dict) -> dict:
    address = _address(listing)
    cash_offer = (
        offer.get("initial_offer")
        or offer.get("cash_offer")
        or offer.get("offer")
        or 0
    )

    lines = [
        _agent_greeting(listing),
        "",
        f"I would like to submit the following cash offer for {address}:",
        "",
        f"Offer Price: {_money(cash_offer)}",
        _earnest_line(),
        f"Closing Timeline: On or before {CLOSE_DAYS} days after acceptance",
        f"Inspection / Walkthrough Period: {DUE_DILIGENCE_DAYS} days after acceptance",
        "Financing: No financing contingency",
        "",
        INVESTMENT_PURPOSE_LINE,
        "",
        BROKER_COMP_LINE,
        "",
        REVIEW_LINE,
        "",
        CLOSING_CTA_LINE,
        "",
        "Thank you,",
        SIGN_OFF,
    ]

    return {
        "variation": 1,
        "subject": f"Offer on {address}",
        "body": "\n".join(lines),
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
    monthly_payment = offer.get("monthly_payment") or 0
    term = offer.get("term") or offer.get("num_payments") or 100
    balloon = offer.get("balloon") or 0

    lines = [
        _agent_greeting(listing),
        "",
        f"I would like to submit the following purchase offer for {address}:",
        "",
        f"Purchase Price: {_money(purchase_price)}",
        f"Down Payment: {_money(down_payment)}",
        f"Monthly Payment: {_money(monthly_payment)}",
        f"Term: {term:g} months" if isinstance(term, (int, float)) else f"Term: {term} months",
    ]
    if balloon:
        lines.append(
            f"Balloon: {balloon:g} months"
            if isinstance(balloon, (int, float))
            else f"Balloon: {balloon} months"
        )
    lines += [
        _earnest_line(),
        f"Closing Timeline: On or before {CLOSE_DAYS} days after acceptance",
        f"Inspection / Walkthrough Period: {DUE_DILIGENCE_DAYS} days after acceptance",
        "",
        INVESTMENT_PURPOSE_LINE,
        "",
        BROKER_COMP_LINE,
        "",
        REVIEW_LINE,
        "",
        CLOSING_CTA_LINE,
        "",
        "Thank you,",
        SIGN_OFF,
    ]

    return {
        "variation": 1,
        "subject": f"Offer on {address}",
        "body": "\n".join(lines),
    }


def _gen_seller_finance_counter_email(listing: dict, offer: dict) -> dict:
    address = _address(listing)
    purchase_price = (
        offer.get("purchase_price")
        or offer.get("owner_finance_offer")
        or listing.get("list_price")
        or listing.get("price")
        or 0
    )
    down_payment = offer.get("down_payment") or max(5000, _number(purchase_price) * 0.05)
    monthly_payment = offer.get("monthly_payment") or 0
    term = offer.get("term") or offer.get("num_payments") or 100
    interest_rate = offer.get("interest_rate", offer.get("seller_rate", 0))
    prepayment_penalty = offer.get("prepayment_penalty") or "None"

    lines = [
        _agent_greeting(listing),
        "",
        f"I reviewed the listing at {address}.",
        "",
        "I can work with the list price if the seller can work with me on the terms. Would the seller consider the following?",
        "",
        f"Purchase Price: {_money(purchase_price)}",
        f"Down Payment: {_money(down_payment)}",
        f"Monthly Payment: {_money(monthly_payment)}",
        f"Term: {term:g} months" if isinstance(term, (int, float)) else f"Term: {term} months",
        f"Interest: {_number(interest_rate):g}%",
        f"Prepayment Penalty: {prepayment_penalty}",
        "",
        "If the seller needs closer to the advertised down payment, I’m open to reviewing a counter.",
        "",
        INVESTMENT_PURPOSE_LINE,
        "",
        BROKER_COMP_LINE,
        "",
        REVIEW_LINE,
        "",
        CLOSING_CTA_LINE,
        "",
        "Thank you,",
        SIGN_OFF,
    ]

    return {
        "variation": 1,
        "subject": f"Offer on {address}",
        "body": "\n".join(lines),
    }


def pick_email(emails: list[dict]) -> dict:
    if not emails:
        return {}
    return random.choice(emails)
