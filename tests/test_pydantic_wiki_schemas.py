"""Layer 1: Zero-token positive and negative Pydantic v2 schema and config tests."""

import pytest
from pathlib import Path
import re
from pydantic import ValidationError
import yaml

from ingestion.validators import (
    _validate_case_study,
    _validate_cover_letter,
    _validate_education,
    _validate_experience,
    _validate_language,
    _validate_note,
    _validate_patent,
    _validate_project,
    _validate_publication,
    _validate_skill,
)
import kb_config
from schemas.config_models import AppConfig, ApplicationRecord, CRMRegistry, ScoringFactorsConfig, StepConfig, WikiCatalog
from schemas.wiki_models import (
    CaseStudyFrontmatter,
    CompanyEntityFrontmatter,
    CoverLetterFrontmatter,
    EducationFrontmatter,
    ExperienceFrontmatter,
    LanguageFrontmatter,
    NoteFrontmatter,
    PatentFrontmatter,
    ProjectFrontmatter,
    PublicationFrontmatter,
    SkillFrontmatter,
    SynthesisFrontmatter,
    VoiceFrontmatter,
    validate_frontmatter_dict,
)


class TestPydanticWikiSchemas:
    """Positive and negative unit tests for all wiki frontmatter and config Pydantic models."""

    def test_wikilink_unwrapping_and_serialization(self) -> None:
        """Unquoted YAML 1.2 nested lists [['slug']] and [[['slug']]] unwrap and serialize cleanly."""
        raw_yaml = """
type: experience
title: Staff Platform Architect
organization: [[acme-corp]]
location: Amsterdam, Netherlands
dates:
  start: "2021-03-01"
  end: Present
skills:
  - Python
  - Kubernetes
case_studies:
  - [[acme-corp-event-mesh]]
projects:
  - [[[project-cloud-router]]]
sources:
  - master-cv.pdf
"""
        parsed = yaml.safe_load(raw_yaml)
        model = ExperienceFrontmatter.model_validate(parsed)
        assert model.organization == "acme-corp"
        assert model.case_studies == ["acme-corp-event-mesh"]
        assert model.projects == ["project-cloud-router"]

        dumped = model.model_dump()
        assert dumped["organization"] == "acme-corp"
        assert dumped["case_studies"] == ["acme-corp-event-mesh"]
        assert dumped["projects"] == ["project-cloud-router"]

    def test_experience_frontmatter_negative_cases(self) -> None:
        """Missing required fields or inverted date ranges raise ValidationError."""
        with pytest.raises(ValidationError):
            ExperienceFrontmatter.model_validate({"type": "experience", "title": ""})

        with pytest.raises(ValidationError):
            ExperienceFrontmatter.model_validate({
                "type": "experience",
                "title": "Engineer",
                "organization": "[[acme]]",
                "dates": {"start": "2024-05-01", "end": "2021-01-01"},
            })

    def test_company_entity_frontmatter_positive_and_negative(self) -> None:
        """CompanyEntityFrontmatter validates bidirectional links and rejects blank titles."""
        entity = CompanyEntityFrontmatter.model_validate({
            "type": "entity",
            "entity_type": "company",
            "title": "Acme Corp",
            "industry": "Cloud Infrastructure",
            "summary": "Global B2B SaaS provider.",
            "experiences": [["acme-corp-staff-architect"]],
            "case_studies": ["[[acme-corp-migration]]"],
        })
        assert entity.experiences == ["acme-corp-staff-architect"]
        assert entity.case_studies == ["acme-corp-migration"]

        with pytest.raises(ValidationError):
            CompanyEntityFrontmatter.model_validate({"type": "entity", "title": ""})

    def test_all_wiki_entity_models_positive_and_negative(self) -> None:
        """Positive and negative validation for case study, project, patent, publication, edu, skill, voice."""
        cs = CaseStudyFrontmatter.model_validate({
            "type": "case_study",
            "title": "Zero-Downtime Mesh Migration",
            "organization": [["acme-corp"]],
            "related_experience": [["acme-corp-architect"]],
            "skills": ["Kubernetes"],
        })
        assert cs.related_experience == "acme-corp-architect"

        proj = ProjectFrontmatter.model_validate({
            "type": "project",
            "title": "Cloud Router",
            "organization": "[[acme-corp]]",
            "project_nature": "open_source",
        })
        assert proj.organization == "acme-corp"

        pat = PatentFrontmatter.model_validate({
            "type": "patent",
            "title": "Distributed Packet Scheduler",
            "number": "US 12,345,678 B2",
            "status": "Granted",
        })
        assert pat.status == "Granted"

        pub = PublicationFrontmatter.model_validate({
            "type": "publication",
            "title": "Scalable Control Planes",
            "venue": "IEEE Cloud",
            "date": "2023-06",
            "authors": ["Jane Doe"],
        })
        assert pub.venue == "IEEE Cloud"

        edu = EducationFrontmatter.model_validate({
            "type": "education",
            "title": "M.Sc. Computer Science",
            "institution": [["tech-university"]],
        })
        assert edu.institution == "tech-university"

        skill = SkillFrontmatter.model_validate({
            "type": "skill",
            "title": "Python",
            "category": ["Language"],
            "related_experiences": [[["acme-corp-architect"]]],
        })
        assert skill.related_experiences == ["acme-corp-architect"]

        lang = LanguageFrontmatter.model_validate({
            "type": "language",
            "title": "English",
            "proficiency": "Fluent",
        })
        assert lang.title == "English"

        note = NoteFrontmatter.model_validate({
            "type": "note",
            "title": "Annual Peer Feedback",
            "related": [["acme-corp-architect"]],
        })
        assert note.related == ["acme-corp-architect"]

        voice = VoiceFrontmatter.model_validate({
            "type": "voice",
            "title": "My Voice",
            "english_proficiency": "Fluent ESL",
        })
        assert voice.type == "voice"

        cl = CoverLetterFrontmatter.model_validate({
            "type": "cover-letter",
            "title": "Cover Letter for Principal Architect",
            "target_organization": [["example-org"]],
        })
        assert cl.target_organization == "example-org"

        syn = SynthesisFrontmatter.model_validate({
            "type": "synthesis",
            "title": "Tailored CV",
            "target_role": "Principal Architect",
            "target_organization": [["example-org"]],
        })
        assert syn.target_organization == "example-org"

        with pytest.raises(ValidationError):
            validate_frontmatter_dict({"type": "publication", "title": "Paper", "venue": "", "date": "2024"})

    def test_ingestion_validators_backed_by_pydantic(self) -> None:
        """Ingestion validators accept valid YAML and report errors on malformed frontmatter."""
        errs: list[str] = []
        _validate_experience(
            {"type": "experience", "title": "Lead", "organization": "[[acme]]", "dates": {"start": "2020-01"}, "tracks": ["IC"], "skills": ["Go"]},
            errs,
        )
        assert errs == []

        bad_errs: list[str] = []
        _validate_experience({"type": "experience", "title": ""}, bad_errs)
        assert len(bad_errs) > 0

        for fn, payload in [
            (_validate_project, {"type": "project", "title": "Tool", "organization": "[[acme]]", "dates": {"start": "2022"}, "skills": ["Go"]}),
            (_validate_patent, {"type": "patent", "title": "Pat", "id": "US1", "inventors": ["A"], "organization": "[[acme]]", "skills": ["Go"]}),
            (_validate_publication, {"type": "publication", "title": "Pub", "venue": "ACM", "date": "2022", "authors": ["A"]}),
            (_validate_education, {"type": "education", "title": "BSc", "institution": "[[uni]]", "dates": {"start": "2015"}, "status": "Completed", "major": "CS", "minor": "Math"}),
            (_validate_skill, {"type": "skill", "title": "Go", "category": "Language", "proficiency": ["Expert"]}),
            (_validate_language, {"type": "language", "title": "Dutch", "proficiency": "B1"}),
            (_validate_note, {"type": "note", "title": "Review", "related": ["[[acme]]"], "perspective": "Third-Party", "tags": ["review"]}),
            (_validate_case_study, {"type": "case_study", "title": "CS", "organization": "[[acme]]"}),
            (_validate_cover_letter, {"type": "cover-letter", "title": "CL", "target_organization": "[[acme]]", "related_synthesis": ""}),
        ]:
            local_errs: list[str] = []
            fn(payload, local_errs)
            assert local_errs == []

    def test_schema_md_yaml_blocks_parse_and_validate(self) -> None:
        """Every YAML frontmatter example in llm-wiki.template/schema.md parses and validates via Pydantic."""
        schema_path = Path(__file__).parent.parent / "llm-wiki.template" / "schema.md"
        content = schema_path.read_text(encoding="utf-8")
        yaml_blocks = re.findall(r"```yaml\n---\n(.*?)\n---", content, flags=re.DOTALL)
        assert len(yaml_blocks) >= 10
        for block in yaml_blocks:
            data = yaml.safe_load(block)
            assert isinstance(data, dict)
            if "type" in data:
                model = validate_frontmatter_dict(data)
                assert model is not None

    def test_app_config_and_preset_configs_validate(self) -> None:
        """All repository config*.yaml files validate against AppConfig."""
        repo_root = Path(__file__).parent.parent
        config_files = sorted(repo_root.glob("config*.yaml"))
        assert len(config_files) >= 1
        for cfg_file in config_files:
            raw = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
            app_cfg = AppConfig.model_validate(raw)
            assert "DRAFTING" in app_cfg.STEPS

        typed_cfg = kb_config.load_typed_config()
        assert isinstance(typed_cfg, AppConfig)

    def test_app_config_negative_validation(self) -> None:
        """Invalid scoring weights, small num_ctx, or empty model names fail AppConfig validation."""
        with pytest.raises(ValidationError):
            ScoringFactorsConfig(ATS_SCORE=0.8, RECENCY=0.8, DURATION=0.2)

        with pytest.raises(ValidationError):
            StepConfig(PROVIDER="ollama", MODEL_NAME="", TEMPERATURE=0.0)

        with pytest.raises(ValidationError):
            AppConfig.model_validate({"OLLAMA_NUM_CTX": 512})

    def test_crm_and_catalog_models_positive_and_negative(self) -> None:
        """ApplicationRecord, CRMRegistry, and WikiCatalog enforce strict field constraints."""
        rec = ApplicationRecord(company="acme", job_title="Architect", date="2026-04-12", ats_score=91)
        reg = CRMRegistry(applications=[rec])
        assert len(reg.applications) == 1

        with pytest.raises(ValidationError):
            ApplicationRecord(company="acme", job_title="Architect", date="2026-04-12", ats_score=150)

        cat = WikiCatalog.model_validate({"metadata": {"total_experiences": 0}})
        assert cat.metadata.total_experiences == 0
