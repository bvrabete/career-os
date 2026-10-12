"""Unit tests for typesetting budget, refiner guard, and fast compressor."""
import unittest
from unittest.mock import MagicMock, patch

from generation.nodes import (
    check_typesetting_budget,
    node_refiner,
    node_compressor,
    node_auditor,
    _resolve_max_pages
)
from generation.state import CVPipelineState, RegionalStrategy


class TestTypesettingAndCompressor(unittest.TestCase):
    """Test suite for Phase 4 typesetting guard and compression."""

    def test_resolve_max_pages_from_metadata(self):
        strategy = RegionalStrategy(max_pages=1)
        state = CVPipelineState(strategy_metadata=strategy)
        self.assertEqual(_resolve_max_pages(state), 1)

    def test_resolve_max_pages_from_text_fallback(self):
        state = CVPipelineState(strategy_info="US Executive 1-page format")
        self.assertEqual(_resolve_max_pages(state), 1)

        state3 = CVPipelineState(strategy_info="Academic 3-page format")
        self.assertEqual(_resolve_max_pages(state3), 3)

        state_def = CVPipelineState(strategy_info="Standard")
        self.assertEqual(_resolve_max_pages(state_def), 2)

    def test_budget_within_limits(self):
        # 1-page: under 500 words and 20 bullets
        draft = "# John Doe\n\n- Bullet 1\n- Bullet 2\n" + ("word " * 200)
        is_over, feedback, words, bullets = check_typesetting_budget(draft, max_pages=1)
        self.assertFalse(is_over)
        self.assertEqual(feedback, "")
        self.assertEqual(bullets, 2)
        self.assertGreater(words, 200)

    def test_budget_word_overflow(self):
        draft = ("word " * 550) + "\n- Bullet 1"
        is_over, feedback, words, bullets = check_typesetting_budget(draft, max_pages=1)
        self.assertTrue(is_over)
        self.assertIn("DENSITY OVERFLOW", feedback)
        self.assertIn(f"Words: {words}/500", feedback)

    def test_budget_bullet_overflow(self):
        bullet_lines = "\n".join([f"- Bullet item {i}" for i in range(25)])
        draft = "# Summary\n" + bullet_lines
        is_over, feedback, words, bullets = check_typesetting_budget(draft, max_pages=1)
        self.assertTrue(is_over)
        self.assertIn("Bullet lines: 25/20", feedback)

    def test_node_refiner_guard(self):
        # Over budget draft
        draft = ("word " * 1200)
        state = CVPipelineState(
            draft_cv=draft,
            strategy_metadata=RegionalStrategy(max_pages=2)
        )
        res = node_refiner(state)
        res_dict = res.update if (hasattr(res, "update") and isinstance(res.update, dict)) else res
        self.assertTrue(bool(res_dict["refiner_feedback"]))
        self.assertIn("DENSITY OVERFLOW", res_dict["refiner_feedback"])

        # Under budget draft
        ok_draft = ("word " * 400)
        state_ok = CVPipelineState(
            draft_cv=ok_draft,
            strategy_metadata=RegionalStrategy(max_pages=2)
        )
        res_ok = node_refiner(state_ok)
        res_ok_dict = res_ok.update if (hasattr(res_ok, "update") and isinstance(res_ok.update, dict)) else res_ok
        self.assertEqual(res_ok_dict["refiner_feedback"], "")

    @patch("generation.nodes.get_model_for_step")
    def test_node_compressor(self, mock_get_model):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "```markdown\n# Compressed CV\n- Impact 1\n```"
        mock_llm.invoke.return_value = mock_response
        mock_get_model.return_value = mock_llm

        state = CVPipelineState(
            draft_cv="# Bloated CV\n" + ("word " * 1200),
            job_description="Target role: Principal Engineer",
            strategy_metadata=RegionalStrategy(max_pages=2),
            compression_count=0
        )
        result = node_compressor(state)
        res_dict = result.update if (hasattr(result, "update") and isinstance(result.update, dict)) else result
        self.assertEqual(res_dict["draft_cv"], "# Compressed CV\n- Impact 1")
        self.assertEqual(res_dict["compression_count"], 1)

    @patch("generation.nodes.get_model_for_step")
    def test_node_auditor_pass(self, mock_get_model):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"pass": true, "ats_score": {"total_score": 95}, "rewrite_checklist": []}'
        mock_llm.invoke.return_value = mock_response
        mock_get_model.return_value = mock_llm

        state = CVPipelineState(
            job_description="JD",
            draft_cv="# Draft",
            skills_entries=["Python"],
            strategy_info="emea",
            iteration_count=0
        )
        result = node_auditor(state)
        res_dict = result.update if (hasattr(result, "update") and isinstance(result.update, dict)) else result
        self.assertEqual(res_dict["audit_feedback"], "PASS")
        self.assertEqual(res_dict["ats_scorecard"]["total_score"], 95)
        self.assertEqual(res_dict["iteration_count"], 1)

    @patch("generation.nodes.get_model_for_step")
    def test_node_auditor_fail(self, mock_get_model):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"pass": false, "ats_score": {"total_score": 68}, "rewrite_checklist": ["Add metrics"]}'
        mock_llm.invoke.return_value = mock_response
        mock_get_model.return_value = mock_llm

        state = CVPipelineState(
            job_description="JD",
            draft_cv="# Draft",
            skills_entries=["Python"],
            strategy_info="emea",
            iteration_count=0,
            interactive=False
        )
        result = node_auditor(state)
        res_dict = result.update if (hasattr(result, "update") and isinstance(result.update, dict)) else result
        self.assertIn("REWRITE REQUIRED", res_dict["audit_feedback"])
        self.assertIn("Add metrics", res_dict["audit_feedback"])
        self.assertEqual(res_dict["ats_scorecard"]["total_score"], 68)


if __name__ == "__main__":
    unittest.main()
