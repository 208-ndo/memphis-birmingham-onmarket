from pathlib import Path
import re
import unittest


WORKFLOW = Path(".github/workflows/pipeline.yml")


class WorkflowMarketKeysTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def input_block(self, key):
        pattern = rf"      {key}:\n(?P<body>(?:        .+\n)+)"
        match = re.search(pattern, self.text)
        self.assertIsNotNone(match, f"{key} input missing")
        return match.group("body")

    def test_market_keys_is_string_input_with_empty_default(self):
        block = self.input_block("market_keys")
        self.assertIn("description: 'Optional comma-separated market keys, example: cleveland,akron'", block)
        self.assertIn("required: false", block)
        self.assertIn("type: string", block)
        self.assertIn("default: ''", block)

    def test_cleveland_akron_test_is_boolean_input(self):
        block = self.input_block("cleveland_akron_test")
        self.assertIn("description: 'Run Cleveland/Akron test markets'", block)
        self.assertIn("required: false", block)
        self.assertIn("type: boolean", block)
        self.assertIn("default: false", block)

    def test_old_target_markets_is_not_used_for_manual_routing(self):
        self.assertIn("      target_markets:", self.text)
        self.assertIn("MARKET_KEYS_RAW=\"${{ github.event.inputs.market_keys }}\"", self.text)
        self.assertNotIn("github.event.inputs.target_markets", self.text)

    def test_market_keys_exports_literal_trimmed_target_markets(self):
        self.assertIn("TARGET_MARKETS_TRIMMED=\"$(echo \"$MARKET_KEYS_RAW\" | xargs)\"", self.text)
        self.assertIn('export TARGET_MARKETS="${TARGET_MARKETS_TRIMMED}"', self.text)
        self.assertIn('echo "TARGET_MARKETS: ${TARGET_MARKETS_TRIMMED:-ACTIVE_MARKETS}"', self.text)
        self.assertIn('echo "Selected markets: ${SELECTED_MARKETS}"', self.text)

    def test_cleveland_akron_selector_overrides_market_keys(self):
        self.assertIn('CLEVELAND_AKRON_TEST_RAW="${{ github.event.inputs.cleveland_akron_test }}"', self.text)
        self.assertIn('if [ "${CLEVELAND_AKRON_TEST_NORMALIZED}" = "true" ]; then', self.text)
        self.assertIn('TARGET_MARKETS_TRIMMED="cleveland,akron"', self.text)
        self.assertIn('echo "CLEVELAND_AKRON_TEST=true"', self.text)
        self.assertIn('echo "TARGET_MARKETS: ${TARGET_MARKETS_TRIMMED:-ACTIVE_MARKETS}"', self.text)
        self.assertIn('echo "Selected markets: ${SELECTED_MARKETS}"', self.text)

    def test_cleveland_akron_selector_does_not_enable_apify(self):
        self.assertIn('export APIFY_ENABLED="${APIFY_ENABLED_NORMALIZED}"', self.text)
        selector_idx = self.text.index('CLEVELAND_AKRON_TEST_RAW="${{ github.event.inputs.cleveland_akron_test }}"')
        export_idx = self.text.index('export APIFY_ENABLED="${APIFY_ENABLED_NORMALIZED}"')
        selector_block = self.text[selector_idx:export_idx]
        self.assertNotIn('APIFY_ENABLED_NORMALIZED="true"', selector_block)
        self.assertNotIn('APIFY_ENABLED=true', selector_block)

    def test_market_keys_is_not_boolean_normalized(self):
        block_start = self.text.index("MARKET_KEYS_RAW")
        block = self.text[block_start:block_start + 450]
        self.assertNotIn("tr '[:upper:]' '[:lower:]'", block)
        self.assertNotIn("TARGET_MARKETS_NORMALIZED", block)

    def test_true_false_market_keys_fail_before_main(self):
        self.assertIn('if [ "${CLEVELAND_AKRON_TEST_NORMALIZED}" != "true" ] && { [ "${TARGET_MARKETS_TRIMMED}" = "true" ] || [ "${TARGET_MARKETS_TRIMMED}" = "false" ]; }; then', self.text)
        self.assertIn("Invalid market_keys value. Enter comma-separated market keys like cleveland,akron.", self.text)
        invalid_idx = self.text.index("Invalid market_keys value")
        run_idx = self.text.index("python main.py")
        self.assertLess(invalid_idx, run_idx)

    def test_blank_selector_and_market_keys_falls_back_to_active_markets(self):
        self.assertIn('echo "TARGET_MARKETS: ${TARGET_MARKETS_TRIMMED:-ACTIVE_MARKETS}"', self.text)
        self.assertIn('SELECTED_MARKETS="little_rock oklahoma_city"', self.text)

    def test_market_keys_still_work_when_selector_is_false(self):
        selector_idx = self.text.index('if [ "${CLEVELAND_AKRON_TEST_NORMALIZED}" = "true" ]; then')
        selector_block = self.text[selector_idx:selector_idx + 250]
        self.assertIn('else', selector_block)
        self.assertIn('TARGET_MARKETS_TRIMMED="$(echo "$MARKET_KEYS_RAW" | xargs)"', selector_block)


if __name__ == "__main__":
    unittest.main()
