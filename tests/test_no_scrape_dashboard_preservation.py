import unittest
from unittest.mock import patch

import tests.test_apify_quota_handling  # noqa: F401 - installs side-effect stubs before importing main
import main
import scraper


class NoScrapeDashboardPreservationTest(unittest.TestCase):
    def test_apify_disabled_preserves_dashboard_json(self):
        with patch.dict("os.environ", {"APIFY_ENABLED": "false"}), \
             patch.object(main, "scrape_market", return_value=[]), \
             patch.object(main, "load_overflow", return_value=[]), \
             patch.object(main, "save_overflow"), \
             patch.object(main, "save_dashboard_data") as save_dashboard_data:
            result = main.run_market("little_rock", dry_run=True)

        self.assertEqual(result["leads"], 0)
        save_dashboard_data.assert_not_called()

    def test_apify_disabled_does_not_save_empty_current_leads(self):
        with patch.dict("os.environ", {"APIFY_ENABLED": "false"}), \
             patch.object(main, "scrape_market", return_value=[]), \
             patch.object(main, "load_overflow", return_value=[]), \
             patch.object(main, "save_overflow"), \
             patch.object(main, "save_dashboard_data") as save_dashboard_data:
            main.run_market("oklahoma_city", dry_run=True)

        self.assertFalse(
            any(call.args[1] == [] for call in save_dashboard_data.call_args_list),
            "no-scrape mode must not save an empty dashboard lead list",
        )

    def test_apify_enabled_quota_error_still_preserves_dashboard_json(self):
        with patch.dict("os.environ", {"APIFY_ENABLED": "true"}), \
             patch.object(main, "scrape_market", side_effect=scraper.ApifyQuotaError("quota exceeded")), \
             patch.object(main, "load_overflow", return_value=[]), \
             patch.object(main, "save_dashboard_data") as save_dashboard_data:
            with self.assertRaises(scraper.ApifyQuotaError):
                main.run_market("little_rock", dry_run=True)

        save_dashboard_data.assert_not_called()

    def test_normal_scrape_with_leads_still_saves_dashboard_json(self):
        lead = {
            "address": "123 Test St",
            "city": "Little Rock",
            "state": "AR",
            "price": 50000,
            "agent_email": "",
            "agent_name": "Test Agent",
            "days_on_market": 45,
        }
        with patch.dict("os.environ", {"APIFY_ENABLED": "true"}), \
             patch.object(main, "scrape_market", return_value=[lead]), \
             patch.object(main, "load_overflow", return_value=[]), \
             patch.object(main, "save_overflow"), \
             patch.object(main, "should_send", return_value=True), \
             patch.object(main, "save_dashboard_data") as save_dashboard_data:
            main.run_market("little_rock", dry_run=True)

        save_dashboard_data.assert_called_once()
        self.assertEqual(save_dashboard_data.call_args.args[0], "little_rock")
        self.assertEqual(save_dashboard_data.call_args.args[1], [lead])


if __name__ == "__main__":
    unittest.main()
