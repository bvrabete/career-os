"""Schema validation routines for wiki entities produced by the ingestion pipeline."""
import logging
import re
from typing import Any

import yaml

from ingestion.helpers import clean_frontmatter

DATE_PATTERN = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$|^Present$")


def _validate_dates(dates: Any, errors: list[str]) -> None:
    """Validate start and end fields in frontmatter dates dictionary."""
    if isinstance(dates, dict):
        for field in ("start", "end"):
            raw_val = str(dates.get(field, ""))
            val = raw_val.split()[0] if raw_val else ""
            if val and not DATE_PATTERN.match(val):
                errors.append(f"dates.{field} invalid format: '{raw_val}'")


def _validate_experience(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate experience type frontmatter schema."""
    EXP_REQUIRED = {"type", "title", "organization", "dates", "tracks", "skills"}
    missing = EXP_REQUIRED - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

    org = str(fm.get("organization", ""))
    if "[[" not in org or "]]" not in org:
        errors.append(f"organization field missing [[slug]] syntax: '{org}'")

    _validate_dates(fm.get("dates"), errors)

    emp_type = fm.get("employment_type")
    if emp_type and str(emp_type).strip().capitalize() not in ("Permanent", "Contract"):
        errors.append(f"employment_type must be either 'Permanent' or 'Contract', got '{emp_type}'")


def _validate_education(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate education type frontmatter schema."""
    EDU_REQUIRED = {"type", "title", "institution", "dates", "status", "major", "minor"}
    missing = EDU_REQUIRED - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

    inst = str(fm.get("institution", ""))
    if "[[" not in inst or "]]" not in inst:
        errors.append(f"institution field missing [[slug]] syntax: '{inst}'")

    _validate_dates(fm.get("dates"), errors)


def _validate_skill(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate skill type frontmatter schema."""
    SKILL_REQUIRED = {"type", "title", "category", "proficiency"}
    missing = SKILL_REQUIRED - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

    category = fm.get("category", "")
    valid_categories = ("Language-Code", "Framework", "Infrastructure", "Leadership", "Spoken-Language")
    if category not in valid_categories:
        errors.append(f"Invalid skill category: '{category}'")


def _validate_language(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate language type frontmatter schema."""
    LANG_REQUIRED = {"type", "title", "proficiency"}
    missing = LANG_REQUIRED - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")


def _validate_project(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate project type frontmatter schema."""
    PROJ_REQUIRED = {"type", "title", "organization", "dates", "skills"}
    missing = PROJ_REQUIRED - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

    org = str(fm.get("organization", ""))
    if "[[" not in org or "]]" not in org:
        errors.append(f"organization field missing [[slug]] syntax: '{org}'")

    _validate_dates(fm.get("dates"), errors)


def _validate_patent(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate patent type frontmatter schema."""
    PAT_REQUIRED = {"type", "title", "id", "inventors", "organization", "skills"}
    missing = PAT_REQUIRED - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

    org = str(fm.get("organization", ""))
    if "[[" not in org or "]]" not in org:
        errors.append(f"organization field missing [[slug]] syntax: '{org}'")


def _validate_note(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate note type frontmatter schema."""
    NOTE_REQUIRED = {"type", "title", "related", "perspective", "tags"}
    missing = NOTE_REQUIRED - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")


def _validate_cover_letter(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate cover letter type frontmatter schema."""
    CL_REQUIRED = {"type", "title", "target_organization", "related_synthesis"}
    missing = CL_REQUIRED - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

    org = str(fm.get("target_organization", ""))
    if "[[" not in org or "]]" not in org:
        errors.append(f"target_organization field missing [[slug]] syntax: '{org}'")


def _validate_entity(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate entity type frontmatter schema."""
    ENTITY_REQUIRED = {"type", "title", "tags", "sources"}
    missing = ENTITY_REQUIRED - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")


def _validate_by_type(page_type: str, fm: dict[str, Any], errors: list[str]) -> None:
    """Invokes the specific validator function based on page_type."""
    validators = {
        "experience": _validate_experience,
        "education": _validate_education,
        "skill": _validate_skill,
        "language": _validate_language,
        "project": _validate_project,
        "patent": _validate_patent,
        "note": _validate_note,
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
            page_type = fm.get("type", "unknown")
            _validate_by_type(page_type, fm, errors)
        except yaml.YAMLError as e:
            errors.append(f"YAML parse error: {e}")

    if errors:
        logging.warning(f"Validation issues for {output['path']}: {errors}")
    else:
        logging.info(f"Validation passed: {output['path']}")

    return {**output, "validation_errors": errors}
