from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/pipeline.yml")


class WorkflowTargetMarketsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_target_markets_is_string_input_with_empty_default(self):
        self.assertIn("      target_markets:", self.text)
        self.assertIn("description: 'Optional comma-separated market keys, example: cleveland,akron'", self.text)
        self.assertIn("        type: string", self.text)
        self.assertIn("        default: ''", self.text)

    def test_target_markets_is_trimmed_not_boolean_normalized(self):
        block_start = self.text.index("TARGET_MARKETS_RAW")
        block = self.text[block_start:block_start + 350]
        self.assertIn("TARGET_MARKETS_TRIMMED", block)
        self.assertNotIn("TARGET_MARKETS_NORMALIZED", block)
        self.assertNotIn("tr '[:upper:]' '[:lower:]'", block)

    def test_target_markets_export_preserves_trimmed_literal(self):
        self.assertIn('export TARGET_MARKETS="${TARGET_MARKETS_TRIMMED}"', self.text)
        self.assertIn('echo "  TARGET_MARKETS                      : ${TARGET_MARKETS_TRIMMED:-ACTIVE_MARKETS}"', self.text)
        self.assertIn('echo "  Selected markets                    : ${SELECTED_MARKETS}"', self.text)


if __name__ == "__main__":
    unittest.main()
