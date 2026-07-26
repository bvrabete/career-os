"""Additional unit tests to boost coverage in src/generation/state.py and src/generation/nodes.py."""

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
from langchain_core.messages import AIMessage
from generation.state import RegionalStrategy, CVPipelineState
from generation.nodes import node_drafter, node_refiner, node_auditor


class TestGenerationAdditional(unittest.TestCase):
    """Test suite covering edge cases and error handling paths in generation state and nodes."""

    def test_regional_strategy_from_markdown_plain_text(self):
        """Test from_markdown with plain text containing no frontmatter."""
        text = "This is a plain regional strategy with no metadata."
        strategy = RegionalStrategy.from_markdown(text)
        self.assertEqual(strategy.body, text)
        self.assertEqual(strategy.region, [])
        self.assertEqual(strategy.max_pages, 2)

    def test_regional_strategy_from_markdown_invalid_yaml(self):
        """Test from_markdown when frontmatter YAML safe_load throws an exception."""
        text = "---\nregion: [unclosed list\n---\nBody content"
        strategy = RegionalStrategy.from_markdown(text)
        self.assertEqual(strategy.body, "Body content")
        self.assertEqual(strategy.region, [])

    def test_regional_strategy_from_markdown_string_lists(self):
        """Test from_markdown when region or focus are strings instead of lists."""
        text = "---\nregion: US\nfocus: Engineering\nmax_pages: 3\n---\nBody"
        strategy = RegionalStrategy.from_markdown(text)
        self.assertEqual(strategy.region, ["US"])
        self.assertEqual(strategy.focus, ["Engineering"])
        self.assertEqual(strategy.max_pages, 3)

    def test_regional_strategy_from_markdown_invalid_max_pages(self):
        """Test from_markdown when max_pages is not integer-coercible."""
        text = "---\nmax_pages: invalid-pages-value\n---\nBody"
        strategy = RegionalStrategy.from_markdown(text)
        self.assertEqual(strategy.max_pages, 2)

    def test_node_drafter_with_languages(self):
        """Test node_drafter when languages_entries is populated to cover the Spoken Languages branch."""
        state: CVPipelineState = {
            "job_description": "We need a software developer.",
            "target_persona": "Senior Developer",
            "target_region": "eu",
            "target_locations": [],
            "cv_expectations": "",
            "primary_keywords": [],
            "selected_entries": ["experience_1"],
            "education_entries": ["Edu 1"],
            "skills_entries": ["Python", "Docker"],
            "strategy_info": "Standard Strategy",
            "pdf_template": "",
            "draft_cv": "",
            "audit_feedback": "Check formatting",
            "refiner_feedback": "Slightly long",
            "iteration_count": 0,
            "strategy_override": "",
            "projects_entries": ["Proj 1"],
            "patents_entries": ["Pat 1"],
            "notes_entries": ["Note 1"],
            "few_shot_examples": ["Shot 1"],
            "skill_bridging_map": {"AWS": "Azure"},
            "target_organization_slug": "tech-corp",
            "target_role": "Developer",
            "strategy_metadata": RegionalStrategy(),
            "languages_entries": ["English (Fluent)", "French (Conversational)"],
        }

        with patch("generation.nodes.get_model_for_step") as mock_get_model, \
             patch("generation.nodes.load_prompt") as mock_load_prompt, \
             patch("generation.nodes.parse_and_sort_chronological_entries") as mock_parse, \
             patch("generation.nodes.invoke_drafter_llm_with_fallback") as mock_invoke:
            
            mock_llm = MagicMock()
            mock_get_model.return_value = mock_llm
            mock_load_prompt.return_value = "System template with {job_description} {skills_text}"
            mock_parse.return_value = "Sorted experience entries"
            mock_invoke.return_value = AIMessage(content="Drafted CV Content")

            result = node_drafter(state)
            self.assertEqual(result["draft_cv"], "Drafted CV Content")

    def test_node_refiner_dynamic_character_limits(self):
        """Test node_refiner limits for different page strategies (1, 3, 4+ pages)."""
        base_state: CVPipelineState = {
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
            "draft_cv": "A" * 5000,  # 5000 chars (over 1 page budget 4500, under 2 page 8500)
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
            "strategy_metadata": RegionalStrategy(max_pages=1),
            "languages_entries": [],
        }

        # 1-page strategy over budget
        res_1_page = node_refiner(base_state)
        self.assertTrue("DENSITY ERROR" in res_1_page["refiner_feedback"])

        # 3-page strategy within budget
        state_3_page = base_state.copy()
        state_3_page["strategy_metadata"] = RegionalStrategy(max_pages=3)
        res_3_page = node_refiner(state_3_page)
        self.assertEqual(res_3_page["refiner_feedback"], "")

        # 4-page strategy within budget
        state_4_page = base_state.copy()
        state_4_page["draft_cv"] = "A" * 15000  # limit is 12500 + 4000 = 16500
        state_4_page["strategy_metadata"] = RegionalStrategy(max_pages=4)
        res_4_page = node_refiner(state_4_page)
        self.assertEqual(res_4_page["refiner_feedback"], "")

    def test_node_auditor_scorecard_parsing_variations(self):
        """Test node_auditor parsing with code blocks and structured scorecard details."""
        state: CVPipelineState = {
            "job_description": "Software engineer.",
            "target_persona": "Engineer",
            "target_region": "eu",
            "target_locations": [],
            "cv_expectations": "",
            "primary_keywords": [],
            "selected_entries": [],
            "education_entries": [],
            "skills_entries": ["Python"],
            "strategy_info": "",
            "pdf_template": "",
            "draft_cv": "Factual draft resume.",
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
            "strategy_metadata": RegionalStrategy(),
            "languages_entries": [],
        }

        # Test valid markdown-wrapped JSON feedback
        with patch("generation.nodes.get_model_for_step") as mock_get_model, \
             patch("generation.nodes.load_prompt") as mock_load_prompt:
            mock_llm = MagicMock()
            mock_get_model.return_value = mock_llm
            mock_load_prompt.return_value = "Auditor template"
            
            mock_response_content = (
                "```json\n"
                "{\n"
                '  "pass": true,\n'
                '  "ats_score": {\n'
                '    "total_score": 95,\n'
                '    "relevance": {"score": 90, "max": 100, "justification": "Highly relevant"}\n'
                "  },\n"
                '  "rewrite_checklist": []\n'
                "}\n"
                "```"
            )
            mock_llm.invoke.return_value = AIMessage(content=mock_response_content)

            res = node_auditor(state)
            self.assertEqual(res["audit_feedback"], "PASS")
            self.assertEqual(res["iteration_count"], 2)

        # Test fallback on invalid JSON format
        with patch("generation.nodes.get_model_for_step") as mock_get_model, \
             patch("generation.nodes.load_prompt") as mock_load_prompt:
            mock_llm = MagicMock()
            mock_get_model.return_value = mock_llm
            mock_load_prompt.return_value = "Auditor template"
            mock_llm.invoke.return_value = AIMessage(content="This is not a JSON string at all.")

            res = node_auditor(state)
            self.assertEqual(res["audit_feedback"], "This is not a JSON string at all.")


if __name__ == "__main__":
    unittest.main()
