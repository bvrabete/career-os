import unittest
from unittest.mock import patch, MagicMock

from generation.helpers import (
    robust_json_loads,
    score_by_keywords,
    generate_skill_bridging_map,
    _extract_json_block
)


class TestGenerationHelpersCoverage(unittest.TestCase):

    def test_extract_json_block_missing_braces(self) -> None:
        with self.assertRaises(ValueError) as context:
            _extract_json_block("Plain string with no braces or brackets")
        self.assertIn("No JSON object or array found", str(context.exception))

    def test_extract_json_block_mismatched_brace(self) -> None:
        with self.assertRaises(ValueError) as context:
            _extract_json_block("Here is some { incomplete json block")
        self.assertIn("Mismatched opening brace", str(context.exception))

    def test_extract_json_block_mismatched_bracket(self) -> None:
        with self.assertRaises(ValueError) as context:
            _extract_json_block("Here is some [ incomplete json array")
        self.assertIn("Mismatched opening bracket", str(context.exception))

    def test_robust_json_loads_empty(self) -> None:
        with self.assertRaises(ValueError) as context:
            robust_json_loads("")
        self.assertIn("Empty input string", str(context.exception))

    def test_robust_json_loads_recovery(self) -> None:
        # Invalid single quotes inside JSON object (invalid JSON standard)
        malformed = "{'name': 'John', 'age': 30}"
        res = robust_json_loads(malformed)
        self.assertEqual(res, {"name": "John", "age": 30})

    def test_score_by_keywords_empty(self) -> None:
        self.assertEqual(score_by_keywords("", ["python"]), 0)
        self.assertEqual(score_by_keywords("Some text", []), 0)
        self.assertEqual(score_by_keywords("Some text", [""]), 0)

    def test_score_by_keywords_overlap(self) -> None:
        text = "Experienced Senior Python Software Engineer with Flask, Docker, and Python."
        # Case insensitive whole-word matches: 'python' (x2), 'flask' (x1)
        self.assertEqual(score_by_keywords(text, ["python", "flask"]), 3)

    @patch("generation.helpers.load_prompt")
    def test_generate_skill_bridging_map_failure(self, mock_load: MagicMock) -> None:
        mock_load.side_effect = Exception("Prompt load error")
        mock_llm = MagicMock()
        res = generate_skill_bridging_map(mock_llm, ["python"], ["python"])
        self.assertEqual(res, {})


if __name__ == "__main__":
    unittest.main()
