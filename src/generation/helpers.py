"""Helper functions for the CV generation pipeline.

This module acts as a unified facade, re-exporting routines decomposed into:
- formatting: JSON parsing, LLM invocations, and text rendering.
- retrieval: Knowledge base entity loading, education, projects, and strategy retrieval.
- grouping: Multi-tenure grouping, company role consolidation, and date normalization.
- pruning: Scoring, deduplication, achievement filtering, and weight calculations.
"""

import json
import logging
import re
from typing import Any
from langchain_core.messages import HumanMessage
from schemas.cv_models import StructuredCVDocument
from generation.state import CVPipelineState
from kb_config import (
    get_fallback_model_for_step,
    get_model_for_step,
    get_strategy_default,
    get_wiki_dir,
)

# Re-export formatting routines
from generation.formatting import (
    BRACKET_LINK_PATTERN,
    _clean_json_comments_and_commas as _clean_json_comments_and_commas,
    _escape_control_chars_in_strings as _escape_control_chars_in_strings,
    _extract_json_block as _extract_json_block,
    _parse_start_date as _parse_start_date,
    check_typesetting_budget,
    compress_experience_llm,
    compress_experience_to_one_liner_llm,
    compress_grouped_experience_llm,
    handle_interactive_audit,
    invoke_drafter_llm_with_fallback,
    invoke_structured_llm,
    llm_text,
    load_prompt,
    parse_and_sort_chronological_entries,
    robust_json_loads,
    strip_wikilinks,
)

# Re-export retrieval routines
from generation.retrieval import (
    _parse_education_candidate as _parse_education_candidate,
    _parse_yaml_frontmatter_from_text as _parse_yaml_frontmatter_from_text,
    assemble_role_evidence_bundles,
    discover_available_strategies,
    generate_skill_bridging_map,
    get_subject_info,
    resolve_regional_strategy,
    resolve_track_strategy,
    retrieve_and_deduplicate_education,
    retrieve_and_score_case_studies,
    retrieve_and_score_notes,
    retrieve_and_score_patents,
    retrieve_and_score_projects,
    retrieve_company_entity,
    retrieve_few_shots,
    retrieve_languages,
    retrieve_voice_guide,
    score_by_keywords,
)

# Re-export grouping routines
from generation.grouping import (
    _build_combined_body as _build_combined_body,
    _consolidate_company_roles as _consolidate_company_roles,
    _detect_employment_type as _detect_employment_type,
    _extract_end_date_normalized as _extract_end_date_normalized,
    _extract_start_date_normalized as _extract_start_date_normalized,
    _extract_start_year as _extract_start_year,
    _get_org_slug as _get_org_slug,
    _group_old_experiences_by_company as _group_old_experiences_by_company,
    _is_old_role as _is_old_role,
    _is_parallel_startup_track as _is_parallel_startup_track,
    _split_recent_and_old_experiences as _split_recent_and_old_experiences,
)

# Re-export pruning and experience weighting routines
from generation.pruning import (
    _compress_and_wrap_experiences as _compress_and_wrap_experiences,
    _compress_and_wrap_single_experience as _compress_and_wrap_single_experience,
    _deduplicate_scored_experiences as _deduplicate_scored_experiences,
    _extract_and_clean_achievements as _extract_and_clean_achievements,
    _get_experience_key as _get_experience_key,
    _prune_recent_frontmatter as _prune_recent_frontmatter,
    _score_experiences_list as _score_experiences_list,
    _score_single_experience as _score_single_experience,
    _select_top_achievements as _select_top_achievements,
    calculate_experience_weight,
    prune_recent_experience,
    retrieve_and_score_experiences,
)

logger = logging.getLogger(__name__)


def _slugify_org_name(name: str) -> str:
    """Convert an organization name into a kebab-case slug."""
    cleaned = re.sub(r"[^a-z0-9\s\-]", "", name.strip().lower())
    return re.sub(r"[\s_]+", "-", cleaned).strip("-")


def _resolve_target_employer_slug(data: dict[str, Any]) -> tuple[str, str, str, str]:
    """Extract posting_organization_type, agency name, employer name, and safe employer slug."""
    org_type = str(data.get("posting_organization_type") or "direct_employer").strip().lower()
    if org_type not in {"direct_employer", "recruitment_agency", "confidential_client"}:
        org_type = "direct_employer"

    agency_name = str(data.get("recruitment_agency_name") or "").strip()
    employer_name = str(data.get("target_employer_name") or "").strip()
    raw_slug = str(data.get("target_organization_slug") or "unknown-company").strip().lower()

    agency_slug = _slugify_org_name(agency_name) if agency_name else ""
    if org_type in {"recruitment_agency", "confidential_client"}:
        if agency_slug and raw_slug == agency_slug:
            raw_slug = _slugify_org_name(employer_name) if employer_name else "confidential-employer"
        elif not raw_slug or raw_slug == "unknown-company":
            raw_slug = _slugify_org_name(employer_name) if employer_name else "confidential-employer"

    return org_type, agency_name, employer_name, raw_slug or "unknown-company"


def _resolve_compressor_input(state: CVPipelineState, draft: str) -> str:
    """Format structured CV JSON or raw draft as input payload for compressor prompt."""
    structured = state.get("structured_cv")
    if structured and isinstance(structured, dict):
        return json.dumps(structured, indent=2)
    return draft


def _resolve_compressed_cv_doc(
    llm: Any, prompt: str, state: CVPipelineState, max_pages: int
) -> StructuredCVDocument:
    """Invoke structured LLM to compress StructuredCVDocument, failing fast on error."""
    _ = max_pages
    res = invoke_structured_llm(llm, StructuredCVDocument, [HumanMessage(content=prompt)])
    if isinstance(res, StructuredCVDocument):
        return res
    if isinstance(res, dict):
        return StructuredCVDocument.model_validate(res)
    raise ValueError(f"Compressor LLM returned unexpected non-StructuredCVDocument output: {type(res).__name__}")


__all__ = [
    "BRACKET_LINK_PATTERN",
    "llm_text",
    "strip_wikilinks",
    "robust_json_loads",
    "load_prompt",
    "score_by_keywords",
    "compress_experience_llm",
    "compress_experience_to_one_liner_llm",
    "compress_grouped_experience_llm",
    "parse_and_sort_chronological_entries",
    "invoke_drafter_llm_with_fallback",
    "get_subject_info",
    "discover_available_strategies",
    "resolve_regional_strategy",
    "resolve_track_strategy",
    "generate_skill_bridging_map",
    "retrieve_and_deduplicate_education",
    "retrieve_and_score_projects",
    "retrieve_and_score_patents",
    "retrieve_and_score_notes",
    "retrieve_and_score_case_studies",
    "retrieve_few_shots",
    "retrieve_languages",
    "calculate_experience_weight",
    "prune_recent_experience",
    "retrieve_and_score_experiences",
    "get_model_for_step",
    "get_fallback_model_for_step",
    "get_wiki_dir",
    "get_strategy_default",
    "check_typesetting_budget",
    "handle_interactive_audit",
    "invoke_structured_llm",
    "assemble_role_evidence_bundles",
    "retrieve_company_entity",
    "retrieve_voice_guide",
    "_slugify_org_name",
    "_resolve_target_employer_slug",
    "_resolve_compressor_input",
    "_resolve_compressed_cv_doc",
]
