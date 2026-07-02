"""
Regression test (2026-07-02): scraper.extract_lead() must never produce a
giant concatenated-item-text string as agent_name when the item has no real
'Listed by:' marker and no email/phone. Found via end-to-end dry-run
simulation after the initial fix — the visible-text fallback parser was
still leaking the whole item blob as agent_name in that case.
"""
import sys
import types
import unittest

if "apify_client" not in sys.modules:
    stub = types.ModuleType("apify_client")
    stub.ApifyClient = object
    sys.modules["apify_client"] = stub

import scraper
from contact_validation import is_valid_agent_name


class TextSoupRegressionTest(unittest.TestCase):
    def _market(self):
        return {"city": "Cleveland", "state": "OH"}

    def test_no_listed_by_no_contact_yields_no_agent_name(self):
        item = {
            "address": "123 Euclid Ave", "addressCity": "Cleveland",
            "addressState": "OH", "unformattedPrice": 65000, "zpid": "111",
            "detailUrl": "/homedetails/123_zpid/",
            "agentName": "33",  # numeric junk, filtered
            "brokerName": "Keller Williams Greater Cleveland",
            "beds": 3, "baths": 1, "livingArea": 1200,
            "description": "Motivated seller, needs TLC, investor special",
        }
        lead = scraper.extract_lead(item, self._market(), "test")
        self.assertIsNotNone(lead)
        self.assertEqual(lead["agent_name"], "",
                         f"expected empty agent_name, got text-soup leak: {lead['agent_name']!r}")
        self.assertLessEqual(len(lead["agent_name"]), 80)
        if lead["agent_name"]:
            self.assertTrue(is_valid_agent_name(lead["agent_name"]))

    def test_junk_brokerage_also_rejected(self):
        item = {
            "address": "789 Lorain Ave", "addressCity": "Cleveland",
            "addressState": "OH", "unformattedPrice": 58000, "zpid": "333",
            "detailUrl": "/homedetails/789_zpid/",
            "agentName": "82", "brokerName": "82",
            "beds": 2, "baths": 1, "livingArea": 900,
            "description": "Great opportunity for rehab, distressed sale",
        }
        lead = scraper.extract_lead(item, self._market(), "test")
        self.assertEqual(lead["agent_name"], "")
        self.assertEqual(lead["brokerage_name"], "")

    def test_real_listed_by_text_still_extracted(self):
        item = {
            "address": "1 Main St", "addressCity": "Cleveland",
            "addressState": "OH", "unformattedPrice": 60000, "zpid": "999",
            "detailUrl": "/homedetails/999_zpid/",
            "description": "Listed by: Jane Smith, ABC Realty",
            "beds": 3, "baths": 2, "livingArea": 1300,
        }
        lead = scraper.extract_lead(item, self._market(), "test")
        self.assertIn("Jane Smith", lead["agent_name"])
        self.assertTrue(is_valid_agent_name(lead["agent_name"]))


if __name__ == "__main__":
    unittest.main()
