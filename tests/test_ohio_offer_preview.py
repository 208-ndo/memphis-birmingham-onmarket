import unittest
from pathlib import Path

from email_gen import BROKER_COMP_LINE, INVESTMENT_PURPOSE_LINE, generate_emails
from offer import calculate_offer
from preview_cash_offer_emails import FORBIDDEN_PUBLIC_TERMS
from preview_ohio_offer_emails import build_preview_records, build_summary


class OhioOfferPreviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = build_preview_records()
        cls.by_address = {row["address"]: row for row in cls.records}

    def test_fixture_emails_generate_without_sending(self):
        summary = build_summary(self.records)
        self.assertEqual(summary["emails_sent"], 0)
        self.assertFalse(summary["scraper_ran"])
        self.assertFalse(summary["apify_ran"])
        self.assertFalse(summary["gmail_ran"])
        self.assertFalse(summary["ghl_ran"])

        owner_finance_records = [
            row for row in self.records if row["offer_lane"] == "OWNER_FINANCE_PRODUCTION"
        ]
        self.assertEqual(len(owner_finance_records), 2)
        for row in owner_finance_records:
            self.assertTrue(row["email_subject"])
            self.assertTrue(row["email_body"])
            self.assertFalse(row["auto_send"])

    def test_normal_low_price_listing_without_seller_finance_uses_owner_finance(self):
        listing = {"address": "Normal Low Price", "list_price": 60000, "agent_name": "Test Agent"}
        offer = calculate_offer(listing)
        self.assertEqual(offer["offer_type"], "owner_finance")
        self.assertEqual(offer["owner_finance_offer"], 60000)
        self.assertEqual(offer["down_payment"], 3000)
        self.assertEqual(offer["monthly_payment"], 570)
        self.assertEqual(offer["num_payments"], 100)
        self.assertTrue(offer["pitch_holds"])
        email = generate_emails(listing, offer)[0]
        self.assertIn("Monthly Payment: $570", email["body"])

    def test_owner_finance_math_is_correct(self):
        expected = {
            "4297 E 139th St, Cleveland, OH 44105": (74000, 5000, 690, 100),
            "10712 Grantwood Ave, Cleveland, OH 44108": (75000, 3750, 712.5, 100),
            "840 Work Dr, Akron, OH 44320": (65000, 3250, 617.5, 100),
        }
        for address, (purchase_price, down_payment, monthly_payment, num_payments) in expected.items():
            row = self.by_address[address]
            self.assertEqual(row["purchase_price"], purchase_price)
            self.assertEqual(row["down_payment"], down_payment)
            self.assertEqual(row["monthly_payment"], monthly_payment)
            self.assertEqual(row["num_payments"], num_payments)
            self.assertTrue(row["math_ok"], row["math_notes"])

    def test_monthly_payment_email_format_preserves_cents_when_present(self):
        expected_lines = {
            "4297 E 139th St, Cleveland, OH 44105": "Monthly Payment: $690",
            "10712 Grantwood Ave, Cleveland, OH 44108": "Monthly Payment: $712.50",
            "840 Work Dr, Akron, OH 44320": "Monthly Payment: $617.50",
        }
        for address, expected_line in expected_lines.items():
            row = self.by_address[address]
            self.assertIn(expected_line, row["email_body"])
            self.assertTrue(row["math_ok"], row["math_notes"])

    def test_seller_finance_description_triggers_counter_lane(self):
        row = self.by_address["4297 E 139th St, Cleveland, OH 44105"]
        self.assertEqual(row["offer_type"], "seller_finance_counter")
        self.assertEqual(row["offer_lane"], "SELLER_FINANCE_LISTING_COUNTER")
        self.assertEqual(row["purchase_price"], 74000)
        self.assertEqual(row["down_payment"], 5000)
        self.assertEqual(row["monthly_payment"], 690)
        self.assertEqual(row["num_payments"], 100)
        self.assertEqual(row["interest_rate"], 0)
        self.assertEqual(row["prepayment_penalty"], "None")

    def test_seller_finance_counter_email_uses_terms_language(self):
        body = self.by_address["4297 E 139th St, Cleveland, OH 44105"]["email_body"]
        # Public copy neutralized 2026-07-02: opening no longer references
        # "owner financing"; it now reviews the listing and proposes terms.
        self.assertIn("I reviewed the listing at", body)
        self.assertNotIn("open to owner financing", body.lower())
        self.assertIn(
            "I can work with the list price if the seller can work with me on the terms",
            body,
        )
        self.assertIn(
            "If the seller needs closer to the advertised down payment, I’m open to reviewing a counter",
            body,
        )

    def test_rent_check_strong_rent_passes(self):
        row = self.by_address["SYNTHETIC FIXTURE - Strong Rent Seller Finance"]
        self.assertEqual(row["offer_lane"], "OWNER_FINANCE_RENT_CHECK_80_100")
        self.assertEqual(row["purchase_price"], 95000)
        self.assertEqual(row["down_payment"], 4750)
        self.assertEqual(row["monthly_payment"], 902.5)
        self.assertEqual(row["estimated_rent"], 1700)
        self.assertEqual(row["rent_check_status"], "PASS")
        self.assertTrue(row["rent_check_pass"])
        self.assertGreaterEqual(row["estimated_monthly_cashflow"], 200)
        self.assertLessEqual(row["payment_to_rent_ratio"], 0.65)
        self.assertTrue(row["eligible_for_human_review"])
        self.assertFalse(row["approved_to_send"])
        self.assertFalse(row["live_send_allowed"])
        self.assertFalse(row["live_send_allowed_after_manual_approval"])

    def test_rent_check_weak_rent_fails(self):
        row = self.by_address["SYNTHETIC FIXTURE - Weak Rent Seller Finance"]
        self.assertEqual(row["offer_lane"], "OWNER_FINANCE_RENT_CHECK_80_100")
        self.assertEqual(row["estimated_rent"], 1250)
        self.assertEqual(row["rent_check_status"], "FAIL")
        self.assertFalse(row["rent_check_pass"])
        self.assertTrue(row["requires_review"])
        self.assertFalse(row["eligible_for_human_review"])
        self.assertFalse(row["approved_to_send"])
        self.assertFalse(row["live_send_allowed"])

    def test_live_send_allowed_only_after_explicit_manual_approval(self):
        base = {
            "address": "Approved Rent Check",
            "market_key": "cleveland",
            "city": "Cleveland",
            "list_price": 95000,
            "estimated_rent": 1700,
        }
        offer = calculate_offer(base)
        self.assertTrue(offer["rent_check_pass"])
        self.assertTrue(offer["eligible_for_human_review"])
        self.assertFalse(offer["approved_to_send"])
        self.assertFalse(offer["live_send_allowed"])
        self.assertFalse(offer["pitch_holds"])

        approved_offer = calculate_offer({**base, "approved_to_send": True})
        self.assertTrue(approved_offer["rent_check_pass"])
        self.assertTrue(approved_offer["eligible_for_human_review"])
        self.assertTrue(approved_offer["approved_to_send"])
        self.assertTrue(approved_offer["live_send_allowed"])
        self.assertTrue(approved_offer["pitch_holds"])

    def test_missing_rent_blocks_live_send(self):
        offer = calculate_offer(
            {
                "address": "Missing Rent",
                "market_key": "cleveland",
                "city": "Cleveland",
                "list_price": 95000,
            }
        )
        self.assertEqual(offer["offer_type"], "owner_finance_rent_check")
        self.assertEqual(offer["rent_check_status"], "RENT_CHECK_REQUIRED")
        self.assertTrue(offer["live_send_blocked"])
        self.assertFalse(offer["approved_to_send"])
        self.assertFalse(offer["live_send_allowed"])
        self.assertFalse(offer["pitch_holds"])

    def test_100k_to_125k_is_manual_review(self):
        row = self.by_address["SYNTHETIC FIXTURE - High Price Manual Review"]
        self.assertEqual(row["offer_lane"], "OWNER_FINANCE_MANUAL_REVIEW_100_125")
        self.assertTrue(row["requires_review"])
        self.assertFalse(row["live_send_allowed"])
        self.assertFalse(row["auto_send"])

    def test_stale_seller_finance_is_review_and_not_price_lowball(self):
        listing = {
            "address": "Stale Seller Finance",
            "list_price": 74000,
            "days_on_zillow": 120,
            "description": "Seller financing available with down payment and interest.",
            "agent_name": "Test Agent",
        }
        offer = calculate_offer(listing)
        self.assertEqual(offer["offer_type"], "seller_finance_counter")
        self.assertEqual(offer["purchase_price"], 74000)
        self.assertEqual(offer["owner_finance_offer"], 74000)
        self.assertTrue(offer["stale_seller_finance"])
        self.assertTrue(offer["requires_review"])
        self.assertFalse(offer["pitch_holds"])
        self.assertIn("Stale seller-finance listing", offer["review_note"])
        email = generate_emails(listing, offer)[0]
        self.assertIn("Purchase Price: $74,000", email["body"])

    def test_agent_direct_email_remains_present(self):
        self.assertEqual(
            self.by_address["4297 E 139th St, Cleveland, OH 44105"]["agent_email"],
            "rbaniya@clevelandpropertymanagement.com",
        )
        self.assertEqual(
            self.by_address["10712 Grantwood Ave, Cleveland, OH 44108"]["agent_email"],
            "leilani7b@gmail.com",
        )
        self.assertEqual(
            self.by_address["840 Work Dr, Akron, OH 44320"]["agent_email"],
            "thefrederickteam@gmail.com",
        )

    def test_company_names_do_not_replace_direct_agent_emails(self):
        for row in self.records[:3]:
            self.assertNotEqual(row["agent_email"], row["brokerage"])
            self.assertIn("@", row["agent_email"])

    def test_higher_price_manual_review_lead_is_not_auto_send(self):
        row = self.by_address["SYNTHETIC FIXTURE - High Price Manual Review 125k"]
        self.assertEqual(row["offer_lane"], "OWNER_FINANCE_MANUAL_REVIEW_100_125")
        self.assertEqual(row["offer_type"], "owner_finance_manual_review")
        self.assertFalse(row["auto_send"])
        self.assertFalse(row["live_send_allowed"])
        self.assertTrue(row["requires_review"])

    def test_generated_email_includes_required_public_lines(self):
        for row in self.records:
            if not row["email_body"]:
                continue
            self.assertIn(INVESTMENT_PURPOSE_LINE, row["email_body"])
            self.assertIn(BROKER_COMP_LINE, row["email_body"])

    def test_public_seller_finance_emails_do_not_include_forbidden_terms(self):
        for row in self.records:
            body = (row["email_body"] or "").lower()
            for term in FORBIDDEN_PUBLIC_TERMS:
                self.assertNotIn(term.lower(), body, f"{term} leaked in {row['address']}")

    def test_synthetic_fixtures_do_not_generate_public_email(self):
        synthetic_rows = [row for row in self.records if row["synthetic_fixture"]]
        self.assertGreaterEqual(len(synthetic_rows), 1)
        for row in synthetic_rows:
            self.assertEqual(row["email_body"], "")
            self.assertEqual(row["email_subject"], "")
            self.assertFalse(row["public_email_generated"])
            self.assertTrue(row["do_not_send"])
            self.assertFalse(row["approved_to_send"])
            self.assertFalse(row["live_send_allowed"])
            self.assertFalse(row["eligible_for_review"])

    def test_4297_still_generates_public_email_preview(self):
        row = self.by_address["4297 E 139th St, Cleveland, OH 44105"]
        self.assertFalse(row["synthetic_fixture"])
        self.assertTrue(row["real_listing"])
        self.assertTrue(row["human_verified_example"])
        self.assertTrue(row["public_email_generated"])
        self.assertIn("Hi Rakesh Baniya,", row["email_body"])

    def test_synthetic_fixture_report_does_not_show_real_looking_email(self):
        report = Path("reports/ohio_offer_preview.md").read_text(encoding="utf-8")
        self.assertNotIn("Hi Strong Rent Agent", report)
        self.assertNotIn("95 Strong Rent Ave", report)
        self.assertIn(
            "SYNTHETIC FIXTURE - math test only. No public email generated. Do not send.",
            report,
        )


if __name__ == "__main__":
    unittest.main()
