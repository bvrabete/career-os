"""Applications CRM registry for tracking tailored CV generations and job applications."""
import logging
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from utils import validate_path

logger = logging.getLogger(__name__)

CRM_FILE_NAME = "applications.yaml"


def _get_crm_path(wiki_dir: Path) -> Path:
    """Resolve and validate the path to applications.yaml."""
    validated_dir = validate_path(wiki_dir)
    wiki_root = validated_dir / "wiki" if (validated_dir / "wiki").is_dir() else validated_dir
    return validate_path(wiki_root / CRM_FILE_NAME)


def load_applications(wiki_dir: Path) -> list[dict[str, Any]]:
    """Load the list of job applications from applications.yaml."""
    crm_path = _get_crm_path(wiki_dir)
    if not crm_path.exists():
        return []

    try:
        data = yaml.safe_load(crm_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "applications" in data:
            apps = data["applications"]
            return apps if isinstance(apps, list) else []
        elif isinstance(data, list):
            return data
    except Exception as e:
        logger.warning(f"Error loading applications CRM at {crm_path}: {e}")

    return []


def save_applications(wiki_dir: Path, applications: list[dict[str, Any]]) -> Path:
    """Save the applications list to applications.yaml."""
    crm_path = _get_crm_path(wiki_dir)
    data = {"applications": applications}
    crm_path.write_text(yaml.dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    logger.info(f"Saved {len(applications)} application records to {crm_path}")
    return crm_path


def _is_matching_entry(entry: dict[str, Any], company: str, role: str, today_str: str) -> bool:
    """Determine if a CRM entry matches the same company, role, and date."""
    entry_company = str(entry.get("company", "")).strip().lower()
    entry_role = str(entry.get("job_title", entry.get("role", ""))).strip().lower()
    entry_date = str(entry.get("date", "")).strip()

    return (
        entry_company == company.strip().lower()
        and entry_role == role.strip().lower()
        and entry_date == today_str
    )


def record_application(
    wiki_dir: Path,
    app_record: dict[str, Any]
) -> dict[str, Any]:
    """
    Record or update a tailored CV generation in applications.yaml.
    Performs same-day, same-company in-place overwrite to prevent duplicate clutter.
    """
    company = str(app_record.get("company", "unknown"))
    role = str(app_record.get("job_title", app_record.get("role", "unknown")))
    today_str = app_record.get("date", date.today().isoformat())

    normalized_record = {
        "company": company,
        "job_title": role,
        "date": today_str,
        "status": app_record.get("status", "drafted"),
        "strategy": app_record.get("strategy", ""),
        "ats_score": app_record.get("ats_score", None),
        "output_markdown": app_record.get("output_markdown", ""),
        "output_pdf": app_record.get("output_pdf", None),
        "output_docx": app_record.get("output_docx", None),
    }

    if "notes" in app_record and app_record["notes"]:
        normalized_record["notes"] = app_record["notes"]

    applications = load_applications(wiki_dir)
    updated = False

    for idx, existing in enumerate(applications):
        if _is_matching_entry(existing, company, role, today_str):
            applications[idx] = {**existing, **normalized_record}
            updated = True
            logger.info(f"Overwrote existing CRM entry for {company} - {role} ({today_str})")
            break

    if not updated:
        applications.append(normalized_record)
        logger.info(f"Appended new CRM entry for {company} - {role} ({today_str})")

    save_applications(wiki_dir, applications)
    return normalized_record
