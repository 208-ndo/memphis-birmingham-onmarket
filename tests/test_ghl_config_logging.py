import unittest
from types import SimpleNamespace
from unittest.mock import patch

import ghl_push


class GhlCredentialLoggingTest(unittest.TestCase):
    def test_401_logs_credential_config_issue_without_secret_values(self):
        response = SimpleNamespace(status_code=401, text='{"msg":"Api key is invalid."}')
        listing = {
            "address": "4309 E 73rd St, Cleveland, OH 44105",
            "agent_email": "",
            "listing_agent": "Listing Agent",
        }

        with patch.object(ghl_push.requests, "post", return_value=response):
            with self.assertLogs("ghl_push", level="ERROR") as logs:
                self.assertIsNone(ghl_push.create_contact(listing, {}, "cleveland"))

        joined = "\n".join(logs.output)
        self.assertIn("GHL credential/config issue", joined)
        self.assertIn("GHL_API_KEY", joined)
        self.assertIn("GHL_LOCATION_ID", joined)
        self.assertIn("Gmail send status is separate", joined)
        self.assertNotIn("Bearer ", joined)


if __name__ == "__main__":
    unittest.main()
