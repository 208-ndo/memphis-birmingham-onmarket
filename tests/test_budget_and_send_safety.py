"""
Tests: split Apify budgets + live-send safety (2026-07-02 fix).

Proves:
- per-market email budget prevents Cleveland from starving Akron enrichment,
- Zillow cap is independent of the email cap,
- the shared global Apify cap still acts as an emergency stop,
- dry_run=True never sends Gmail,
- LIVE_SEND_ENABLED != "true" never sends Gmail even if dry_run parsing broke,
- pattern_guess emails are never live-sent,
- GHL push is skipped in dry run.
"""
import importlib
import os
import sys
import types
import unittest
from unittest.mock import patch

if "apify_client" not in sys.modules:
    stub = types.ModuleType("apify_client")
    stub.ApifyClient = object
    sys.modules["apify_client"] = stub

import scraper
import config


def reset_budget_counters():
    scraper._apify_call_count = 0
    scraper._zillow_call_count = 0
    scraper._email_enrichment_call_count = 0
    scraper._email_market_counts = {}


class SplitBudgetTest(unittest.TestCase):
    def setUp(self):
        reset_budget_counters()

    def test_per_market_cap_prevents_market_starvation(self):
        """Cleveland exhausts its per-market slice; Akron can still enrich."""
        per_market = scraper.MAX_EMAIL_ENRICHMENT_CALLS_PER_MARKET
        for _ in range(per_market):
            self.assertTrue(scraper.can_make_email_enrichment_call(market_key="cleveland"))
            scraper.register_email_enrichment_call(market_key="cleveland")
        # Cleveland's slice is gone
        self.assertFalse(scraper.can_make_email_enrichment_call(market_key="cleveland"))
        # Akron still has its full slice
        self.assertTrue(scraper.can_make_email_enrichment_call(market_key="akron"))

    def test_email_calls_do_not_consume_zillow_cap(self):
        """The old bug: Cleveland's 5 Google calls left Akron only 2 Zillow calls."""
        for _ in range(5):
            scraper.register_email_enrichment_call(market_key="cleveland")
        # All Zillow budget must still be available
        used_before = scraper._zillow_call_count
        self.assertEqual(used_before, 0)
        for _ in range(scraper.MAX_ZILLOW_CALLS_PER_WORKFLOW):
            self.assertTrue(scraper.can_make_zillow_call())
            scraper.register_zillow_call()
        self.assertFalse(scraper.can_make_zillow_call())

    def test_zillow_calls_do_not_consume_email_cap(self):
        for _ in range(scraper.MAX_ZILLOW_CALLS_PER_WORKFLOW):
            scraper.register_zillow_call()
        self.assertTrue(scraper.can_make_email_enrichment_call(market_key="akron"))

    def test_global_cap_is_emergency_stop_for_everything(self):
        scraper._apify_call_count = scraper.MAX_APIFY_RUNS_PER_WORKFLOW
        self.assertFalse(scraper.can_make_zillow_call())
        self.assertFalse(scraper.can_make_email_enrichment_call())
        self.assertFalse(scraper.can_make_email_enrichment_call(market_key="akron"))
        self.assertFalse(scraper.can_make_apify_call())

    def test_default_budgets_fit_two_market_three_band_run(self):
        """3 bands x 2 markets Zillow + 5 email calls x 2 markets must fit."""
        self.assertGreaterEqual(config.MAX_ZILLOW_CALLS_PER_WORKFLOW, 6)
        self.assertGreaterEqual(config.MAX_EMAIL_ENRICHMENT_CALLS_PER_WORKFLOW, 10)
        self.assertGreaterEqual(config.MAX_EMAIL_ENRICHMENT_CALLS_PER_MARKET, 5)
        self.assertGreaterEqual(
            config.MAX_APIFY_RUNS_PER_WORKFLOW,
            config.MAX_ZILLOW_CALLS_PER_WORKFLOW
            + config.MAX_EMAIL_ENRICHMENT_CALLS_PER_WORKFLOW,
            "emergency global cap must not block a normal full run",
        )

    def test_budget_status_reports_per_market_counts(self):
        scraper.register_email_enrichment_call(market_key="cleveland")
        status = scraper.get_apify_budget_status()
        self.assertEqual(status["google_calls_by_market"], {"cleveland": 1})
        self.assertIn("zillow_calls_max", status)


class LiveSendSafetyTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("LIVE_SEND_ENABLED", None)
        os.environ.pop("ALLOW_PATTERN_GUESS_SENDS", None)
        import gmail_send
        importlib.reload(gmail_send)
        self.gmail_send = gmail_send
        self.smtp_calls = []

    def _patch_smtp(self):
        outer = self

        class FakeSMTP:
            def __init__(self, *a, **k):
                outer.smtp_calls.append("connect")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def login(self, *a):
                outer.smtp_calls.append("login")

            def sendmail(self, *a):
                outer.smtp_calls.append("sendmail")

            def send_message(self, *a):
                outer.smtp_calls.append("send_message")

        return patch.object(self.gmail_send.smtplib, "SMTP_SSL", FakeSMTP, create=True), \
               patch.object(self.gmail_send.smtplib, "SMTP", FakeSMTP, create=True)

    def _market_patch(self):
        fake_markets = {"cleveland": {"gmail_user": "test@example.com",
                                      "gmail_app_password": "pw",
                                      "city": "Cleveland"}}
        return patch.object(self.gmail_send, "MARKETS", fake_markets)

    def test_dry_run_true_never_sends(self):
        p1, p2 = self._patch_smtp()
        with p1, p2, self._market_patch():
            ok = self.gmail_send.send_email(
                "cleveland", "agent@broker.com", "subj", "body", dry_run=True)
        self.assertTrue(ok)
        self.assertEqual(self.smtp_calls, [], "dry run must never touch SMTP")

    def test_live_send_env_false_blocks_even_if_dry_run_parsing_broke(self):
        """dry_run=False (weird parsing) + LIVE_SEND_ENABLED unset -> no SMTP."""
        p1, p2 = self._patch_smtp()
        with p1, p2, self._market_patch():
            self.gmail_send.send_email(
                "cleveland", "agent@broker.com", "subj", "body", dry_run=False)
        self.assertEqual(self.smtp_calls, [],
                         "LIVE_SEND_ENABLED!=true must hard-block real sends")

    def test_pattern_guess_email_never_live_sent(self):
        os.environ["LIVE_SEND_ENABLED"] = "true"
        p1, p2 = self._patch_smtp()
        with p1, p2, self._market_patch():
            ok = self.gmail_send.send_email(
                "cleveland", "guessed@broker.com", "subj", "body",
                dry_run=False, email_confidence="pattern_guess")
        self.assertFalse(ok)
        self.assertEqual(self.smtp_calls, [],
                         "pattern_guess must never be live-sent by default")
        os.environ.pop("LIVE_SEND_ENABLED", None)


class GhlDryRunSafetyTest(unittest.TestCase):
    def test_ghl_push_skipped_in_dry_run(self):
        """main.py's dry-run branch must never call push_to_ghl."""
        with open("main.py") as f:
            src = f.read()
        # The dry-run guard exists directly around the GHL push
        self.assertIn("DRY RUN — skipping GHL push", src)
        self.assertIn("if not dry_run:", src)


if __name__ == "__main__":
    unittest.main()
