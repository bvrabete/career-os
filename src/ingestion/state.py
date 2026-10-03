"""State definition and schema models for the ingestion pipeline."""
from typing import TypedDict, Any
from pydantic import BaseModel, Field


class DateSpan(BaseModel):
    """Start and end dates for roles, tenures, and education."""
    start: str = ""
    end: str | None = None


class RoleEntry(BaseModel):
    """An individual progressive role held within an employer tenure."""
    title: str
    dates: DateSpan | dict[str, str | None] | str | None = None
    summary: str = ""
    key_achievements: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    case_studies: list[str] = Field(default_factory=list)


class CompanyTenure(BaseModel):
    """A contiguous period of employment at an organization with one or more roles."""
    type: str = "experience"
    organization: str
    organization_name: str
    dates: DateSpan | dict[str, str | None] | None = None
    employment_nature: str = "primary"
    employment_type: str = "full_time"
    location: str | None = None
    roles: list[RoleEntry] = Field(default_factory=list)
    patents: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class ProjectRecord(BaseModel):
    """A technical side project, open-source repository, or research prototype."""
    type: str = "project"
    title: str
    slug: str | None = None
    project_nature: str = "open_source"
    repo_url: str | None = None
    organization: str | None = None
    dates: DateSpan | dict[str, str | None] | None = None
    summary: str = ""
    key_contributions: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class EducationEntry(BaseModel):
    """Academic degree or certification credential."""
    type: str = "education"
    institution: str
    institution_name: str
    degree: str
    field_of_study: str | None = None
    dates: DateSpan | dict[str, str | None] | None = None
    grade: str | None = None
    activities: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class CaseStudyRef(BaseModel):
    """Reference linking an engineering case study to an employer experience."""
    slug: str
    title: str
    organization_slug: str
    summary_one_liner: str


class IngestionState(TypedDict):
    """The state dictionary passed between nodes in the ingestion LangGraph."""
    source_file: str
    raw_text: str
    doc_type: str
    extracted_roles: list[dict[str, Any]]
    extracted_education: list[dict[str, Any]]
    extracted_languages: list[dict[str, Any]]
    extracted_projects: list[dict[str, Any]]
    extracted_patents: list[dict[str, Any]]
    extracted_notes: list[dict[str, Any]]
    extracted_cover_letters: list[dict[str, Any]]
    extracted_profile: dict[str, Any]
    resolved_entities: dict[str, str]
    wiki_outputs: list[dict[str, Any]]
