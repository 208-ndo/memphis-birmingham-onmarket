import json
import unittest
from pathlib import Path

from contact_validation import clean_agent_name, display_agent_name, is_valid_agent_name


BOOLEAN_JUNK_NAMES = ("True False False False", "False False True False")


class DashboardDisplaySanitizationTest(unittest.TestCase):
    def test_boolean_junk_agent_names_are_not_valid_display_names(self):
        for name in BOOLEAN_JUNK_NAMES:
            self.assertFalse(is_valid_agent_name(name))
            self.assertEqual(clean_agent_name(name), "")
            self.assertEqual(display_agent_name(name), "-")

    def test_valid_agent_name_still_displays_normally(self):
        self.assertTrue(is_valid_agent_name("Melissa Harris"))
        self.assertEqual(display_agent_name("Melissa Harris"), "Melissa Harris")

    def test_dashboard_and_sent_history_do_not_show_boolean_junk_names(self):
        paths = [
            Path("data/cleveland_leads.json"),
            Path("data/pipeline_log.json"),
            Path("data/dedup_log.json"),
        ]
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for name in BOOLEAN_JUNK_NAMES:
                self.assertNotIn(name, text, str(path))

    def test_saved_email_preview_greeting_is_sanitized(self):
        data = json.loads(Path("data/pipeline_log.json").read_text(encoding="utf-8"))
        all_rows = data.get("queue", []) + data.get("history", [])
        bodies = "\n".join(row.get("email_body") or "" for row in all_rows)
        self.assertNotIn("Hi True False False False,", bodies)
        self.assertNotIn("Hi False False True False,", bodies)

    def test_bounced_email_does_not_display_as_clean_success(self):
        data = json.loads(Path("data/pipeline_log.json").read_text(encoding="utf-8"))
        parkview_history = [
            row for row in data.get("history", [])
            if str(row.get("agent_email", "")).lower() == "melissa.harris@remax.net"
        ]
        self.assertTrue(parkview_history)
        for row in parkview_history:
            self.assertEqual(row.get("status"), "BOUNCED")


if __name__ == "__main__":
    unittest.main()
