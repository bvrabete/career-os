"""Schema validation routines for wiki entities produced by the ingestion pipeline."""

import logging
import re
from typing import Any
from pydantic import ValidationError
import yaml

from ingestion.helpers import clean_frontmatter
from schemas.wiki_models import (
    CaseStudyFrontmatter,
    CoverLetterFrontmatter,
    EducationFrontmatter,
    EntityFrontmatter,
    ExperienceFrontmatter,
    LanguageFrontmatter,
    NoteFrontmatter,
    PatentFrontmatter,
    ProjectFrontmatter,
    PublicationFrontmatter,
    SkillFrontmatter,
    VALID_EMPLOYMENT_TYPES,
    VALID_SKILL_CATEGORIES,
)
from utils import extract_wikilink_slug

DATE_PATTERN = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$|^Present$", re.IGNORECASE)


def _has_wikilink_syntax(raw_val: Any) -> bool:
    """Return True if raw YAML value was written with [[slug]] syntax (quoted or unquoted nested list)."""
    if isinstance(raw_val, list):
        return bool(extract_wikilink_slug(raw_val))
    if isinstance(raw_val, str):
        return "[[" in raw_val and "]]" in raw_val and bool(extract_wikilink_slug(raw_val))
    return False


def _validate_dates(dates: Any, errors: list[str]) -> None:
    """Validate start and end fields in frontmatter dates dictionary."""
    if isinstance(dates, dict):
        for field in ("start", "end"):
            raw_val = str(dates.get(field, ""))
            val = raw_val.split()[0] if raw_val else ""
            if val and not DATE_PATTERN.match(val):
                errors.append(f"dates.{field} invalid format: '{raw_val}'")


def _validate_experience(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate experience type frontmatter schema via Pydantic and explicit error messages."""
    exp_required = {"type", "title", "organization", "dates", "tracks", "skills"}
    missing = exp_required - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

    org_raw = fm.get("organization", "")
    if not _has_wikilink_syntax(org_raw):
        errors.append(f"organization field missing [[slug]] syntax: '{org_raw}'")

    _validate_dates(fm.get("dates"), errors)

    emp_type = fm.get("employment_type")
    if emp_type:
        try:
            ExperienceFrontmatter.model_validate(
                {
                    "type": "experience",
                    "title": str(fm.get("title") or "Role"),
                    "organization": "[[org]]",
                    "dates": {"start": "2020-01-01", "end": "Present"},
                    "employment_type": emp_type,
                    "tracks": ["Engineering"],
                    "skills": ["Python"],
                }
            )
        except ValidationError:
            errors.append(
                f"employment_type must be either 'Permanent' or 'Contract' (or {VALID_EMPLOYMENT_TYPES}), got '{emp_type}'"
            )


def _validate_education(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate education type frontmatter schema."""
    edu_required = {"type", "title", "institution", "dates", "status", "major", "minor"}
    missing = edu_required - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

    inst_raw = fm.get("institution", "")
    if not _has_wikilink_syntax(inst_raw):
        errors.append(f"institution field missing [[slug]] syntax: '{inst_raw}'")

    _validate_dates(fm.get("dates"), errors)
    if not errors:
        try:
            EducationFrontmatter.model_validate(fm)
        except ValidationError as exc:
            errors.extend(err["msg"] for err in exc.errors())


def _validate_skill(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate skill type frontmatter schema (supporting both string and list categories)."""
    skill_required = {"type", "title", "category", "proficiency"}
    missing = skill_required - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

    category_raw = fm.get("category", "")
    cat_list = [category_raw] if isinstance(category_raw, str) else (category_raw if isinstance(category_raw, list) else [])
    if not cat_list:
        errors.append(f"Invalid skill category: '{category_raw}'")
    else:
        for cat in cat_list:
            if str(cat) not in VALID_SKILL_CATEGORIES:
                errors.append(f"Invalid skill category: '{cat}'")
    if not errors:
        try:
            SkillFrontmatter.model_validate(fm)
        except ValidationError as exc:
            errors.extend(err["msg"] for err in exc.errors())


def _validate_language(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate language type frontmatter schema."""
    lang_required = {"type", "title", "proficiency"}
    missing = lang_required - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")
    if not errors:
        try:
            LanguageFrontmatter.model_validate(fm)
        except ValidationError as exc:
            errors.extend(err["msg"] for err in exc.errors())


def _validate_project(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate project type frontmatter schema."""
    nature = str(fm.get("project_nature", "")).lower()
    is_independent = nature in ("open_source", "side_project", "research_prototype")
    proj_required = {"type", "title", "dates", "skills"} if is_independent else {"type", "title", "organization", "dates", "skills"}
    missing = proj_required - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

    org_raw = fm.get("organization", "")
    if org_raw or not is_independent:
        if not _has_wikilink_syntax(org_raw):
            errors.append(f"organization field missing [[slug]] syntax: '{org_raw}'")

    _validate_dates(fm.get("dates"), errors)
    if not errors:
        try:
            ProjectFrontmatter.model_validate(fm)
        except ValidationError as exc:
            errors.extend(err["msg"] for err in exc.errors())


def _validate_patent(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate patent type frontmatter schema."""
    pat_required = {"type", "title", "id", "inventors", "organization", "skills"}
    missing = pat_required - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

    org_raw = fm.get("organization", "")
    if not _has_wikilink_syntax(org_raw):
        errors.append(f"organization field missing [[slug]] syntax: '{org_raw}'")
    if not errors:
        try:
            PatentFrontmatter.model_validate(fm)
        except ValidationError as exc:
            errors.extend(err["msg"] for err in exc.errors())


def _validate_publication(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate publication type frontmatter schema."""
    pub_required = {"type", "title"}
    missing = pub_required - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")
    if not errors:
        try:
            PublicationFrontmatter.model_validate(fm)
        except ValidationError as exc:
            errors.extend(err["msg"] for err in exc.errors())


def _validate_note(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate note type frontmatter schema."""
    note_required = {"type", "title", "related", "perspective", "tags"}
    missing = note_required - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")
    if not errors:
        try:
            NoteFrontmatter.model_validate(fm)
        except ValidationError as exc:
            errors.extend(err["msg"] for err in exc.errors())


def _validate_cover_letter(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate cover letter type frontmatter schema."""
    cl_required = {"type", "title", "target_organization", "related_synthesis"}
    missing = cl_required - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

    org_raw = fm.get("target_organization", "")
    if not _has_wikilink_syntax(org_raw):
        errors.append(f"target_organization field missing [[slug]] syntax: '{org_raw}'")
    if not errors:
        try:
            CoverLetterFrontmatter.model_validate(fm)
        except ValidationError as exc:
            errors.extend(err["msg"] for err in exc.errors())


def _validate_entity(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate entity type frontmatter schema."""
    entity_required = {"type", "title", "tags", "sources"}
    missing = entity_required - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")
    if not errors:
        try:
            EntityFrontmatter.model_validate(fm)
        except ValidationError as exc:
            errors.extend(err["msg"] for err in exc.errors())


def _validate_case_study(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate case study type frontmatter schema."""
    cs_required = {"type", "title"}
    missing = cs_required - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")
    if not errors:
        try:
            CaseStudyFrontmatter.model_validate(fm)
        except ValidationError as exc:
            errors.extend(err["msg"] for err in exc.errors())


def _validate_by_type(page_type: str, fm: dict[str, Any], errors: list[str]) -> None:
    """Invokes the specific validator function based on page_type."""
    validators = {
        "experience": _validate_experience,
        "education": _validate_education,
        "skill": _validate_skill,
        "language": _validate_language,
        "project": _validate_project,
        "patent": _validate_patent,
        "publication": _validate_publication,
        "note": _validate_note,
        "case_study": _validate_case_study,
        "cover-letter": _validate_cover_letter,
        "entity": _validate_entity,
    }
    validator = validators.get(page_type)
    if validator:
        validator(fm, errors)
    else:
        errors.append(f"Unknown frontmatter type: '{page_type}'")


def _validate_single_output(output: dict[str, Any]) -> dict[str, Any]:
    """Validates the frontmatter and content of a single wiki output."""
    errors: list[str] = list(output.get("validation_errors", []))
    content = clean_frontmatter(output.get("content", ""))
    output["content"] = content

    if not content:
        errors.append("Empty content — generation may have failed")
        return {**output, "validation_errors": errors}

    fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not fm_match:
        errors.append("No valid YAML frontmatter block found")
    else:
        try:
            fm = yaml.safe_load(fm_match.group(1)) or {}
            page_type = fm.get("type", "unknown") if isinstance(fm, dict) else "unknown"
            if isinstance(fm, dict):
                _validate_by_type(str(page_type), fm, errors)
            else:
                errors.append("YAML frontmatter must be a mapping")
        except yaml.YAMLError as e:
            errors.append(f"YAML parse error: {e}")

    if errors:
        logging.warning(f"Validation issues for {output['path']}: {errors}")
    else:
        logging.info(f"Validation passed: {output['path']}")

    return {**output, "validation_errors": errors}
