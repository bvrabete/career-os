"""Strongly-typed Pydantic v2 models for CV Generation and Ingestion LLM step outputs."""

from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ExperienceScoreOutput(BaseModel):
    """Structured LLM output when scoring a single experience entry against a JD."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    score: int = Field(default=0, ge=0, le=100)
    justification: str = "N/A"


class CompressedSummaryOutput(BaseModel):
    """Structured LLM output for experience compression steps (no YAML frontmatter)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    summary: str = ""


class SkillBridgingOutput(BaseModel):
    """Structured LLM output mapping required JD skills to equivalent candidate skills."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    mappings: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _coerce_flat_dict(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "mappings" in data and isinstance(data["mappings"], dict):
                return {"mappings": {str(k): str(v) for k, v in data["mappings"].items() if k and v}}
            return {"mappings": {str(k): str(v) for k, v in data.items() if k and v}}
        return {"mappings": {}}


class RequirementMapperOutput(BaseModel):
    """Structured LLM output for JD requirement extraction."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    requirements: list[dict[str, Any]] = Field(default_factory=list)


class ContactHeader(BaseModel):
    """Candidate contact header fields for deterministic top-of-CV rendering."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    full_name: str = ""
    location: str = ""
    phone: str = ""
    email: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""


class SkillCategory(BaseModel):
    """A single domain category of skills for the ATS-safe Key Skills bullet list."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    category: str
    skills: list[str] = Field(default_factory=list)

    @field_validator("skills", mode="before")
    @classmethod
    def _coerce_skills_list(cls, val: Any) -> list[str]:
        if isinstance(val, str):
            return [s.strip() for s in val.split(",") if s.strip()]
        if isinstance(val, list):
            return [str(s).strip() for s in val if str(s).strip()]
        return []


class CVRoleEntry(BaseModel):
    """A structured work experience role entry prior to final-stage Markdown/DOCX/PDF formatting."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    title: str
    organization: str = ""
    location: str = ""
    dates_display: str = ""
    employment_type: str = "Permanent"
    scope_summary: str = ""
    bullets: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)

    @field_validator("bullets", mode="before")
    @classmethod
    def _coerce_bullets(cls, val: Any) -> list[str]:
        if isinstance(val, str):
            return [line.strip("- *•\t ") for line in val.splitlines() if line.strip()]
        if isinstance(val, list):
            cleaned: list[str] = []
            for item in val:
                if isinstance(item, dict):
                    txt = str(item.get("text", "")).strip("- *•\t ")
                elif hasattr(item, "text"):
                    txt = str(getattr(item, "text", "")).strip("- *•\t ")
                else:
                    txt = str(item).strip("- *•\t ")
                if txt:
                    cleaned.append(txt)
            return cleaned
        return []

    @field_validator("technologies", mode="before")
    @classmethod
    def _coerce_technologies(cls, val: Any) -> list[str]:
        if isinstance(val, str):
            cleaned = val.replace("*Technologies:", "").replace("Technologies:", "").strip(" .*")
            return [t.strip() for t in cleaned.split(",") if t.strip()]
        if isinstance(val, list):
            return [str(t).strip() for t in val if str(t).strip()]
        return []


class EducationItem(BaseModel):
    """A structured education credential entry."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    degree: str
    institution: str = ""
    location: str = ""
    year: str = ""


class PatentOrPublicationItem(BaseModel):
    """A structured patent or technical publication entry."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    identifier: str = ""
    title: str
    organization: str = ""
    year: str = ""


class ProjectItem(BaseModel):
    """A structured open-source or standalone project entry."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    title: str
    nature: str = "Open Source"
    description: str = ""
    url: str = ""


class LanguageItem(BaseModel):
    """A structured spoken language competency entry."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    language: str
    proficiency: str = ""
    cefr: str = ""


class StructuredCVDocument(BaseModel):
    """Complete, strongly-typed CV document produced by Drafter/Compressor before final deterministic rendering."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    contact: ContactHeader = Field(default_factory=ContactHeader)
    professional_summary: str = ""
    skill_categories: list[SkillCategory] = Field(default_factory=list)
    experience_roles: list[CVRoleEntry] = Field(default_factory=list)
    earlier_career_roles: list[CVRoleEntry] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    patents_and_publications: list[PatentOrPublicationItem] = Field(default_factory=list)
    selected_projects: list[ProjectItem] = Field(default_factory=list)
    languages: list[LanguageItem] = Field(default_factory=list)


class ClassifierOutput(BaseModel):
    """Structured LLM output for the ingestion document classifier."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    doc_type: str = "skip"
    reason: str = ""


class ExperienceExtractionOutput(BaseModel):
    """Structured LLM output for experience document extraction."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    roles: list[dict[str, Any]] = Field(default_factory=list)
    education: list[dict[str, Any]] = Field(default_factory=list)
    languages: list[dict[str, Any]] = Field(default_factory=list)
    projects: list[dict[str, Any]] = Field(default_factory=list)
    patents: list[dict[str, Any]] = Field(default_factory=list)
    profile: dict[str, Any] = Field(default_factory=dict)


class CoverLetterExtractionOutput(BaseModel):
    """Structured LLM output for cover letter extraction."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    cover_letters: list[dict[str, Any]] = Field(default_factory=list)


class SupplementalExtractionOutput(BaseModel):
    """Structured LLM output for supplemental/performance note extraction."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    notes: list[dict[str, Any]] = Field(default_factory=list)


class CaseStudyExtractionOutput(BaseModel):
    """Structured LLM output for engineering case study extraction."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    case_study: dict[str, Any] | None = None
