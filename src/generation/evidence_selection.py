"""Marginal coverage optimization engine for evidence selection in CareerOS."""

import logging
import uuid

from generation.state import EvidenceItem, JobRequirement, SelectionConfig, SelectionManifest


def optimize_evidence_selection(
    requirements: list[JobRequirement],
    candidates: list[EvidenceItem],
    config: SelectionConfig | None = None,
) -> SelectionManifest:
    """Greedy knapsack optimization maximizing marginal requirement coverage within word budget constraints."""
    if config is None:
        config = SelectionConfig()

    run_id = f"sel_{uuid.uuid4().hex[:8]}"

    if not requirements or not candidates:
        logging.info("Empty requirements or candidates passed to evidence selection. Returning default manifest.")
        return SelectionManifest(
            run_id=run_id,
            content_budget_words=config.content_budget_words,
            requirements=requirements,
            excluded_evidence=candidates,
            selection_config=config,
        )

    selected: list[EvidenceItem] = []
    excluded: list[EvidenceItem] = []
    remaining_candidates = list(candidates)
    requirement_coverage_counts: dict[str, int] = {req.id: 0 for req in requirements}
    group_counts: dict[str, int] = {}
    current_words = 0

    while remaining_candidates and current_words < config.content_budget_words:
        best_item, best_utility, best_idx = _find_best_candidate(
            remaining_candidates,
            requirements,
            requirement_coverage_counts,
            group_counts,
            config,
        )

        if best_item is None or best_utility <= 0.05:
            # No candidate offers positive marginal utility
            break

        # Check if adding best_item exceeds budget
        if current_words + best_item.estimated_words > config.content_budget_words + 50 and selected:

            best_item.selection_status = "excluded"
            best_item.exclusion_reason = f"Word budget reached ({current_words}/{config.content_budget_words} words)"
            excluded.append(best_item)
            remaining_candidates.pop(best_idx)
            continue

        # Accept best_item
        best_item.selection_status = "selected"
        best_item.selection_reason = f"Selected for marginal coverage utility {best_utility:.3f}"
        selected.append(best_item)
        remaining_candidates.pop(best_idx)

        current_words += best_item.estimated_words
        _update_coverage_state(best_item, requirement_coverage_counts, group_counts)

    # Process remaining unselected candidates
    for item in remaining_candidates:
        item.selection_status = "excluded"
        item.exclusion_reason = "Lower marginal coverage utility or budget limit"
        excluded.append(item)

    uncovered = [req for req in requirements if requirement_coverage_counts.get(req.id, 0) == 0]
    coverage_summary = _compute_coverage_summary(requirements, requirement_coverage_counts)

    return SelectionManifest(
        run_id=run_id,
        content_budget_words=config.content_budget_words,
        estimated_selected_words=current_words,
        requirements=requirements,
        selected_evidence=selected,
        uncovered_requirements=uncovered,
        excluded_evidence=excluded,
        coverage_summary=coverage_summary,
        selection_config=config,
    )


def _find_best_candidate(
    candidates: list[EvidenceItem],
    requirements: list[JobRequirement],
    requirement_coverage_counts: dict[str, int],
    group_counts: dict[str, int],
    config: SelectionConfig,
) -> tuple[EvidenceItem | None, float, int]:
    """Identify candidate offering highest marginal utility density."""
    best_item: EvidenceItem | None = None
    best_utility = -1.0
    best_idx = -1

    for idx, item in enumerate(candidates):
        utility = calculate_marginal_utility(
            item,
            requirements,
            requirement_coverage_counts,
            group_counts,
            config,
        )
        words_denom = max(15, item.estimated_words)
        utility_density = utility / (words_denom / 25.0)  # normalized by 25-word chunk

        if utility_density > best_utility:
            best_utility = utility_density
            best_item = item
            best_idx = idx

    return best_item, best_utility, best_idx


def calculate_marginal_utility(
    item: EvidenceItem,
    requirements: list[JobRequirement],
    requirement_coverage_counts: dict[str, int],
    group_counts: dict[str, int],
    config: SelectionConfig,
) -> float:
    """Calculate marginal utility U(e | S) = alpha*DeltaCoverage + beta*Quality + gamma*RoleScore - RedundancyPenalty."""
    req_map = {req.id: req for req in requirements}
    marginal_coverage = 0.0

    for support in item.supports:
        req = req_map.get(support.requirement_id)
        if not req:
            continue
        curr_count = requirement_coverage_counts.get(req.id, 0)
        diminishing_factor = 1.0 if curr_count == 0 else (0.4 if curr_count == 1 else 0.1)
        marginal_coverage += support.relevance_score * req.weight * diminishing_factor

    quality_score = item.impact_assessment
    role_score = item.existing_role_score

    # Redundancy penalty if group already represented
    prev_group_count = group_counts.get(item.redundancy_group, 0)
    penalty = 0.0
    if prev_group_count > 0 and item.redundancy_group != "general":
        penalty = config.redundancy_penalty_multiplier * (0.25 * prev_group_count)

    utility = (
        config.alpha_marginal_coverage * marginal_coverage
        + config.beta_evidence_quality * quality_score
        + config.gamma_role_calibration * role_score
        - penalty
    )
    return max(0.0, utility)


def _update_coverage_state(
    item: EvidenceItem,
    requirement_coverage_counts: dict[str, int],
    group_counts: dict[str, int],
) -> None:
    """Update requirement coverage counts and group counts after selecting an item."""
    for support in item.supports:
        req_id = support.requirement_id
        requirement_coverage_counts[req_id] = requirement_coverage_counts.get(req_id, 0) + 1

    if item.redundancy_group:
        group_counts[item.redundancy_group] = group_counts.get(item.redundancy_group, 0) + 1


def _compute_coverage_summary(
    requirements: list[JobRequirement],
    requirement_coverage_counts: dict[str, int],
) -> dict[str, float]:
    """Compute overall requirement coverage percentages."""
    total_reqs = len(requirements)
    if total_reqs == 0:
        return {"total_coverage": 1.0, "essential_coverage": 1.0}

    covered_count = sum(1 for req in requirements if requirement_coverage_counts.get(req.id, 0) > 0)

    essential_reqs = [req for req in requirements if req.priority == "essential"]
    covered_essential = sum(1 for req in essential_reqs if requirement_coverage_counts.get(req.id, 0) > 0)
    essential_ratio = (covered_essential / len(essential_reqs)) if essential_reqs else 1.0

    return {
        "total_coverage": round(covered_count / total_reqs, 3),
        "essential_coverage": round(essential_ratio, 3),
        "covered_requirements_count": covered_count,
        "total_requirements_count": total_reqs,
    }
