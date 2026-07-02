"""
Tests: agent-name validation + enrichment query fallback (2026-07-02 fix).

Proves the exact dry-run failure can't recur: numeric agent strings like
"33", "35", "82", "134" are rejected everywhere and never used as Google
search names; invalid/missing names fall back to property address +
brokerage + listing URL queries.
"""
import sys
import types
import unittest

# Stub apify_client before importing modules that reference it
if "apify_client" not in sys.modules:
    stub = types.ModuleType("apify_client")
    stub.ApifyClient = object
    sys.modules["apify_client"] = stub

from contact_validation import (
    is_valid_agent_name, clean_agent_name, extract_emails_from_text,
    email_is_sendable, SENDABLE_CONFIDENCES,
)
import agent_email_finder as aef
aef.time.sleep = lambda *_: None  # no real sleeping in tests


class FakeGoogleClient:
    """Records every query; returns canned organic results per call."""

    def __init__(self, results_by_call=None):
        self.queries = []
        self.results_by_call = results_by_call or []

    def actor(self, actor_id):
        outer = self

        class _Actor:
            def call(self, run_input=None, timeout_secs=None):
                outer.queries.append(run_input["queries"])
                return {"defaultDatasetId": len(outer.queries) - 1}
        return _Actor()

    def dataset(self, dataset_id):
        outer = self

        class _Dataset:
            def iterate_items(self):
                if dataset_id < len(outer.results_by_call):
                    return iter([{"organicResults": outer.results_by_call[dataset_id]}])
                return iter([{"organicResults": []}])
        return _Dataset()


class AgentNameValidationTest(unittest.TestCase):
    def test_numeric_agent_strings_rejected(self):
        # The exact values from the failed Cleveland/Akron dry run
        for junk in ["33", "35", "82", "134", "0", "999999"]:
            self.assertFalse(is_valid_agent_name(junk), junk)
            self.assertEqual(clean_agent_name(junk), "")

    def test_empty_null_and_short_rejected(self):
        for junk in ["", None, "  ", "ab", "J", 42, ["list"]]:
            self.assertFalse(is_valid_agent_name(junk), repr(junk))

    def test_id_count_phone_fragments_rejected(self):
        for junk in ["MLS 123456", "#82", "ID: 4471", "zpid 20374887",
                     "(216) 555", "330-555-1234", "12 photos",
                     "33 days on Zillow", "25 views"]:
            self.assertFalse(is_valid_agent_name(junk), junk)

    def test_real_names_accepted(self):
        for name in ["Jane Smith", "The Smith Team", "J. Alvarez",
                     "Keller Williams Greater Metropolitan",
                     "Mary O'Brien-Walsh", "DeShawn Carter Jr."]:
            self.assertTrue(is_valid_agent_name(name), name)

    def test_overlong_text_soup_rejected(self):
        """
        Regression (found during dry-run simulation 2026-07-02): when an item
        has no 'Listed by:' marker and no email/phone anywhere, the old
        visible-text parser fell back to the ENTIRE concatenated item as
        agent_name. Long concatenated blobs must never validate as a name.
        """
        blob = ("123 Euclid Ave Cleveland OH 111 /homedetails/123_zpid/ 33 "
                "Keller Williams Greater Cleveland Motivated seller, needs "
                "TLC, investor special")
        self.assertFalse(is_valid_agent_name(blob))
        self.assertEqual(clean_agent_name(blob), "")


class FallbackQueryTest(unittest.TestCase):
    def test_numeric_agent_never_appears_in_queries(self):
        client = FakeGoogleClient()
        lead = {
            "agent_name": "33",                    # junk from old extraction
            "brokerage_name": "Acme Realty Group",
            "address": "123 Euclid Ave",
            "city": "Cleveland",
            "url": "https://www.zillow.com/homedetails/123_zpid/",
        }
        aef.find_published_agent_contact(lead, client)
        self.assertTrue(client.queries, "expected fallback queries to run")
        for q in client.queries:
            self.assertNotIn('"33"', q, f"junk agent name leaked into query: {q}")

    def test_invalid_agent_falls_back_to_address_brokerage_listing(self):
        client = FakeGoogleClient()
        lead = {
            "agent_name": "82",
            "brokerage_name": "Acme Realty Group",
            "address": "456 Main St",
            "city": "Akron",
            "url": "https://www.zillow.com/homedetails/456_zpid/",
        }
        aef.find_published_agent_contact(lead, client)
        joined = " || ".join(client.queries)
        self.assertIn("456 Main St", joined)
        self.assertIn("Acme Realty Group", joined)
        self.assertIn("zillow.com/homedetails/456_zpid", joined)

    def test_valid_agent_name_is_used_in_queries(self):
        client = FakeGoogleClient()
        lead = {
            "agent_name": "Jane Smith",
            "brokerage_name": "Acme Realty Group",
            "address": "789 Oak St",
            "city": "Cleveland",
            "url": "",
        }
        aef.find_published_agent_contact(lead, client)
        joined = " || ".join(client.queries)
        self.assertIn('"Jane Smith"', joined)


class EmailExtractionTest(unittest.TestCase):
    def test_extracts_visible_email_from_snippet_text(self):
        emails = extract_emails_from_text(
            "Contact Jane Smith at jane.smith@acmerealty.com or call the office.")
        self.assertEqual(emails, ["jane.smith@acmerealty.com"])

    def test_extracts_mailto_links(self):
        emails = extract_emails_from_text(
            '<a href="mailto:Office@AcmeRealty.com">Email us</a>')
        self.assertEqual(emails, ["office@acmerealty.com"])

    def test_portal_and_freemail_domains_skipped(self):
        emails = extract_emails_from_text(
            "reply@zillow.com janedoe@gmail.com jane@acmerealty.com")
        self.assertEqual(emails, ["jane@acmerealty.com"])

    def test_ladder_returns_source_fields_for_snippet_email(self):
        results = [[{"title": "Jane Smith - Acme Realty",
                     "description": "Reach Jane at jane@acmerealty.com",
                     "url": "https://www.acmerealty.com/agents/jane"}]]
        client = FakeGoogleClient(results_by_call=results)
        lead = {"agent_name": "Jane Smith", "brokerage_name": "Acme Realty",
                "address": "1 Elm St", "city": "Cleveland",
                "url": "https://www.zillow.com/homedetails/1_zpid/"}
        contact = aef.find_published_agent_contact(lead, client)
        self.assertEqual(contact["email"], "jane@acmerealty.com")
        self.assertEqual(contact["email_confidence"], "snippet_verified")
        self.assertTrue(contact["email_is_sendable"])
        self.assertTrue(contact["email_source_url"].startswith("https://"))

    def test_office_fallback_is_marked_office_fallback(self):
        # Ladder for this lead makes: rung-3 (address+brokerage), rung-5
        # (roster), then rung-7 (office intake) — office result on call #3.
        empty = [[], []]
        office = [[{"title": "Acme Realty — Contact",
                    "description": "General inquiries: office@acmerealty.com",
                    "url": "https://www.acmerealty.com/contact"}]]
        client = FakeGoogleClient(results_by_call=empty + office)
        lead = {"agent_name": "", "brokerage_name": "Acme Realty",
                "address": "9 Pine St", "city": "Akron", "url": ""}
        contact = aef.find_published_agent_contact(lead, client)
        self.assertEqual(contact["email"], "office@acmerealty.com")
        self.assertEqual(contact["email_source_type"], "office_fallback")
        self.assertEqual(contact["email_confidence"], "office_fallback")
        self.assertTrue(contact["email_is_sendable"])

    def test_phone_only_after_all_rungs_fail(self):
        client = FakeGoogleClient()  # every call returns no results
        lead = {"agent_name": "Jane Smith", "brokerage_name": "Acme Realty",
                "address": "2 Elm St", "city": "Cleveland", "url": "",
                "agent_phone": "216-555-1234"}
        contact = aef.find_published_agent_contact(lead, client)
        self.assertEqual(contact["email"], "")
        self.assertFalse(contact["email_is_sendable"])
        self.assertEqual(contact["agent_phone"], "216-555-1234")
        self.assertGreaterEqual(len(client.queries), 3,
                                "must exhaust the ladder before phone-only")


class SendableConfidenceTest(unittest.TestCase):
    def test_sendable_confidences(self):
        self.assertEqual(SENDABLE_CONFIDENCES,
                         {"source_verified", "snippet_verified", "office_fallback"})
        for c in SENDABLE_CONFIDENCES:
            self.assertTrue(email_is_sendable(c))

    def test_pattern_guess_never_sendable_by_default(self):
        import os
        os.environ.pop("ALLOW_PATTERN_GUESS_SENDS", None)
        self.assertFalse(email_is_sendable("pattern_guess"))
        self.assertFalse(email_is_sendable(""))
        self.assertFalse(email_is_sendable("made_up_level"))


if __name__ == "__main__":
    unittest.main()
