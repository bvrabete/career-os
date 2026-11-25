"""Unit tests for the generation helper functions."""
import pytest
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
    calculate_experience_weight,
)


class TestGenerationHelpers:
    """Deterministic, isolated unit tests for CV Generation Helpers."""

    def test_llm_text_str(self):
        """Test llm_text with a simple string."""
        assert llm_text("hello") == "hello"

    def test_llm_text_list(self):
        """Test llm_text with a list of parts."""
        assert llm_text(["hello", 123, "world"]) == "hello 123 world"

    def test_extract_json_block_markdown(self):
        """Test _extract_json_block handles markdown code blocks."""
        raw = "Some preamble ```json\n{\"key\": \"val\"}\n``` postscript"
        assert _extract_json_block(raw) == "{\"key\": \"val\"}"

    def test_extract_json_block_raw(self):
        """Test _extract_json_block handles raw json."""
        assert _extract_json_block("  {\"key\": \"val\"} ") == "{\"key\": \"val\"}"

    def test_extract_json_block_array(self):
        """Test _extract_json_block handles raw array."""
        assert _extract_json_block("   [1, 2, 3]  ") == "[1, 2, 3]"

    def test_extract_json_block_invalid(self):
        """Test _extract_json_block raises ValueError on malformed blocks."""
        with pytest.raises(ValueError):
            _extract_json_block("no braces here")
        with pytest.raises(ValueError):
            _extract_json_block("{ unclosed")
        with pytest.raises(ValueError):
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
        expected = "{\n            \n            \n            \"key\": \"val\",\n            \"arr\": [1, 2]}"
        assert _clean_json_comments_and_commas(raw).strip() == expected.strip()

    def test_escape_control_chars_in_strings(self):
        """Test escaping raw control characters in string values."""
        raw = '{"key": "value with \n newline and \t tab"}'
        expected = '{"key": "value with \\n newline and \\t tab"}'
        assert _escape_control_chars_in_strings(raw) == expected

    def test_robust_json_loads_empty(self):
        """Test robust_json_loads raises ValueError on empty string."""
        with pytest.raises(ValueError):
            robust_json_loads("")

    def test_robust_json_loads_single_quotes(self):
        """Test robust_json_loads falls back to single-to-double quote replace."""
        raw = "{'key': 'value'}"
        assert robust_json_loads(raw) == {"key": "value"}

    def test_is_old_role_true(self):
        """Test _is_old_role detects old pre-2015 roles."""
        fm = {"dates": {"start": "2012-01-01"}}
        assert _is_old_role(fm)

    def test_is_old_role_false(self):
        """Test _is_old_role detects recent roles."""
        fm = {"dates": {"start": "2020-01-01"}}
        assert not _is_old_role(fm)

    def test_is_old_role_missing(self):
        """Test _is_old_role handles missing dates by returning False."""
        assert not _is_old_role({})

    def test_get_experience_key(self):
        """Test _get_experience_key combines org and start_year."""
        content = """---
organization: "[[intel-slug]]"
dates:
  start: 2020-01-01
---
"""
        assert _get_experience_key("intel.md", content) == ("intel-slug", "2020")

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
        assert len(dedupped) == 2
        # Verify the higher scored intel Engineer is kept
        assert (10, "intel.md", content_1, "justification-1") in dedupped
        assert (5, "intel.md", content_2, "justification-2") not in dedupped

    def test_extract_start_date_normalized(self):
        """Test _extract_start_date_normalized handles format variations."""
        assert _extract_start_date_normalized({"dates": {"start": "2020-01-01"}}) == "2020-01-01"
        assert _extract_start_date_normalized({"dates": {"start": "2020-01"}}) == "2020-01-01"
        assert _extract_start_date_normalized({}) == "1970-01-01"

    def test_extract_end_date_normalized(self):
        """Test _extract_end_date_normalized handles formats."""
        current_date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        assert _extract_end_date_normalized({"dates": {"end": "Present"}}) == current_date_str
        assert _extract_end_date_normalized({"dates": {"end": "2022-05-15"}}) == "2022-05-15"
        assert _extract_end_date_normalized({}) == current_date_str

    def test_is_parallel_startup_track(self):
        """Test parallel startup tracking."""
        assert _is_parallel_startup_track({"tracks": ["co-founder", "Engineering"]})
        assert not _is_parallel_startup_track({"tracks": ["Engineering"]})
        assert not _is_parallel_startup_track({})

    def test_get_org_slug(self):
        """Test _get_org_slug matches [[slug]] and normalization rules."""
        assert _get_org_slug("acme", {"organization": "[[acme-slug]]"}) == "acme-slug"
        assert _get_org_slug("google", {"organization": "[[google-slug]]"}) == "google-slug"
        assert _get_org_slug("google", {}) == "google"

    def test_split_recent_and_old_experiences(self):
        """Test splitting by age."""
        content1 = """---
organization: "[[acme-slug]]"
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
            (10, "acme.md", content1, "acme-key"),
            (5, "ibm.md", content2, "ibm-key"),
        ]
        recent, old = _split_recent_and_old_experiences(deduplicated)
        assert len(recent) == 1
        assert len(old) == 1
        assert recent[0][1] == "acme.md"
        assert "ibm-slug" in old

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
        assert "strategy content text" in strategy_text
        assert pdf_template == "custom-template.css"

    def test_resolve_regional_strategy_fallback(self):
        """Test resolve_regional_strategy falls back gracefully."""
        mock_wiki_dir = MagicMock()
        mock_strategy_file = MagicMock()
        mock_strategy_file.exists.return_value = False

        # mock_wiki_dir / "wiki" / "strategies" / f"strategy-non-existent.md"
        mock_wiki_dir.__truediv__.return_value.__truediv__.return_value.__truediv__.return_value = mock_strategy_file

        strategy_text, pdf_template = resolve_regional_strategy(mock_wiki_dir, "non-existent")
        assert strategy_text == ""
        assert pdf_template == "templates/base.css"

    @patch("pathlib.Path.glob")
    @patch("pathlib.Path.exists")
    def test_get_subject_info(self, mock_exists, mock_glob):
        """Test get_subject_info reads subject.md."""
        mock_exists.return_value = True
        mock_file = MagicMock(spec=Path)
        mock_file.read_text.return_value = 'tags: ["person"]\nSubject Detail Info'
        mock_glob.return_value = [mock_file]
        assert get_subject_info(Path("wiki")) == 'tags: ["person"]\nSubject Detail Info'

    def test_parse_start_date(self):
        """Test parsing dates to year-month tuples."""
        assert _parse_start_date("start: 2020-05-15") == (2020, 5)
        assert _parse_start_date("START_DATE: 2020-05-15") == (2020, 5)
        assert _parse_start_date("invalid-date") == (1970, 1)

    def test_parse_and_sort_chronological_entries(self):
        """Test parse_and_sort_chronological_entries correctly sorts entries."""
        entries = [
            "--- CAREER ENTRY: b.md ---\nstart: 2018-05-01\n---",
            "--- CAREER ENTRY: a.md ---\nstart: 2022-01-01\n---",
        ]
        sorted_output = parse_and_sort_chronological_entries(entries)
        # Check that the entry with the later start date is listed first
        assert sorted_output.find("a.md") < sorted_output.find("b.md")

    def test_calculate_experience_weight_recent_high_relevance_long_duration(self):
        """Test weight calculation for a recent, highly relevant, and long duration role."""
        fm = {
            "dates": {
                "start": "2023-01-01",
                "end": "Present"
            }
        }
        # Score is 95, recent, duration is ~3.5 years (assuming current year is 2026)
        weight = calculate_experience_weight(95, fm)
        assert weight >= 0.70  # Should route to Tier 1

    def test_calculate_experience_weight_historical_long_duration(self):
        """Test weight calculation for a historical, long duration role."""
        fm = {
            "dates": {
                "start": "2010-01-01",
                "end": "2015-12-31"
            }
        }
        # High relevance score, old role, long duration (6 years)
        weight = calculate_experience_weight(90, fm)
        # ATS score factor: 0.9 * 0.5 = 0.45
        # Recency factor: max(0.0, 1.0 - (2026 - 2015)/15) = 1.0 - 11/15 = 0.266 -> 0.266 * 0.3 = 0.08
        # Duration factor: 6/3 capped at 1.0 -> 1.0 * 0.2 = 0.2
        # Expected weight: ~0.73
        assert weight >= 0.65

    def test_calculate_experience_weight_old_low_relevance_short_duration(self):
        """Test weight calculation for an old, low relevance, and short duration role."""
        fm = {
            "dates": {
                "start": "2005-01-01",
                "end": "2005-03-01"
            }
        }
        # Score is 30, very old, duration is 2 months
        weight = calculate_experience_weight(30, fm)
        assert weight < 0.40  # Should route to Tier 3

    def test_calculate_experience_weight_discounts_contract_role(self):
        """Test calculate_experience_weight discounts contract roles vs permanent roles of equal score."""
        fm_perm = {
            "dates": {"start": "2023-01-01", "end": "Present"},
            "employment_type": "Permanent",
        }
        fm_contract = {
            "dates": {"start": "2023-01-01", "end": "Present"},
            "employment_type": "Contract",
        }
        weight_perm = calculate_experience_weight(85, fm_perm, employment_type="Permanent", org_culture="corporate")
        weight_contract = calculate_experience_weight(
            85, fm_contract, employment_type="Contract", org_culture="corporate"
        )
        assert weight_contract < weight_perm
        assert weight_contract == pytest.approx(round(weight_perm * 0.85, 4), abs=10**(-2))

    def test_calculate_experience_weight_discounts_startup_for_corporate(self):
        """Test calculate_experience_weight discounts startup/co-founder roles when target is corporate."""
        fm_startup = {
            "dates": {"start": "2023-01-01", "end": "Present"},
            "employment_type": "Startup / Co-Founder",
        }
        fm_perm = {
            "dates": {"start": "2023-01-01", "end": "Present"},
            "employment_type": "Permanent",
        }
        weight_corp = calculate_experience_weight(
            85, fm_startup, employment_type="Startup / Co-Founder", org_culture="corporate"
        )
        weight_perm = calculate_experience_weight(
            85, fm_perm, employment_type="Permanent", org_culture="corporate"
        )
        assert weight_corp < weight_perm
        assert weight_corp == pytest.approx(round(weight_perm * 0.80, 4), abs=10**(-2))

    def test_calculate_experience_weight_boosts_startup_for_startup_track(self):
        """Test calculate_experience_weight boosts startup/co-founder roles when target is startup."""
        fm_startup = {
            "dates": {"start": "2023-01-01", "end": "2024-01-01"},
            "employment_type": "Startup / Co-Founder",
        }
        fm_perm = {
            "dates": {"start": "2023-01-01", "end": "2024-01-01"},
            "employment_type": "Permanent",
        }
        weight_startup_track = calculate_experience_weight(
            80, fm_startup, employment_type="Startup / Co-Founder", org_culture="startup"
        )
        weight_perm_track = calculate_experience_weight(
            80, fm_perm, employment_type="Permanent", org_culture="startup"
        )
        assert weight_startup_track > weight_perm_track
        assert weight_startup_track == pytest.approx(round(min(1.0, weight_perm_track * 1.10), 4), abs=10**(-2))

    def test_short_contract_cannot_outrank_permanent_role_across_variances(self):
        """Test short contract (high score 95) cannot outrank 2.5yr permanent role (moderate score 80)."""
        current_year = datetime.date.today().year
        fm_contract_6mo = {
            "dates": {
                "start": f"{current_year}-01-01",
                "end": f"{current_year}-07-01",
            },
            "employment_type": "Contract",
        }
        fm_perm_2_5yr = {
            "dates": {
                "start": f"{current_year - 3}-01-01",
                "end": f"{current_year}-07-01",
            },
            "employment_type": "Permanent",
        }
        contract_weight = calculate_experience_weight(
            95, fm_contract_6mo, employment_type="Contract", org_culture="corporate"
        )
        perm_weight = calculate_experience_weight(
            80, fm_perm_2_5yr, employment_type="Permanent", org_culture="corporate"
        )
        assert perm_weight > contract_weight
        assert perm_weight >= 0.70
        assert contract_weight < 0.70
