"""State definition for the CV generation pipeline."""
from dataclasses import dataclass, field
import re
from typing import TypedDict, Any, Literal
from pydantic import BaseModel, Field
import yaml


@dataclass
class RegionalStrategy:
    """Strongly-typed representation of a regional CV tailoring strategy."""
    type: str = "strategy"
    title: str = ""
    region: list[str] = field(default_factory=list)
    focus: list[str] = field(default_factory=list)
    pdf_template: str = "templates/base.css"
    max_pages: int = 2
    created: str = ""
    updated: str = ""
    body: str = ""

    @classmethod
    def from_markdown(cls, text: str) -> "RegionalStrategy":
        """Parse raw markdown content with frontmatter into a RegionalStrategy."""
        fm_match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        if not fm_match:
            return cls(body=text)

        frontmatter_str = fm_match.group(1)
        body_text = text[fm_match.end():].strip()

        try:
            fm = yaml.safe_load(frontmatter_str) or {}
        except Exception:
            fm = {}

        region_raw = fm.get("region", [])
        region_list = [str(r) for r in region_raw] if isinstance(region_raw, list) else [str(region_raw)]

        focus_raw = fm.get("focus", [])
        focus_list = [str(f) for f in focus_raw] if isinstance(focus_raw, list) else [str(focus_raw)]

        try:
            max_pages = int(fm.get("max_pages", 2))
        except (ValueError, TypeError):
            max_pages = 2

        return cls(
            type=str(fm.get("type", "strategy")),
            title=str(fm.get("title", "")),
            region=region_list,
            focus=focus_list,
            pdf_template=str(fm.get("pdf_template", "templates/base.css")),
            max_pages=max_pages,
            created=str(fm.get("created", "")),
            updated=str(fm.get("updated", "")),
            body=body_text
        )


@dataclass
class TrackStrategy:
    """Strongly-typed representation of a career track CV tailoring strategy."""
    type: str = "strategy-track"
    title: str = ""
    seniority_levels: list[str] = field(default_factory=list)
    archetype: str = ""
    focus: list[str] = field(default_factory=list)
    org_culture: str = "corporate"
    created: str = ""
    updated: str = ""
    body: str = ""

    @classmethod
    def from_markdown(cls, text: str) -> "TrackStrategy":
        """Parse raw markdown content with frontmatter into a TrackStrategy."""
        fm_match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        if not fm_match:
            return cls(body=text)

        frontmatter_str = fm_match.group(1)
        body_text = text[fm_match.end():].strip()

        try:
            fm = yaml.safe_load(frontmatter_str) or {}
        except Exception:
            fm = {}

        seniority_raw = fm.get("seniority_levels", [])
        seniority_list = (
            [str(s) for s in seniority_raw]
            if isinstance(seniority_raw, list)
            else [str(seniority_raw)]
        )

        focus_raw = fm.get("focus", [])
        focus_list = (
            [str(f) for f in focus_raw]
            if isinstance(focus_raw, list)
            else [str(focus_raw)]
        )

        org_culture_raw = str(fm.get("org_culture", "")).strip().lower()
        if not org_culture_raw:
            title_lower = str(fm.get("title", "")).lower()
            archetype_lower = str(fm.get("archetype", "")).lower()
            if any(k in title_lower or k in archetype_lower for k in ["startup", "founding", "founder"]):
                org_culture_raw = "startup"
            else:
                org_culture_raw = "corporate"

        return cls(
            type=str(fm.get("type", "strategy-track")),
            title=str(fm.get("title", "")),
            seniority_levels=seniority_list,
            archetype=str(fm.get("archetype", "")),
            focus=focus_list,
            org_culture=org_culture_raw,
            created=str(fm.get("created", "")),
            updated=str(fm.get("updated", "")),
            body=body_text,
        )


class RequirementSupport(BaseModel):
    """Semantic or keyword support relationship between an evidence item and a requirement."""
    requirement_id: str
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    support_strength: Literal["primary", "secondary", "supporting"] = "supporting"
    rationale: str = ""


class JobRequirement(BaseModel):
    """Explicit, typed, weighted requirement extracted from a target job description."""
    id: str
    text: str
    category: Literal[
        "core_technical",
        "system_architecture",
        "leadership_management",
        "domain_specialization",
        "delivery_methodology",
        "business_impact",
        "cultural_soft_skill"
    ] = "core_technical"
    priority: Literal["essential", "important", "supporting"] = "important"
    weight: float = Field(default=1.0, ge=0.1, le=2.0)
    keywords: list[str] = Field(default_factory=list)
    source_text: str = ""
    notes: str = ""


class EvidenceItem(BaseModel):
    """Normalized atomic unit of evidence (achievement bullet, project, patent, note) for selection."""
    id: str
    source_ref: str  # e.g., "experiences/acme-corp.md:achievements[2]"
    source_type: Literal["experience", "project", "patent", "case_study", "note"]
    role_or_project: str
    text: str
    existing_role_score: float = 0.0
    keyword_relevance: float = 0.0
    impact_assessment: float = 0.5  # 0.0 to 1.0 based on metrics/scope
    evidence_confidence: float = 1.0
    estimated_words: int = 0
    supports: list[RequirementSupport] = Field(default_factory=list)
    redundancy_group: str = ""  # cluster key e.g. "aws_cloud_migration"
    selection_status: Literal["selected", "marginal_pass", "excluded"] = "excluded"
    selection_reason: str = ""
    exclusion_reason: str = ""


class SelectionConfig(BaseModel):
    """Knapsack optimization configuration parameters."""
    target_page_budget: int = 2
    content_budget_words: int = 700
    alpha_marginal_coverage: float = 0.50
    beta_evidence_quality: float = 0.30
    gamma_role_calibration: float = 0.20
    redundancy_penalty_multiplier: float = 0.60
    min_essential_coverage_ratio: float = 0.85


class SelectionManifest(BaseModel):
    """Machine-readable evidence selection record informing Drafter and Auditor."""
    schema_version: str = "1.0.0"
    run_id: str = ""
    content_budget_words: int = 700
    estimated_selected_words: int = 0
    requirements: list[JobRequirement] = Field(default_factory=list)
    selected_evidence: list[EvidenceItem] = Field(default_factory=list)
    uncovered_requirements: list[JobRequirement] = Field(default_factory=list)
    excluded_evidence: list[EvidenceItem] = Field(default_factory=list)
    coverage_summary: dict[str, float] = Field(default_factory=dict)
    selection_config: SelectionConfig = Field(default_factory=SelectionConfig)


class CVPipelineState(TypedDict, total=False):
    """The state dictionary passed between nodes in the CV generation LangGraph."""
    job_description: str
    target_persona: str
    target_region: str
    target_track: str
    target_locations: list[str]
    cv_expectations: str
    primary_keywords: list[str]
    selected_entries: list[str]
    education_entries: list[str]
    skills_entries: list[str]
    strategy_info: str
    strategy_metadata: RegionalStrategy
    track_strategy_info: str
    track_strategy_metadata: TrackStrategy
    pdf_template: str
    draft_cv: str
    audit_feedback: str
    refiner_feedback: str
    iteration_count: int
    compression_count: int
    interactive: bool
    ats_scorecard: dict[str, Any]
    total_words: int
    total_bullet_lines: int
    strategy_override: str
    track_override: str
    projects_entries: list[str]
    patents_entries: list[str]
    notes_entries: list[str]
    case_studies_entries: list[str]
    few_shot_examples: list[str]
    skill_bridging_map: dict[str, str]
    languages_entries: list[str]
    target_organization_slug: str
    target_role: str
    requirements: list[dict[str, Any]]
    candidate_evidence: list[dict[str, Any]]
    selection_manifest: dict[str, Any] | None

