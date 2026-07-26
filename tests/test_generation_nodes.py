"""Unit tests for the generation pipeline nodes and orchestration logic."""

import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch, MagicMock
from langchain_core.messages import AIMessage

# Ensure src is in python path
import sys

sys.path.append(str(Path(__file__).parent.parent / "src"))

from generation.nodes import (
    node_analyzer,
    node_retriever,
    node_drafter,
    node_refiner,
    node_auditor,
)
from generation.state import CVPipelineState


class TestGenerationNodes(unittest.TestCase):
    """Deterministic offline unit tests for CV Generation Nodes."""

    @patch("generation.nodes.get_wiki_dir")
    @patch("generation.nodes.get_model_for_step")
    @patch("generation.nodes.load_prompt")
    def test_node_analyzer_success(
        self, mock_load_prompt, mock_get_model, mock_get_wiki_dir
    ):
        """Test node_analyzer successfully analyzes job description and suggest strategy."""
        mock_load_prompt.return_value = "System template with {AVAILABLE_STRATEGIES}, {DEFAULT_STRATEGY}, and {JOB_DESCRIPTION}"
        mock_wiki = MagicMock()
        mock_strategy_dir = MagicMock()
        mock_strategy_dir.exists.return_value = True
        mock_file1 = MagicMock()
        mock_file1.stem = "strategy-us"
        mock_file2 = MagicMock()
        mock_file2.stem = "strategy-eu"
        mock_strategy_dir.glob.return_value = [mock_file1, mock_file2]
        mock_wiki.__truediv__.return_value.__truediv__.return_value = mock_strategy_dir
        mock_get_wiki_dir.return_value = mock_wiki

        mock_llm = MagicMock()
        mock_response = AIMessage(
            content='{"persona": "AI Leader", "keywords": ["python", "AI"], "locations": ["London"], "expectations": "Premium", "suggested_region": "eu", "target_organization_slug": "intel", "target_role": "Architect"}'
        )
        mock_llm.invoke.return_value = mock_response
        mock_get_model.return_value = mock_llm

        state: CVPipelineState = {
            "job_description": "We need a python AI leader in London.",
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
            "iteration_count": 0,
            "strategy_override": "",
            "projects_entries": [],
            "patents_entries": [],
            "notes_entries": [],
            "few_shot_examples": [],
            "skill_bridging_map": {},
            "target_organization_slug": "",
            "target_role": "",
            "strategy_metadata": cast(Any, {}),
            "languages_entries": [],
        }

        result = node_analyzer(state)
        self.assertEqual(result["target_persona"], "AI Leader")
        self.assertEqual(result["primary_keywords"], ["python", "AI"])
        self.assertEqual(result["target_region"], "eu")
        self.assertEqual(result["target_locations"], ["London"])
        self.assertEqual(result["cv_expectations"], "Premium")
        self.assertEqual(result["target_organization_slug"], "intel")
        self.assertEqual(result["target_role"], "Architect")

    @patch("generation.nodes.get_wiki_dir")
    @patch("generation.nodes.get_model_for_step")
    @patch("generation.nodes.load_prompt")
    def test_node_analyzer_fallback(
        self, mock_load_prompt, mock_get_model, mock_get_wiki_dir
    ):
        """Test node_analyzer falls back to default on JSON parsing failure."""
        mock_load_prompt.return_value = "template"
        mock_wiki = MagicMock()
        mock_wiki.__truediv__.return_value.__truediv__.return_value.exists.return_value = (
            False
        )
        mock_get_wiki_dir.return_value = mock_wiki

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="invalid-json-text")
        mock_get_model.return_value = mock_llm

        state: CVPipelineState = {
            "job_description": "We need a python AI leader in London.",
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
            "iteration_count": 0,
            "strategy_override": "",
            "projects_entries": [],
            "patents_entries": [],
            "notes_entries": [],
            "few_shot_examples": [],
            "skill_bridging_map": {},
            "target_organization_slug": "",
            "target_role": "",
            "strategy_metadata": cast(Any, {}),
            "languages_entries": [],
        }

        result = node_analyzer(state)
        self.assertEqual(result["target_persona"], "invalid-json-text")
        self.assertEqual(result["primary_keywords"], [])
        self.assertEqual(result["target_region"], "emea")  # strategy_default: emea
        self.assertEqual(result["target_locations"], [])
        self.assertEqual(result["cv_expectations"], "Standard professional CV")

    @patch("generation.nodes.get_wiki_dir")
    @patch("generation.nodes.get_model_for_step")
    @patch("generation.nodes.load_prompt")
    def test_node_analyzer_strategy_override(
        self, mock_load_prompt, mock_get_model, mock_get_wiki_dir
    ):
        """Test node_analyzer honors strategy_override."""
        mock_load_prompt.return_value = "template"
        mock_wiki = MagicMock()
        mock_wiki.__truediv__.return_value.__truediv__.return_value.exists.return_value = (
            False
        )
        mock_get_wiki_dir.return_value = mock_wiki

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(
            content='{"persona": "Staff", "suggested_region": "us"}'
        )
        mock_get_model.return_value = mock_llm

        state: CVPipelineState = {
            "job_description": "JD",
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
            "iteration_count": 0,
            "strategy_override": "eu",
            "projects_entries": [],
            "patents_entries": [],
            "notes_entries": [],
            "few_shot_examples": [],
            "skill_bridging_map": {},
            "target_organization_slug": "",
            "target_role": "",
            "strategy_metadata": cast(Any, {}),
            "languages_entries": [],
        }

        result = node_analyzer(state)
        self.assertEqual(result["target_region"], "eu")

    @patch("generation.nodes.retrieve_languages")
    @patch("generation.skills_helper.get_compact_skills_list")
    @patch("generation.nodes.get_wiki_dir")
    @patch("generation.nodes.get_model_for_step")
    @patch("generation.nodes.retrieve_and_score_experiences")
    @patch("generation.nodes.retrieve_and_deduplicate_education")
    @patch("generation.nodes.retrieve_and_score_projects")
    @patch("generation.nodes.retrieve_and_score_patents")
    @patch("generation.nodes.retrieve_and_score_notes")
    @patch("generation.nodes.retrieve_few_shots")
    @patch("generation.nodes.generate_skill_bridging_map")
    @patch("generation.nodes.resolve_regional_strategy")
    @patch("generation.nodes.get_subject_info")
    def test_node_retriever_success(
        self,
        mock_get_subject_info,
        mock_resolve_strategy,
        mock_generate_bridge,
        mock_retrieve_few_shots,
        mock_retrieve_notes,
        mock_retrieve_patents,
        mock_retrieve_projects,
        mock_retrieve_education,
        mock_retrieve_experiences,
        mock_get_model,
        mock_get_wiki_dir,
        mock_get_compact_skills,
        mock_retrieve_languages,
    ):
        """Test node_retriever pulls and formats all relevant files."""
        mock_get_wiki_dir.return_value = Path("mock-wiki")
        mock_get_model.return_value = MagicMock()

        mock_retrieve_experiences.return_value = (
            ["exp1", "exp2"],
            ["intel-corporation"],
        )
        mock_retrieve_education.return_value = ["edu1"]
        mock_retrieve_projects.return_value = ["proj1"]
        mock_retrieve_patents.return_value = ["pat1"]
        mock_retrieve_notes.return_value = ["note1"]
        mock_retrieve_few_shots.return_value = ["shot1"]
        mock_generate_bridge.return_value = {"python": "advanced python"}
        mock_resolve_strategy.return_value = (
            "strategy detail text",
            "pdf-template-path",
        )
        mock_get_subject_info.return_value = "Name: John Doe\nEmail: john@doe.com"

        mock_get_compact_skills.return_value = ["skill1"]
        mock_retrieve_languages.return_value = ["English (Fluent)"]

        if True:
            state: CVPipelineState = {
                "job_description": "JD",
                "target_persona": "Persona",
                "target_locations": ["London"],
                "cv_expectations": "Standard",
                "primary_keywords": ["python"],
                "target_region": "us",
                "selected_entries": [],
                "education_entries": [],
                "skills_entries": [],
                "strategy_info": "",
                "pdf_template": "",
                "draft_cv": "",
                "audit_feedback": "",
                "refiner_feedback": "",
                "iteration_count": 0,
                "strategy_override": "",
                "projects_entries": [],
                "patents_entries": [],
                "notes_entries": [],
                "few_shot_examples": [],
                "skill_bridging_map": {},
                "target_organization_slug": "",
                "target_role": "",
                "strategy_metadata": cast(Any, {}),
                "languages_entries": [],
            }

            result = node_retriever(state)
            self.assertEqual(result["selected_entries"], ["exp1", "exp2"])
            self.assertEqual(result["education_entries"], ["edu1"])
            self.assertEqual(result["projects_entries"], ["proj1"])
            self.assertEqual(result["patents_entries"], ["pat1"])
            self.assertEqual(result["notes_entries"], ["note1"])
            self.assertEqual(result["few_shot_examples"], ["shot1"])
            self.assertEqual(
                result["skill_bridging_map"], {"python": "advanced python"}
            )
            self.assertEqual(result["pdf_template"], "pdf-template-path")
            self.assertIn("Name: John Doe", result["strategy_info"])
            self.assertIn("strategy detail text", result["strategy_info"])

    @patch("generation.nodes.get_model_for_step")
    @patch("generation.nodes.load_prompt")
    @patch("generation.nodes.invoke_drafter_llm_with_fallback")
    @patch("generation.nodes.parse_and_sort_chronological_entries")
    def test_node_drafter_success(
        self,
        mock_sort_entries,
        mock_invoke_fallback,
        mock_load_prompt,
        mock_get_model,
    ):
        """Test node_drafter invokes LLM with formatted prompts and returns drafted CV."""
        mock_get_model.return_value = MagicMock()
        mock_load_prompt.side_effect = [
            "system instructions",
            "user {job_description} {feedback_instruction} {strategy_info} {skill_bridge_text} {few_shots_text} {chronological_entries_text} {projects_text} {patents_text} {notes_text} {education_text} {skills_text}",
        ]

        mock_sort_entries.return_value = "Sorted experiences list"
        mock_invoke_fallback.return_value = AIMessage(content="DRAFTED_RESUME_CONTENT")

        state: CVPipelineState = {
            "job_description": "Python dev",
            "target_persona": "Persona",
            "target_locations": ["London"],
            "cv_expectations": "Standard",
            "primary_keywords": ["python"],
            "target_region": "us",
            "selected_entries": ["exp1"],
            "education_entries": ["edu1"],
            "skills_entries": ["skill1"],
            "strategy_info": "Strategy info",
            "pdf_template": "",
            "draft_cv": "",
            "audit_feedback": "Audit fix list",
            "refiner_feedback": "Compress length",
            "iteration_count": 0,
            "strategy_override": "",
            "projects_entries": ["proj1"],
            "patents_entries": ["pat1"],
            "notes_entries": ["note1"],
            "few_shot_examples": ["shot1"],
            "skill_bridging_map": {"python": "expert"},
            "target_organization_slug": "",
            "target_role": "",
            "strategy_metadata": cast(Any, {}),
            "languages_entries": [],
        }

        result = node_drafter(state)
        self.assertEqual(result["draft_cv"], "DRAFTED_RESUME_CONTENT")

    def test_node_refiner_long(self):
        """Test node_refiner sets feedback when CV is too long."""
        state: CVPipelineState = {
            "job_description": "",
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
            "draft_cv": "A" * 9000,  # Too long (> 8500 chars)
            "audit_feedback": "",
            "refiner_feedback": "",
            "iteration_count": 0,
            "strategy_override": "",
            "projects_entries": [],
            "patents_entries": [],
            "notes_entries": [],
            "few_shot_examples": [],
            "skill_bridging_map": {},
            "target_organization_slug": "",
            "target_role": "",
            "strategy_metadata": cast(Any, {}),
            "languages_entries": [],
        }

        result = node_refiner(state)
        self.assertIn("DENSITY ERROR: The CV is too long", result["refiner_feedback"])

    def test_node_refiner_short(self):
        """Test node_refiner returns empty feedback when CV length is acceptable."""
        state: CVPipelineState = {
            "job_description": "",
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
            "draft_cv": "A" * 5000,  # Acceptable length (< 8500 chars)
            "audit_feedback": "",
            "refiner_feedback": "",
            "iteration_count": 0,
            "strategy_override": "",
            "projects_entries": [],
            "patents_entries": [],
            "notes_entries": [],
            "few_shot_examples": [],
            "skill_bridging_map": {},
            "target_organization_slug": "",
            "target_role": "",
            "strategy_metadata": cast(Any, {}),
            "languages_entries": [],
        }

        result = node_refiner(state)
        self.assertEqual(result["refiner_feedback"], "")

    @patch("generation.nodes.get_model_for_step")
    @patch("generation.nodes.load_prompt")
    def test_node_auditor_success(self, mock_load_prompt, mock_get_model):
        """Test node_auditor invokes audit LLM and increments iteration count."""
        mock_load_prompt.return_value = "auditor template {job_description} {draft_cv}"
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="AUDIT FEEDBACK TEXT")
        mock_get_model.return_value = mock_llm

        state: CVPipelineState = {
            "job_description": "JD",
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
            "draft_cv": "DRAFT",
            "audit_feedback": "",
            "refiner_feedback": "",
            "iteration_count": 1,
            "strategy_override": "",
            "projects_entries": [],
            "patents_entries": [],
            "notes_entries": [],
            "few_shot_examples": [],
            "skill_bridging_map": {},
            "target_organization_slug": "",
            "target_role": "",
            "strategy_metadata": cast(Any, {}),
            "languages_entries": [],
        }

        result = node_auditor(state)
        self.assertEqual(result["audit_feedback"], "AUDIT FEEDBACK TEXT")
        self.assertEqual(result["iteration_count"], 2)


if __name__ == "__main__":
    unittest.main()
