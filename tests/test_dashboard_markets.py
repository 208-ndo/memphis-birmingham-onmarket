"""
Tests: dashboard Cleveland/Akron market wiring + modal email freshness
(2026-07-02).

These are static/behavioral checks on index.html:
 - Cleveland OH / Akron OH appear in the market filter,
 - loadScoredLeads fetches cleveland_leads.json and akron_leads.json,
 - scored/queue/history filters handle cleveland + akron,
 - the modal "Offer Sent" tab pulls the current-run email_subject/email_body
   from the pipeline_log queue and falls back to
   "No email preview saved for this row.",
 - the stale static wording is gone.

The modal email-lookup logic is additionally exercised as real JS via node
(node is available in this environment; the test skips if it isn't).
"""
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(REPO, "index.html")


def read_index():
    with open(INDEX, encoding="utf-8") as f:
        return f.read()


class MarketFilterWiringTest(unittest.TestCase):
    def setUp(self):
        self.html = read_index()

    def test_cleveland_akron_filter_options_present(self):
        self.assertIn('<option value="cleveland">Cleveland OH</option>', self.html)
        self.assertIn('<option value="akron">Akron OH</option>', self.html)

    def test_active_market_filters_include_cleveland_akron(self):
        m = re.search(r"ACTIVE_MARKET_FILTERS\s*=\s*\[([^\]]*)\]", self.html)
        self.assertIsNotNone(m)
        arr = m.group(1)
        self.assertIn("'cleveland'", arr)
        self.assertIn("'akron'", arr)

    def test_loaders_fetch_cleveland_akron_json(self):
        self.assertIn("./data/cleveland_leads.json", self.html)
        self.assertIn("./data/akron_leads.json", self.html)

    def test_scored_render_handles_cleveland_akron(self):
        self.assertIn("f==='cleveland'", self.html)
        self.assertIn("f==='akron'", self.html)
        self.assertIn("marketLabel:'Cleveland OH'", self.html)
        self.assertIn("marketLabel:'Akron OH'", self.html)

    def test_queue_and_history_filters_handle_cleveland_akron(self):
        # cleveland/akron appear in both queue and history market matching
        self.assertGreaterEqual(self.html.count("marketMatches(q.market,'cleveland')"), 1)
        self.assertGreaterEqual(self.html.count("marketMatches(h.market,'cleveland')"), 1)
        self.assertGreaterEqual(self.html.count("marketMatches(q.market,'akron')"), 1)
        self.assertGreaterEqual(self.html.count("marketMatches(h.market,'akron')"), 1)

    def test_modal_sources_map_cle_akr(self):
        self.assertIn("source==='cle' ? _scoredCLEData[idx]", self.html)
        self.assertIn("source==='akr' ? _scoredAKRData[idx]", self.html)


class ModalEmailFreshnessStaticTest(unittest.TestCase):
    def setUp(self):
        self.html = read_index()

    def test_modal_uses_current_run_queue_email(self):
        self.assertIn("findCurrentRunEmailForAddress", self.html)
        # modal fills subject/body from the live lookup
        self.assertIn("liveEmail && liveEmail.email_subject", self.html)
        self.assertIn("liveEmail && liveEmail.email_body", self.html)

    def test_no_email_preview_fallback_present(self):
        self.assertIn("No email preview saved for this row.", self.html)

    def test_stale_static_wording_removed(self):
        self.assertNotIn("sent — open from Active Queue or Sent History for the saved copy",
                         self.html)
        self.assertNotIn("email body not saved — run pipeline again to capture",
                         self.html)


class ModalEmailLookupBehaviorTest(unittest.TestCase):
    """Exercise findCurrentRunEmailForAddress as real JS via node."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")
        self.html = read_index()
        m = re.search(r"function findCurrentRunEmailForAddress\(address\)\{.*?\n\}",
                      self.html, re.S)
        self.assertIsNotNone(m, "helper not found in index.html")
        self.fn_src = m.group(0)

    def _run(self, queue_json, address):
        script = textwrap.dedent(f"""
            var _queueData = {queue_json};
            {self.fn_src}
            var r = findCurrentRunEmailForAddress({address!r});
            console.log(JSON.stringify(r));
        """)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(script)
            path = f.name
        try:
            out = subprocess.run(["node", path], capture_output=True, text=True,
                                  timeout=15)
            return out.stdout.strip()
        finally:
            os.unlink(path)

    def test_matches_current_run_email_by_address(self):
        queue = ('[{"address":"12 Maple Dr","email_subject":"Offer on 12 Maple Dr",'
                 '"email_body":"Hi Jane"}]')
        out = self._run(queue, "12 Maple Dr")
        self.assertIn("Offer on 12 Maple Dr", out)

    def test_returns_null_when_no_email_on_row(self):
        queue = '[{"address":"12 Maple Dr"}]'  # no email fields
        out = self._run(queue, "12 Maple Dr")
        self.assertEqual(out, "null")

    def test_returns_null_when_address_absent(self):
        queue = ('[{"address":"999 Other St","email_subject":"Offer on 999 Other St",'
                 '"email_body":"x"}]')
        out = self._run(queue, "12 Maple Dr")
        self.assertEqual(out, "null")

    def test_address_match_is_case_insensitive(self):
        queue = ('[{"address":"12 MAPLE DR","email_subject":"Offer on 12 Maple Dr",'
                 '"email_body":"x"}]')
        out = self._run(queue, "12 maple dr")
        self.assertIn("Offer on 12 Maple Dr", out)


if __name__ == "__main__":
    unittest.main()
