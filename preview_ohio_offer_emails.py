"""
Fixture-only Cleveland/Akron offer email preview.

This script does not scrape, enrich, send email, or push to a CRM. It builds a
small set of Ohio fixture leads, runs the same offer and deterministic email
generation helpers used by the pipeline, and writes review artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path

from config import OF_AUDIT_MAX_PRICE, OF_AUDIT_MIN_PRICE, OF_MAX_PRICE, OF_MIN_PRICE
from email_gen import BROKER_COMP_LINE, INVESTMENT_PURPOSE_LINE, generate_emails
from offer import calculate_offer


DATA_PATH = Path("data/ohio_offer_preview.json")
REPORT_PATH = Path("reports/ohio_offer_preview.md")


FIXTURE_LEADS = [
    {
        "market_key": "cleveland",
        "market": "Cleveland, OH",
        "city": "Cleveland",
        "state": "OH",
        "address": "4297 E 139th St, Cleveland, OH 44105",
        "list_price": 74000,
        "price": 74000,
        "agent_name": "Rakesh Baniya",
        "agent_email": "rbaniya@clevelandpropertymanagement.com",
        "agent_phone": "440-901-7145",
        "brokerage": "Cleveland Property Management Group, LLC",
        "brokerage_name": "Cleveland Property Management Group, LLC",
        "days_on_zillow": 36,
        "description": (
            "Owner financing option $15,000 down. 7% interest, "
            "$310 monthly payment, 240 amortization, no PPP."
        ),
    },
    {
        "market_key": "cleveland",
        "market": "Cleveland, OH",
        "city": "Cleveland",
        "state": "OH",
        "address": "10712 Grantwood Ave, Cleveland, OH 44108",
        "list_price": 75000,
        "price": 75000,
        "agent_name": "Leilani M Bowersock",
        "agent_email": "leilani7b@gmail.com",
        "agent_phone": "440-570-9514",
        "brokerage": "Coldwell Banker Schmidt Realty",
        "brokerage_name": "Coldwell Banker Schmidt Realty",
        "days_on_zillow": 88,
    },
    {
        "market_key": "akron",
        "market": "Akron, OH",
        "city": "Akron",
        "state": "OH",
        "address": "840 Work Dr, Akron, OH 44320",
        "list_price": 65000,
        "price": 65000,
        "agent_name": "Christopher A Frederick",
        "agent_email": "thefrederickteam@gmail.com",
        "agent_phone": "216-210-7653",
        "brokerage": "Coldwell Banker Schmidt Realty",
        "brokerage_name": "Coldwell Banker Schmidt Realty",
        "days_on_zillow": 40,
    },
    {
        "market_key": "cleveland",
        "market": "Cleveland, OH",
        "city": "Cleveland",
        "state": "OH",
        "address": "123 Example Review Ave, Cleveland, OH 44105",
        "list_price": 125000,
        "price": 125000,
        "agent_name": "Test Agent",
        "agent_email": "test@example.com",
        "agent_phone": "",
        "brokerage": "Example Brokerage",
        "brokerage_name": "Example Brokerage",
        "days_on_zillow": 60,
    },
]


def classify_preview_offer_lane(list_price: float, offer: dict) -> str:
    """Match main.py dashboard/audit lane labels without importing main.py."""
    if list_price <= 0:
        return "UNCLASSIFIED"
    offer_type = (offer or {}).get("offer_type", "")
    if offer_type == "seller_finance_counter":
        if (offer or {}).get("stale_seller_finance") or (offer or {}).get("requires_review"):
            return "STALE_SELLER_FINANCE_REVIEW"
        return "SELLER_FINANCE_LISTING_COUNTER"
    if OF_MIN_PRICE <= list_price <= OF_MAX_PRICE:
        return "OWNER_FINANCE_PRODUCTION"
    if OF_AUDIT_MIN_PRICE < list_price <= OF_AUDIT_MAX_PRICE:
        return "OWNER_FINANCE_AUDIT"

    if offer_type == "manual_review":
        return "NO_AUTO_OFFER_HIGH_PRICE"
    if offer_type == "cash_lowball":
        return "CASH_LOWBALL_ARV_CONFIRMED"
    return "CASH_REVIEW_ARV_REQUIRED"


def _round_money(value: float | int | None) -> float:
    return round(float(value or 0), 2)


def _format_money(value: float | int | None) -> str:
    amount = _round_money(value)
    if amount.is_integer():
        return f"${amount:,.0f}"
    return f"${amount:,.2f}"


def build_preview_records() -> list[dict]:
    records = []
    for lead in FIXTURE_LEADS:
        list_price = float(lead["list_price"])
        offer = calculate_offer(lead) or {}
        offer_lane = classify_preview_offer_lane(list_price, offer)
        emails = generate_emails(lead, offer)
        email = emails[0] if emails else {"subject": "", "body": ""}

        purchase_price = _round_money(
            offer.get("owner_finance_offer")
            or offer.get("purchase_price")
            or offer.get("cash_offer")
            or 0
        )
        down_payment = _round_money(offer.get("down_payment"))
        monthly_payment = _round_money(offer.get("monthly_payment"))
        num_payments = int(offer.get("num_payments") or 0)

        is_terms_offer = offer.get("offer_type") in ("owner_finance", "seller_finance_counter")
        expected_down = _round_money(
            max(5000, list_price * 0.05)
            if offer.get("offer_type") == "seller_finance_counter"
            else list_price * 0.05
        )
        expected_monthly = _round_money((list_price - expected_down) / 100)
        math_ok = True
        math_notes = []
        if is_terms_offer:
            if down_payment != expected_down:
                math_ok = False
                math_notes.append(f"down_payment expected {expected_down}, got {down_payment}")
            if monthly_payment != expected_monthly:
                math_ok = False
                math_notes.append(f"monthly_payment expected {expected_monthly}, got {monthly_payment}")
            if num_payments != 100:
                math_ok = False
                math_notes.append(f"num_payments expected 100, got {num_payments}")
        else:
            math_notes.append("manual/review lead; no owner-finance payment math generated")

        email_body = email["body"]
        email_subject = email["subject"]
        email_has_required_lines = (
            (not email_body)
            or (INVESTMENT_PURPOSE_LINE in email_body and BROKER_COMP_LINE in email_body)
        )
        if not email_has_required_lines:
            math_ok = False
            math_notes.append("email missing required public-facing lines")

        records.append(
            {
                "market": lead["market"],
                "market_key": lead["market_key"],
                "address": lead["address"],
                "list_price": list_price,
                "days_on_zillow": lead["days_on_zillow"],
                "agent_name": lead["agent_name"],
                "agent_email": lead["agent_email"],
                "agent_phone": lead.get("agent_phone", ""),
                "brokerage": lead.get("brokerage") or lead.get("brokerage_name", ""),
                "offer_type": offer.get("offer_type", ""),
                "offer_lane": offer_lane,
                "purchase_price": purchase_price,
                "down_payment": down_payment,
                "monthly_payment": monthly_payment,
                "num_payments": num_payments,
                "interest_rate": offer.get("interest_rate", offer.get("seller_rate", 0)),
                "prepayment_penalty": offer.get("prepayment_penalty", ""),
                "requires_review": bool(offer.get("requires_review") or offer.get("manual_review")),
                "review_note": offer.get("review_note", ""),
                "math_ok": math_ok,
                "math_check": "PASS" if math_ok else "FAIL",
                "math_notes": "; ".join(math_notes) if math_notes else "Term-offer math matches fixture expectations",
                "email_subject": email_subject,
                "email_body": email_body,
                "eligible_for_review": bool(email_body and lead.get("agent_email") and math_ok),
                "auto_send": False,
            }
        )
    return records


def build_summary(records: list[dict]) -> dict:
    return {
        "total_fixture_leads": len(records),
        "owner_finance_preview_count": sum(1 for row in records if row["offer_lane"] == "OWNER_FINANCE_PRODUCTION"),
        "seller_finance_counter_count": sum(1 for row in records if row["offer_lane"] == "SELLER_FINANCE_LISTING_COUNTER"),
        "stale_seller_finance_review_count": sum(1 for row in records if row["offer_lane"] == "STALE_SELLER_FINANCE_REVIEW"),
        "manual_review_count": sum(
            1 for row in records if row["requires_review"] or not row["email_body"]
        ),
        "math_issues_count": sum(1 for row in records if not row["math_ok"]),
        "emails_eligible_for_review": sum(1 for row in records if row["eligible_for_review"]),
        "emails_sent": 0,
        "scraper_ran": False,
        "apify_ran": False,
        "gmail_ran": False,
        "ghl_ran": False,
    }


def write_json(records: list[dict], summary: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"summary": summary, "records": records}
    DATA_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_report(records: list[dict], summary: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Ohio Offer Email Preview",
        "",
        "Fixture-only Cleveland/Akron preview. No scraper, Apify, enrichment, Gmail, or GHL call was made.",
        "",
        "## Summary",
        "",
        f"- Total fixture leads: {summary['total_fixture_leads']}",
        f"- Owner finance preview count: {summary['owner_finance_preview_count']}",
        f"- Seller finance counter count: {summary['seller_finance_counter_count']}",
        f"- Stale seller finance review count: {summary['stale_seller_finance_review_count']}",
        f"- Manual review count: {summary['manual_review_count']}",
        f"- Math issues count: {summary['math_issues_count']}",
        f"- Emails that would be eligible for review: {summary['emails_eligible_for_review']}",
        "- Emails sent: 0",
        "",
        "## Lead Previews",
        "",
    ]
    for row in records:
        lines += [
            f"### {row['address']}",
            "",
            f"- Market: {row['market']}",
            f"- List price: ${row['list_price']:,.0f}",
            f"- Agent email: {row['agent_email']}",
            f"- Offer lane: {row['offer_lane']}",
            f"- Purchase price: {_format_money(row['purchase_price'])}",
            f"- Down payment: {_format_money(row['down_payment'])}",
            f"- Monthly payment: {_format_money(row['monthly_payment'])}",
            f"- Number of payments: {row['num_payments']}",
            f"- Interest: {row['interest_rate']:g}%",
            f"- Prepayment penalty: {row['prepayment_penalty'] or 'N/A'}",
            f"- Requires review: {str(row['requires_review']).lower()}",
            f"- Math OK: {str(row['math_ok']).lower()}",
            f"- Email subject: {row['email_subject'] or 'N/A - manual/review only'}",
            "",
            "Email body:",
            "",
            "```text",
            row["email_body"] or "N/A - manual/review only; no auto-send email generated.",
            "```",
            "",
        ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> dict:
    records = build_preview_records()
    summary = build_summary(records)
    write_json(records, summary)
    write_report(records, summary)
    print(json.dumps(summary, indent=2))
    return {"summary": summary, "records": records}


if __name__ == "__main__":
    main()
