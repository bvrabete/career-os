"""LangGraph pipeline nodes for Coverage-Aware Evidence Selection."""

import logging
from typing import Any

from generation.evidence_mapping import (
    assign_redundancy_groups,
    compute_requirement_supports,
    extract_candidate_evidence_items,
    extract_requirements_from_jd,
)
from generation.evidence_selection import optimize_evidence_selection
from generation.state import CVPipelineState, EvidenceItem, JobRequirement, SelectionConfig
from kb_config import get_coverage_selection_config


def node_requirement_mapper(state: CVPipelineState) -> dict[str, Any]:
    """Node: Extract job requirements from JD and normalize retrieved assets into EvidenceItem records."""
    logging.info("--- NODE S1: REQUIREMENT MAPPER ---")
    jd = str(state.get("job_description") or "")
    persona = str(state.get("target_persona") or "")

    # Extract requirements
    req_models = extract_requirements_from_jd(jd, persona)
    req_dicts = [req.model_dump() for req in req_models]

    # Normalize candidates
    experiences_raw = state.get("selected_entries") or []
    # If selected_entries are raw markdown strings or dicts, handle normalizer input:
    exp_dicts: list[dict[str, Any]] = []
    for entry in experiences_raw:
        if isinstance(entry, dict):
            exp_dicts.append(entry)
        elif isinstance(entry, str):
            exp_dicts.append({"role": "Experience", "achievements": [entry]})

    projects_raw = state.get("projects_entries") or []
    patents_raw = state.get("patents_entries") or []

    proj_dicts = [p if isinstance(p, dict) else {"title": "Project", "description": str(p)} for p in projects_raw]
    pat_dicts = [p if isinstance(p, dict) else {"title": "Patent", "abstract": str(p)} for p in patents_raw]

    candidates = extract_candidate_evidence_items(
        experiences_raw=exp_dicts,
        projects_raw=proj_dicts,
        patents_raw=pat_dicts,
    )

    # Compute supports and redundancy groups
    compute_requirement_supports(req_models, candidates)
    assign_redundancy_groups(candidates)

    candidate_dicts = [item.model_dump() for item in candidates]
    logging.info(f"Requirement Mapper: Extracted {len(req_models)} requirements and {len(candidates)} candidate items.")

    return {
        "requirements": req_dicts,
        "candidate_evidence": candidate_dicts,
    }


def node_evidence_selector(state: CVPipelineState) -> dict[str, Any]:
    """Node: Optimize marginal coverage, generate SelectionManifest, and prepare tailored evidence text for Drafter."""
    logging.info("--- NODE S2: EVIDENCE SELECTOR ---")
    req_dicts = state.get("requirements") or []
    cand_dicts = state.get("candidate_evidence") or []

    req_models = [JobRequirement.model_validate(r) for r in req_dicts if isinstance(r, dict)]
    cand_models = [EvidenceItem.model_validate(c) for c in cand_dicts if isinstance(c, dict)]

    raw_config = get_coverage_selection_config()
    selection_config = SelectionConfig(
        target_page_budget=int(raw_config.get("TARGET_PAGE_BUDGET", 2)),
        content_budget_words=int(raw_config.get("CONTENT_BUDGET_WORDS", 700)),
        alpha_marginal_coverage=float(raw_config.get("ALPHA_MARGINAL_COVERAGE", 0.50)),
        beta_evidence_quality=float(raw_config.get("BETA_EVIDENCE_QUALITY", 0.30)),
        gamma_role_calibration=float(raw_config.get("GAMMA_ROLE_CALIBRATION", 0.20)),
        redundancy_penalty_multiplier=float(raw_config.get("REDUNDANCY_PENALTY", 0.60)),
        min_essential_coverage_ratio=float(raw_config.get("MIN_ESSENTIAL_COVERAGE", 0.85)),
    )

    manifest = optimize_evidence_selection(req_models, cand_models, selection_config)
    manifest_dict = manifest.model_dump()

    logging.info(
        f"Evidence Selector: Selected {len(manifest.selected_evidence)} items "
        f"({manifest.estimated_selected_words} words). "
        f"Total coverage: {manifest.coverage_summary.get('total_coverage', 0):.1%}"
    )

    return {
        "selection_manifest": manifest_dict,
    }
