"""Unit and integration tests for Coverage-Aware Evidence Selection."""

import unittest

from generation.evidence_mapping import (
    assign_redundancy_groups,
    compute_requirement_supports,
    extract_candidate_evidence_items,
)
from generation.evidence_selection import calculate_marginal_utility, optimize_evidence_selection
from generation.selection_nodes import node_evidence_selector, node_requirement_mapper
from generation.state import CVPipelineState, EvidenceItem, JobRequirement, RequirementSupport, SelectionConfig


class TestEvidenceSelection(unittest.TestCase):

    def setUp(self):
        self.config = SelectionConfig(
            target_page_budget=2,
            content_budget_words=200,
            alpha_marginal_coverage=0.50,
            beta_evidence_quality=0.30,
            gamma_role_calibration=0.20,
            redundancy_penalty_multiplier=0.60,
        )

        self.reqs = [
            JobRequirement(
                id="req-1",
                text="Architect AWS cloud infrastructure using Terraform and Kubernetes",
                category="system_architecture",
                priority="essential",
                weight=1.5,
                keywords=["AWS", "Terraform", "Kubernetes", "Cloud"],
            ),
            JobRequirement(
                id="req-2",
                text="Lead cross-functional engineering teams in agile environment",
                category="leadership_management",
                priority="important",
                weight=1.0,
                keywords=["Lead", "Managed", "Agile", "Team"],
            ),
        ]

    def test_evidence_normalization_and_support(self):
        exp_data = [
            {
                "title": "Principal Architect",
                "score": 0.9,
                "achievements": [
                    "Architected AWS multi-region cloud platform using Terraform and Kubernetes.",
                    "Led engineering team of 15 developers in agile sprints.",
                ],
            }
        ]
        items = extract_candidate_evidence_items(experiences_raw=exp_data)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].source_type, "experience")

        compute_requirement_supports(self.reqs, items)
        assign_redundancy_groups(items)

        self.assertGreater(len(items[0].supports), 0)
        self.assertEqual(items[0].supports[0].requirement_id, "req-1")
        self.assertEqual(items[0].redundancy_group, "cloud_aws")

    def test_marginal_utility_diminishing_returns(self):
        item1 = EvidenceItem(
            id="item-1",
            source_ref="exp:1",
            source_type="experience",
            role_or_project="Role 1",
            text="Architected AWS multi-region cloud platform using Terraform and Kubernetes.",
            existing_role_score=0.9,
            impact_assessment=0.8,
            estimated_words=20,
            supports=[
                RequirementSupport(
                    requirement_id="req-1",
                    relevance_score=0.9,
                    support_strength="primary",
                )
            ],
            redundancy_group="cloud_aws",
        )

        coverage_counts = {"req-1": 0}
        group_counts: dict[str, int] = {}

        # First selection utility
        u1 = calculate_marginal_utility(item1, self.reqs, coverage_counts, group_counts, self.config)
        self.assertGreater(u1, 0.5)

        # After selecting req-1 once, utility should diminish
        coverage_counts["req-1"] = 1
        group_counts["cloud_aws"] = 1

        u2 = calculate_marginal_utility(item1, self.reqs, coverage_counts, group_counts, self.config)
        self.assertLess(u2, u1)

    def test_greedy_knapsack_optimization(self):
        item1 = EvidenceItem(
            id="item-1",
            source_ref="exp:1",
            source_type="experience",
            role_or_project="Role 1",
            text="Architected AWS cloud infrastructure using Terraform and Kubernetes.",
            existing_role_score=0.9,
            impact_assessment=0.8,
            estimated_words=20,
            supports=[
                RequirementSupport(requirement_id="req-1", relevance_score=0.9, support_strength="primary")
            ],
            redundancy_group="cloud_aws",
        )
        item2 = EvidenceItem(
            id="item-2",
            source_ref="exp:2",
            source_type="experience",
            role_or_project="Role 1",
            text="Led team of 15 developers across agile sprints and delivered roadmap on time.",
            existing_role_score=0.8,
            impact_assessment=0.7,
            estimated_words=20,
            supports=[
                RequirementSupport(requirement_id="req-2", relevance_score=0.85, support_strength="primary")
            ],
            redundancy_group="leadership_team",
        )

        manifest = optimize_evidence_selection(self.reqs, [item1, item2], self.config)
        self.assertEqual(len(manifest.selected_evidence), 2)
        self.assertEqual(manifest.coverage_summary["total_coverage"], 1.0)
        self.assertEqual(manifest.coverage_summary["essential_coverage"], 1.0)

    def test_selection_nodes_state_flow(self):
        state: CVPipelineState = {
            "job_description": "We are seeking a Lead Cloud Architect with AWS, Terraform, and Agile experience.",
            "target_persona": "Executive Architect",
            "selected_entries": [
                "Architected AWS cloud platform with Terraform.",
                "Managed engineering team of 10 developers in agile environment.",
            ],
        }

        res_mapper = node_requirement_mapper(state)
        self.assertIn("requirements", res_mapper)
        self.assertIn("candidate_evidence", res_mapper)

        state["requirements"] = res_mapper.get("requirements")  # type: ignore[typeddict-item]
        state["candidate_evidence"] = res_mapper.get("candidate_evidence")  # type: ignore[typeddict-item]
        res_selector = node_evidence_selector(state)
        self.assertIn("selection_manifest", res_selector)
        manifest = res_selector["selection_manifest"]
        self.assertGreater(len(manifest["selected_evidence"]), 0)


if __name__ == "__main__":
    unittest.main()
