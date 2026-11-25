"""Unit tests for typesetting budget, refiner guard, and fast compressor."""
from unittest.mock import MagicMock, patch
import pytest

from generation.nodes import (
    check_typesetting_budget,
    node_refiner,
    node_compressor,
    node_auditor,
    _resolve_max_pages
)
from generation.state import CVPipelineState, RegionalStrategy


class TestTypesettingAndCompressor:
    """Test suite for Phase 4 typesetting guard and compression."""

    def test_resolve_max_pages_from_metadata(self):
        strategy = RegionalStrategy(max_pages=1)
        state = CVPipelineState(strategy_metadata=strategy)
        assert _resolve_max_pages(state) == 1

    def test_resolve_max_pages_from_text_fallback(self):
        state = CVPipelineState(strategy_info="US Executive 1-page format")
        assert _resolve_max_pages(state) == 1

        state3 = CVPipelineState(strategy_info="Academic 3-page format")
        assert _resolve_max_pages(state3) == 3

        state_def = CVPipelineState(strategy_info="Standard")
        assert _resolve_max_pages(state_def) == 2

    def test_budget_within_limits(self):
        # 1-page: under 500 words and 20 bullets
        draft = "# John Doe\n\n- Bullet 1\n- Bullet 2\n" + ("word " * 200)
        is_over, feedback, words, bullets = check_typesetting_budget(draft, max_pages=1)
        assert not is_over
        assert feedback == ""
        assert bullets == 2
        assert words > 200

    def test_budget_word_overflow(self):
        draft = ("word " * 550) + "\n- Bullet 1"
        is_over, feedback, words, bullets = check_typesetting_budget(draft, max_pages=1)
        assert is_over
        assert "DENSITY OVERFLOW" in feedback
        assert f"Words: {words}/500" in feedback

    def test_budget_bullet_overflow(self):
        bullet_lines = "\n".join([f"- Bullet item {i}" for i in range(25)])
        draft = "# Summary\n" + bullet_lines
        is_over, feedback, words, bullets = check_typesetting_budget(draft, max_pages=1)
        assert is_over
        assert "Bullet lines: 25/20" in feedback

    def test_node_refiner_guard(self):
        # Over budget draft
        draft = ("word " * 1200)
        state = CVPipelineState(
            draft_cv=draft,
            strategy_metadata=RegionalStrategy(max_pages=2)
        )
        res = node_refiner(state)
        res_dict = res.update if (hasattr(res, "update") and isinstance(res.update, dict)) else res
        assert bool(res_dict["refiner_feedback"])
        assert "DENSITY OVERFLOW" in res_dict["refiner_feedback"]

        # Under budget draft
        ok_draft = ("word " * 400)
        state_ok = CVPipelineState(
            draft_cv=ok_draft,
            strategy_metadata=RegionalStrategy(max_pages=2)
        )
        res_ok = node_refiner(state_ok)
        res_ok_dict = res_ok.update if (hasattr(res_ok, "update") and isinstance(res_ok.update, dict)) else res_ok
        assert res_ok_dict["refiner_feedback"] == ""

    @patch("generation.nodes.get_model_for_step")
    def test_node_compressor(self, mock_get_model):
        from schemas.cv_models import CVRoleEntry, ContactHeader, StructuredCVDocument

        mock_llm = MagicMock()
        mock_response = MagicMock()
        doc = StructuredCVDocument(
            contact=ContactHeader(full_name="Candidate Name"),
            professional_summary="Compressed summary",
            experience_roles=[CVRoleEntry(title="Lead", organization="Acme", bullets=["Impact 1"])],
        )
        mock_response.content = doc.model_dump_json()
        mock_llm.invoke.return_value = mock_response
        mock_get_model.return_value = mock_llm

        state = CVPipelineState(
            draft_cv="# Bloated CV\n" + ("word " * 1200),
            job_description="Target role: Principal Engineer",
            strategy_metadata=RegionalStrategy(max_pages=2),
            compression_count=0,
        )
        result = node_compressor(state)
        res_dict = result.update if (hasattr(result, "update") and isinstance(result.update, dict)) else result
        assert "Impact 1" in res_dict["draft_cv"]
        assert res_dict["structured_cv"] is not None
        assert res_dict["compression_count"] == 1

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
        assert res_dict["audit_feedback"] == "PASS"
        assert res_dict["ats_scorecard"]["total_score"] == 95
        assert res_dict["iteration_count"] == 1

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
        assert "REWRITE REQUIRED" in res_dict["audit_feedback"]
        assert "Add metrics" in res_dict["audit_feedback"]
        assert res_dict["ats_scorecard"]["total_score"] == 68

    @patch("generation.nodes.get_model_for_step")
    def test_node_compressor_returns_typed_structured_cv(self, mock_get_model):
        from schemas.cv_models import ContactHeader, StructuredCVDocument

        mock_llm = MagicMock()
        doc = StructuredCVDocument(
            contact=ContactHeader(full_name="Jane Doe", email="jane@example.com"),
            professional_summary="Concise compressed executive summary.",
        )
        mock_response = MagicMock()
        mock_response.content = doc.model_dump_json()
        mock_llm.invoke.return_value = mock_response
        mock_structured_llm = MagicMock()
        mock_structured_llm.invoke.return_value = doc
        mock_llm.with_structured_output.return_value = mock_structured_llm
        mock_get_model.return_value = mock_llm

        state = CVPipelineState(
            draft_cv="# Jane Doe\n\n## Professional Summary\nLong summary...",
            job_description="Platform Engineer",
            target_region="emea",
            compression_count=0,
        )
        result = node_compressor(state)
        assert result["structured_cv"]["contact"]["full_name"] == "Jane Doe"
        assert "Concise compressed executive summary." in result["draft_cv"]
        assert "Summary of Compression" not in result["draft_cv"]
        assert result["compression_count"] == 1

    @patch("generation.nodes.get_model_for_step")
    def test_node_compressor_deterministic_fallback_when_llm_fails(self, mock_get_model):
        from schemas.cv_models import CVRoleEntry, ContactHeader, StructuredCVDocument

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("Compressor LLM failed")
        mock_structured_llm = MagicMock()
        mock_structured_llm.invoke.side_effect = RuntimeError("Compressor LLM failed")
        mock_llm.with_structured_output.return_value = mock_structured_llm
        mock_get_model.return_value = mock_llm

        base_doc = StructuredCVDocument(
            contact=ContactHeader(full_name="Jane Doe"),
            professional_summary="Summary",
            experience_roles=[
                CVRoleEntry(
                    title="Lead",
                    organization="Acme",
                    bullets=["Bullet 1", "Bullet 2", "Bullet 3", "Bullet 4", "Bullet 5", "Bullet 6"],
                )
            ],
        )

        state = CVPipelineState(
            draft_cv="# Jane Doe\n\nLong draft",
            structured_cv=base_doc.model_dump(),
            job_description="Platform Engineer",
            target_region="emea",
            compression_count=0,
            strategy_info="1 page",
        )
        with pytest.raises(RuntimeError, match="Compressor LLM failed"):
            node_compressor(state)
