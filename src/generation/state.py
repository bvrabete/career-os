"""State definition for the CV generation pipeline."""
from dataclasses import dataclass, field
import re
from typing import TypedDict, Any
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
    strategy_metadata: RegionalStrategy
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
    languages_entries: list[str]
    target_organization_slug: str
    target_role: str
