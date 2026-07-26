import unittest
from unittest.mock import patch, MagicMock

from generation.helpers import (
    robust_json_loads,
    score_by_keywords,
    generate_skill_bridging_map,
    _extract_json_block,
    load_prompt,
    _prune_recent_frontmatter,
    compress_experience_llm
)
from utils import sanitize_slug, sanitize_entity_name, safe_read_text, safe_write_text


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

    def test_load_prompt_missing(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_prompt("totally_missing_prompt_template_file.txt")

    @patch("generation.helpers.load_prompt")
    def test_load_prompt_success(self, mock_load: MagicMock) -> None:
        # verify load_prompt maps path correctly and reads contents
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value="some template text"):
                self.assertEqual(load_prompt("dummy.txt"), "some template text")

    def test_prune_recent_frontmatter_date_healing(self) -> None:
        # Test start/end top level fields mapped to dates dict
        fm = {"start": "2020-01", "end": "2022-12", "role": "Engineer"}
        yaml_str = _prune_recent_frontmatter(fm)
        self.assertIn("start: 2020-01", yaml_str)
        self.assertIn("end: 2022-12", yaml_str)

    @patch("generation.helpers.get_model_for_step")
    @patch("generation.helpers.load_prompt")
    def test_compress_experience_llm_success(self, mock_load: MagicMock, mock_model: MagicMock) -> None:
        mock_load.return_value = "System template {CONTENT}"
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="Compressed sentence")
        mock_model.return_value = mock_llm

        res = compress_experience_llm("Original heavy content")
        self.assertEqual(res, "Compressed sentence")

    @patch("generation.helpers.get_model_for_step")
    def test_compress_experience_llm_failure(self, mock_model: MagicMock) -> None:
        # Let it raise an exception
        mock_model.side_effect = Exception("No RETRIEVAL model")
        res = compress_experience_llm("Original heavy content")
        # Should fallback to returning original content
        self.assertEqual(res, "Original heavy content")

    def test_sanitize_slug(self) -> None:
        self.assertEqual(sanitize_slug("hello-world-123"), "hello-world-123")
        self.assertEqual(sanitize_slug("hello/world../test"), "helloworld..test")
        self.assertEqual(sanitize_slug("malicious_dir_traversal\\path"), "malicious_dir_traversalpath")

    def test_sanitize_entity_name(self) -> None:
        # Since parens are removed, " (" and ")" become empty space, which strip/collapsing handles
        self.assertEqual(sanitize_entity_name("Google LLC (Corp)"), "Google LLC Corp")
        self.assertEqual(sanitize_entity_name("malicious/path../inject"), "maliciouspath..inject")

    def test_safe_read_write_text(self) -> None:
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory(dir=str(Path.cwd())) as tmp_dir:
            file_path = Path(tmp_dir) / "test_file.txt"
            safe_write_text(file_path, "Secure content")
            self.assertEqual(safe_read_text(file_path), "Secure content")

        # Test invalid paths trigger ValueError
        with self.assertRaises(ValueError):
            safe_read_text("malicious_dir_traversal?\\path")


if __name__ == "__main__":
    unittest.main()
