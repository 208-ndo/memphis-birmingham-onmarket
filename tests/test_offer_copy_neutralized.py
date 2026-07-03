"""
Tests: public-facing offer copy is neutralized before live send (2026-07-02).

Wording-only guard — proves the owner-finance and seller-finance-counter
emails no longer expose "Owner Finance" / "Seller-Finance" / financing
language in subjects or opening lines, while every offer TERM and the exact
broker-compensation line are preserved. No offer math is asserted to change.
"""
import sys
import types
import unittest

if "apify_client" not in sys.modules:
    stub = types.ModuleType("apify_client")
    stub.ApifyClient = object
    sys.modules["apify_client"] = stub

from email_gen import generate_emails, BROKER_COMP_LINE, _agent_greeting

ADDRESS = "12 Maple Dr, Olmsted Falls, OH 44138"


def _listing():
    return {"address": ADDRESS, "list_price": 65000, "price": 65000,
            "agent_name": "Jane Smith"}


def _owner_finance_email():
    offer = {"offer_type": "owner_finance", "purchase_price": 65000,
             "owner_finance_offer": 65000, "down_payment": 3250,
             "monthly_payment": 617.5, "num_payments": 100, "seller_rate": 0}
    return generate_emails(_listing(), offer)[0]


def _seller_finance_counter_email():
    offer = {"offer_type": "seller_finance_counter", "purchase_price": 65000,
             "owner_finance_offer": 65000, "down_payment": 3250,
             "monthly_payment": 617.5, "num_payments": 100,
             "interest_rate": 0, "prepayment_penalty": "None"}
    return generate_emails(_listing(), offer)[0]


class OwnerFinanceCopyTest(unittest.TestCase):
    def test_subject_is_exactly_offer_on_address(self):
        self.assertEqual(_owner_finance_email()["subject"], f"Offer on {ADDRESS}")

    def test_body_has_no_owner_finance_wording(self):
        body = _owner_finance_email()["body"].lower()
        self.assertNotIn("owner finance", body)
        self.assertNotIn("owner-finance", body)
        self.assertNotIn("owner financing", body)

    def test_body_opening_is_purchase_offer(self):
        body = _owner_finance_email()["body"]
        self.assertIn(f"I would like to submit the following purchase offer for {ADDRESS}:", body)

    def test_offer_terms_still_present(self):
        body = _owner_finance_email()["body"]
        for term in ("Purchase Price", "Down Payment", "Monthly Payment", "Term",
                     "Earnest Money", "Closing Timeline",
                     "Inspection / Walkthrough Period"):
            self.assertIn(term, body, term)

    def test_broker_comp_line_present_verbatim(self):
        self.assertIn(BROKER_COMP_LINE, _owner_finance_email()["body"])
        self.assertIn(
            "Seller to handle any listing broker compensation per the existing "
            "listing agreement from seller proceeds, down payment/closing "
            "funds, or as otherwise agreed in writing by the seller and broker.",
            _owner_finance_email()["body"])


class SellerFinanceCounterCopyTest(unittest.TestCase):
    def test_subject_is_offer_on_address(self):
        self.assertEqual(_seller_finance_counter_email()["subject"], f"Offer on {ADDRESS}")

    def test_subject_has_no_finance_wording(self):
        subject = _seller_finance_counter_email()["subject"].lower()
        self.assertNotIn("seller-finance", subject)
        self.assertNotIn("seller finance", subject)
        self.assertNotIn("seller financing", subject)
        self.assertNotIn("owner finance", subject)
        self.assertNotIn("owner financing", subject)

    def test_opening_reviewed_listing_wording(self):
        body = _seller_finance_counter_email()["body"]
        self.assertIn(f"I reviewed the listing at {ADDRESS}.", body)
        self.assertIn("I can work with the list price if the seller can work "
                      "with me on the terms. Would the seller consider the following?",
                      body)

    def test_opening_has_no_owner_financing_claim(self):
        # The old opening claimed "the seller is open to owner financing" — gone.
        body = _seller_finance_counter_email()["body"].lower()
        self.assertNotIn("open to owner financing", body)

    def test_broker_comp_line_present_verbatim(self):
        self.assertIn(BROKER_COMP_LINE, _seller_finance_counter_email()["body"])


class NoProhibitedLanguageTest(unittest.TestCase):
    """No agent bonus / flat fee / extra commission / assignment / wholesale /
    end-buyer language was introduced by this wording change."""
    def test_no_prohibited_terms_in_either_email(self):
        for email in (_owner_finance_email(), _seller_finance_counter_email()):
            text = (email["subject"] + " " + email["body"]).lower()
            for banned in ("agent bonus", "flat fee", "assignment",
                           "wholesale", "end buyer", "end-buyer"):
                self.assertNotIn(banned, text, banned)


class AgentGreetingSafetyTest(unittest.TestCase):
    def test_boolean_junk_agent_name_uses_generic_greeting(self):
        self.assertEqual(_agent_greeting({"agent_name": "False False True False"}), "Hi,")

    def test_unknown_agent_name_uses_generic_greeting(self):
        self.assertEqual(_agent_greeting({"agent_name": "UNKNOWN"}), "Hi,")

    def test_blank_agent_name_uses_generic_greeting(self):
        self.assertEqual(_agent_greeting({"agent_name": ""}), "Hi,")

    def test_valid_agent_name_still_uses_name(self):
        self.assertEqual(_agent_greeting({"agent_name": "Melissa Harris"}), "Hi Melissa Harris,")


if __name__ == "__main__":
    unittest.main()
