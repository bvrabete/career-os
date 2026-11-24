"""Deterministic final-stage ATS & Executive CV renderer from StructuredCVDocument to Markdown."""

import logging
import re
from typing import Any

from docx_generator import normalize_markdown_tables
from generation.formatting import robust_json_loads
from schemas.cv_models import (
    ContactHeader,
    CVRoleEntry,
    EducationItem,
    LanguageItem,
    PatentOrPublicationItem,
    ProjectItem,
    SkillCategory,
    StructuredCVDocument,
)

logger = logging.getLogger(__name__)

SLASH_VERB_MAP = {
    "Architected/deployed": "Architected and deployed",
    "Architected/implemented": "Architected and implemented",
    "Architected/launched": "Architected and launched",
    "Engineered/automated": "Engineered and automated",
    "Negotiated/executed": "Negotiated and executed",
    "Designed/implemented": "Designed and implemented",
    "Built/deployed": "Built and deployed",
}


def _clean_slash_verbs(text: str) -> str:
    """Replace mechanical slash-joined leading verbs (e.g. Architected/deployed) with natural phrasing."""
    cleaned = text.strip()
    for bad, good in SLASH_VERB_MAP.items():
        if cleaned.startswith(bad):
            cleaned = good + cleaned[len(bad):]
    return re.sub(r"^([A-Z][a-z]+ed)/([a-z]+ed)\b", r"\1 and \2", cleaned)


def _format_clickable_url(raw: str) -> str:
    """Format a bare URL or email into a Markdown hyperlink [label](url)."""
    val = raw.strip().strip("*")
    if not val:
        return ""
    if "[" in val and "](" in val:
        return val
    if "@" in val and " " not in val and not val.startswith("mailto:"):
        return f"[{val}](mailto:{val})"
    if any(domain in val.lower() for domain in ["linkedin.com", "github.com", "gitlab.com", "http://", "https://"]):
        url = val if val.startswith(("http://", "https://")) else f"https://{val}"
        label = re.sub(r"^https?://(?:www\.)?", "", url).rstrip("/")
        return f"[{label}]({url})"
    return f"**{val}**"


def _render_header(contact: ContactHeader) -> list[str]:
    """Render # Full Name and clickable contact line."""
    name = contact.full_name.strip().lstrip("# ").strip() or "Candidate"
    lines = [f"# {name}"]
    parts: list[str] = []
    if contact.location.strip():
        parts.append(f"**{contact.location.strip().strip('*')}**")
    if contact.phone.strip():
        parts.append(f"**{contact.phone.strip().strip('*')}**")
    if contact.email.strip():
        parts.append(_format_clickable_url(contact.email))
    if contact.linkedin_url.strip():
        parts.append(_format_clickable_url(contact.linkedin_url))
    if contact.github_url.strip():
        parts.append(_format_clickable_url(contact.github_url))
    if contact.portfolio_url.strip():
        parts.append(_format_clickable_url(contact.portfolio_url))
    if parts:
        lines.append(" | ".join(parts))
    return lines


def _render_summary(summary: str) -> list[str]:
    """Render ## Professional Summary."""
    clean = summary.strip()
    if not clean:
        return []
    return ["## Professional Summary", clean]


def _render_key_skills(categories: list[SkillCategory]) -> list[str]:
    """Render ## Key Skills as ATS-safe categorized bullet lines (never pipe tables)."""
    valid = [c for c in categories if c.category.strip() and c.skills]
    if not valid:
        return []
    lines = ["## Key Skills"]
    for cat in valid:
        cat_name = cat.category.strip().strip("*:")
        if cat_name.lower() == "languages":
            continue
        skills_str = ", ".join(s.strip() for s in cat.skills if s.strip())
        if skills_str:
            lines.append(f"- **{cat_name}:** {skills_str}")
    return lines if len(lines) > 1 else []


def _render_single_role(role: CVRoleEntry) -> list[str]:
    """Render a single role entry with clean H3 Title — Company and **Location** | **Dates** subtitle."""
    title_clean = role.title.strip().lstrip("# ").strip()
    org_clean = role.organization.strip()
    if org_clean and org_clean.lower() not in title_clean.lower():
        heading = f"### {title_clean} — {org_clean}"
    else:
        heading = f"### {title_clean}"

    lines = [heading]
    meta_parts: list[str] = []
    if role.location.strip():
        meta_parts.append(f"**{role.location.strip().strip('*')}**")
    if role.dates_display.strip():
        meta_parts.append(f"**{role.dates_display.strip().strip('*')}**")

    emp_type = role.employment_type.strip()
    emp_suffix = ""
    if emp_type and emp_type.lower() not in {"permanent", "full-time", "full time", ""}:
        clean_emp = emp_type.strip("()* ")
        emp_suffix = f" *({clean_emp})*"

    if meta_parts:
        lines.append(" | ".join(meta_parts) + emp_suffix)

    scope = role.scope_summary.strip()
    bullets = [_clean_slash_verbs(b) for b in role.bullets if b.strip()]

    if scope and not bullets:
        # Ensure every role has at least 1 ATS-parseable bullet item
        lines.append(f"- {_clean_slash_verbs(scope)}")
    else:
        if scope:
            lines.append(scope)
        for b in bullets:
            lines.append(f"- {b}")

    if role.technologies:
        tech_str = ", ".join(t.strip().rstrip(".") for t in role.technologies if t.strip())
        if tech_str:
            lines.append(f"*Technologies: {tech_str}.*")

    return lines


def _render_work_experience(
    roles: list[CVRoleEntry], earlier_roles: list[CVRoleEntry]
) -> list[str]:
    """Render ## Work Experience with ATS-parseable H3 headers for both primary and historical roles."""
    if not roles and not earlier_roles:
        return []
    lines = ["## Work Experience"]
    for idx, role in enumerate(roles):
        if idx > 0:
            lines.append("")
        lines.extend(_render_single_role(role))

    for role in earlier_roles:
        if len(lines) > 1:
            lines.append("")
        lines.extend(_render_single_role(role))

    return lines


def _render_patents(items: list[PatentOrPublicationItem]) -> list[str]:
    """Render ## Patents & Publications."""
    if not items:
        return []
    lines = ["## Patents & Publications"]
    for item in items:
        ident = item.identifier.strip().strip("*:")
        title = item.title.strip()
        org_yr = ", ".join(p for p in [item.organization.strip(), item.year.strip()] if p)
        qual = f" ({org_yr})" if org_yr else ""
        if ident and ident.lower() not in {"publication", "whitepaper", "paper"}:
            lines.append(f"- **{ident}{qual}:** {title}")
        else:
            lines.append(f"- {title}{qual}")
    return lines


def _render_projects(items: list[ProjectItem]) -> list[str]:
    """Render ## Selected Projects with clickable URLs."""
    if not items:
        return []
    lines = ["## Selected Projects"]
    for proj in items:
        title = proj.title.strip().strip("*:")
        nature = f" ({proj.nature.strip()})" if proj.nature.strip() and proj.nature.strip() not in title else ""
        desc = proj.description.strip()
        url_part = f" ({_format_clickable_url(proj.url)})" if proj.url.strip() else ""
        lines.append(f"- **{title}{nature}:** {desc}{url_part}")
    return lines


def _render_education(items: list[EducationItem]) -> list[str]:
    """Render ## Education."""
    if not items:
        return []
    lines = ["## Education"]
    for edu in items:
        deg = edu.degree.strip().strip("*")
        inst = edu.institution.strip()
        loc = f", {edu.location.strip()}" if edu.location.strip() and edu.location.strip() not in inst else ""
        yr = f" ({edu.year.strip()})" if edu.year.strip() else ""
        if inst:
            lines.append(f"- **{deg}** — {inst}{loc}{yr}")
        else:
            lines.append(f"- **{deg}**{loc}{yr}")
    return lines


def _normalize_language_proficiency(proficiency: str, cefr: str) -> str:
    """Normalize CEFR C2/C1/B2 labels for executive HR & ATS clarity."""
    prof_clean = proficiency.strip()
    cefr_clean = cefr.strip().upper().strip("()")
    if not cefr_clean:
        cefr_match = re.search(r"\b([ABC][12])\b", prof_clean)
        if cefr_match:
            cefr_clean = cefr_match.group(1)
            prof_clean = re.sub(r"\s*\(?[ABC][12]\)?", "", prof_clean).strip(" ,-")

    if cefr_clean == "C2" and prof_clean.lower() in {"proficient", "fluent", ""}:
        prof_clean = "Full Professional Proficiency"
    elif cefr_clean == "C1" and prof_clean.lower() in {"proficient", "advanced", ""}:
        prof_clean = "Advanced Professional Proficiency"
    elif cefr_clean == "B2" and prof_clean.lower() in {"intermediate", ""}:
        prof_clean = "Independent Working Proficiency"
    elif cefr_clean in {"A1", "A2"} and prof_clean.lower() == "beginner":
        prof_clean = "Elementary Proficiency"

    if cefr_clean and cefr_clean not in prof_clean:
        return f"{prof_clean} ({cefr_clean})" if prof_clean else cefr_clean
    return prof_clean or "Working Proficiency"


def _render_languages(items: list[LanguageItem]) -> list[str]:
    """Render dedicated ## Languages section for European/global ATS parsers."""
    if not items:
        return []
    lines = ["## Languages"]
    for item in items:
        lang = item.language.strip().strip("*:")
        if not lang:
            continue
        label = _normalize_language_proficiency(item.proficiency, item.cefr)
        lines.append(f"- **{lang}:** {label}")
    return lines if len(lines) > 1 else []


def render_ats_markdown(cv: StructuredCVDocument, strategy_region: str = "emea") -> str:
    """
    Deterministic Final-Stage Renderer: converts a validated StructuredCVDocument into
    100% ATS-safe, executive-grade Markdown without any LLM formatting involvement.
    """
    blocks: list[list[str]] = []
    header_block = _render_header(cv.contact)
    if header_block:
        blocks.append(header_block)

    section_map: dict[str, list[str]] = {
        "summary": _render_summary(cv.professional_summary),
        "skills": _render_key_skills(cv.skill_categories),
        "experience": _render_work_experience(cv.experience_roles, cv.earlier_career_roles),
        "patents": _render_patents(cv.patents_and_publications),
        "projects": _render_projects(cv.selected_projects),
        "education": _render_education(cv.education),
        "languages": _render_languages(cv.languages),
    }

    region_norm = (strategy_region or "emea").strip().lower()
    if region_norm in {"netherlands", "nl"}:
        order = ["summary", " key_skills_first", "experience", "patents", "projects", "education", "languages"]
        # Keep Key Skills right after Summary for immediate ATS/Recruiter scanning while keeping dedicated Languages at end
        order = ["summary", "skills", "experience", "patents", "projects", "education", "languages"]
    else:
        order = ["summary", "skills", "experience", "patents", "projects", "education", "languages"]

    for key in order:
        sec_lines = section_map.get(key, [])
        if sec_lines:
            blocks.append(sec_lines)

    return "\n\n".join("\n".join(b) for b in blocks).strip() + "\n"


def compute_structured_cv_metrics(cv: StructuredCVDocument) -> tuple[int, int]:
    """Compute exact total words and total achievement bullet count from a StructuredCVDocument."""
    rendered = render_ats_markdown(cv)
    words = len(rendered.split())
    exp_bullets = sum(len(r.bullets) or (1 if r.scope_summary else 0) for r in cv.experience_roles)
    early_bullets = sum(len(r.bullets) or (1 if r.scope_summary else 0) for r in cv.earlier_career_roles)
    return words, exp_bullets + early_bullets


def compress_structured_cv_deterministically(
    cv: StructuredCVDocument, max_pages: int
) -> StructuredCVDocument:
    """Deterministically prune excess bullets from lower-priority roles to fit page budget without altering headers."""
    max_bullets_per_recent = 4 if max_pages == 1 else (7 if max_pages >= 3 else 5)
    for idx, role in enumerate(cv.experience_roles):
        cap = max_bullets_per_recent if idx == 0 else max(2, max_bullets_per_recent - 1)
        if len(role.bullets) > cap:
            role.bullets = role.bullets[:cap]
    for role in cv.earlier_career_roles:
        if len(role.bullets) > 1:
            role.bullets = role.bullets[:1]
    return cv


def parse_and_render_structured_cv(
    raw_content: str, region: str = "emea", max_pages: int | None = None
) -> tuple[dict[str, Any] | None, str]:
    """Validate StructuredCVDocument JSON if present and deterministically render ATS-safe Markdown."""
    if "{" in raw_content and "}" in raw_content:
        try:
            data = robust_json_loads(raw_content)
            if isinstance(data, dict) and any(
                k in data for k in ("professional_summary", "experience_roles", "skill_categories")
            ):
                cv_doc = StructuredCVDocument.model_validate(data)
                if max_pages is not None:
                    cv_doc = compress_structured_cv_deterministically(cv_doc, max_pages)
                rendered_md = render_ats_markdown(cv_doc, strategy_region=region)
                return cv_doc.model_dump(), rendered_md
        except Exception as e:
            logger.debug("Output was not StructuredCVDocument JSON (%s); using normalized markdown.", e)

    cleaned = raw_content
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:markdown)?\n", "", cleaned)
        cleaned = re.sub(r"\n```$", "", cleaned).strip()
    return None, normalize_markdown_tables(cleaned)

