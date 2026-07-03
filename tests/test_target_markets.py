import sys
import types
import unittest
from unittest.mock import patch


def stub_module(name, **attrs):
    module = types.ModuleType(name)
    module.__test_stub__ = True
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules.setdefault(name, module)


stub_module("offer", calculate_offer=lambda listing: {})
stub_module("email_gen", generate_emails=lambda listing, offer: [], pick_email=lambda emails: None)
stub_module(
    "dedup",
    should_send=lambda listing: True,
    mark_sent=lambda listing, email: None,
    get_stats=lambda: {"total_properties_emailed": 0, "total_agents_contacted": 0},
)
stub_module("gmail_send", send_batch=lambda queue, market_key, dry_run=False: [])
stub_module("ghl_push", push_to_ghl=lambda listing, offer, email, market_key: None)

import main

for module_name in ("offer", "email_gen", "dedup", "gmail_send", "ghl_push"):
    if getattr(sys.modules.get(module_name), "__test_stub__", False):
        sys.modules.pop(module_name, None)


class TargetMarketsTest(unittest.TestCase):
    def test_target_markets_selects_only_cleveland_akron(self):
        self.assertEqual(
            main.get_target_markets("cleveland,akron"),
            ["cleveland", "akron"],
        )

    def test_unknown_market_fails_fast(self):
        with self.assertRaisesRegex(ValueError, "Unknown TARGET_MARKETS"):
            main.get_target_markets("cleveland,missing_market")

    def test_empty_target_markets_keeps_normal_active_markets(self):
        self.assertEqual(main.get_target_markets(""), list(main.ACTIVE_MARKETS))
        self.assertEqual(main.get_target_markets("   "), list(main.ACTIVE_MARKETS))

    def test_inactive_markets_are_not_run_unless_explicitly_targeted(self):
        self.assertNotIn("cleveland", main.get_target_markets(""))
        self.assertNotIn("akron", main.get_target_markets(""))
        self.assertEqual(main.get_target_markets("cleveland"), ["cleveland"])

    def test_env_target_markets_is_supported(self):
        with patch.dict("os.environ", {"TARGET_MARKETS": "akron,cleveland"}):
            self.assertEqual(main.get_target_markets(), ["akron", "cleveland"])


if __name__ == "__main__":
    unittest.main()
