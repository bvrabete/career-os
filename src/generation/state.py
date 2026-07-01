"""State definition for the CV generation pipeline."""
from typing import TypedDict, Any


class CVPipelineState(TypedDict):
    """The state dictionary passed between nodes in the CV generation LangGraph."""
    job_description: str
    target_persona: str
    target_region: str
    target_locations: list[str]
    cv_expectations: str
    primary_keywords: list[str]
    selected_entries: list[str]
    education_entries: list[str]
    skills_entries: list[str]
    strategy_info: str
    pdf_template: str
    draft_cv: str
    audit_feedback: str
    refiner_feedback: str
    iteration_count: int
    strategy_override: str
    projects_entries: list[str]
    patents_entries: list[str]
    notes_entries: list[str]
    few_shot_examples: list[str]
    skill_bridging_map: dict[str, str]
    target_organization_slug: str
    target_role: str
