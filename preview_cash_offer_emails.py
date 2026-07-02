"""
Fixture-only cash review preview.

This script does not scrape, enrich, send email, or push to a CRM. Cash rows
stay manual/review until ARV, repairs, comps, and spread math are approved.
"""

from __future__ import annotations

import json
from pathlib import Path


DATA_PATH = Path("data/cash_offer_preview.json")
REPORT_PATH = Path("reports/cash_offer_preview.md")


CASH_FIXTURE_LEADS = [
    {
        "address": "SYNTHETIC FIXTURE - Cash Review 85k",
        "market": "Cleveland, OH",
        "market_key": "cleveland",
        "list_price": 85000,
        "estimated_value": 120000,
        "agent_name": "Cash Review Agent",
        "agent_email": "cash85@example.com",
        "synthetic_fixture": True,
        "real_listing": False,
        "do_not_send": True,
        "approved_to_send": False,
        "live_send_allowed": False,
        "public_email_generated": False,
    },
    {
        "address": "SYNTHETIC FIXTURE - Cash Review 100k",
        "market": "Cleveland, OH",
        "market_key": "cleveland",
        "list_price": 100000,
        "estimated_value": 150000,
        "agent_name": "Cash Review Agent",
        "agent_email": "cash100@example.com",
        "synthetic_fixture": True,
        "real_listing": False,
        "do_not_send": True,
        "approved_to_send": False,
        "live_send_allowed": False,
        "public_email_generated": False,
    },
    {
        "address": "SYNTHETIC FIXTURE - Cash Review 125k",
        "market": "Akron, OH",
        "market_key": "akron",
        "list_price": 125000,
        "estimated_value": 180000,
        "agent_name": "Cash Review Agent",
        "agent_email": "cash125@example.com",
        "synthetic_fixture": True,
        "real_listing": False,
        "do_not_send": True,
        "approved_to_send": False,
        "live_send_allowed": False,
        "public_email_generated": False,
    },
    {
        "address": "SYNTHETIC FIXTURE - Owner Finance Only 75k",
        "market": "Cleveland, OH",
        "market_key": "cleveland",
        "list_price": 75000,
        "estimated_value": 90000,
        "agent_name": "Owner Finance Agent",
        "agent_email": "of75@example.com",
        "synthetic_fixture": True,
        "real_listing": False,
        "do_not_send": True,
        "approved_to_send": False,
        "live_send_allowed": False,
        "public_email_generated": False,
    },
]


FORBIDDEN_PUBLIC_TERMS = (
    "assignment",
    "assignable",
    "wholesale",
    "wholesaler",
    "assignment fee",
    "end buyer",
    "buyer’s buyer",
    "buyer's buyer",
    "dispo",
    "selling to my buyer",
    "resell to buyer",
    "market this to buyers",
    "buyer list",
    "our buyers",
    "investor buyer pool",
    "bonus",
    "extra commission",
    "agent incentive",
    "seller comes out of pocket",
)


def zompz_bracket_offer(estimated_value: float) -> float:
    if estimated_value <= 75000:
        pct = 0.20
    elif estimated_value <= 150000:
        pct = 0.40
    elif estimated_value <= 300000:
        pct = 0.50
    elif estimated_value <= 750000:
        pct = 0.60
    elif estimated_value <= 1500000:
        pct = 0.65
    else:
        pct = 0.0
    return estimated_value * pct


def suggested_optional_reserve(list_price: float) -> float:
    if list_price < 50000:
        return 1000.0
    if list_price <= 150000:
        return 1500.0
    return 0.0


def expected_spread_target(estimated_value: float) -> float:
    return max(7500.0, min(30000.0, estimated_value * 0.08))


def forbidden_terms_found(text: str) -> bool:
    normalized = (text or "").lower()
    return any(term.lower() in normalized for term in FORBIDDEN_PUBLIC_TERMS)


def build_cash_preview_records() -> list[dict]:
    records = []
    for lead in CASH_FIXTURE_LEADS:
        list_price = float(lead["list_price"])
        estimated_value = float(lead["estimated_value"])
        if list_price <= 80000:
            offer_lane = "OWNER_FINANCE_ONLY"
            manual_review_reason = "30k-80k houses route to owner-finance only; no cash offer created."
            conservative_offer = None
            bracket_offer = None
            email_subject = ""
            email_body = ""
        else:
            offer_lane = "CASH_REVIEW_ARV_REQUIRED"
            manual_review_reason = (
                "Manual review required: verify ARV, repairs, comps, and visible spread before any cash offer."
            )
            conservative_offer = estimated_value * 0.20
            bracket_offer = zompz_bracket_offer(estimated_value)
            email_subject = ""
            email_body = ""

        internal_only = {
            "expected_assignment_fee_target": expected_spread_target(estimated_value),
            "optional_agent_comp_reserve": 0.0,
            "suggested_optional_agent_comp_reserve": suggested_optional_reserve(list_price),
            "net_spread_after_optional_agent_comp": None,
            "manual_approval_agent_comp": False,
        }
        records.append(
            {
                "address": lead["address"],
                "market": lead["market"],
                "market_key": lead["market_key"],
                "synthetic_fixture": True,
                "real_listing": False,
                "do_not_send": True,
                "approved_to_send": False,
                "live_send_allowed": False,
                "public_email_generated": False,
                "list_price": list_price,
                "estimated_value": estimated_value,
                "conservative_20pct_offer": conservative_offer,
                "zompz_bracket_offer": bracket_offer,
                "selected_cash_offer": None,
                "offer_lane": offer_lane,
                "manual_review_reason": manual_review_reason,
                "email_subject": email_subject,
                "email_body": email_body,
                "public_copy_forbidden_terms_found": forbidden_terms_found(email_body),
                "auto_send": False,
                "INTERNAL_ONLY": internal_only,
            }
        )
    return records


def build_summary(records: list[dict]) -> dict:
    return {
        "total_fixture_leads": len(records),
        "cash_review_count": sum(1 for row in records if row["offer_lane"] == "CASH_REVIEW_ARV_REQUIRED"),
        "owner_finance_only_count": sum(1 for row in records if row["offer_lane"] == "OWNER_FINANCE_ONLY"),
        "auto_send_eligible_count": sum(1 for row in records if row["auto_send"]),
        "public_copy_forbidden_terms_found": any(row["public_copy_forbidden_terms_found"] for row in records),
        "emails_sent": 0,
        "scraper_ran": False,
        "apify_ran": False,
        "gmail_ran": False,
        "ghl_ran": False,
    }


def _money(value) -> str:
    if value is None:
        return "N/A"
    amount = round(float(value), 2)
    if amount.is_integer():
        return f"${amount:,.0f}"
    return f"${amount:,.2f}"


def write_json(records: list[dict], summary: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps({"summary": summary, "records": records}, indent=2) + "\n", encoding="utf-8")


def write_report(records: list[dict], summary: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Cash Offer Review Preview",
        "",
        "Rows marked synthetic_fixture=true are math/test examples only. They are not real leads, do not have real agent contacts, and must never generate sendable public email.",
        "",
        "Fixture-only cash review preview. No scraper, Apify, enrichment, Gmail, or GHL call was made.",
        "",
        "## Summary",
        "",
        f"- Total fixture leads: {summary['total_fixture_leads']}",
        f"- Cash review count: {summary['cash_review_count']}",
        f"- Owner-finance-only count: {summary['owner_finance_only_count']}",
        f"- Auto-send eligible count: {summary['auto_send_eligible_count']}",
        f"- Public copy forbidden terms found: {str(summary['public_copy_forbidden_terms_found']).lower()}",
        "- Emails sent: 0",
        "",
        "## Synthetic Math Fixtures - No Public Email Generated",
        "",
    ]
    for row in records:
        internal = row["INTERNAL_ONLY"]
        lines += [
            f"### {row['address']}",
            "",
            f"- Market: {row['market']}",
            f"- Synthetic fixture: {str(row['synthetic_fixture']).lower()}",
            f"- Real listing: {str(row['real_listing']).lower()}",
            f"- Do not send: {str(row['do_not_send']).lower()}",
            f"- Public email generated: {str(row['public_email_generated']).lower()}",
            f"- Approved to send: {str(row['approved_to_send']).lower()}",
            f"- Live send allowed: {str(row['live_send_allowed']).lower()}",
            f"- List price: {_money(row['list_price'])}",
            f"- Estimated value: {_money(row['estimated_value'])}",
            f"- Conservative 20pct offer: {_money(row['conservative_20pct_offer'])}",
            f"- Zompz bracket offer: {_money(row['zompz_bracket_offer'])}",
            f"- Selected cash offer: {_money(row['selected_cash_offer'])}",
            f"- Offer lane: {row['offer_lane']}",
            f"- Manual review reason: {row['manual_review_reason']}",
            "- Email subject: SYNTHETIC FIXTURE - math test only. No public email generated. Do not send.",
            "",
            "Email body:",
            "",
            "```text",
            "SYNTHETIC FIXTURE - math test only. No public email generated. Do not send.",
            "```",
            "",
            "INTERNAL_ONLY:",
            "",
            f"- expected_assignment_fee_target: {_money(internal['expected_assignment_fee_target'])}",
            f"- optional_agent_comp_reserve: {_money(internal['optional_agent_comp_reserve'])}",
            f"- suggested_optional_agent_comp_reserve: {_money(internal['suggested_optional_agent_comp_reserve'])}",
            f"- net_spread_after_optional_agent_comp: {_money(internal['net_spread_after_optional_agent_comp'])}",
            f"- manual_approval_agent_comp: {str(internal['manual_approval_agent_comp']).lower()}",
            "",
        ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> dict:
    records = build_cash_preview_records()
    summary = build_summary(records)
    write_json(records, summary)
    write_report(records, summary)
    print(json.dumps(summary, indent=2))
    return {"summary": summary, "records": records}


if __name__ == "__main__":
    main()
