import importlib
import os
import unittest
from unittest.mock import patch


class MarketSenderConfigTest(unittest.TestCase):
    def test_cleveland_and_akron_reuse_existing_sender_secrets(self):
        env = {
            "GMAIL_USER_MEMPHIS": "memphis@example.com",
            "GMAIL_APP_PASSWORD_MEMPHIS": "memphis-app-password",
            "GHL_PHONE_MEMPHIS": "+15550001001",
            "GMAIL_USER_BIRMINGHAM": "birmingham@example.com",
            "GMAIL_APP_PASSWORD_BIRMINGHAM": "birmingham-app-password",
            "GHL_PHONE_BIRMINGHAM": "+15550002002",
        }
        with patch.dict(os.environ, env, clear=False):
            import config

            cfg = importlib.reload(config)
            self.addCleanup(importlib.reload, cfg)

        self.assertEqual(cfg.MARKETS["cleveland"]["gmail_user"], "memphis@example.com")
        self.assertEqual(cfg.MARKETS["cleveland"]["gmail_app_password"], "memphis-app-password")
        self.assertEqual(cfg.MARKETS["cleveland"]["ghl_phone_number"], "+15550001001")
        self.assertEqual(cfg.MARKETS["akron"]["gmail_user"], "birmingham@example.com")
        self.assertEqual(cfg.MARKETS["akron"]["gmail_app_password"], "birmingham-app-password")
        self.assertEqual(cfg.MARKETS["akron"]["ghl_phone_number"], "+15550002002")


if __name__ == "__main__":
    unittest.main()
