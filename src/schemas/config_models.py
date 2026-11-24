"""Pydantic v2 configuration, CRM registry, and catalog schemas for CareerOS."""

from pathlib import Path
from typing import Annotated, Any, Literal
from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def _normalize_provider_type(val: Any) -> str:
    """Normalize LLM provider type string to lower-case."""
    if not isinstance(val, str) or not val.strip():
        raise ValueError("Step 'TYPE' must be a non-empty string ('gemini', 'openai', 'ollama').")
    cleaned = val.strip().lower()
    if cleaned not in ("gemini", "openai", "ollama"):
        raise ValueError(f"Invalid provider TYPE '{val}'. Expected one of: 'gemini', 'openai', 'ollama'.")
    return cleaned


def _strip_path(val: Any) -> Path:
    """Strip whitespace around configured filesystem paths."""
    if isinstance(val, Path):
        return Path(str(val).strip())
    if isinstance(val, str) and val.strip():
        return Path(val.strip())
    raise ValueError(f"Invalid path configuration value: {val!r}")


ProviderType = Annotated[Literal["gemini", "openai", "ollama"], BeforeValidator(_normalize_provider_type)]
StrippedPath = Annotated[Path, BeforeValidator(_strip_path)]


class FallbackModelConfig(BaseModel):
    """Pydantic schema for a step's fallback LLM configuration."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    TYPE: ProviderType
    MODEL_NAME: str = Field(min_length=1)


class StepModelConfig(BaseModel):
    """Pydantic schema for a single pipeline step's LLM configuration."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    TYPE: ProviderType | None = Field(default=None, validation_alias=AliasChoices("TYPE", "PROVIDER"))
    MODEL_NAME: str | None = None
    FALLBACK: FallbackModelConfig | None = None

    @model_validator(mode="after")
    def _validate_model_name(self) -> "StepModelConfig":
        if self.MODEL_NAME is not None and not self.MODEL_NAME.strip():
            raise ValueError("MODEL_NAME cannot be an empty string.")
        if self.TYPE is None and self.FALLBACK is None:
            raise ValueError("Step configuration must specify 'TYPE' (or 'FALLBACK').")
        return self


StepConfig = StepModelConfig


class PathsConfig(BaseModel):
    """Pydantic schema for workspace directory paths in config.yaml."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    WIKI_DIR: StrippedPath = Field(default=Path("llm-wiki"))
    OUTPUT_DIR: StrippedPath = Field(default=Path("ai-generated-cvs"))


class DefaultsConfig(BaseModel):
    """Pydantic schema for default generation parameters in config.yaml."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    STRATEGY: str = "emea"
    TRACK: str = "Corporate"
    GENERATE_PDF: bool = False
    GENERATE_DOCX: bool = False


class ScoringFactorsConfig(BaseModel):
    """Weights for multi-factor experience scoring."""

    ATS_SCORE: float = Field(default=0.50, ge=0.0, le=1.0)
    RECENCY: float = Field(default=0.30, ge=0.0, le=1.0)
    DURATION: float = Field(default=0.20, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_weights_sum(self) -> "ScoringFactorsConfig":
        total = self.ATS_SCORE + self.RECENCY + self.DURATION
        if abs(total - 1.0) > 0.05:
            raise ValueError(f"Scoring factor weights must sum to 1.0 (got {total:.2f})")
        return self


class ScoringTiersConfig(BaseModel):
    """Thresholds for experience compression tiers."""

    TIER_1_EXPANDED: float = Field(default=0.70, ge=0.0, le=1.0)
    TIER_2_BALANCED: float = Field(default=0.45, ge=0.0, le=1.0)
    TIER_3_COMPRESSED: float = Field(default=0.30, ge=0.0, le=1.0)


class ScoringConfig(BaseModel):
    """Complete scoring configuration block."""

    FACTORS: ScoringFactorsConfig = Field(default_factory=ScoringFactorsConfig)
    DURATION_CAP_YEARS: float = Field(default=3.0, gt=0.0)
    RECENCY_HORIZON_YEARS: float = Field(default=15.0, gt=0.0)
    MIN_CONCURRENT_CONTRACT_SCORE: int = Field(default=25, ge=0, le=100)
    ANCHOR_TENURE_MIN_YEARS: float = Field(default=5.0, ge=1.0)
    ANCHOR_TENURE_MIN_SCORE: int = Field(default=75, ge=0, le=100)
    EMPLOYMENT_TYPE_MULTIPLIERS: dict[str, float] = Field(
        default_factory=lambda: {
            "Permanent": 1.00,
            "Startup / Co-Founder": 1.00,
            "Contract": 0.85,
            "Advisory": 0.75,
        }
    )
    CULTURE_MULTIPLIERS: dict[str, dict[str, float]] = Field(
        default_factory=lambda: {
            "corporate": {
                "Permanent": 1.00,
                "Contract": 1.00,
                "Startup / Co-Founder": 0.80,
                "Advisory": 0.85,
            },
            "startup": {
                "Permanent": 1.00,
                "Contract": 1.00,
                "Startup / Co-Founder": 1.10,
                "Advisory": 1.00,
            },
        }
    )
    TIERS: ScoringTiersConfig = Field(default_factory=ScoringTiersConfig)


class CoverageSelectionConfigModel(BaseModel):
    """Configuration for coverage-aware evidence selection."""

    TARGET_PAGE_BUDGET: int = Field(default=2, ge=1, le=5)
    CONTENT_BUDGET_WORDS: int = Field(default=700, ge=100, le=5000)
    ALPHA_MARGINAL_COVERAGE: float = Field(default=0.50, ge=0.0, le=1.0)
    BETA_EVIDENCE_QUALITY: float = Field(default=0.30, ge=0.0, le=1.0)
    GAMMA_ROLE_CALIBRATION: float = Field(default=0.20, ge=0.0, le=1.0)
    REDUNDANCY_PENALTY: float = Field(default=0.60, ge=0.0, le=2.0)
    MIN_ESSENTIAL_COVERAGE: float = Field(default=0.85, ge=0.0, le=1.0)


class GenerationConfigModel(BaseModel):
    """Generation stage feature flags and parameters."""

    ENABLE_COVERAGE_SELECTION: bool = True
    COVERAGE_SELECTION: CoverageSelectionConfigModel = Field(default_factory=CoverageSelectionConfigModel)


class AppConfig(BaseModel):
    """Root strongly-typed Pydantic model for config.yaml."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    MODELS: dict[str, str] = Field(default_factory=dict)
    STEPS: dict[str, StepModelConfig] = Field(default_factory=dict)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_NUM_CTX: int = Field(default=12288, ge=2048, le=131072)
    PATHS: PathsConfig = Field(default_factory=PathsConfig)
    DEFAULTS: DefaultsConfig = Field(default_factory=DefaultsConfig)
    SCORING: ScoringConfig = Field(default_factory=ScoringConfig)
    GENERATION: GenerationConfigModel = Field(default_factory=GenerationConfigModel)
    WIKI_DIR: str | None = None
    OUTPUT_DIR: str | None = None
    STRATEGY_DEFAULT: str | None = None
    TRACK_DEFAULT: str | None = None


    @model_validator(mode="after")
    def _sync_legacy_aliases(self) -> "AppConfig":
        if self.WIKI_DIR and self.PATHS.WIKI_DIR == Path("llm-wiki"):
            self.PATHS.WIKI_DIR = Path(self.WIKI_DIR.strip())
        if self.OUTPUT_DIR and self.PATHS.OUTPUT_DIR == Path("ai-generated-cvs"):
            self.PATHS.OUTPUT_DIR = Path(self.OUTPUT_DIR.strip())
        if self.STRATEGY_DEFAULT and self.DEFAULTS.STRATEGY == "emea":
            self.DEFAULTS.STRATEGY = self.STRATEGY_DEFAULT.strip()
        if self.TRACK_DEFAULT and self.DEFAULTS.TRACK == "Corporate":
            self.DEFAULTS.TRACK = self.TRACK_DEFAULT.strip()
        return self


class ApplicationRecord(BaseModel):
    """Pydantic model for a single job application record in applications.yaml."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    company: str = "unknown"
    job_title: str = Field(default="unknown", validation_alias=AliasChoices("job_title", "role"))
    date: str
    status: str = "drafted"
    posting_organization_type: str = "direct_employer"
    recruitment_agency: str | None = None
    strategy: str = ""
    ats_score: int | float | None = Field(default=None, ge=0, le=100)
    output_markdown: str = ""
    output_pdf: str | None = None
    output_docx: str | None = None
    jd_markdown: str | None = None
    long_draft_markdown: str | None = None
    notes: str | None = None


class CRMRegistry(BaseModel):
    """Pydantic model for the applications.yaml CRM registry."""

    applications: list[ApplicationRecord] = Field(default_factory=list)


class CatalogMetadata(BaseModel):
    """Metadata summary block for catalog.json."""

    generated_at: str = ""
    total_experiences: int = 0
    total_education: int = 0
    total_projects: int = 0
    total_case_studies: int = 0
    total_skills_categories: int = 0
    total_strategies: int = 0
    total_location_strategies: int = 0
    total_track_strategies: int = 0


class WikiCatalog(BaseModel):
    """Strongly-typed Pydantic model for catalog.json."""

    metadata: CatalogMetadata
    experiences: list[dict[str, Any]] = Field(default_factory=list)
    education: list[dict[str, Any]] = Field(default_factory=list)
    projects: list[dict[str, Any]] = Field(default_factory=list)
    case_studies: list[dict[str, Any]] = Field(default_factory=list)
    skills_categories: list[str] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)
    location_strategies: list[str] = Field(default_factory=list)
    track_strategies: list[str] = Field(default_factory=list)
