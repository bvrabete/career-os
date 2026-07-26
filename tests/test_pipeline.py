import unittest
import tempfile
from unittest.mock import MagicMock, patch
from pathlib import Path
import json
import sys

from docx_generator import generate_docx

# Ensure src is in python path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from generation.state import CVPipelineState
from generation.nodes import node_analyzer
from generation.helpers import (
    score_by_keywords as _score_by_keywords,
    generate_skill_bridging_map as _generate_skill_bridging_map,
    _detect_employment_type,
)


class TestCVGeneratorPipeline(unittest.TestCase):
    """Unit tests for the Career OS CV Generator Pipeline enhancements."""

    def test_score_by_keywords_exact_matches(self):
        """Test _score_by_keywords with exact whole-word matches."""
        text = "Experienced in Python and Azure Cloud deployments."
        keywords = ["Python", "Azure", "Cloud", "Nonexistent"]
        score = _score_by_keywords(text, keywords)
        self.assertEqual(score, 3)

    def test_score_by_keywords_case_insensitivity(self):
        """Test _score_by_keywords is case-insensitive."""
        text = "experienced in python and azure cloud deployments."
        keywords = ["PYTHON", "AZURE", "CLOUD"]
        score = _score_by_keywords(text, keywords)
        self.assertEqual(score, 3)

    def test_score_by_keywords_word_boundaries(self):
        """Test _score_by_keywords respects word boundaries (no partial matching)."""
        text = "We use Pythoneer and AzureDevOps daily."
        keywords = ["Python", "Azure"]
        score = _score_by_keywords(text, keywords)
        self.assertEqual(
            score, 0
        )  # "Python" does not match "Pythoneer", "Azure" does not match "AzureDevOps"

    def test_score_by_keywords_empty_inputs(self):
        """Test _score_by_keywords handles empty inputs gracefully."""
        self.assertEqual(_score_by_keywords("", ["Python"]), 0)
        self.assertEqual(_score_by_keywords("Some text", []), 0)

    @patch("generation.helpers.get_model_for_step")
    def test_generate_skill_bridging_map_basic(self, mock_get_model):
        """Test _generate_skill_bridging_map returns expected dictionary."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        # Mock LLM returning valid JSON
        mock_response.content = '```json\n{"AWS": "Azure (equivalent)", "React": "Angular (equivalent)"}\n```'
        mock_llm.invoke.return_value = mock_response
        mock_get_model.return_value = mock_llm

        skills = ["Azure Cloud Platform", "Angular 17 Frontend"]
        keywords = ["AWS", "React"]

        bridge_map = _generate_skill_bridging_map(mock_llm, skills, keywords)

        self.assertEqual(bridge_map.get("AWS"), "Azure (equivalent)")
        self.assertEqual(bridge_map.get("React"), "Angular (equivalent)")

    @patch("generation.helpers.get_model_for_step")
    def test_generate_skill_bridging_map_invalid_json(self, mock_get_model):
        """Test _generate_skill_bridging_map returns empty dict on malformed JSON."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Not a JSON string"
        mock_llm.invoke.return_value = mock_response
        mock_get_model.return_value = mock_llm

        bridge_map = _generate_skill_bridging_map(mock_llm, [], ["AWS"])
        self.assertEqual(bridge_map, {})

    @patch("generation.nodes.get_model_for_step")
    @patch("generation.nodes.get_wiki_dir")
    def test_node_analyzer_with_strategy_override(
        self, mock_get_wiki_dir, mock_get_model
    ):
        """Test node_analyzer respects strategy_override and bypasses suggested_region."""
        # Mock strategy directory
        mock_wiki_path = Path("/mock/wiki")
        mock_get_wiki_dir.return_value = mock_wiki_path

        mock_llm = MagicMock()
        mock_response = MagicMock()
        # Analyzer LLM suggestions
        mock_response.content = json.dumps(
            {
                "persona": "Staff Engineer",
                "keywords": ["Python", "K8s"],
                "locations": ["Remote"],
                "expectations": "Standard CV",
                "suggested_region": "emea",
                "target_organization_slug": "mock-org",
                "target_role": "Mock Role",
            }
        )
        mock_llm.invoke.return_value = mock_response
        mock_get_model.return_value = mock_llm

        # Test state with strategy_override set to "ireland"
        state: CVPipelineState = {
            "job_description": "We need a Python coder",
            "iteration_count": 0,
            "strategy_override": "ireland",
            "target_persona": "",
            "target_region": "",
            "target_locations": [],
            "cv_expectations": "",
            "primary_keywords": [],
            "selected_entries": [],
            "education_entries": [],
            "skills_entries": [],
            "strategy_info": "",
            "pdf_template": "",
            "draft_cv": "",
            "audit_feedback": "",
            "refiner_feedback": "",
            "projects_entries": [],
            "patents_entries": [],
            "notes_entries": [],
            "few_shot_examples": [],
            "skill_bridging_map": {},
            "target_organization_slug": "",
            "target_role": "",
            "strategy_metadata": [],
            "languages_entries": "",
        }

        result = node_analyzer(state)

        # Verify region is the overridden value "ireland" instead of suggested "emea"
        self.assertEqual(result["target_region"], "ireland")
        self.assertEqual(result["target_organization_slug"], "mock-org")
        self.assertEqual(result["target_role"], "Mock Role")

    @patch("generation.helpers.get_model_for_step")
    def test_compress_experience_llm_success(self, mock_get_model):
        """Test that _compress_experience_llm correctly calls retrieval model and compresses."""
        from generation.helpers import (
            compress_experience_llm as _compress_experience_llm,
        )

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Compressed content summary."
        mock_llm.invoke.return_value = mock_response
        mock_get_model.return_value = mock_llm

        raw_experience = "---\ntype: experience\n---\nLong body list..."
        compressed = _compress_experience_llm(raw_experience)
        self.assertEqual(compressed, "Compressed content summary.")
        mock_get_model.assert_called_once_with("RETRIEVAL")

    @patch("generation.nodes.get_model_for_step")
    @patch("generation.helpers.get_fallback_model_for_step")
    def test_node_drafter_fallback_on_rate_limit(
        self, mock_get_fallback, mock_get_model
    ):
        """Test that node_drafter falls back to configured fallback model when OpenAI raises rate limit exception."""
        from generation.nodes import node_drafter

        # Mock main LLM to raise RateLimitError
        mock_openai_llm = MagicMock()
        mock_openai_llm.invoke.side_effect = Exception(
            "rate_limit_exceeded: TPM limit reached"
        )
        mock_get_model.return_value = mock_openai_llm

        # Mock fallback LLM
        mock_gemini_llm = MagicMock()
        mock_gemini_response = MagicMock()
        mock_gemini_response.content = "Gemini-drafted CV content"
        mock_gemini_llm.invoke.return_value = mock_gemini_response
        mock_get_fallback.return_value = mock_gemini_llm

        state: CVPipelineState = {
            "job_description": "We need a Python coder",
            "iteration_count": 0,
            "target_persona": "Persona",
            "target_region": "emea",
            "target_locations": [],
            "cv_expectations": "",
            "primary_keywords": [],
            "selected_entries": ["--- CAREER ENTRY: test.md ---\nContent"],
            "education_entries": [],
            "skills_entries": [],
            "strategy_info": "",
            "pdf_template": "",
            "draft_cv": "",
            "audit_feedback": "",
            "refiner_feedback": "",
            "projects_entries": [],
            "patents_entries": [],
            "notes_entries": [],
            "few_shot_examples": [],
            "skill_bridging_map": {},
            "target_organization_slug": "org",
            "target_role": "role",
            "strategy_metadata": [],
            "strategy_override": "",
            "languages_entries": "",
        }

        result = node_drafter(state)
        self.assertEqual(result["draft_cv"], "Gemini-drafted CV content")
        mock_get_fallback.assert_called_once_with("DRAFTING")

    @patch("generation.nodes.get_model_for_step")
    @patch("generation.helpers.get_fallback_model_for_step")
    def test_node_drafter_no_fallback_configured(
        self, mock_get_fallback, mock_get_model
    ):
        """Test that node_drafter raises the original exception when no fallback is configured."""
        from generation.nodes import node_drafter

        # Mock main LLM to raise RateLimitError
        mock_openai_llm = MagicMock()
        mock_openai_llm.invoke.side_effect = Exception(
            "rate_limit_exceeded: TPM limit reached"
        )
        mock_get_model.return_value = mock_openai_llm

        # Mock fallback loader to return None (no fallback configured)
        mock_get_fallback.return_value = None

        state: CVPipelineState = {
            "job_description": "We need a Python coder",
            "iteration_count": 0,
            "target_persona": "Persona",
            "target_region": "emea",
            "target_locations": [],
            "cv_expectations": "",
            "primary_keywords": [],
            "selected_entries": ["--- CAREER ENTRY: test.md ---\nContent"],
            "education_entries": [],
            "skills_entries": [],
            "strategy_info": "",
            "pdf_template": "",
            "draft_cv": "",
            "audit_feedback": "",
            "refiner_feedback": "",
            "projects_entries": [],
            "patents_entries": [],
            "notes_entries": [],
            "few_shot_examples": [],
            "skill_bridging_map": {},
            "target_organization_slug": "org",
            "target_role": "role",
            "strategy_metadata": [],
            "strategy_override": "",
            "languages_entries": "",
        }

        with self.assertRaises(Exception) as context:
            node_drafter(state)
        self.assertIn("rate_limit_exceeded", str(context.exception))

    def test_prune_recent_experience_top_achievements(self):
        """Test that _prune_recent_experience ranks and limits achievements to the top 4."""
        from generation.helpers import (
            prune_recent_experience as _prune_recent_experience,
        )

        # Experience with 6 achievements
        test_content = """---
type: experience
title: "Senior Manager"
organization: [[test-org]]
dates:
  start: 2020-01-01
  end: Present
skills: [Python, Go]
---

# Senior Manager at Test Org

## Narrative & Reflections
This is some narrative text that should be stripped.

## Achievements

- **Situation**: Need a highly scalable microservice.
  - **Task**: Write a service in Python.
  - **Action**: Wrote it using FastAPI and asyncio.
  - **Result**: Handled 10k RPS.
- **Situation**: Legacy database migration.
  - **Task**: Migrate Postgres to CockroachDB.
  - **Action**: Automated with Python and SQL scripts.
  - **Result**: Zero downtime migration.
- **Situation**: Heavy manual deployment overhead.
  - **Task**: Reduce deploy time.
  - **Action**: Implemented Docker and Kubernetes CI/CD.
  - **Result**: Saved 20 hours a week.
- **Situation**: Team was not using Go.
  - **Task**: Standardize on Go for high performance.
  - **Action**: Trained 5 engineers in Go.
  - **Result**: Built new high speed RPC services.
- **Situation**: Low test coverage.
  - **Task**: Raise coverage to 90%.
  - **Action**: Wrote pytest unit tests.
  - **Result**: Fixed 15 bugs early.
- **Situation**: Unrelated achievement with low overlap.
  - **Task**: Paint the office kitchen.
  - **Action**: Painted it yellow.
  - **Result**: Better office mood.
"""

        # Run with keywords matching the first 4 achievements (Python, Postgres, Kubernetes, Go)
        pruned = _prune_recent_experience(
            test_content, ["Python", "Postgres", "Kubernetes", "Go"]
        )

        # Verify that Narrative & Reflections is stripped
        self.assertNotIn("Narrative & Reflections", pruned)
        self.assertNotIn("should be stripped", pruned)

        # Verify that only 4 achievements are kept (and the "office kitchen" one is filtered out)
        self.assertIn("FastAPI", pruned)
        self.assertIn("CockroachDB", pruned)
        self.assertIn("Docker and Kubernetes", pruned)
        self.assertIn("Trained 5 engineers", pruned)
        self.assertNotIn("Paint the office kitchen", pruned)

        # Count the number of achievements (Situation blocks)
        self.assertEqual(pruned.count("- **Situation"), 4)

    def test_detect_employment_type_explicit(self):
        """Test _detect_employment_type with explicit frontmatter."""
        fm = {"employment_type": "Contract"}
        self.assertEqual(_detect_employment_type(fm, ""), "Contract")

        fm = {"employment_type": "Permanent"}
        self.assertEqual(_detect_employment_type(fm, ""), "Permanent")

        fm = {"employment_type": "contract"}
        self.assertEqual(_detect_employment_type(fm, ""), "Contract")

    def test_detect_employment_type_fallback(self):
        """Test _detect_employment_type fallbacks when frontmatter is missing."""
        fm = {"tags": ["contract", "remote"]}
        self.assertEqual(_detect_employment_type(fm, ""), "Contract")

        fm = {"title": "Contract Software Engineer"}
        self.assertEqual(_detect_employment_type(fm, ""), "Contract")

        fm = {}
        content = "Worked as a contractor for 6 months."
        self.assertEqual(_detect_employment_type(fm, content), "Contract")

        fm = {}
        content = "Regular full-time software developer role."
        self.assertEqual(_detect_employment_type(fm, content), "Permanent")


class TestDOCXGenerator(unittest.TestCase):
    """Unit tests for the DOCX generation utility using Pandoc."""

    def test_docx_generation_success(self):
        """Test docx generation with valid input using tempfile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "test_output.docx"
            md_content = "# Hello World\nSome body text."
            success = generate_docx(md_content, str(out_file))
            self.assertTrue(success)
            self.assertTrue(out_file.exists())
            self.assertGreater(out_file.stat().st_size, 0)

    @patch("docx.Document")
    def test_docx_generation_failure(self, mock_doc):
        """Test docx generation failure handling on document save or creation error."""
        from docx_generator import generate_docx

        # Mock docx.Document raising an exception
        mock_doc.side_effect = Exception("Mocked document creation failure")

        success = generate_docx("# Dummy", "dummy.docx")
        self.assertFalse(success)


if __name__ == "__main__":
    unittest.main()
