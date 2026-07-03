"""
Tests: Zillow detail-page "Listed by" contact extraction (2026-07-02).

Proves:
- the four real production "Listed by" strings parse to the correct
  agent/email/phone/brokerage,
- multi-agent, email-without-phone, phone-without-email, and
  brokerage-after-comma formats all work,
- no email is ever produced that wasn't literally in the text,
- the detail-page rung runs BEFORE any Google call and short-circuits it,
- a detail-page email is marked source_verified / sendable with
  source_type zillow_detail_listed_by.
"""
import sys
import types
import unittest

if "apify_client" not in sys.modules:
    stub = types.ModuleType("apify_client")
    stub.ApifyClient = object
    sys.modules["apify_client"] = stub

from zillow_detail_contact import parse_listed_by_block, fetch_detail_contact
import agent_email_finder as aef

aef.time.sleep = lambda *_: None


# The four real listings from manual review.
REAL_CASES = {
    "12 Maple Dr": {
        "text": "Listed by: Sonja Halstead 330-388-0566 sonjahalstead@kw.com, "
                "Keller Williams Elevate",
        "name": "Sonja Halstead",
        "email": "sonjahalstead@kw.com",
        "phone": "330-388-0566",
        "brokerage_contains": "Keller Williams",
    },
    "657 E 131st St": {
        "text": "Listed by: Seth B Task jeannet@taskteamcle.com, "
                "Berkshire Hathaway HomeServices Professional Realty, "
                "Jeannet Wright 216-269-3467",
        "name": "Seth B Task",
        "email": "jeannet@taskteamcle.com",
        "phone": "216-269-3467",
        "brokerage_contains": "Berkshire Hathaway",
    },
    "7300 Claasen Ave": {
        "text": "Listed by: Daniel S Reid 216-387-0757 dreid@stoufferrealty.com, "
                "Berkshire Hathaway HomeServices Stouffer Realty",
        "name": "Daniel S Reid",
        "email": "dreid@stoufferrealty.com",
        "phone": "216-387-0757",
        "brokerage_contains": "Stouffer",
    },
    "9807 Elizabeth Ave": {
        "text": "Listed by: David L Sturgeon 216-375-4486 davidsturgeon@howardhanna.com, "
                "Howard Hanna",
        "name": "David L Sturgeon",
        "email": "davidsturgeon@howardhanna.com",
        "phone": "216-375-4486",
        "brokerage_contains": "Howard Hanna",
    },
}


class RealListedByExamplesTest(unittest.TestCase):
    def test_all_four_real_examples(self):
        for label, exp in REAL_CASES.items():
            r = parse_listed_by_block(exp["text"])
            self.assertEqual(r["agent_email"], exp["email"], f"{label} email")
            self.assertEqual(r["agent_phone"], exp["phone"], f"{label} phone")
            self.assertEqual(r["agent_name"], exp["name"], f"{label} name")
            self.assertIn(exp["brokerage_contains"], r["brokerage"], f"{label} brokerage")


class ListedByFormatVariantsTest(unittest.TestCase):
    def test_email_without_phone(self):
        r = parse_listed_by_block("Listed by: Jane Smith jane@acmerealty.com, Acme Realty")
        self.assertEqual(r["agent_email"], "jane@acmerealty.com")
        self.assertEqual(r["agent_phone"], "")
        self.assertEqual(r["agent_name"], "Jane Smith")
        self.assertIn("Acme", r["brokerage"])

    def test_phone_without_email(self):
        r = parse_listed_by_block("Listed by: John Doe 216-555-1212, Big Broker LLC")
        self.assertEqual(r["agent_email"], "")
        self.assertEqual(r["agent_phone"], "216-555-1212")
        self.assertEqual(r["agent_name"], "John Doe")
        self.assertIn("Big Broker", r["brokerage"])

    def test_multiple_agents_on_one_line(self):
        r = parse_listed_by_block(
            "Listed by: Seth B Task jeannet@taskteamcle.com, ABC Realty, "
            "Jeannet Wright 216-269-3467")
        # Primary email + a phone from the second agent are both captured
        self.assertEqual(r["agent_email"], "jeannet@taskteamcle.com")
        self.assertEqual(r["agent_phone"], "216-269-3467")
        self.assertEqual(len(r["all_agents"]), 2)

    def test_brokerage_after_comma(self):
        r = parse_listed_by_block("Listed by: Amy Lin 555-123-4567 amy@lin.com, Coldwell Banker")
        self.assertIn("Coldwell Banker", r["brokerage"])

    def test_no_listed_by_marker_returns_empty(self):
        r = parse_listed_by_block("Just some random page text with no contact block")
        self.assertEqual(r["agent_email"], "")
        self.assertEqual(r["agent_name"], "")

    def test_never_invents_email(self):
        # No email in text → email must stay empty (no guessing from name/brokerage)
        r = parse_listed_by_block("Listed by: Jane Smith 216-555-0000, Acme Realty")
        self.assertEqual(r["agent_email"], "")

    def test_empty_input(self):
        r = parse_listed_by_block("")
        self.assertEqual(r["agent_email"], "")


class FakeDetailClient:
    """Apify-style client returning canned detail-page items."""
    def __init__(self, detail_text):
        self.detail_text = detail_text
        self.google_calls = 0

    def actor(self, actor_id):
        outer = self
        is_google = "google" in actor_id.lower()

        class _Actor:
            def call(self, run_input=None, timeout_secs=None):
                if is_google:
                    outer.google_calls += 1
                    return {"defaultDatasetId": "google"}
                return {"defaultDatasetId": "detail"}
        return _Actor()

    def dataset(self, dataset_id):
        outer = self

        class _Dataset:
            def iterate_items(self):
                if dataset_id == "detail":
                    return iter([{"description": outer.detail_text}])
                return iter([{"organicResults": []}])
        return _Dataset()


class DetailFetchAndLadderOrderingTest(unittest.TestCase):
    def test_fetch_detail_contact_marks_source_verified_sendable(self):
        client = FakeDetailClient(REAL_CASES["12 Maple Dr"]["text"])
        contact = fetch_detail_contact("https://www.zillow.com/homedetails/1_zpid/",
                                       client=client)
        self.assertEqual(contact["email"], "sonjahalstead@kw.com")
        self.assertEqual(contact["email_source_type"], "zillow_detail_listed_by")
        self.assertEqual(contact["email_confidence"], "source_verified")
        self.assertTrue(contact["email_is_sendable"])
        self.assertEqual(contact["email_source_url"],
                         "https://www.zillow.com/homedetails/1_zpid/")

    def test_detail_page_runs_before_google_and_short_circuits(self):
        """When the detail page yields an email, ZERO Google calls happen."""
        client = FakeDetailClient(REAL_CASES["9807 Elizabeth Ave"]["text"])
        lead = {
            "address": "9807 Elizabeth Ave", "brokerage_name": "Howard Hanna",
            "city": "Cleveland", "agent_email": "",
            "listing_url": "https://www.zillow.com/homedetails/9807_zpid/",
        }
        contact = aef.find_published_agent_contact(lead, client)
        self.assertEqual(contact["email"], "davidsturgeon@howardhanna.com")
        self.assertEqual(contact["email_source_type"], "zillow_detail_listed_by")
        self.assertEqual(client.google_calls, 0,
                         "Google must not be called when detail page has the email")

    def test_falls_back_to_google_when_detail_has_no_email(self):
        # Detail page has a phone but no email → Google ladder should run
        client = FakeDetailClient("Listed by: Jane Smith 216-555-0000, Acme Realty")
        lead = {
            "address": "1 Main St", "brokerage_name": "Acme Realty",
            "city": "Cleveland", "agent_email": "",
            "listing_url": "https://www.zillow.com/homedetails/1_zpid/",
        }
        aef.find_published_agent_contact(lead, client)
        self.assertGreater(client.google_calls, 0,
                           "Google fallback must run when detail page has no email")

    def test_enrich_leads_uses_detail_page(self):
        client = FakeDetailClient(REAL_CASES["7300 Claasen Ave"]["text"])
        leads = [{
            "address": "7300 Claasen Ave", "brokerage_name": "BHHS Stouffer Realty",
            "agent_email": "", "listing_url": "https://www.zillow.com/homedetails/7300_zpid/",
        }]
        out = aef.enrich_leads_with_emails(leads, {"city": "Cleveland"}, client)
        self.assertEqual(out[0]["agent_email"], "dreid@stoufferrealty.com")
        self.assertEqual(out[0]["email_source_type"], "zillow_detail_listed_by")
        self.assertEqual(client.google_calls, 0)


if __name__ == "__main__":
    unittest.main()
