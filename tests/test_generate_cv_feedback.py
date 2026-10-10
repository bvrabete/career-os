"""Tests for node feedback logging in generate_cv."""

import unittest
from unittest.mock import patch

from generate_cv import _print_node_feedback


class TestGenerateCVFeedback(unittest.TestCase):
    """Test suite for _print_node_feedback in generate_cv."""

    def test_analyzer_feedback(self) -> None:
        state = {
            "target_role": "Staff Engineer",
            "target_organization_slug": "acme-corp",
            "target_region": "us",
            "target_track": "staff-principal",
        }
        with patch("generate_cv.logger.info") as mock_info:
            _print_node_feedback("analyzer", state)
            mock_info.assert_called_once()
            args = mock_info.call_args[0]
            self.assertIn("Staff Engineer", args)
            self.assertIn("acme-corp", args)

    def test_retriever_feedback_with_selected_entries(self) -> None:
        state = {
            "selected_entries": ["exp1", "exp2", "exp3"],
            "skills_entries": ["skill1", "skill2"],
        }
        with patch("generate_cv.logger.info") as mock_info:
            _print_node_feedback("retriever", state)
            mock_info.assert_called_once()
            args = mock_info.call_args[0]
            self.assertIn(3, args)
            self.assertIn(2, args)

    def test_retriever_feedback_with_fallback_key(self) -> None:
        state = {
            "retrieved_experiences": ["exp1", "exp2"],
            "skills_entries": ["skill1"],
        }
        with patch("generate_cv.logger.info") as mock_info:
            _print_node_feedback("retriever", state)
            mock_info.assert_called_once()
            args = mock_info.call_args[0]
            self.assertIn(2, args)
            self.assertIn(1, args)

    def test_retriever_feedback_empty_state(self) -> None:
        state: dict[str, list[str]] = {}
        with patch("generate_cv.logger.info") as mock_info:
            _print_node_feedback("retriever", state)
            mock_info.assert_called_once()
            args = mock_info.call_args[0]
            self.assertIn(0, args)

    def test_drafter_feedback(self) -> None:
        state = {"draft_cv": "Hello world CV content"}
        with patch("generate_cv.logger.info") as mock_info:
            _print_node_feedback("drafter", state)
            mock_info.assert_called_once()
            args = mock_info.call_args[0]
            self.assertIn(len("Hello world CV content"), args)

    def test_refiner_feedback(self) -> None:
        state_ok = {"refiner_feedback": ""}
        with patch("generate_cv.logger.info") as mock_info:
            _print_node_feedback("refiner", state_ok)
            mock_info.assert_called_once_with("  📐 [Refiner Guard] %s", "Page budget OK")

        state_exceeded = {"refiner_feedback": "Exceeded by 50 lines"}
        with patch("generate_cv.logger.info") as mock_info:
            _print_node_feedback("refiner", state_exceeded)
            mock_info.assert_called_once_with(
                "  📐 [Refiner Guard] %s", "Page budget exceeded -> routing to compressor"
            )

    def test_compressor_feedback(self) -> None:
        state = {"compression_count": 2}
        with patch("generate_cv.logger.info") as mock_info:
            _print_node_feedback("compressor", state)
            mock_info.assert_called_once()
            args = mock_info.call_args[0]
            self.assertIn(2, args)

    def test_auditor_feedback_pass(self) -> None:
        state = {
            "ats_scorecard": {"total_score": 92},
            "audit_feedback": "PASS - Great fit",
            "iteration_count": 1,
        }
        with patch("generate_cv.logger.info") as mock_info:
            _print_node_feedback("auditor", state)
            mock_info.assert_called_once()
            args = mock_info.call_args[0]
            self.assertIn(92, args)
            self.assertIn("PASS", args)

    def test_auditor_feedback_rewrite(self) -> None:
        state = {
            "ats_scorecard": {"total_score": 65},
            "audit_feedback": "REWRITE - Missing keywords",
            "iteration_count": 1,
        }
        with patch("generate_cv.logger.info") as mock_info, \
             patch("generate_cv.logger.warning") as mock_warning:
            _print_node_feedback("auditor", state)
            mock_info.assert_called_once()
            mock_warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
