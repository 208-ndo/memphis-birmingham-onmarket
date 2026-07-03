"""
Tests: Zillow-detail free-mail acceptance vs Google strictness (2026-07-02).

The bug: a real agent email published on Zillow's own listing page
(frefrederickteam@gmail.com) was dropped because the detail parser reused
the general business-email skip list, which rejects gmail globally. Fix:
detail-page extraction uses its own acceptance rule that keeps free-mail
domains, while Google/snippet extraction stays strict and unchanged.
"""
import sys
import types
import unittest

if "apify_client" not in sys.modules:
    stub = types.ModuleType("apify_client")
    stub.ApifyClient = object
    sys.modules["apify_client"] = stub

from zillow_detail_contact import (
    parse_listed_by_block, is_valid_zillow_detail_email,
    extract_zillow_detail_emails, extract_contact_from_flat_text,
    fetch_detail_contact,
)
from contact_validation import (
    is_plausible_business_email, extract_emails_from_text,
)


class ZillowDetailAcceptsPublishedFreeMailTest(unittest.TestCase):
    REAL_CASES = [
        ("Listed by: Christopher Frederick 216-210-7653 "
         "frefrederickteam@gmail.com, Coldwell Banker Schmidt Realty",
         "Christopher Frederick", "frefrederickteam@gmail.com", "216-210-7653"),
        ("Listed by: Brett Munich 440-539-2897 brett@impactsellshomes.com, "
         "Keller Williams Greater Metropolitan",
         "Brett Munich", "brett@impactsellshomes.com", "440-539-2897"),
        ("Listed by: Sonja Halstead 330-388-0566 sonjahalstead@kw.com, "
         "Keller Williams Elevate",
         "Sonja Halstead", "sonjahalstead@kw.com", "330-388-0566"),
    ]

    def test_all_three_real_examples_extract_email(self):
        for text, name, email, phone in self.REAL_CASES:
            r = parse_listed_by_block(text)
            self.assertEqual(r["agent_email"], email, text)
            self.assertEqual(r["agent_name"], name, text)
            self.assertEqual(r["agent_phone"], phone, text)

    def test_validator_accepts_free_mail(self):
        for email in ("frefrederickteam@gmail.com", "someone@yahoo.com",
                      "agent@outlook.com", "person@hotmail.com",
                      "brett@impactsellshomes.com", "sonjahalstead@kw.com"):
            self.assertTrue(is_valid_zillow_detail_email(email), email)

    def test_validator_rejects_junk_and_image_domains(self):
        for bad in ("", "notanemail", "x@sentry.io", "logo@example.com",
                    "img@2x.png", "sprite@assets.png"):
            self.assertFalse(is_valid_zillow_detail_email(bad), bad)

    def test_extract_zillow_detail_emails_keeps_gmail(self):
        emails = extract_zillow_detail_emails(
            "Listed by: Chris frefrederickteam@gmail.com, Coldwell Banker")
        self.assertIn("frefrederickteam@gmail.com", emails)


class GoogleSnippetStaysStrictTest(unittest.TestCase):
    """Google/snippet extraction must STILL reject free-mail (unchanged)."""

    def test_google_business_email_still_rejects_gmail(self):
        self.assertFalse(is_plausible_business_email("frefrederickteam@gmail.com"))
        self.assertFalse(is_plausible_business_email("someone@yahoo.com"))

    def test_google_extract_still_drops_gmail(self):
        # This is the function used by the Google ladder — unchanged behavior.
        result = extract_emails_from_text(
            "Contact frefrederickteam@gmail.com or info@realbrokerage.com")
        self.assertNotIn("frefrederickteam@gmail.com", result)
        self.assertIn("info@realbrokerage.com", result)

    def test_google_business_email_still_accepts_business_domain(self):
        self.assertTrue(is_plausible_business_email("brett@impactsellshomes.com"))


class FetchDetailContactFreeMailTest(unittest.TestCase):
    """End-to-end: a published gmail on the detail page is source_verified + sendable."""

    class FakeClient:
        def __init__(self, text):
            self.text = text

        def actor(self, actor_id):
            outer = self

            class _A:
                def call(self, run_input=None, timeout_secs=None):
                    return {"defaultDatasetId": "d"}
            return _A()

        def dataset(self, dataset_id):
            outer = self

            class _D:
                def iterate_items(self):
                    # nested under unguessed keys
                    return iter([{"props": {"gdp": {"attr": {"blurb": outer.text}}}}])
            return _D()

    def test_gmail_on_detail_page_is_source_verified_sendable(self):
        text = ("Listed by: Christopher Frederick 216-210-7653 "
                "frefrederickteam@gmail.com, Coldwell Banker Schmidt Realty")
        client = self.FakeClient(text)
        contact = fetch_detail_contact(
            "https://www.zillow.com/homedetails/19806_zpid/", client=client)
        self.assertEqual(contact["email"], "frefrederickteam@gmail.com")
        self.assertEqual(contact["email_source_type"], "zillow_detail_listed_by")
        self.assertEqual(contact["email_confidence"], "source_verified")
        self.assertTrue(contact["email_is_sendable"])

    def test_structured_attribution_gmail_extracted(self):
        # No literal "Listed by" marker; email sits after agentEmail key.
        flat = ('property attributionInfo agentName Christopher Frederick '
                'agentPhoneNumber 216-210-7653 agentEmail '
                'frefrederickteam@gmail.com brokerName Coldwell Banker')
        r = extract_contact_from_flat_text(flat)
        self.assertEqual(r["agent_email"], "frefrederickteam@gmail.com")
        self.assertEqual(r["agent_phone"], "216-210-7653")


if __name__ == "__main__":
    unittest.main()
