import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import json

import sys
# Ensure src is in python path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from cv_generator_graph import (
    _score_by_keywords,
    _generate_skill_bridging_map,
    node_analyzer,
    CVPipelineState
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
        self.assertEqual(score, 0)  # "Python" does not match "Pythoneer", "Azure" does not match "AzureDevOps"

    def test_score_by_keywords_empty_inputs(self):
        """Test _score_by_keywords handles empty inputs gracefully."""
        self.assertEqual(_score_by_keywords("", ["Python"]), 0)
        self.assertEqual(_score_by_keywords("Some text", []), 0)

    @patch("cv_generator_graph.get_model_for_step")
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
        
        bridge_map = _generate_skill_bridging_map(mock_llm, "Job Description", skills, keywords)
        
        self.assertEqual(bridge_map.get("AWS"), "Azure (equivalent)")
        self.assertEqual(bridge_map.get("React"), "Angular (equivalent)")

    @patch("cv_generator_graph.get_model_for_step")
    def test_generate_skill_bridging_map_invalid_json(self, mock_get_model):
        """Test _generate_skill_bridging_map returns empty dict on malformed JSON."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Not a JSON string"
        mock_llm.invoke.return_value = mock_response
        mock_get_model.return_value = mock_llm

        bridge_map = _generate_skill_bridging_map(mock_llm, "Job Description", [], ["AWS"])
        self.assertEqual(bridge_map, {})

    @patch("cv_generator_graph.get_model_for_step")
    @patch("cv_generator_graph.get_wiki_dir")
    def test_node_analyzer_with_strategy_override(self, mock_get_wiki_dir, mock_get_model):
        """Test node_analyzer respects strategy_override and bypasses suggested_region."""
        # Mock strategy directory
        mock_wiki_path = Path("/mock/wiki")
        mock_get_wiki_dir.return_value = mock_wiki_path
        
        mock_llm = MagicMock()
        mock_response = MagicMock()
        # Analyzer LLM suggestions
        mock_response.content = json.dumps({
            "persona": "Staff Engineer",
            "keywords": ["Python", "K8s"],
            "locations": ["Remote"],
            "expectations": "Standard CV",
            "suggested_region": "emea",
            "target_organization_slug": "mock-org",
            "target_role": "Mock Role"
        })
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
            "skill_bridging_map": {}
        }

        result = node_analyzer(state)
        
        # Verify region is the overridden value "ireland" instead of suggested "emea"
        self.assertEqual(result["target_region"], "ireland")
        self.assertEqual(result["target_organization_slug"], "mock-org")
        self.assertEqual(result["target_role"], "Mock Role")


if __name__ == "__main__":
    unittest.main()
