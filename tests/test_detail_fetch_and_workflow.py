"""
Tests: Zillow detail fetch robustness + dry-run no-sleep + workflow guard
(2026-07-02).

Proves:
- recursive JSON flatten finds a nested "Listed by" / attributionInfo email
  even when it's buried under unguessed keys,
- the HTML/script fallback finds brett@impactsellshomes.com in a
  Zillow-like HTML body,
- dry_run send_batch never sleeps between "would send" lines,
- the workflow "Commit dashboard data" step is no longer if: always()
  (won't auto-commit on canceled/failed runs).
"""
import os
import re
import sys
import types
import unittest
from unittest.mock import patch

if "apify_client" not in sys.modules:
    stub = types.ModuleType("apify_client")
    stub.ApifyClient = object
    sys.modules["apify_client"] = stub

import zillow_detail_contact as zdc
from zillow_detail_contact import (
    _flatten_json, parse_listed_by_block, extract_contact_from_flat_text,
    fetch_detail_contact,
)


class RecursiveFlattenTest(unittest.TestCase):
    def test_flatten_finds_deeply_nested_listed_by_email(self):
        nested = {
            "props": {"pageProps": {"componentProps": {"gdpClientCache": {
                "ForSale": {"property": {"attributionInfo": {
                    "listingText": "Listed by: Brett Munich 440-539-2897 "
                                   "brett@impactsellshomes.com, Impact Real Estate"
                }}}}}}}}
        flat = _flatten_json(nested)
        self.assertIn("brett@impactsellshomes.com", flat)
        self.assertIn("Listed by", flat)
        parsed = parse_listed_by_block(flat)
        self.assertEqual(parsed["agent_email"], "brett@impactsellshomes.com")
        self.assertEqual(parsed["agent_phone"], "440-539-2897")

    def test_flatten_handles_lists_and_scalars(self):
        obj = {"a": [1, 2, {"b": "hello@x.com"}], "c": None, "d": 42}
        flat = _flatten_json(obj)
        self.assertIn("hello@x.com", flat)
        self.assertIn("42", flat)

    def test_structured_json_without_listed_by_marker(self):
        nested = {"property": {"attributionInfo": {
            "agentName": "Brett Munich",
            "agentPhoneNumber": "440-539-2897",
            "agentEmail": "brett@impactsellshomes.com",
        }}}
        flat = _flatten_json(nested)
        contact = extract_contact_from_flat_text(flat)
        self.assertEqual(contact["agent_email"], "brett@impactsellshomes.com")
        self.assertEqual(contact["agent_phone"], "440-539-2897")


class HtmlFallbackTest(unittest.TestCase):
    ZILLOW_LIKE_HTML = (
        '<html><head><script>var x = {"attributionInfo":'
        '{"agentName":"Brett Munich","agentPhoneNumber":"440-539-2897",'
        '"agentEmail":"brett@impactsellshomes.com",'
        '"brokerName":"Impact Real Estate"}};</script></head>'
        '<body><div>1133 W 9th St APT 120</div></body></html>'
    )

    def test_html_fallback_finds_email(self):
        class Resp:
            status_code = 200
            text = self.ZILLOW_LIKE_HTML

        with patch.object(zdc, "USE_PLAYWRIGHT_ZILLOW_DETAIL", False):
            import requests
            with patch.object(requests, "get", lambda *a, **k: Resp()):
                # client=None forces the HTTP path
                contact = fetch_detail_contact(
                    "https://www.zillow.com/homedetails/1133_zpid/", client=None)
        self.assertEqual(contact.get("email"), "brett@impactsellshomes.com")
        self.assertEqual(contact["email_source_type"], "zillow_detail_listed_by")
        self.assertTrue(contact["email_is_sendable"])

    def test_html_fallback_never_invents_email(self):
        class Resp:
            status_code = 200
            text = "<html><body>No contact info here at all</body></html>"

        import requests
        with patch.object(zdc, "USE_PLAYWRIGHT_ZILLOW_DETAIL", False), \
             patch.object(requests, "get", lambda *a, **k: Resp()):
            contact = fetch_detail_contact(
                "https://www.zillow.com/homedetails/x_zpid/", client=None)
        self.assertEqual(contact, {})


class DryRunNoSleepTest(unittest.TestCase):
    def setUp(self):
        import importlib
        import gmail_send
        importlib.reload(gmail_send)
        self.gmail_send = gmail_send

    def test_dry_run_never_sleeps_between_would_sends(self):
        sleep_calls = []
        queue = [
            {"listing": {"address": f"{i} Main St", "agent_email": "a@b.com",
                        "price": 60000}, "offer": {},
             "email": {"subject": "s", "body": "b"}}
            for i in range(3)
        ]
        markets = {"cleveland": {"gmail_user": "", "gmail_app_password": "",
                                 "city": "Cleveland"}}
        with patch.object(self.gmail_send, "MARKETS", markets), \
             patch.object(self.gmail_send, "generate_offer_pdf", lambda *a, **k: None), \
             patch.object(self.gmail_send.time, "sleep",
                          lambda s: sleep_calls.append(s)):
            results = self.gmail_send.send_batch(queue, "cleveland", dry_run=True)

        self.assertEqual(len(results), 3)
        self.assertTrue(all(r["success"] for r in results))
        self.assertEqual(sleep_calls, [],
                         "dry run must not sleep between would-send emails")


class WorkflowCommitGuardTest(unittest.TestCase):
    """The commit step must not be if: always() (would commit on cancel/fail)."""
    WORKFLOW = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            ".github", "workflows", "pipeline.yml")

    def test_commit_step_not_always(self):
        with open(self.WORKFLOW) as f:
            text = f.read()
        idx = text.find("Commit dashboard data")
        self.assertNotEqual(idx, -1, "commit step not found")
        block = text[idx: idx + 900]
        # Look at the actual `if:` directive line, not explanatory comments
        # (a comment may legitimately reference the old "if: always()").
        directive_lines = [ln.strip() for ln in block.splitlines()
                           if ln.strip().startswith("if:")
                           or (ln.strip().startswith("&&"))
                           or ln.strip() in ("success()",)]
        directive = " ".join(directive_lines)
        self.assertNotIn("always()", directive,
                         "commit step must not run on canceled/failed jobs")
        self.assertIn("success()", directive,
                      "commit step should be gated on success()")

    def test_commit_step_skips_dry_run(self):
        with open(self.WORKFLOW) as f:
            text = f.read()
        idx = text.find("Commit dashboard data")
        block = text[idx: idx + 900]
        self.assertIn("dry_run != 'true'", block,
                      "commit step should not commit dry-run data")


if __name__ == "__main__":
    unittest.main()
