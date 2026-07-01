import unittest

from scraper import extract_lead, get_market_price_bands


MARKET = {"city": "Cleveland", "state": "OH", "min_price": 30000, "max_price": 125000}


class ZillowContactExtractionTest(unittest.TestCase):
    def lead_from_visible_text(self, address, listed_by):
        return extract_lead(
            {
                "address": address,
                "city": "Cleveland",
                "state": "OH",
                "price": "$75,000",
                "zpid": "123",
                "detailUrl": "/homedetails/test_zpid/",
                "listedByText": listed_by,
                "brokerName": "Brokerage should not become the agent",
            },
            MARKET,
        )

    def test_extracts_rakesh_baniya_contact_from_visible_listed_by_text(self):
        lead = self.lead_from_visible_text(
            "4297 E 139th St, Cleveland, OH 44105",
            "Listed by: Rakesh Baniya 440-901-7145 "
            "rbaniya@clevelandpropertymanagement.com, "
            "Cleveland Property Management Group, LLC.",
        )

        self.assertEqual(lead["agent_name"], "Rakesh Baniya")
        self.assertEqual(lead["agent_phone"], "440-901-7145")
        self.assertEqual(lead["agent_email"], "rbaniya@clevelandpropertymanagement.com")
        self.assertEqual(lead["brokerage_name"], "Brokerage should not become the agent")

    def test_extracts_leilani_bowersock_contact_from_visible_listed_by_text(self):
        lead = self.lead_from_visible_text(
            "10712 Grantwood Ave, Cleveland, OH 44108",
            "Listed by: Leilani M Bowersock 440-570-9514 "
            "leilani7b@gmail.com, Coldwell Banker Schmidt Realty.",
        )

        self.assertEqual(lead["agent_name"], "Leilani M Bowersock")
        self.assertEqual(lead["agent_phone"], "440-570-9514")
        self.assertEqual(lead["agent_email"], "leilani7b@gmail.com")

    def test_extracts_christopher_frederick_contact_from_visible_listed_by_text(self):
        lead = extract_lead(
            {
                "address": "840 Work Dr, Akron, OH 44320",
                "city": "Akron",
                "state": "OH",
                "price": "$80,000",
                "listedByText": (
                    "Listed by: Christopher A Frederick 216-210-7653 "
                    "thefrederickteam@gmail.com, Coldwell Banker Schmidt Realty."
                ),
                "brokerName": "Coldwell Banker Schmidt Realty",
            },
            {"city": "Akron", "state": "OH", "min_price": 30000, "max_price": 125000},
        )

        self.assertEqual(lead["agent_name"], "Christopher A Frederick")
        self.assertEqual(lead["agent_phone"], "216-210-7653")
        self.assertEqual(lead["agent_email"], "thefrederickteam@gmail.com")
        self.assertNotEqual(lead["agent_name"], lead["brokerage_name"])

    def test_does_not_guess_email_when_none_is_visible(self):
        lead = self.lead_from_visible_text(
            "999 No Email Ave, Cleveland, OH 44105",
            "Listed by: Direct Agent 440-111-2222 Cleveland Property Management Group, LLC.",
        )

        self.assertEqual(lead["agent_phone"], "440-111-2222")
        self.assertEqual(lead["agent_email"], "")

    def test_cleveland_akron_market_bands_are_capped_at_125k(self):
        self.assertEqual(
            get_market_price_bands(MARKET),
            [
                {"min": 30000, "max": 55000},
                {"min": 55001, "max": 80000},
                {"min": 80001, "max": 125000},
            ],
        )


if __name__ == "__main__":
    unittest.main()
