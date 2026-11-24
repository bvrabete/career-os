"""Grouping, consolidation, and tenure segmentation for company experiences."""

from collections import defaultdict
import datetime
import logging
import re
from typing import Any
import yaml
from generation.formatting import BRACKET_LINK_PATTERN
from generation.retrieval import _parse_yaml_frontmatter_from_text
from utils import extract_wikilink_slug

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


def _parse_date_safe(date_str: str, fallback: datetime.date) -> datetime.date:
    """Parse YYYY-MM-DD safely with fallback."""
    try:
        return datetime.datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except Exception:
        return fallback


def _is_anchor_tenure(
    fm: dict[str, Any], score: int = 0, min_years: float = 5.0, min_score: int = 75
) -> bool:
    """Return True if a role is a high-relevance multi-year anchor tenure that should not be 1-line compressed."""
    if score < min_score:
        return False
    today = datetime.date.today()
    start_dt = _parse_date_safe(_extract_start_date_normalized(fm), today)
    end_dt = _parse_date_safe(_extract_end_date_normalized(fm), today)
    duration_years = max(0.0, (end_dt - start_dt).days / 365.25)
    years_since_end = max(0, today.year - end_dt.year)
    return duration_years >= min_years and years_since_end <= 12


def _is_old_role(fm: dict[str, Any], score: int = 0) -> bool:
    """Check if the career entry ended before or at current_year - 10 (unless protected as an Anchor Tenure)."""
    if _is_anchor_tenure(fm, score=score):
        return False
    current_year = datetime.datetime.now().year
    dates = fm.get("dates")
    end_val = ""
    if isinstance(dates, dict) and dates.get("end") is not None:
        end_val = str(dates.get("end", "")).strip()
    elif fm.get("end") is not None:
        end_val = str(fm.get("end", "")).strip()

    if end_val:
        if end_val.lower() in {"present", "current", "ongoing"}:
            return False
        if len(end_val) >= 4 and end_val[:4].isdigit():
            return int(end_val[:4]) <= (current_year - 10)

    start_year = _extract_start_year(fm)
    return bool(start_year and start_year.isdigit() and int(start_year) <= (current_year - 10))


def _detect_employment_type(fm: dict[str, Any], content: str) -> str:
    """Detect if the role is Contract, Permanent, Startup / Co-Founder, or Advisory based on YAML frontmatter, tags, title, or body."""
    emp_type = fm.get("employment_type")
    if emp_type:
        emp_type_str = str(emp_type).strip()
        lowered = emp_type_str.lower().replace("-", " ").replace("_", " ")
        if lowered in ["contract", "contractor"]:
            return "Contract"
        if lowered in ["permanent", "full time", "fulltime"]:
            return "Permanent"
        if lowered in ["self employed", "co founder", "cofounder", "startup"]:
            return "Startup / Co-Founder"
        if lowered in ["advisory", "advisor"]:
            return "Advisory"
        if emp_type_str.capitalize() in ["Contract", "Permanent", "Self-employed"]:
            return emp_type_str.capitalize()
        return emp_type_str

    tags = [str(t).lower() for t in fm.get("tags", [])]
    tracks = [str(tr).lower() for tr in fm.get("tracks", [])]
    title = str(fm.get("title", "")).lower()
    is_cofounder_title = any(x in title for x in ["co-founder", "cofounder", "co founder"])
    if "co-founder" in tags or "co-founder" in tracks or "entrepreneurial" in tracks or is_cofounder_title:
        return "Startup / Co-Founder"

    if "advisory" in tags or "advisory" in tracks or "advisor" in title:
        return "Advisory"

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
    org_slug = extract_wikilink_slug(org_raw)
    if not org_slug:
        org_slug = name.replace(".md", "").split("-")[0]

    org_str = BRACKET_LINK_PATTERN.sub(r'\1', org_slug)
    org_clean = org_str.strip().lower()
    org_clean = re.sub(r'[^a-z0-9\s\-]', '', org_clean)
    org_clean = re.sub(r'[\s\_]+', '-', org_clean)
    return org_clean


def _split_recent_and_old_experiences(
    deduplicated: list[tuple[int, str, str, str]]
) -> tuple[list[tuple[int, str, str, str]], dict[str, list[tuple[tuple[int, str, str, str], dict[str, Any]]]]]:
    """Split deduplicated scored experiences into recent list and old grouped by organization."""
    recent_entries: list[tuple[int, str, str, str]] = []
    old_entries_by_org = defaultdict(list)

    for item in deduplicated:
        score, name, content, _ = item
        fm = _parse_yaml_frontmatter_from_text(content)
        if _is_old_role(fm, score=score):
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


def _overlap_days(s1: datetime.date, e1: datetime.date, s2: datetime.date, e2: datetime.date) -> int:
    """Return the number of overlapping days between two date intervals [s1, e1] and [s2, e2]."""
    return max(0, (min(e1, e2) - max(s1, s2)).days)


def _clamp_content_dates(content: str, start_dt: datetime.date, end_dt: datetime.date) -> str:
    """Update start and end dates in YAML frontmatter to reflect clamped non-overlapping tenure bounds."""
    s_str = start_dt.strftime("%Y-%m-%d")
    e_str = end_dt.strftime("%Y-%m-%d")
    updated = re.sub(r"(start:\s*['\"]?)\d{4}-\d{1,2}(?:-\d{1,2})?(['\"]?)", rf"\g<1>{s_str}\2", content, count=1)
    return re.sub(
        r"(end:\s*['\"]?)(?:\d{4}-\d{1,2}(?:-\d{1,2})?|Present|present)(['\"]?)",
        rf"\g<1>{e_str}\2",
        updated,
        count=1,
    )


def _clamp_venture_to_corporate_gap(
    s_v: datetime.date,
    e_v: datetime.date,
    corp_intervals: list[tuple[datetime.date, datetime.date, str]],
) -> tuple[datetime.date, datetime.date] | None:
    """Clamp a startup/venture interval against overlapping corporate roles; return None if <90 days remain."""
    cur_s, cur_e = s_v, e_v
    today = datetime.date.today()
    for c_s, c_e, c_type in corp_intervals:
        ov = _overlap_days(cur_s, cur_e, c_s, c_e)
        if ov <= 30:
            continue
        v_dur = max(1, (cur_e - cur_s).days)
        if c_type == "Permanent" and (today.year - c_e.year) <= 5 and (ov >= 180 or (ov / v_dur) >= 0.5):
            return None
        if c_s <= cur_s and c_e < cur_e:
            cur_s = c_e
        elif c_s > cur_s and c_e >= cur_e:
            cur_e = c_s
        elif c_s <= cur_s and c_e >= cur_e:
            return None
    if (cur_e - cur_s).days < 90:
        return None
    return cur_s, cur_e


def _filter_and_clamp_ventures(
    venture_roles: list[dict[str, Any]],
    all_corp_intervals: list[tuple[datetime.date, datetime.date, str]],
) -> list[dict[str, Any]]:
    """Clamp ventures against corporate gaps and disambiguate mutually overlapping ventures."""
    clamped_ventures: list[dict[str, Any]] = []
    for v in venture_roles:
        has_corp_overlap = any(_overlap_days(v["start"], v["end"], cs, ce) > 30 for cs, ce, _ in all_corp_intervals)
        if not has_corp_overlap:
            clamped_ventures.append(v)
            continue
        clamped_bounds = _clamp_venture_to_corporate_gap(v["start"], v["end"], all_corp_intervals)
        if clamped_bounds is None:
            logger.info("Timeline resolver: suppressed overlapping venture '%s' under strict_single_timeline.", v["name"])
            continue
        new_s, new_e = clamped_bounds
        if (new_s, new_e) != (v["start"], v["end"]):
            new_content = _clamp_content_dates(v["content"], new_s, new_e)
            v = {
                **v,
                "start": new_s,
                "end": new_e,
                "days": max(1, (new_e - new_s).days),
                "content": new_content,
                "item": (v["score"], v["name"], new_content, v["just"]),
            }
        clamped_ventures.append(v)

    clamped_ventures.sort(key=lambda r: (r["score"], r["days"]), reverse=True)
    accepted: list[dict[str, Any]] = []
    for v in clamped_ventures:
        if any(_overlap_days(v["start"], v["end"], av["start"], av["end"]) >= 60 for av in accepted):
            logger.info("Timeline resolver: suppressed redundant overlapping venture '%s'.", v["name"])
            continue
        accepted.append(v)
    return accepted


def _filter_subsumed_short_contracts(
    corp_roles: list[dict[str, Any]],
    accepted_ventures: list[dict[str, Any]],
    min_contract_score: int,
) -> list[dict[str, Any]]:
    """Suppress short (<=185 day) low-relevance (<min_contract_score) contracts subsumed by another role."""
    retained_intervals = [(r["start"], r["end"], r["name"]) for r in accepted_ventures] + [
        (r["start"], r["end"], r["name"])
        for r in corp_roles
        if not (r["emp_type"] == "Contract" and r["days"] <= 185 and r["score"] < min_contract_score)
    ]
    final_corp: list[dict[str, Any]] = []
    for r in corp_roles:
        if r["emp_type"] == "Contract" and r["days"] <= 185 and r["score"] < min_contract_score:
            is_subsumed = any(
                other_name != r["name"] and _overlap_days(r["start"], r["end"], os, oe) >= int(r["days"] * 0.8)
                for os, oe, other_name in retained_intervals
            )
            if is_subsumed:
                logger.info(
                    "Timeline resolver: suppressed subsumed short contract '%s' (score %d < %d).",
                    r["name"],
                    r["score"],
                    min_contract_score,
                )
                continue
        final_corp.append(r)
    return final_corp


def resolve_timeline_conflicts(
    deduplicated: list[tuple[int, str, str, str]],
    parallel_venture_policy: str = "strict_single_timeline",
    min_contract_score: int = 25,
) -> list[tuple[int, str, str, str]]:
    """
    Generic interval-graph resolver for parallel startup tracks and subsumed low-score short contracts.
    Operates strictly on YAML frontmatter dates, employment_type, duration, and semantic relevance score.
    """
    if parallel_venture_policy != "strict_single_timeline" or len(deduplicated) <= 1:
        return deduplicated

    today = datetime.date.today()
    parsed_roles: list[dict[str, Any]] = []
    for item in deduplicated:
        score, name, content, just = item
        fm = _parse_yaml_frontmatter_from_text(content)
        emp_type = _detect_employment_type(fm, content)
        is_venture = _is_parallel_startup_track(fm) or emp_type in {"Startup / Co-Founder", "Self-employed"}
        s_dt = _parse_date_safe(_extract_start_date_normalized(fm), today)
        e_dt = _parse_date_safe(_extract_end_date_normalized(fm), today)
        parsed_roles.append({
            "item": item,
            "score": score,
            "name": name,
            "content": content,
            "just": just,
            "emp_type": emp_type,
            "is_venture": is_venture,
            "start": s_dt,
            "end": e_dt,
            "days": max(1, (e_dt - s_dt).days),
        })

    corp_roles = [r for r in parsed_roles if not r["is_venture"]]
    venture_roles = [r for r in parsed_roles if r["is_venture"]]
    all_corp_intervals = [(r["start"], r["end"], r["emp_type"]) for r in corp_roles]

    accepted_ventures = _filter_and_clamp_ventures(venture_roles, all_corp_intervals)
    final_corp = _filter_subsumed_short_contracts(corp_roles, accepted_ventures, min_contract_score)
    return [r["item"] for r in (final_corp + accepted_ventures)]
