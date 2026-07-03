import json
import unittest
from pathlib import Path

from dedup import should_send


ADDRESS = "10513 Parkview Ave, Cleveland, OH 44104"
EMAIL = "melissa.harris@remax.net"
FALSE_DATE = "2026-07-03"
SUBJECT = "Offer on 10513 Parkview Ave, Cleveland, OH 44104"


def is_false_parkview_sent_record(record):
    return (
        str(record.get("address", "")).strip().lower() == ADDRESS.lower()
        and str(record.get("agent_email", "")).strip().lower() == EMAIL
        and str(record.get("sent_at", record.get("sent", ""))).startswith(FALSE_DATE)
        and str(record.get("email_subject", record.get("subject", ""))).strip() == SUBJECT
    )


class FalseParkviewHistoryCleanupTest(unittest.TestCase):
    def test_false_parkview_record_removed_from_dedup_history(self):
        data = json.loads(Path("data/dedup_log.json").read_text(encoding="utf-8"))

        for key, record in data.get("properties", {}).items():
            self.assertFalse(is_false_parkview_sent_record(record), key)

        agent_record = data.get("agents", {}).get(EMAIL)
        self.assertIsNone(agent_record)

    def test_parkview_bounce_is_audited_and_email_is_blocked(self):
        data = json.loads(Path("data/dedup_log.json").read_text(encoding="utf-8"))

        self.assertIn(EMAIL, data.get("bad_emails", []))
        self.assertTrue(any(
            record.get("agent_email") == EMAIL
            and record.get("property_key") == "zpid:33415553"
            and record.get("status") == "bounced_invalid_recipient"
            for record in data.get("bounces", [])
        ))

        listing = {
            "address": ADDRESS,
            "agent_email": EMAIL,
            "zpid": "33415553",
            "url": "https://www.zillow.com/homedetails/10513-Parkview-Ave-Cleveland-OH-44104/33415553_zpid/",
        }
        self.assertFalse(should_send(listing, check_hours=False))

    def test_false_parkview_record_removed_from_pipeline_sent_history(self):
        data = json.loads(Path("data/pipeline_log.json").read_text(encoding="utf-8"))

        for section in ("queue", "history"):
            for record in data.get(section, []):
                self.assertFalse(is_false_parkview_sent_record(record), section)

        self.assertEqual(data["summary"]["emails_sent"], 0)
        self.assertEqual(data["summary"]["ghl_pushed"], 0)

    def test_current_dashboard_lead_is_not_marked_successfully_emailed(self):
        leads = json.loads(Path("data/cleveland_leads.json").read_text(encoding="utf-8"))
        matches = [
            lead for lead in leads
            if str(lead.get("address", "")).strip().lower() == ADDRESS.lower()
            and str(lead.get("agent_email", "")).strip().lower() == EMAIL
        ]
        self.assertEqual(len(matches), 1)
        self.assertFalse(matches[0]["email_sent"])
        self.assertTrue(matches[0]["email_bounced"])
        self.assertEqual(matches[0]["contact_status"], "bounced_invalid_recipient")


if __name__ == "__main__":
    unittest.main()
