import os
import unittest
from unittest.mock import patch

import gmail_send


class GmailLiveSendGuardTest(unittest.TestCase):
    def setUp(self):
        self.market = {
            "gmail_user": "sender@example.com",
            "gmail_app_password": "app-password",
        }

    def test_send_email_returns_false_when_live_send_env_unset(self):
        with patch.dict(gmail_send.MARKETS, {"cleveland": self.market}, clear=False), \
             patch.dict(os.environ, {}, clear=False), \
             patch("gmail_send.smtplib.SMTP_SSL") as smtp_ssl:
            os.environ.pop("LIVE_SEND_ENABLED", None)

            result = gmail_send.send_email(
                market_key="cleveland",
                to_email="agent@example.com",
                subject="Test",
                body="Body",
                dry_run=False,
            )

        self.assertFalse(result)
        smtp_ssl.assert_not_called()

    def test_blocked_live_send_does_not_count_as_successful(self):
        queue = [{
            "listing": {"address": "4297 E 139th St", "agent_email": "agent@example.com"},
            "offer": {"offer_type": "owner_finance"},
            "email": {"subject": "Test", "body": "Body"},
        }]

        with patch.dict(gmail_send.MARKETS, {"cleveland": self.market}, clear=False), \
             patch.dict(os.environ, {}, clear=False), \
             patch("gmail_send.count_sent_today_by_inbox", return_value=0), \
             patch("gmail_send.count_sent_today_global", return_value=0), \
             patch("gmail_send.generate_offer_pdf", return_value=None), \
             patch("gmail_send.smtplib.SMTP_SSL") as smtp_ssl:
            os.environ.pop("LIVE_SEND_ENABLED", None)

            results = gmail_send.send_batch(queue, market_key="cleveland", dry_run=False)

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["success"])
        smtp_ssl.assert_not_called()


if __name__ == "__main__":
    unittest.main()
