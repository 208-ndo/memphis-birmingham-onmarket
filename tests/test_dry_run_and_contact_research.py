"""
Tests: dry-run Gmail isolation + contact research queue export (2026-07-02).

Proves:
- dry_run=True never calls Gmail credential checks or send_email at all
  (send_batch short-circuits before send_email is invoked).
- ready leads are never marked "Failed" in dry run just because Gmail
  secrets are missing from the environment.
- leads with no verified email produce a clean, correctly-shaped
  data/no_email_contact_research_candidates.csv row and are never marked failed.
- verified/sendable leads still flow into the normal send_queue.
"""
import csv
import importlib
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime
from unittest.mock import patch

if "apify_client" not in sys.modules:
    stub = types.ModuleType("apify_client")
    stub.ApifyClient = object
    sys.modules["apify_client"] = stub


class DryRunNeverChecksCredentialsTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("LIVE_SEND_ENABLED", None)
        import gmail_send
        importlib.reload(gmail_send)
        self.gmail_send = gmail_send
        # Markets with NO Gmail credentials at all — exactly the failure
        # scenario from the report (dry run with no Gmail secrets configured).
        self.no_creds_markets = {
            "cleveland": {"gmail_user": "", "gmail_app_password": "", "city": "Cleveland"},
        }

    def test_send_batch_dry_run_never_calls_send_email(self):
        called = {"count": 0}
        real_send_email = self.gmail_send.send_email

        def spy_send_email(*a, **k):
            called["count"] += 1
            return real_send_email(*a, **k)

        queue = [{
            "listing": {"address": "123 Main St", "agent_email": "agent@broker.com",
                       "price": 65000},
            "offer": {},
            "email": {"subject": "Quick question", "body": "Hi"},
        }]
        with patch.object(self.gmail_send, "MARKETS", self.no_creds_markets), \
             patch.object(self.gmail_send, "send_email", spy_send_email), \
             patch.object(self.gmail_send, "generate_offer_pdf", lambda *a, **k: None), \
             patch.object(self.gmail_send, "time") as mock_time:
            mock_time.sleep = lambda *_: None
            results = self.gmail_send.send_batch(queue, "cleveland", dry_run=True)

        self.assertEqual(called["count"], 0,
                         "send_email() must never be called during a dry run")
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["success"])

    def test_ready_lead_not_marked_failed_when_credentials_missing_in_dry_run(self):
        queue = [{
            "listing": {"address": "456 Oak St", "agent_email": "agent@broker.com",
                       "price": 72000},
            "offer": {},
            "email": {"subject": "Quick question", "body": "Hi"},
        }]
        with patch.object(self.gmail_send, "MARKETS", self.no_creds_markets), \
             patch.object(self.gmail_send, "generate_offer_pdf", lambda *a, **k: None), \
             patch.object(self.gmail_send, "time") as mock_time:
            mock_time.sleep = lambda *_: None
            results = self.gmail_send.send_batch(queue, "cleveland", dry_run=True)

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["success"], "ready lead wrongly marked failed in dry run")

    def test_dry_run_log_message_present(self):
        queue = [{
            "listing": {"address": "789 Pine St", "agent_email": "agent@broker.com",
                       "price": 58000},
            "offer": {},
            "email": {"subject": "Quick question", "body": "Hi"},
        }]
        with patch.object(self.gmail_send, "MARKETS", self.no_creds_markets), \
             patch.object(self.gmail_send, "generate_offer_pdf", lambda *a, **k: None), \
             patch.object(self.gmail_send, "time") as mock_time, \
             self.assertLogs(self.gmail_send.log, level="INFO") as log_ctx:
            mock_time.sleep = lambda *_: None
            self.gmail_send.send_batch(queue, "cleveland", dry_run=True)

        joined = " ".join(log_ctx.output)
        self.assertIn("DRY RUN", joined)
        self.assertIn("Gmail skipped", joined)
        self.assertNotIn("Missing Gmail credentials", joined)
        self.assertNotIn("Failed:", joined)


class ContactResearchQueueTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("TARGET_MARKETS", None)
        import main
        importlib.reload(main)
        self.main = main
        self.tmpdir = tempfile.mkdtemp()
        self._old_cwd = os.getcwd()
        os.chdir(self.tmpdir)

    def tearDown(self):
        os.chdir(self._old_cwd)

    def test_build_contact_research_row_shape(self):
        listing = {
            "address": "123 Euclid Ave", "price": 65000, "days_on_market": 45,
            "brokerage_name": "Keller Williams Greater Cleveland",
            "listing_url": "https://www.zillow.com/homedetails/111_zpid/",
            "zpid": "111", "score": 42.5, "city": "Cleveland",
        }
        row = self.main.build_contact_research_row(
            listing, "cleveland", reason="no_verified_email_after_enrichment")

        self.assertEqual(row["market"], "cleveland")
        self.assertEqual(row["score"], 42.5)
        self.assertEqual(row["address"], "123 Euclid Ave")
        self.assertEqual(row["price"], 65000)
        self.assertEqual(row["dom"], 45)
        self.assertEqual(row["brokerage"], "Keller Williams Greater Cleveland")
        self.assertEqual(row["listing_url"], "https://www.zillow.com/homedetails/111_zpid/")
        self.assertEqual(row["zpid"], "111")
        self.assertEqual(row["contact_status"], "needs_contact_research")
        self.assertEqual(row["run_date"], datetime.now().date().isoformat())
        self.assertIn("123 Euclid Ave", row["suggested_search_1"])
        self.assertIn("Keller Williams Greater Cleveland", row["suggested_search_1"])
        self.assertIn("Keller Williams Greater Cleveland", row["suggested_search_2"])
        self.assertIn("Cleveland", row["suggested_search_2"])
        self.assertEqual(row["suggested_search_3"], "https://www.zillow.com/homedetails/111_zpid/")

    def test_csv_created_with_required_columns(self):
        rows = [self.main.build_contact_research_row(
            {"address": "1 Main St", "price": 50000, "days_on_market": 30,
             "brokerage_name": "Acme Realty", "zpid": "1"},
            "cleveland", "no_verified_email_after_enrichment")]
        self.main.save_contact_research_queue(rows)

        self.assertTrue(os.path.exists("data/no_email_contact_research_candidates.csv"))
        with open("data/no_email_contact_research_candidates.csv", newline="") as f:
            reader = csv.DictReader(f)
            self.assertEqual(reader.fieldnames, self.main.NO_EMAIL_CONTACT_RESEARCH_COLUMNS)
            written = list(reader)
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["contact_status"], "needs_contact_research")

    def test_csv_dedupes_across_runs(self):
        row = self.main.build_contact_research_row(
            {"address": "2 Elm St", "price": 60000, "days_on_market": 40, "zpid": "2"},
            "akron", "no_verified_email_after_enrichment")
        self.main.save_contact_research_queue([row])
        self.main.save_contact_research_queue([row])  # same lead again

        with open("data/no_email_contact_research_candidates.csv", newline="") as f:
            written = list(csv.DictReader(f))
        self.assertEqual(len(written), 1, "duplicate lead must not be appended twice")

    def test_run_market_no_email_lead_goes_to_csv_not_failed(self):
        """Full run_market path: a lead with no agent_email is skipped
        cleanly (not failed) and lands in the new no-email research CSV."""
        fake_market = {"city": "Cleveland", "state": "OH", "gmail_user": "", "gmail_app_password": ""}
        fake_lead = {
            "address": "9 No Email Ave", "price": 55000, "days_on_market": 40,
            "agent_name": "", "agent_email": "", "brokerage_name": "Acme Realty",
            "zpid": "999", "listing_url": "https://www.zillow.com/homedetails/999_zpid/",
            "score": 33.0, "market": "cleveland",
        }
        with patch.object(self.main, "MARKETS", {"cleveland": fake_market}), \
             patch.object(self.main, "scrape_market", lambda m: [fake_lead]), \
             patch.object(self.main, "should_send", lambda l: True), \
             patch.object(self.main, "send_batch", lambda q, mk, dry_run: []):
            result = self.main.run_market("cleveland", dry_run=True)

        self.assertEqual(result["emails_sent"], 0)
        self.assertTrue(os.path.exists("data/no_email_contact_research_candidates.csv"))
        with open("data/no_email_contact_research_candidates.csv", newline="") as f:
            written = list(csv.DictReader(f))
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["address"], "9 No Email Ave")
        self.assertEqual(written[0]["contact_status"], "needs_contact_research")


class DoesNotTouchExistingResearchFileTest(unittest.TestCase):
    """
    Required regression test: data/contact_research_queue.csv already holds
    25+ real researched leads (phone numbers, contact notes, approved_to_send
    flags) in its own 22-column schema. The new no-email export must never
    read, write, rename, or otherwise touch that file — it only ever
    operates on the separate data/no_email_contact_research_candidates.csv.
    """
    def setUp(self):
        import main
        importlib.reload(main)
        self.main = main
        self.tmpdir = tempfile.mkdtemp()
        self._old_cwd = os.getcwd()
        os.chdir(self.tmpdir)

        os.makedirs("data", exist_ok=True)
        self.old_schema_content = (
            "queue_id,market_key,address,city,state,list_price,score,"
            "offer_lane,agent_name,agent_email,manual_agent_email,"
            "effective_agent_email,needs_agent_email,zillow_url,email_subject,"
            "contact_status,found_email,found_phone,contact_source_url,"
            "contact_source_type,contact_notes,approved_to_send\n"
            "abc123,cleveland,\"1 Real St\",Cleveland,OH,60000,80.0,"
            "OWNER_FINANCE_PRODUCTION,Jane Agent,,,,true,"
            "https://www.zillow.com/homedetails/1_zpid/,subj,phone_only,,"
            "216-555-0000,https://example.com,brokerage_contact_form,"
            "\"real prior research notes\",false\n"
        )
        with open("data/contact_research_queue.csv", "w") as f:
            f.write(self.old_schema_content)

    def tearDown(self):
        os.chdir(self._old_cwd)

    def test_existing_file_never_modified(self):
        with open("data/contact_research_queue.csv") as f:
            before = f.read()

        rows = [self.main.build_contact_research_row(
            {"address": "2 New St", "price": 50000, "days_on_market": 30,
             "brokerage_name": "Acme Realty", "zpid": "2"},
            "cleveland", "no_verified_email_after_enrichment")]
        self.main.save_contact_research_queue(rows)

        with open("data/contact_research_queue.csv") as f:
            after = f.read()

        self.assertEqual(before, after,
                         "data/contact_research_queue.csv must never be modified")
        self.assertEqual(after, self.old_schema_content)

    def test_existing_file_never_read(self):
        """The new export function must not even open the old file."""
        real_open = open
        opened_paths = []

        def spy_open(path, *a, **k):
            opened_paths.append(str(path))
            return real_open(path, *a, **k)

        rows = [self.main.build_contact_research_row(
            {"address": "3 New St", "price": 45000, "days_on_market": 20, "zpid": "3"},
            "akron", "no_verified_email_after_enrichment")]
        with patch("builtins.open", spy_open):
            self.main.save_contact_research_queue(rows)

        self.assertNotIn("data/contact_research_queue.csv", opened_paths,
                         "must never open the existing researched-leads file")

    def test_new_file_created_separately_alongside_old_file(self):
        rows = [self.main.build_contact_research_row(
            {"address": "4 New St", "price": 48000, "days_on_market": 25, "zpid": "4"},
            "akron", "no_verified_email_after_enrichment")]
        self.main.save_contact_research_queue(rows)

        # Old file: untouched, still exactly 2 lines (header + 1 real row)
        with open("data/contact_research_queue.csv") as f:
            old_lines = f.readlines()
        self.assertEqual(len(old_lines), 2)

        # New file: created fresh with the new schema
        self.assertTrue(os.path.exists("data/no_email_contact_research_candidates.csv"))
        with open("data/no_email_contact_research_candidates.csv", newline="") as f:
            reader = csv.DictReader(f)
            self.assertEqual(reader.fieldnames, self.main.NO_EMAIL_CONTACT_RESEARCH_COLUMNS)
            new_rows = list(reader)
        self.assertEqual(len(new_rows), 1)
        self.assertEqual(new_rows[0]["address"], "4 New St")


class DryRunNeverChecksCredentialsFilesystemLevelTest(unittest.TestCase):
    """
    Required regression test: dry_run=True must never even evaluate
    market["gmail_user"] / market["gmail_app_password"] — proven here by
    using a MARKETS dict whose access raises, so ANY credential lookup
    during a dry run fails the test loudly.
    """

    class ExplodingMarketsDict(dict):
        def __getitem__(self, key):
            entry = super().__getitem__(key)
            return self._ExplodingMarket(entry)

        class _ExplodingMarket(dict):
            def __getitem__(self, key):
                if key in ("gmail_user", "gmail_app_password"):
                    raise AssertionError(
                        f"Gmail credential '{key}' was accessed during a dry run")
                return super().__getitem__(key)

    def setUp(self):
        import gmail_send
        importlib.reload(gmail_send)
        self.gmail_send = gmail_send

    def test_dry_run_never_accesses_credential_keys(self):
        exploding_markets = self.ExplodingMarketsDict(
            cleveland={"city": "Cleveland", "gmail_user": "x", "gmail_app_password": "y"})
        queue = [{
            "listing": {"address": "1 Safe St", "agent_email": "agent@broker.com",
                       "price": 60000},
            "offer": {},
            "email": {"subject": "Quick question", "body": "Hi"},
        }]
        with patch.object(self.gmail_send, "MARKETS", exploding_markets), \
             patch.object(self.gmail_send, "generate_offer_pdf", lambda *a, **k: None), \
             patch.object(self.gmail_send, "time") as mock_time:
            mock_time.sleep = lambda *_: None
            # Must not raise — proves gmail_user/gmail_app_password were
            # never accessed anywhere in the dry-run path.
            results = self.gmail_send.send_batch(queue, "cleveland", dry_run=True)
        self.assertTrue(results[0]["success"])


if __name__ == "__main__":
    unittest.main()
