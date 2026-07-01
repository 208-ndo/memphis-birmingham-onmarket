"""
Export a manual contact-research queue from data/review_queue.json.

Research order for missing agent contact info:
1. Active listing page.
2. Brokerage listing page.
3. Brokerage roster/profile.
4. Office intake email/phone.
5. Managing broker fallback.

This script does not enrich, guess, scrape, send email, or call external APIs.
It only reshapes existing committed queue data into a CSV for manual research.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path


INPUT_PATH = Path("data/review_queue.json")
OUTPUT_PATH = Path("data/contact_research_queue.csv")
LIMIT = 25

CSV_COLUMNS = [
    "queue_id",
    "market_key",
    "address",
    "city",
    "state",
    "list_price",
    "score",
    "offer_lane",
    "agent_name",
    "agent_email",
    "manual_agent_email",
    "effective_agent_email",
    "needs_agent_email",
    "zillow_url",
    "email_subject",
    "contact_status",
    "found_email",
    "found_phone",
    "contact_source_url",
    "contact_source_type",
    "contact_notes",
    "approved_to_send",
]


def main() -> None:
    records = _load_review_queue(INPUT_PATH)
    top_records = sorted(records, key=_score, reverse=True)[:LIMIT]
    rows = [_to_contact_row(record) for record in top_records]
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    rows_with_email = sum(1 for row in rows if row["contact_status"] == "has_email")
    rows_needing_research = len(rows) - rows_with_email
    print(f"Contact research queue written: {OUTPUT_PATH}")
    print(f"Rows exported: {len(rows)}")
    print(f"Rows needing research: {rows_needing_research}")
    print(f"Rows with email: {rows_with_email}")


def _load_review_queue(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise ValueError(f"Unsupported review queue format in {path}")


def _score(record: dict) -> float:
    try:
        return float(record.get("score") or 0)
    except (TypeError, ValueError):
        return 0.0


def _to_contact_row(record: dict) -> dict:
    agent_email = _clean(record.get("agent_email"))
    manual_agent_email = _clean(record.get("manual_agent_email"))
    effective_agent_email = (
        _clean(record.get("effective_agent_email"))
        or manual_agent_email
        or agent_email
    )
    found_email = _clean(record.get("found_email"))
    contact_status = "has_email" if effective_agent_email else "needs_research"

    return {
        "queue_id": _clean(record.get("queue_id")),
        "market_key": _clean(record.get("market_key")),
        "address": _clean(record.get("address")),
        "city": _clean(record.get("city")),
        "state": _clean(record.get("state")),
        "list_price": record.get("list_price") or "",
        "score": record.get("score") or "",
        "offer_lane": _clean(record.get("offer_lane")),
        "agent_name": _clean(record.get("agent_name")),
        "agent_email": agent_email,
        "manual_agent_email": manual_agent_email,
        "effective_agent_email": effective_agent_email,
        "needs_agent_email": "false" if effective_agent_email else "true",
        "zillow_url": _clean(record.get("zillow_url")),
        "email_subject": _clean(record.get("email_subject")),
        "contact_status": contact_status,
        "found_email": found_email,
        "found_phone": _clean(record.get("found_phone")),
        "contact_source_url": _clean(record.get("contact_source_url")),
        "contact_source_type": _clean(record.get("contact_source_type")),
        "contact_notes": _clean(record.get("contact_notes")),
        "approved_to_send": _bool_text(record.get("approved_to_send")),
    }


def _clean(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _bool_text(value) -> str:
    return "true" if value is True else "false"


if __name__ == "__main__":
    main()
