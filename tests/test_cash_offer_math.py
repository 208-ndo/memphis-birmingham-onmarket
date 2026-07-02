import unittest

from preview_cash_offer_emails import (
    FORBIDDEN_PUBLIC_TERMS,
    build_cash_preview_records,
    build_summary,
    zompz_bracket_offer,
)


class CashOfferPreviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = build_cash_preview_records()
        cls.by_address = {row["address"]: row for row in cls.records}

    def test_30k_to_80k_does_not_create_cash_offer(self):
        row = self.by_address["75 Owner Finance Only Ave, Cleveland, OH 44105"]
        self.assertEqual(row["offer_lane"], "OWNER_FINANCE_ONLY")
        self.assertIsNone(row["conservative_20pct_offer"])
        self.assertIsNone(row["zompz_bracket_offer"])
        self.assertIsNone(row["selected_cash_offer"])
        self.assertFalse(row["auto_send"])

    def test_80k_to_150k_cash_preview_calculates_review_numbers(self):
        row = self.by_address["85 Cash Review Ave, Cleveland, OH 44105"]
        self.assertEqual(row["offer_lane"], "CASH_REVIEW_ARV_REQUIRED")
        self.assertEqual(row["conservative_20pct_offer"], 24000)
        self.assertEqual(row["zompz_bracket_offer"], 48000)
        self.assertIsNone(row["selected_cash_offer"])

        row = self.by_address["100 Cash Review Ave, Cleveland, OH 44105"]
        self.assertEqual(row["conservative_20pct_offer"], 30000)
        self.assertEqual(row["zompz_bracket_offer"], 60000)

        row = self.by_address["125 Cash Review Ave, Akron, OH 44320"]
        self.assertEqual(row["conservative_20pct_offer"], 36000)
        self.assertEqual(row["zompz_bracket_offer"], 90000)

    def test_zompz_brackets(self):
        self.assertEqual(zompz_bracket_offer(75000), 15000)
        self.assertEqual(zompz_bracket_offer(150000), 60000)
        self.assertEqual(zompz_bracket_offer(300000), 150000)
        self.assertEqual(zompz_bracket_offer(750000), 450000)
        self.assertEqual(zompz_bracket_offer(1500000), 975000)

    def test_cash_leads_are_manual_review_and_not_auto_send(self):
        summary = build_summary(self.records)
        self.assertEqual(summary["cash_review_count"], 3)
        self.assertEqual(summary["owner_finance_only_count"], 1)
        self.assertEqual(summary["auto_send_eligible_count"], 0)
        self.assertEqual(summary["emails_sent"], 0)
        self.assertFalse(summary["scraper_ran"])
        self.assertFalse(summary["apify_ran"])
        self.assertFalse(summary["gmail_ran"])
        self.assertFalse(summary["ghl_ran"])

    def test_optional_agent_comp_reserve_is_internal_only(self):
        row = self.by_address["100 Cash Review Ave, Cleveland, OH 44105"]
        internal = row["INTERNAL_ONLY"]
        self.assertEqual(internal["optional_agent_comp_reserve"], 0)
        self.assertEqual(internal["suggested_optional_agent_comp_reserve"], 1500)
        self.assertNotIn("optional_agent_comp_reserve", row["email_body"])

    def test_cash_public_email_text_has_no_forbidden_terms(self):
        for row in self.records:
            body = (row["email_body"] or "").lower()
            for term in FORBIDDEN_PUBLIC_TERMS:
                self.assertNotIn(term.lower(), body, f"{term} leaked in {row['address']}")
            self.assertNotIn("owner finance", body)
            self.assertNotIn("seller finance", body)


if __name__ == "__main__":
    unittest.main()
