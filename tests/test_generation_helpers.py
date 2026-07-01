"""Unit tests for the generation helper functions."""
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import datetime

# Ensure src is in python path
import sys
sys.path.append(str(Path(__file__).parent.parent / "src"))

from generation.helpers import (
    llm_text,
    _extract_json_block,
    _clean_json_comments_and_commas,
    _escape_control_chars_in_strings,
    robust_json_loads,
    _is_old_role,
    _get_experience_key,
    _deduplicate_scored_experiences,
    _extract_start_date_normalized,
    _extract_end_date_normalized,
    _is_parallel_startup_track,
    _get_org_slug,
    _split_recent_and_old_experiences,
    resolve_regional_strategy,
    get_subject_info,
    _parse_start_date,
    parse_and_sort_chronological_entries,
)


class TestGenerationHelpers(unittest.TestCase):
    """Deterministic, isolated unit tests for CV Generation Helpers."""

    def test_llm_text_str(self):
        """Test llm_text with a simple string."""
        self.assertEqual(llm_text("hello"), "hello")

    def test_llm_text_list(self):
        """Test llm_text with a list of parts."""
        self.assertEqual(llm_text(["hello", 123, "world"]), "hello 123 world")

    def test_extract_json_block_markdown(self):
        """Test _extract_json_block handles markdown code blocks."""
        raw = "Some preamble ```json\n{\"key\": \"val\"}\n``` postscript"
        self.assertEqual(_extract_json_block(raw), "{\"key\": \"val\"}")

    def test_extract_json_block_raw(self):
        """Test _extract_json_block handles raw json."""
        self.assertEqual(_extract_json_block("  {\"key\": \"val\"} "), "{\"key\": \"val\"}")

    def test_extract_json_block_array(self):
        """Test _extract_json_block handles raw array."""
        self.assertEqual(_extract_json_block("   [1, 2, 3]  "), "[1, 2, 3]")

    def test_extract_json_block_invalid(self):
        """Test _extract_json_block raises ValueError on malformed blocks."""
        with self.assertRaises(ValueError):
            _extract_json_block("no braces here")
        with self.assertRaises(ValueError):
            _extract_json_block("{ unclosed")
        with self.assertRaises(ValueError):
            _extract_json_block("[ unclosed")

    def test_clean_json_comments_and_commas(self):
        """Test cleaning trailing commas and comments."""
        raw = """{
            // single line comment
            /* multi line
               comment */
            "key": "val",
            "arr": [1, 2,],
        }"""
        expected = """{
            
            
            "key": "val",
            "arr": [1, 2]}"""
        self.assertEqual(
            _clean_json_comments_and_commas(raw).strip(),
            expected.strip()
        )

    def test_escape_control_chars_in_strings(self):
        """Test escaping raw control characters in string values."""
        raw = '{"key": "value with \n newline and \t tab"}'
        expected = '{"key": "value with \\n newline and \\t tab"}'
        self.assertEqual(_escape_control_chars_in_strings(raw), expected)

    def test_robust_json_loads_empty(self):
        """Test robust_json_loads raises ValueError on empty string."""
        with self.assertRaises(ValueError):
            robust_json_loads("")

    def test_robust_json_loads_single_quotes(self):
        """Test robust_json_loads falls back to single-to-double quote replace."""
        raw = "{'key': 'value'}"
        self.assertEqual(robust_json_loads(raw), {"key": "value"})

    def test_is_old_role_true(self):
        """Test _is_old_role detects old pre-2015 roles."""
        fm = {"dates": {"start": "2012-01-01"}}
        self.assertTrue(_is_old_role(fm))

    def test_is_old_role_false(self):
        """Test _is_old_role detects recent roles."""
        fm = {"dates": {"start": "2020-01-01"}}
        self.assertFalse(_is_old_role(fm))

    def test_is_old_role_missing(self):
        """Test _is_old_role handles missing dates by returning False."""
        self.assertFalse(_is_old_role({}))

    def test_get_experience_key(self):
        """Test _get_experience_key combines org and start_year."""
        content = """---
organization: "[[intel-slug]]"
dates:
  start: 2020-01-01
---
"""
        self.assertEqual(_get_experience_key("intel.md", content), ("intel-slug", "2020"))

    def test_deduplicate_scored_experiences(self):
        """Test _deduplicate_scored_experiences keeps highest scored duplicates."""
        content_1 = """---
organization: "[[intel-slug]]"
dates:
  start: 2020-01-01
---
"""
        content_2 = """---
organization: "[[intel-slug]]"
dates:
  start: 2020-01-01
---
"""
        content_3 = """---
organization: "[[google-slug]]"
dates:
  start: 2021-01-01
---
"""
        experiences = [
            (10, "intel.md", content_1, "justification-1"),
            (5, "intel.md", content_2, "justification-2"),
            (20, "google.md", content_3, "justification-3"),
        ]
        dedupped = _deduplicate_scored_experiences(experiences)
        self.assertEqual(len(dedupped), 2)
        # Verify the higher scored intel Engineer is kept
        self.assertIn((10, "intel.md", content_1, "justification-1"), dedupped)
        self.assertNotIn((5, "intel.md", content_2, "justification-2"), dedupped)

    def test_extract_start_date_normalized(self):
        """Test _extract_start_date_normalized handles format variations."""
        self.assertEqual(_extract_start_date_normalized({"dates": {"start": "2020-01-01"}}), "2020-01-01")
        self.assertEqual(_extract_start_date_normalized({"dates": {"start": "2020-01"}}), "2020-01-01")
        self.assertEqual(_extract_start_date_normalized({}), "1970-01-01")

    def test_extract_end_date_normalized(self):
        """Test _extract_end_date_normalized handles formats."""
        current_date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        self.assertEqual(_extract_end_date_normalized({"dates": {"end": "Present"}}), current_date_str)
        self.assertEqual(_extract_end_date_normalized({"dates": {"end": "2022-05-15"}}), "2022-05-15")
        self.assertEqual(_extract_end_date_normalized({}), current_date_str)

    def test_is_parallel_startup_track(self):
        """Test parallel startup tracking."""
        self.assertTrue(_is_parallel_startup_track({"tracks": ["co-founder", "Engineering"]}))
        self.assertFalse(_is_parallel_startup_track({"tracks": ["Engineering"]}))
        self.assertFalse(_is_parallel_startup_track({}))

    def test_get_org_slug(self):
        """Test _get_org_slug matches [[slug]] and normalization rules."""
        self.assertEqual(_get_org_slug("intel", {"organization": "[[intel-slug]]"}), "intel")
        self.assertEqual(_get_org_slug("google", {"organization": "[[google-slug]]"}), "google-slug")
        self.assertEqual(_get_org_slug("google", {}), "google")

    def test_split_recent_and_old_experiences(self):
        """Test splitting by age."""
        content1 = """---
organization: "[[intel-slug]]"
dates:
  start: 2022-01-01
---
"""
        content2 = """---
organization: "[[ibm-slug]]"
dates:
  start: 2010-01-01
---
"""
        deduplicated = [
            (10, "intel.md", content1, "intel-key"),
            (5, "ibm.md", content2, "ibm-key"),
        ]
        recent, old = _split_recent_and_old_experiences(deduplicated)
        self.assertEqual(len(recent), 1)
        self.assertEqual(len(old), 1)
        self.assertEqual(recent[0][1], "intel.md")
        self.assertIn("ibm-slug", old)

    def test_resolve_regional_strategy_success(self):
        """Test resolve_regional_strategy successfully resolves files with frontmatter."""
        mock_wiki_dir = MagicMock()
        mock_strategy_file = MagicMock()
        mock_strategy_file.exists.return_value = True
        mock_strategy_file.read_text.return_value = """---
pdf_template: custom-template.css
---
strategy content text"""

        # mock_wiki_dir / "wiki" / "strategies" / "strategy-us.md"
        mock_wiki_dir.__truediv__.return_value.__truediv__.return_value.__truediv__.return_value = mock_strategy_file

        strategy_text, pdf_template = resolve_regional_strategy(mock_wiki_dir, "us")
        self.assertIn("strategy content text", strategy_text)
        self.assertEqual(pdf_template, "custom-template.css")

    def test_resolve_regional_strategy_fallback(self):
        """Test resolve_regional_strategy falls back gracefully."""
        mock_wiki_dir = MagicMock()
        mock_strategy_file = MagicMock()
        mock_strategy_file.exists.return_value = False

        # mock_wiki_dir / "wiki" / "strategies" / f"strategy-non-existent.md"
        mock_wiki_dir.__truediv__.return_value.__truediv__.return_value.__truediv__.return_value = mock_strategy_file

        strategy_text, pdf_template = resolve_regional_strategy(mock_wiki_dir, "non-existent")
        self.assertEqual(strategy_text, "")
        self.assertEqual(pdf_template, "templates/base.css")

    @patch("pathlib.Path.glob")
    @patch("pathlib.Path.exists")
    def test_get_subject_info(self, mock_exists, mock_glob):
        """Test get_subject_info reads subject.md."""
        mock_exists.return_value = True
        mock_file = MagicMock(spec=Path)
        mock_file.read_text.return_value = 'tags: ["person"]\nSubject Detail Info'
        mock_glob.return_value = [mock_file]
        self.assertEqual(get_subject_info(Path("wiki")), 'tags: ["person"]\nSubject Detail Info')

    def test_parse_start_date(self):
        """Test parsing dates to year-month tuples."""
        self.assertEqual(_parse_start_date("start: 2020-05-15"), (2020, 5))
        self.assertEqual(_parse_start_date("START_DATE: 2020-05-15"), (2020, 5))
        self.assertEqual(_parse_start_date("invalid-date"), (1970, 1))

    def test_parse_and_sort_chronological_entries(self):
        """Test parse_and_sort_chronological_entries correctly sorts entries."""
        entries = [
            "--- CAREER ENTRY: b.md ---\nstart: 2018-05-01\n---",
            "--- CAREER ENTRY: a.md ---\nstart: 2022-01-01\n---",
        ]
        sorted_output = parse_and_sort_chronological_entries(entries)
        # Check that the entry with the later start date is listed first
        self.assertLess(sorted_output.find("a.md"), sorted_output.find("b.md"))


if __name__ == "__main__":
    unittest.main()
