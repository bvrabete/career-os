"""Grouping, consolidation, and tenure segmentation for company experiences."""

import datetime
import logging
from pathlib import Path
import re
from typing import Any
import yaml
from generation.formatting import BRACKET_LINK_PATTERN
from generation.retrieval import _parse_yaml_frontmatter_from_text

logger = logging.getLogger(__name__)


def _extract_start_year(fm: dict[str, Any]) -> str:
    """Extract start year as string from frontmatter."""
    start_val = ""
    dates = fm.get("dates")
    if isinstance(dates, dict):
        start_val = str(dates.get("start", "")).strip()
    elif fm.get("start"):
        start_val = str(fm.get("start", "")).strip()
    elif isinstance(dates, (str, int)):
        start_val = str(dates).strip()

    if start_val:
        return start_val[:4]
    return ""


def _is_old_role(fm: dict[str, Any]) -> bool:
    """Check if the career entry starts before or at current_year - 10 (old role)."""
    start_year = _extract_start_year(fm)
    current_year = datetime.datetime.now().year
    return bool(start_year and start_year.isdigit() and int(start_year) <= (current_year - 10))


def _detect_employment_type(fm: dict[str, Any], content: str) -> str:
    """Detect if the role is Contract, Permanent, or Self-Employed based on YAML frontmatter, tags, title, or body."""
    emp_type = fm.get("employment_type")
    if emp_type:
        emp_type_str = str(emp_type).strip().capitalize()
        if emp_type_str in ["Contract", "Permanent", "Self-employed"]:
            return emp_type_str

    tags = [str(t).lower() for t in fm.get("tags", [])]
    tracks = [str(tr).lower() for tr in fm.get("tracks", [])]
    title = str(fm.get("title", "")).lower()

    if "co-founder" in tags or "co-founder" in tracks or "entrepreneurial" in tracks or any(x in title for x in ["co-founder", "cofounder", "co founder"]):
        return "Self-Employed"

    if "contract" in tags or "contract" in title:
        return "Contract"

    first_lines = "\n".join(content.splitlines()[:10]).lower()
    if "(contract)" in first_lines or "contractor" in first_lines:
        return "Contract"

    return "Permanent"


def _extract_start_date_normalized(fm: dict[str, Any]) -> str:
    """Extract start date as normalized YYYY-MM-DD string from frontmatter."""
    start_val = ""
    dates = fm.get("dates")
    if isinstance(dates, dict):
        start_val = str(dates.get("start", "")).strip()
    elif fm.get("start"):
        start_val = str(fm.get("start", "")).strip()
    elif isinstance(dates, (str, int)):
        start_val = str(dates).strip()

    if start_val:
        parts = start_val.split('-')
        if len(parts) == 3:
            try:
                year = int(parts[0])
                month = int(parts[1])
                day = int(parts[2])
                return f"{year:04d}-{month:02d}-{day:02d}"
            except Exception:
                pass
        elif len(parts) == 2:
            try:
                year = int(parts[0])
                month = int(parts[1])
                return f"{year:04d}-{month:02d}-01"
            except Exception:
                pass
        elif len(start_val) >= 4 and start_val[:4].isdigit():
            return f"{start_val[:4]}-01-01"
    return "1970-01-01"


def _is_parallel_startup_track(fm: dict[str, Any]) -> bool:
    """Check if the role is a parallel startup/co-founding track."""
    title = str(fm.get("title", "")).lower()
    tags = [str(t).lower() for t in fm.get("tags", [])]
    tracks = [str(tr).lower() for tr in fm.get("tracks", [])]

    if "co-founder" in tags or "co-founder" in tracks or "entrepreneurial" in tracks:
        return True
    if any(x in title for x in ["co-founder", "cofounder", "co founder"]):
        return True
    return False


def _get_org_slug(name: str, fm: dict[str, Any]) -> str:
    """Extract canonical organization name or slug from frontmatter or filename, normalized for grouping."""
    org_raw = fm.get("organization")
    if isinstance(org_raw, list):
        org_str = " ".join(str(x) for x in org_raw)
    elif org_raw:
        org_str = str(org_raw)
    else:
        org_str = name.replace(".md", "").split("-")[0]

    org_str = BRACKET_LINK_PATTERN.sub(r'\1', org_str)
    org_clean = org_str.strip().lower()
    org_clean = re.sub(r'[^a-z0-9\s\-]', '', org_clean)
    org_clean = re.sub(r'[\s\_]+', '-', org_clean)
    return org_clean


def _split_recent_and_old_experiences(
    deduplicated: list[tuple[int, str, str, str]]
) -> tuple[list[tuple[int, str, str, str]], dict[str, list[tuple[tuple[int, str, str, str], dict[str, Any]]]]]:
    """Split deduplicated scored experiences into recent list and old grouped by organization."""
    from collections import defaultdict
    recent_entries: list[tuple[int, str, str, str]] = []
    old_entries_by_org = defaultdict(list)

    for item in deduplicated:
        _, name, content, _ = item
        fm = _parse_yaml_frontmatter_from_text(content)
        if _is_old_role(fm):
            org = _get_org_slug(name, fm)
            old_entries_by_org[org].append((item, fm))
        else:
            recent_entries.append(item)

    return recent_entries, dict(old_entries_by_org)


def _extract_end_date_normalized(fm: dict[str, Any]) -> str:
    """Extract and normalize end date from frontmatter."""
    dates = fm.get("dates")
    end_val = ""
    if isinstance(dates, dict):
        end_val = str(dates.get("end", "")).strip()
    elif fm.get("end"):
        end_val = str(fm.get("end", "")).strip()
    elif isinstance(dates, (str, int)):
        end_val = str(dates).strip()

    if not end_val or end_val.lower() == "present":
        return datetime.datetime.now().strftime("%Y-%m-%d")

    parts = end_val.split('-')
    if len(parts) == 3:
        return end_val
    if len(parts) == 2:
        return f"{parts[0]}-{parts[1]}-28"
    if len(end_val) >= 4 and end_val[:4].isdigit():
        return f"{end_val[:4]}-12-31"
    return "1970-01-01"


def _build_combined_body(roles_with_fm: list[tuple[tuple[int, str, str, str], dict[str, Any]]]) -> str:
    """Build a unified body text from a list of experiences with frontmatter."""
    body_parts = []
    for item, fm in roles_with_fm:
        title = fm.get("title", item[1])
        start_year = _extract_start_date_normalized(fm)[:4]

        dates_val = fm.get("dates")
        end_str = "Present"
        if isinstance(dates_val, dict):
            end_str = str(dates_val.get("end", "Present"))
        elif fm.get("end"):
            end_str = str(fm.get("end", "Present"))
        end_year = end_str[:4] if end_str else "Present"

        raw_body = re.sub(r'^---\n.*?\n---', '', item[2], flags=re.DOTALL).strip()
        clean_body = re.sub(r'<!--.*?-->', '', raw_body, flags=re.DOTALL).strip()

        body_parts.append(
            f"### ROLE: {title}\n"
            f"DATES: {start_year} to {end_year}\n"
            f"BODY:\n{clean_body}\n"
        )
    return "\n\n".join(body_parts)


def _consolidate_company_roles(
    org: str,
    roles_with_fm: list[tuple[tuple[int, str, str, str], dict[str, Any]]]
) -> tuple[int, str, str, str]:
    """Consolidate multiple old experiences at the same company into a single tuple."""
    roles_with_fm.sort(
        key=lambda x: _extract_start_date_normalized(x[1]),
        reverse=True
    )

    max_score = max(x[0][0] for x in roles_with_fm)
    grouped_name = f"grouped-{org}.md"

    justifications = [f"[{x[0][1]}]: {x[0][3]}" for x in roles_with_fm if x[0][3] and x[0][3] != "N/A"]
    combined_justification = " | ".join(justifications) if justifications else "Consolidated historical roles."

    earliest_start = min(_extract_start_date_normalized(x[1]) for x in roles_with_fm)
    latest_end = max(_extract_end_date_normalized(x[1]) for x in roles_with_fm)

    all_skills = []
    for _, fm in roles_with_fm:
        all_skills.extend(fm.get("skills", []))
    seen_skills = set()
    unique_skills = []
    for sk in all_skills:
        sk_clean = str(sk).strip()
        if sk_clean and sk_clean.lower() not in seen_skills:
            seen_skills.add(sk_clean.lower())
            unique_skills.append(sk_clean)

    most_recent_fm = roles_with_fm[0][1]
    org_display = most_recent_fm.get("organization", org.capitalize())
    location = most_recent_fm.get("location", "Unknown")
    emp_type = _detect_employment_type(most_recent_fm, roles_with_fm[0][0][2])

    titles = [fm.get("title", "") for _, fm in roles_with_fm if fm.get("title")]
    combined_title = " / ".join(titles) if len(" / ".join(titles)) <= 80 else titles[0]

    grouped_fm = {
        "type": "experience",
        "title": combined_title,
        "organization": org_display,
        "location": location,
        "dates": {"start": earliest_start, "end": latest_end},
        "skills": unique_skills,
        "employment_type": emp_type
    }

    grouped_fm_str = yaml.dump(grouped_fm, sort_keys=False)
    combined_body = _build_combined_body(roles_with_fm)
    combined_content = f"---\n{grouped_fm_str}---\n\n{combined_body}"

    return max_score, grouped_name, combined_content, combined_justification


def _group_old_experiences_by_company(
    deduplicated: list[tuple[int, str, str, str]]
) -> list[tuple[int, str, str, str]]:
    """Group multiple old experiences at the same company before compression."""
    recent_entries, old_entries_by_org = _split_recent_and_old_experiences(deduplicated)
    grouped_entries: list[tuple[int, str, str, str]] = []

    for org, roles_with_fm in old_entries_by_org.items():
        if len(roles_with_fm) == 1:
            grouped_entries.append(roles_with_fm[0][0])
        else:
            consolidated = _consolidate_company_roles(org, roles_with_fm)
            grouped_entries.append(consolidated)

    def get_start_date(item: tuple[int, str, str, str]) -> str:
        fm = _parse_yaml_frontmatter_from_text(item[2])
        return _extract_start_date_normalized(fm)

    grouped_entries.sort(key=get_start_date, reverse=True)
    return recent_entries + grouped_entries
