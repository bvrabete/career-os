"""Helper functions for the CV generation pipeline.

This module acts as a unified facade, re-exporting routines decomposed into:
- formatting: JSON parsing, LLM invocations, and text rendering.
- retrieval: Knowledge base entity loading, education, projects, and strategy retrieval.
- grouping: Multi-tenure grouping, company role consolidation, and date normalization.
- pruning: Scoring, deduplication, achievement filtering, and weight calculations.
"""

from kb_config import (
    get_fallback_model_for_step,
    get_model_for_step,
    get_strategy_default,
    get_wiki_dir,
)

# Re-export formatting routines
from generation.formatting import (
    BRACKET_LINK_PATTERN,
    _clean_json_comments_and_commas,
    _escape_control_chars_in_strings,
    _extract_json_block,
    _parse_start_date,
    compress_experience_llm,
    compress_experience_to_one_liner_llm,
    compress_grouped_experience_llm,
    invoke_drafter_llm_with_fallback,
    llm_text,
    load_prompt,
    parse_and_sort_chronological_entries,
    robust_json_loads,
    strip_wikilinks,
)

# Re-export retrieval routines
from generation.retrieval import (
    _parse_education_candidate,
    _parse_yaml_frontmatter_from_text,
    generate_skill_bridging_map,
    get_subject_info,
    resolve_regional_strategy,
    retrieve_and_deduplicate_education,
    retrieve_and_score_notes,
    retrieve_and_score_patents,
    retrieve_and_score_projects,
    retrieve_few_shots,
    retrieve_languages,
    score_by_keywords,
)

# Re-export grouping routines
from generation.grouping import (
    _build_combined_body,
    _consolidate_company_roles,
    _detect_employment_type,
    _extract_end_date_normalized,
    _extract_start_date_normalized,
    _extract_start_year,
    _get_org_slug,
    _group_old_experiences_by_company,
    _is_old_role,
    _is_parallel_startup_track,
    _split_recent_and_old_experiences,
)

# Re-export pruning and experience weighting routines
from generation.pruning import (
    _compress_and_wrap_experiences,
    _compress_and_wrap_single_experience,
    _deduplicate_scored_experiences,
    _extract_and_clean_achievements,
    _get_experience_key,
    _prune_recent_frontmatter,
    _score_experiences_list,
    _score_single_experience,
    _select_top_achievements,
    calculate_experience_weight,
    prune_recent_experience,
    retrieve_and_score_experiences,
)

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
    "resolve_regional_strategy",
    "generate_skill_bridging_map",
    "retrieve_and_deduplicate_education",
    "retrieve_and_score_projects",
    "retrieve_and_score_patents",
    "retrieve_and_score_notes",
    "retrieve_few_shots",
    "retrieve_languages",
    "calculate_experience_weight",
    "prune_recent_experience",
    "retrieve_and_score_experiences",
    "get_model_for_step",
    "get_fallback_model_for_step",
    "get_wiki_dir",
    "get_strategy_default",
]
