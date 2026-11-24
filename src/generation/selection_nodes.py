"""LangGraph pipeline nodes for Coverage-Aware Evidence Selection."""

import logging
from typing import Any

from generation.evidence_mapping import (
    assign_redundancy_groups,
    compute_requirement_supports,
    extract_candidate_evidence_items,
    extract_requirements_from_jd,
    parse_experience_entry_to_dict,
)
from generation.evidence_selection import optimize_evidence_selection
from generation.state import (
    CVPipelineState,
    EvidenceItem,
    JobRequirement,
    SelectionConfig,
    SynthesizedBullet,
    SynthesizedRole,
    TailoredLongDraft,
)
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
    exp_dicts: list[dict[str, Any]] = []
    for entry in experiences_raw:
        if isinstance(entry, dict):
            exp_dicts.append(entry)
        elif isinstance(entry, str):
            exp_dicts.append(parse_experience_entry_to_dict(entry))

    projects_raw = state.get("projects_entries") or []
    patents_raw = state.get("patents_entries") or []
    case_studies_raw = state.get("case_studies_entries") or []
    notes_raw = state.get("notes_entries") or []

    proj_dicts = [p if isinstance(p, dict) else {"title": "Project", "description": str(p)} for p in projects_raw]
    pat_dicts = [p if isinstance(p, dict) else {"title": "Patent", "abstract": str(p)} for p in patents_raw]
    cs_dicts = [c if isinstance(c, dict) else {"title": "Case Study", "summary": str(c)} for c in case_studies_raw]
    note_dicts = [n if isinstance(n, dict) else {"title": "Note", "text": str(n)} for n in notes_raw]

    candidates = extract_candidate_evidence_items(
        experiences_raw=exp_dicts,
        projects_raw=proj_dicts,
        patents_raw=pat_dicts,
        case_studies_raw=cs_dicts,
        notes_raw=note_dicts,
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


def _build_tailored_long_draft(
    state: CVPipelineState,
    selected_items: list[EvidenceItem],
) -> dict[str, Any]:
    """Assemble a structured TailoredLongDraft grouping selected evidence by role/source."""
    grouped: dict[str, list[SynthesizedBullet]] = {}
    for item in selected_items:
        role_key = item.role_or_project or "Experience"
        grouped.setdefault(role_key, []).append(
            SynthesizedBullet(
                text=item.text,
                covered_requirement_ids=[s.requirement_id for s in item.supports],
                source_refs=[item.source_ref],
            )
        )

    roles = [
        SynthesizedRole(
            role_slug=role_name.lower().replace(" ", "-"),
            title=role_name,
            organization="",
            bullets=achs,
        )
        for role_name, achs in grouped.items()
    ]
    long_draft = TailoredLongDraft(
        hiring_thesis=str(state.get("target_persona") or ""),
        executive_summary_draft=str(state.get("target_persona") or ""),
        synthesized_roles=roles,
        standalone_projects=[i.text for i in selected_items if i.source_type == "project"][:5],
        standalone_patents_publications=[i.text for i in selected_items if i.source_type == "patent"][:5],
    )
    return long_draft.model_dump()


def node_evidence_selector(state: CVPipelineState) -> dict[str, Any]:
    """Node: Optimize marginal coverage, generate SelectionManifest, and prepare TailoredLongDraft for Drafter."""
    logging.info("--- NODE S2: EVIDENCE SELECTOR ---")
    req_dicts = state.get("requirements") or []
    cand_dicts = state.get("candidate_evidence") or []

    req_models = [JobRequirement.model_validate(r) for r in req_dicts if isinstance(r, dict)]
    cand_models = [EvidenceItem.model_validate(c) for c in cand_dicts if isinstance(c, dict)]

    raw_config = get_coverage_selection_config()
    strategy_meta = state.get("strategy_metadata")
    page_budget = int(getattr(strategy_meta, "max_pages", raw_config.get("TARGET_PAGE_BUDGET", 2)) or 2)
    default_words = 380 if page_budget == 1 else (1150 if page_budget >= 3 else 700)
    content_budget = int(raw_config.get("CONTENT_BUDGET_WORDS", default_words))
    if page_budget == 1 and content_budget > 500:
        content_budget = 380
    elif page_budget >= 3 and content_budget < 900:
        content_budget = 1150

    selection_config = SelectionConfig(
        target_page_budget=max(1, min(3, page_budget)),
        content_budget_words=content_budget,
        alpha_marginal_coverage=float(raw_config.get("ALPHA_MARGINAL_COVERAGE", 0.50)),
        beta_evidence_quality=float(raw_config.get("BETA_EVIDENCE_QUALITY", 0.30)),
        gamma_role_calibration=float(raw_config.get("GAMMA_ROLE_CALIBRATION", 0.20)),
        redundancy_penalty_multiplier=float(raw_config.get("REDUNDANCY_PENALTY", 0.60)),
        min_essential_coverage_ratio=float(raw_config.get("MIN_ESSENTIAL_COVERAGE", 0.85)),
    )

    manifest = optimize_evidence_selection(req_models, cand_models, selection_config)
    manifest_dict = manifest.model_dump()
    long_draft_dict = _build_tailored_long_draft(state, manifest.selected_evidence)

    logging.info(
        f"Evidence Selector: Selected {len(manifest.selected_evidence)} items "
        f"({manifest.estimated_selected_words} words). "
        f"Total coverage: {manifest.coverage_summary.get('total_coverage', 0):.1%}"
    )

    return {
        "selection_manifest": manifest_dict,
        "long_draft": long_draft_dict,
    }
