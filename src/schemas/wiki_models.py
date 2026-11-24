"""Pydantic v2 domain, frontmatter, and structured LLM output schemas for CareerOS."""

import re
from typing import Annotated, Any, Literal
from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator
from utils import extract_wikilink_list, extract_wikilink_slug

DATE_ISO_PATTERN = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$|^Present$", re.IGNORECASE)
VALID_SKILL_CATEGORIES = (
    "Language-Code", "Language", "Framework", "Infrastructure", "Leadership",
    "Spoken-Language", "Architecture", "Cloud", "Data",
)
VALID_EMPLOYMENT_TYPES = ("Permanent", "Contract", "Startup / Co-Founder", "Advisory")


def _require_wikilink_syntax_and_extract(val: Any) -> str:
    """Require that a raw YAML value was formatted as [[slug]] (string or nested list) and return the clean slug."""
    if val is None or val == "":
        raise ValueError("Missing required wikilink field")
    if isinstance(val, str) and ("[[" not in val or "]]" not in val):
        raise ValueError(f"Field missing [[slug]] syntax: '{val}'")
    slug = extract_wikilink_slug(val)
    if not slug:
        raise ValueError(f"Empty wikilink slug in '{val}'")
    return slug


def _optional_wikilink_extract(val: Any) -> str:
    """Extract clean slug from optional wikilink field (accepting empty, plain slug, or [[slug]])."""
    if val is None or val == "":
        return ""
    return extract_wikilink_slug(val)


def _coerce_str_list(val: Any) -> list[str]:
    """Coerce a string or list of strings into a clean list[str]."""
    if val is None or val == "":
        return []
    if isinstance(val, str):
        return [val.strip()] if val.strip() else []
    if isinstance(val, (list, tuple)):
        return [str(x).strip() for x in val if x is not None and str(x).strip()]
    raise ValueError(f"Expected string or list of strings, got {type(val).__name__}")


def _validate_date_value(val: Any) -> str:
    """Validate and normalize a date string (YYYY, YYYY-MM, YYYY-MM-DD, or Present)."""
    if val is None or val == "":
        return ""
    raw = str(val).strip()
    token = raw.split()[0] if raw else ""
    if token and not DATE_ISO_PATTERN.match(token):
        raise ValueError(f"Invalid date format: '{raw}'")
    if token.lower() == "present":
        return "Present"
    return token


def _normalize_employment_type(val: Any) -> str:
    """Normalize and validate employment_type against canonical values."""
    if val is None or str(val).strip() == "":
        return "Permanent"
    raw = str(val).strip()
    lowered = raw.lower().replace("-", " ").replace("_", " ")
    if lowered in ("permanent", "full time", "fulltime"):
        return "Permanent"
    if lowered == "contract":
        return "Contract"
    if lowered in ("startup / co founder", "startup", "co founder", "cofounder", "self employed"):
        return "Startup / Co-Founder"
    if lowered in ("advisory", "advisor"):
        return "Advisory"
    raise ValueError(
        f"employment_type must be either 'Permanent' or 'Contract' (or {VALID_EMPLOYMENT_TYPES}), got '{raw}'"
    )


StrictWikiLinkSlug = Annotated[str, BeforeValidator(_require_wikilink_syntax_and_extract)]
OptionalWikiLinkSlug = Annotated[str, BeforeValidator(_optional_wikilink_extract)]
WikiLinkSlugList = Annotated[list[str], BeforeValidator(extract_wikilink_list)]
CoercedStrList = Annotated[list[str], BeforeValidator(_coerce_str_list)]
ValidatedDateStr = Annotated[str, BeforeValidator(_validate_date_value)]
NormalizedEmploymentType = Annotated[str, BeforeValidator(_normalize_employment_type)]


class DateSpan(BaseModel):
    """Start and end dates for experiences, projects, case studies, and education."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    start: ValidatedDateStr = ""
    end: ValidatedDateStr = ""

    @model_validator(mode="after")
    def _validate_chronology(self) -> "DateSpan":
        s, e = self.start[:4], self.end[:4]
        if s.isdigit() and e.isdigit() and int(e) < int(s):
            raise ValueError(f"end date '{self.end}' cannot precede start date '{self.start}'")
        return self


class ExperienceScope(BaseModel):
    """Structured executive scope metadata for an experience role."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    team_size: str = ""
    budget: str = ""
    reports_to: str = ""
    company_context: str = ""


class ExperienceFrontmatter(BaseModel):
    """Pydantic v2 schema for wiki/experiences/*.md frontmatter."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    type: Literal["experience"] = "experience"
    title: str = Field(min_length=1)
    organization: StrictWikiLinkSlug
    location: str = ""
    dates: DateSpan = Field(default_factory=DateSpan)
    employment_type: NormalizedEmploymentType = "Permanent"
    tracks: CoercedStrList = Field(default_factory=list)
    skills: CoercedStrList = Field(default_factory=list)
    tags: CoercedStrList = Field(default_factory=list)
    case_studies: WikiLinkSlugList = Field(default_factory=list)
    projects: WikiLinkSlugList = Field(default_factory=list)
    patents: WikiLinkSlugList = Field(default_factory=list)
    notes: WikiLinkSlugList = Field(default_factory=list)
    scope: ExperienceScope | None = None
    sources: CoercedStrList = Field(default_factory=list)
    created: str = ""
    updated: str = ""


class EducationFrontmatter(BaseModel):
    """Pydantic v2 schema for wiki/education/*.md frontmatter."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    type: Literal["education"] = "education"
    title: str = Field(min_length=1)
    institution: StrictWikiLinkSlug
    dates: DateSpan = Field(default_factory=DateSpan)
    status: CoercedStrList | str = "Completed"
    major: str = ""
    minor: str = ""
    sources: CoercedStrList = Field(default_factory=list)
    created: str = ""
    updated: str = ""


class SkillFrontmatter(BaseModel):
    """Pydantic v2 schema for wiki/skills/*.md frontmatter."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    type: Literal["skill"] = "skill"
    title: str = Field(min_length=1)
    category: CoercedStrList
    related_experiences: WikiLinkSlugList = Field(default_factory=list)
    proficiency: CoercedStrList = Field(default_factory=lambda: ["Proficient"])
    sources: CoercedStrList = Field(default_factory=list)

    @field_validator("category")
    @classmethod
    def _check_categories(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("Skill category cannot be empty")
        for cat in v:
            if cat not in VALID_SKILL_CATEGORIES:
                raise ValueError(f"Invalid skill category: '{cat}'")
        return v


class LanguageFrontmatter(BaseModel):
    """Pydantic v2 schema for wiki/languages/*.md frontmatter."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    type: Literal["language"] = "language"
    title: str = Field(min_length=1)
    category: CoercedStrList = Field(default_factory=lambda: ["Spoken-Language"])
    proficiency: CoercedStrList | str = "Fluent"
    cefr: str = ""
    sources: CoercedStrList = Field(default_factory=list)
    created: str = ""
    updated: str = ""


class ProjectFrontmatter(BaseModel):
    """Pydantic v2 schema for wiki/projects/*.md frontmatter."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    type: Literal["project"] = "project"
    title: str = Field(min_length=1)
    project_nature: Literal["open_source", "side_project", "research_prototype", "enterprise_initiative"] = "open_source"
    status: str = "completed"
    repo_url: str = ""
    demo_url: str = ""
    organization: OptionalWikiLinkSlug = ""
    related_experience: OptionalWikiLinkSlug = Field(
        default="", validation_alias=AliasChoices("related_experience", "tenure")
    )
    dates: DateSpan = Field(default_factory=DateSpan)
    skills: CoercedStrList = Field(default_factory=list)
    domains: CoercedStrList = Field(default_factory=list)
    sources: CoercedStrList = Field(default_factory=list)
    created: str = ""
    updated: str = ""

    @field_validator("organization", mode="before")
    @classmethod
    def _validate_org_syntax_if_present(cls, v: Any) -> Any:
        if isinstance(v, str) and v.strip() and ("[[" not in v or "]]" not in v):
            raise ValueError(f"organization field missing [[slug]] syntax: '{v}'")
        return v


class PatentFrontmatter(BaseModel):
    """Pydantic v2 schema for wiki/patents/*.md frontmatter."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    type: Literal["patent"] = "patent"
    title: str = Field(min_length=1)
    id: str = Field(default="", validation_alias=AliasChoices("id", "number"))
    status: str = "Granted"
    inventors: CoercedStrList = Field(default_factory=list)
    organization: OptionalWikiLinkSlug = ""
    related_experience: OptionalWikiLinkSlug = Field(
        default="", validation_alias=AliasChoices("related_experience", "tenure")
    )
    grant_date: ValidatedDateStr = Field(default="", validation_alias=AliasChoices("grant_date", "date_granted", "filing_date"))
    link: str = ""
    skills: CoercedStrList = Field(default_factory=list)
    sources: CoercedStrList = Field(default_factory=list)
    created: str = ""
    updated: str = ""


class PublicationFrontmatter(BaseModel):
    """Pydantic v2 schema for wiki/publications/*.md frontmatter."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    type: Literal["publication"] = "publication"
    title: str = Field(min_length=1)
    doi: str = ""
    publication_type: str = "whitepaper"
    venue: str = Field(default="", min_length=1)
    date: ValidatedDateStr = ""
    authors: CoercedStrList = Field(default_factory=list)
    organization: OptionalWikiLinkSlug = ""
    related_experience: OptionalWikiLinkSlug = Field(
        default="", validation_alias=AliasChoices("related_experience", "tenure")
    )
    skills: CoercedStrList = Field(default_factory=list)
    sources: CoercedStrList = Field(default_factory=list)


class CaseStudyFrontmatter(BaseModel):
    """Pydantic v2 schema for wiki/case-studies/*.md frontmatter."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    type: Literal["case_study"] = "case_study"
    title: str = Field(min_length=1)
    organization: OptionalWikiLinkSlug = ""
    related_experience: OptionalWikiLinkSlug = Field(
        default="", validation_alias=AliasChoices("related_experience", "tenure")
    )
    dates: DateSpan = Field(default_factory=DateSpan)
    skills: CoercedStrList = Field(default_factory=list)
    tags: CoercedStrList = Field(default_factory=list)
    sources: CoercedStrList = Field(default_factory=list)
    created: str = ""
    updated: str = ""


class NoteFrontmatter(BaseModel):
    """Pydantic v2 schema for wiki/notes/*.md frontmatter."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    type: Literal["note"] = "note"
    title: str = Field(min_length=1)
    related: WikiLinkSlugList = Field(default_factory=list, validation_alias=AliasChoices("related", "related_experiences"))
    perspective: CoercedStrList | str = "Third-Party"
    tags: CoercedStrList = Field(default_factory=list)
    sources: CoercedStrList = Field(default_factory=list)
    created: str = ""
    updated: str = ""


class CoverLetterFrontmatter(BaseModel):
    """Pydantic v2 schema for wiki/cover-letters/*.md frontmatter."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    type: Literal["cover-letter"] = "cover-letter"
    title: str = Field(min_length=1)
    target_organization: StrictWikiLinkSlug
    related_synthesis: OptionalWikiLinkSlug = ""
    sources: CoercedStrList = Field(default_factory=list)
    created: str = ""
    updated: str = ""


class EntityFrontmatter(BaseModel):
    """Pydantic v2 schema for wiki/entities/*.md (Companies, Universities, Persons)."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    type: Literal["entity"] = "entity"
    entity_type: str = "company"
    title: str = Field(min_length=1)
    category: CoercedStrList | str = "organization"
    industry: str = ""
    company_size: str = ""
    headquarters: str = ""
    summary: str = ""
    tags: CoercedStrList = Field(default_factory=list)
    related: WikiLinkSlugList = Field(default_factory=list)
    experiences: WikiLinkSlugList = Field(default_factory=list)
    case_studies: WikiLinkSlugList = Field(default_factory=list)
    projects: WikiLinkSlugList = Field(default_factory=list)
    patents: WikiLinkSlugList = Field(default_factory=list)
    sources: CoercedStrList = Field(default_factory=list)
    created: str = ""
    updated: str = ""


CompanyEntityFrontmatter = EntityFrontmatter


class VoiceFrontmatter(BaseModel):
    """Pydantic v2 schema for wiki/voice/my-voice.md frontmatter."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    type: Literal["voice"] = "voice"
    title: str = Field(min_length=1)
    english_proficiency: str = "Fluent"
    preferred_tone: str = ""
    tags: CoercedStrList = Field(default_factory=list)
    sources: CoercedStrList = Field(default_factory=list)
    created: str = ""
    updated: str = ""


class SynthesisFrontmatter(BaseModel):
    """Pydantic v2 schema for wiki/synthesis/*.md frontmatter."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    type: Literal["synthesis"] = "synthesis"
    title: str = Field(min_length=1)
    target_role: str = ""
    target_organization: OptionalWikiLinkSlug = ""
    status: str = "Generated"
    created: str = ""
    updated: str = ""


class GenericFrontmatter(BaseModel):
    """Fallback Pydantic model for strategy and miscellaneous markdown frontmatter."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")


def validate_frontmatter_dict(data: dict[str, Any]) -> BaseModel:
    """Validate a raw YAML frontmatter dict against its type-specific Pydantic v2 model."""
    page_type = str(data.get("type", "")).strip()
    registry: dict[str, type[BaseModel]] = {
        "experience": ExperienceFrontmatter,
        "education": EducationFrontmatter,
        "skill": SkillFrontmatter,
        "language": LanguageFrontmatter,
        "project": ProjectFrontmatter,
        "patent": PatentFrontmatter,
        "publication": PublicationFrontmatter,
        "case_study": CaseStudyFrontmatter,
        "note": NoteFrontmatter,
        "cover-letter": CoverLetterFrontmatter,
        "entity": EntityFrontmatter,
        "voice": VoiceFrontmatter,
        "synthesis": SynthesisFrontmatter,
    }
    model_cls = registry.get(page_type, GenericFrontmatter)
    return model_cls.model_validate(data)


class RoleEvidenceBundle(BaseModel):
    """Role-centric evidence bundle grouping a role with its linked company, case studies, projects, patents, and notes."""

    slug: str
    title: str
    organization_slug: str
    organization_name: str
    organization_overview: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = "Present"
    employment_type: str = "Permanent"
    is_startup_track: bool = False
    is_concurrent: bool = False
    is_old_role: bool = False
    relevance_score: int = 80
    weight: float = 0.75
    justification: str = ""
    scope: ExperienceScope = Field(default_factory=ExperienceScope)
    skills: list[str] = Field(default_factory=list)
    context_text: str = ""
    narrative_text: str = ""
    achievements: list[str] = Field(default_factory=list)
    linked_case_studies: list[str] = Field(default_factory=list)
    linked_projects: list[str] = Field(default_factory=list)
    linked_patents: list[str] = Field(default_factory=list)
    linked_notes: list[str] = Field(default_factory=list)


class SynthesizedBullet(BaseModel):
    """A single synthesized, JD-aligned STAR achievement bullet produced by the Long-Form Evidence Synthesizer."""

    text: str
    covered_requirement_ids: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class SynthesizedRole(BaseModel):
    """A role's synthesized executive scope and JD-aligned achievement bullets in the Master Matching Draft."""

    role_slug: str
    title: str
    organization: str
    location: str = ""
    dates_display: str = ""
    employment_type: str = "Permanent"
    is_old_role: bool = False
    scope_summary: str = ""
    technologies: list[str] = Field(default_factory=list)
    bullets: list[SynthesizedBullet] = Field(default_factory=list)


class TailoredLongDraft(BaseModel):
    """Stage 3 Master Matching Draft containing all synthesized, requirement-mapped role evidence before page sculpting."""

    hiring_thesis: str = ""
    executive_summary_draft: str = ""
    synthesized_roles: list[SynthesizedRole] = Field(default_factory=list)
    standalone_projects: list[str] = Field(default_factory=list)
    standalone_patents_publications: list[str] = Field(default_factory=list)


class AnalyzerOutput(BaseModel):
    """Structured Pydantic output from the Strategic Analyzer node."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    persona: str = "Senior Engineering Leader"
    posting_organization_type: Literal["direct_employer", "recruitment_agency", "confidential_client"] = "direct_employer"
    recruitment_agency_name: str | None = None
    target_employer_name: str = "unknown-company"
    target_organization_slug: str = "unknown-company"
    target_role: str = "unknown-role"
    keywords: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    expectations: str = "Standard professional CV"
    suggested_region: str = "emea"
    suggested_track: str = "engineering-management"
    employer_archetype: Literal["enterprise_corporate", "intrapreneurial_bu", "scaleup_growth", "early_stage_startup"] = "enterprise_corporate"
    parallel_venture_policy: Literal["strict_single_timeline", "highlight_entrepreneurial"] = "strict_single_timeline"


class DimensionScore(BaseModel):
    """Single rubric dimension score in the ATS Scorecard."""

    score: int = Field(default=0, ge=0, le=100)
    max: int = Field(default=50, ge=1, le=100)
    justification: str = ""


class ATSScorecard(BaseModel):
    """Structured ATS compliance breakdown."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    skills_match: DimensionScore = Field(default_factory=lambda: DimensionScore(score=0, max=50))
    outcomes_impact: DimensionScore = Field(default_factory=lambda: DimensionScore(score=0, max=30))
    domain_context: DimensionScore = Field(default_factory=lambda: DimensionScore(score=0, max=20))
    total_score: int = Field(default=0, ge=0, le=100)


class AuditOutput(BaseModel):
    """Structured Pydantic output from the Executive & ATS Auditor node."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    is_pass: bool = Field(default=False, validation_alias=AliasChoices("pass", "is_pass"))
    ats_score: ATSScorecard = Field(default_factory=ATSScorecard)
    rewrite_checklist: list[str] = Field(default_factory=list)
