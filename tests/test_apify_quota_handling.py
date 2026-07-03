import sys
import types
import unittest
from unittest.mock import patch


def stub_module(name, **attrs):
    module = types.ModuleType(name)
    module.__test_stub__ = True
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules.setdefault(name, module)


stub_module("offer", calculate_offer=lambda listing: {})
stub_module("email_gen", generate_emails=lambda listing, offer: [], pick_email=lambda emails: None)
stub_module(
    "dedup",
    should_send=lambda listing: True,
    mark_sent=lambda listing, email: None,
    get_stats=lambda: {"total_properties_emailed": 0, "total_agents_contacted": 0},
)
stub_module(
    "gmail_send",
    send_batch=lambda queue, market_key, dry_run=False: [],
    count_sent_today_global=lambda: 0,
)
stub_module("ghl_push", push_to_ghl=lambda listing, offer, email, market_key: None)

import main
import scraper

for module_name in ("offer", "email_gen", "dedup", "gmail_send", "ghl_push"):
    if getattr(sys.modules.get(module_name), "__test_stub__", False):
        sys.modules.pop(module_name, None)


class FakeActor:
    def __init__(self, calls, error):
        self.calls = calls
        self.error = error

    def call(self, **kwargs):
        self.calls.append(kwargs)
        raise self.error


class FakeClient:
    calls = []
    error = RuntimeError("Monthly usage hard limit exceeded")

    def __init__(self, token):
        self.token = token

    def actor(self, actor_id):
        return FakeActor(self.calls, self.error)


class ApifyQuotaHandlingTest(unittest.TestCase):
    def setUp(self):
        FakeClient.calls = []
        FakeClient.error = RuntimeError("Monthly usage hard limit exceeded")

    def test_quota_error_stops_remaining_bands(self):
        with patch.object(scraper, "ApifyClient", FakeClient), patch.object(scraper, "APIFY_TOKEN", "token"):
            with self.assertRaises(scraper.ApifyQuotaError):
                scraper.scrape_market({"city": "Cleveland", "state": "OH", "min_price": 30000, "max_price": 125000})

        self.assertEqual(len(FakeClient.calls), 1)

    def test_quota_error_stops_remaining_markets(self):
        with patch.object(main, "get_target_markets", return_value=["little_rock", "oklahoma_city"]), \
             patch.object(main, "run_market", side_effect=scraper.ApifyQuotaError("quota exceeded")) as run_market, \
             patch.object(main, "save_pipeline_log") as save_pipeline_log, \
             patch.object(sys, "argv", ["main.py", "--dry-run", "--force"]):
            main.main()

        self.assertEqual(run_market.call_count, 1)
        save_pipeline_log.assert_not_called()

    def test_quota_error_does_not_save_empty_dashboard_json(self):
        with patch.object(main, "scrape_market", side_effect=scraper.ApifyQuotaError("quota exceeded")), \
             patch.object(main, "load_overflow", return_value=[]), \
             patch.object(main, "save_dashboard_data") as save_dashboard_data:
            with self.assertRaises(scraper.ApifyQuotaError):
                main.run_market("little_rock", dry_run=True)

        save_dashboard_data.assert_not_called()

    def test_non_quota_scrape_errors_still_follow_existing_behavior(self):
        FakeClient.error = RuntimeError("temporary actor failure")
        with patch.object(scraper, "ApifyClient", FakeClient), patch.object(scraper, "APIFY_TOKEN", "token"):
            leads = scraper.scrape_market({"city": "Cleveland", "state": "OH", "min_price": 30000, "max_price": 125000})

        self.assertEqual(leads, [])
        self.assertGreater(len(FakeClient.calls), 1)


if __name__ == "__main__":
    unittest.main()
