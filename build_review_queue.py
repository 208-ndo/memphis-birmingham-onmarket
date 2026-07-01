"""
build_review_queue.py — build a human-review email/LOI queue from dashboard leads.

No Apify. No Google enrichment. No Gmail. No GHL.

This script reads the current restored dashboard lead JSON files, rebuilds the
same deterministic public-facing email copy from email_gen.py, checks the basic
owner-finance math, and writes data/review_queue.json for manual approval.
"""

import hashlib
import json
import os
from datetime import datetime

from email_gen import generate_emails

QUEUE_FILE = "data/review_queue.json"

DEFAULT_MARKETS = {
    "little_rock": "data/little_rock_leads.json",
    "oklahoma_city": "data/oklahoma_city_leads.json",
}


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _money_float(value, default=0.0):
    try:
        return float(value or 0)
    except Exception:
        return default


def _queue_id(market_key: str, address: str) -> str:
    raw = f"{market_key}|{address}".lower().encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


def _math_check(lead: dict) -> dict:
    offer_type = lead.get("offer_type")
    purchase = _money_float(
        lead.get("owner_finance_offer") or lead.get("cash_offer") or lead.get("list_price")
    )
    down_payment = _money_float(lead.get("down_payment"))
    monthly = _money_float(lead.get("monthly_payment"))

    if offer_type != "owner_finance" or purchase <= 0:
        return {
            "checked": False,
            "math_ok": True,
            "reason": "not_owner_finance_or_missing_purchase_price",
        }

    expected_down = round(purchase * 0.05, 2)
    expected_monthly = round((purchase - expected_down) / 100, 2)
    down_ok = abs(down_payment - expected_down) <= 1.00
    monthly_ok = abs(monthly - expected_monthly) <= 1.00

    return {
        "checked": True,
        "math_ok": bool(down_ok and monthly_ok),
        "purchase_price": purchase,
        "down_payment": down_payment,
        "expected_down_payment": expected_down,
        "monthly_payment": monthly,
        "expected_monthly_payment": expected_monthly,
        "down_payment_ok": bool(down_ok),
        "monthly_payment_ok": bool(monthly_ok),
        "formula": "down_payment=5% of purchase; monthly=(purchase-down_payment)/100",
    }


def _build_offer(lead: dict) -> dict:
    return {
        "offer_type": lead.get("offer_type") or "owner_finance",
        "purchase_price": lead.get("owner_finance_offer") or lead.get("list_price"),
        "owner_finance_offer": lead.get("owner_finance_offer"),
        "cash_offer": lead.get("cash_offer"),
        "down_payment": lead.get("down_payment"),
        "monthly_payment": lead.get("monthly_payment"),
        "your_fee_estimate": lead.get("your_fee_estimate"),
        "pitch_holds": lead.get("pitch_holds"),
        "num_payments": lead.get("num_payments", 100),
    }


def _build_listing(lead: dict, market_key: str) -> dict:
    return {
        "address": lead.get("address"),
        "city": lead.get("city"),
        "state": lead.get("state"),
        "list_price": lead.get("list_price"),
        "price": lead.get("list_price"),
        "days_on_market": lead.get("days_on_market"),
        "score": lead.get("score"),
        "agent_name": lead.get("agent_name"),
        "agent_email": lead.get("agent_email") or "",
        "agent_phone": lead.get("agent_phone"),
        "brokerName": lead.get("agent_name"),
        "zillow_url": lead.get("zillow_url"),
        "url": lead.get("zillow_url"),
        "market": market_key,
    }


def build_queue() -> list[dict]:
    os.makedirs("data", exist_ok=True)

    limit_per_market = int(os.environ.get("REVIEW_LIMIT_PER_MARKET", "25"))
    min_score = float(os.environ.get("REVIEW_MIN_SCORE", "0"))

    old_queue = _load_json(QUEUE_FILE, [])
    old_by_id = {item.get("queue_id"): item for item in old_queue if item.get("queue_id")}

    queue = []
    for market_key, path in DEFAULT_MARKETS.items():
        leads = _load_json(path, [])
        leads = [l for l in leads if _money_float(l.get("score")) >= min_score]
        leads.sort(key=lambda l: _money_float(l.get("score")), reverse=True)

        for lead in leads[:limit_per_market]:
            qid = _queue_id(market_key, lead.get("address", ""))
            prior = old_by_id.get(qid, {})
            offer = _build_offer(lead)
            listing = _build_listing(lead, market_key)
            listing["offer"] = offer

            email_options = generate_emails(listing, offer)
            email = email_options[0] if email_options else {"subject": "", "body": ""}

            effective_email = (
                prior.get("manual_agent_email")
                or prior.get("agent_email")
                or listing.get("agent_email")
                or ""
            )

            queue.append({
                "queue_id": qid,
                "status": prior.get("status", "needs_review"),
                "approved_to_send": bool(prior.get("approved_to_send", False)),
                "market_key": market_key,
                "address": listing.get("address"),
                "city": listing.get("city"),
                "state": listing.get("state"),
                "list_price": lead.get("list_price"),
                "days_on_market": lead.get("days_on_market"),
                "score": lead.get("score"),
                "offer_lane": lead.get("offer_lane"),
                "offer": offer,
                "math_check": _math_check(lead),
                "agent_name": listing.get("agent_name"),
                "agent_email": listing.get("agent_email") or "",
                "manual_agent_email": prior.get("manual_agent_email", ""),
                "effective_agent_email": effective_email,
                "needs_agent_email": not bool(effective_email),
                "zillow_url": listing.get("zillow_url"),
                "email_subject": email.get("subject", ""),
                "email_body": email.get("body", ""),
                "notes": prior.get("notes", ""),
                "last_built_at": datetime.now().isoformat(timespec="seconds"),
                "sent_at": prior.get("sent_at"),
            })

    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2)

    ready = sum(1 for q in queue if q.get("effective_agent_email"))
    math_bad = sum(1 for q in queue if not q.get("math_check", {}).get("math_ok", True))
    print(f"Review queue written: {QUEUE_FILE}")
    print(f"Items: {len(queue)} | with email: {ready} | missing email: {len(queue) - ready} | math issues: {math_bad}")
    return queue


if __name__ == "__main__":
    build_queue()
