"""Retrieval functions for wiki candidate information, education, projects, patents, and regional strategy."""

import datetime
import logging
from pathlib import Path
import re
import sys
from typing import Any
import yaml
from langchain_core.messages import HumanMessage
from generation.formatting import BRACKET_LINK_PATTERN, llm_text, load_prompt, robust_json_loads, strip_wikilinks
from generation.strategy import (
    discover_available_strategies as discover_available_strategies,
    resolve_regional_strategy as resolve_regional_strategy,
    resolve_track_strategy as resolve_track_strategy,
)
from schemas.wiki_models import ExperienceScope, RoleEvidenceBundle
from utils import extract_wikilink_list, extract_wikilink_slug

logger = logging.getLogger(__name__)


def _resolve_prompt(filename: str) -> str:
    helpers = sys.modules.get("generation.helpers")
    if helpers and hasattr(helpers, "load_prompt"):
        return str(helpers.load_prompt(filename))
    return load_prompt(filename)


def score_by_keywords(text: str, keywords: list[str]) -> int:
    """Calculate simple keyword overlap score (case-insensitive count of whole word matches)."""
    if not text or not keywords:
        return 0
    score = 0
    text_lower = text.lower()
    for kw in keywords:
        kw_lower = kw.lower().strip()
        if not kw_lower:
            continue
        pattern = r'\b' + re.escape(kw_lower) + r'\b'
        matches = len(re.findall(pattern, text_lower))
        score += matches
    return score


def _parse_yaml_frontmatter_from_text(content: str) -> dict[str, Any]:
    """Extract and parse YAML frontmatter mapping from raw or wrapped markdown content."""
    for fm_match in re.finditer(r'(?:^|\n)---\n(.*?)\n---', content, re.DOTALL):
        try:
            parsed = yaml.safe_load(fm_match.group(1))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue
    return {}


def get_subject_info(wiki_dir: Path) -> str:
    """Retrieve subject personal/contact info from wiki/profile.md, falling back to entities."""
    profile_path = wiki_dir / "wiki" / "profile.md"
    if profile_path.exists():
        try:
            return profile_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error("Failed to read profile.md: %s", e)

    entities_dir = wiki_dir / "wiki" / "entities"
    if entities_dir.exists():
        for ent in entities_dir.glob("*.md"):
            try:
                c = ent.read_text(encoding="utf-8")
                if c.startswith("---"):
                    fm = _parse_yaml_frontmatter_from_text(c)
                    if fm:
                        category = str(fm.get("category", "")).lower()
                        tags = [str(t).lower() for t in fm.get("tags", []) if t]
                        if category == "person" or "person" in tags:
                            return c
                if any(x in c for x in ['tags: ["person"', 'tags: ["person",', '- "person"', '- person']):
                    return c
            except Exception:
                pass
    return ""


def generate_skill_bridging_map(llm: Any, skills: list[str], keywords: list[str]) -> dict[str, str]:
    """Ask LLM to construct an explicit key-value mapping of required JD skills
    to sibling/equivalent candidate skills."""
    skills_summary = "\n".join(skills)

    try:
        system_template = _resolve_prompt("skill_bridging_map.txt")
        prompt = (
            system_template
            .replace("{KEYWORDS}", ", ".join(keywords))
            .replace("{SKILLS_SUMMARY}", skills_summary)
        )

        response = llm.invoke([HumanMessage(content=prompt)])
        content = llm_text(response.content)
        data = robust_json_loads(content)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception as e:
        logger.warning(f"Failed to generate skill bridging map: {e}")

    return {}


def _parse_education_candidate(f: Path) -> dict[str, Any] | None:
    """Parse a single education candidate file."""
    try:
        edu_text = f.read_text(encoding="utf-8")
        inst = ""
        start_year = ""
        status = ""
        fm = _parse_yaml_frontmatter_from_text(edu_text)
        if fm:
            inst_raw = str(fm.get("institution", ""))
            inst_match = BRACKET_LINK_PATTERN.search(inst_raw)
            inst = inst_match.group(1) if inst_match else inst_raw.strip().lower()

            dates = fm.get("dates", {})
            if isinstance(dates, dict):
                start_date_val = str(dates.get("start", ""))
                if start_date_val:
                    start_year = start_date_val[:4]
            status = str(fm.get("status", ""))

        if not inst:
            inst = f.name.replace(".md", "").split("-")[0]

        return {
            "path": f,
            "content": edu_text,
            "inst": inst,
            "start_year": start_year,
            "status": status,
            "size": len(edu_text)
        }
    except Exception:
        return None


def retrieve_and_deduplicate_education(wiki_dir: Path) -> list[str]:
    """Retrieve and deduplicate candidate education entries."""
    education_dir = wiki_dir / "wiki" / "education"
    edu_candidates: list[dict[str, Any]] = []
    if not education_dir.exists():
        return []

    for f in education_dir.glob("*.md"):
        cand = _parse_education_candidate(f)
        if cand is not None:
            edu_candidates.append(cand)

    def edu_sort_key(x: dict[str, Any]) -> tuple[int, int]:
        is_completed = 1 if "completed" in str(x["status"]).lower() else 0
        return (is_completed, x["size"])

    edu_candidates.sort(key=edu_sort_key, reverse=True)

    education_content: list[str] = []
    seen_edu: set[tuple[str, str]] = set()
    for item in edu_candidates:
        key = (item["inst"], item["start_year"])
        if key not in seen_edu:
            seen_edu.add(key)
            education_content.append(item["content"])
    return education_content


def _calculate_project_recency_factor(fm: dict[str, Any]) -> float:
    """Calculate recency factor (0.1 to 1.0) decaying linearly over 15 years from project dates."""
    dates = fm.get("dates", {})
    if not isinstance(dates, dict):
        return 0.5
    end_val = str(dates.get("end", "")).strip().lower()
    start_val = str(dates.get("start", "")).strip()
    current_year = datetime.date.today().year

    target_year = None
    if end_val in ["present", "current", "ongoing"]:
        target_year = current_year
    elif len(end_val) >= 4 and end_val[:4].isdigit():
        target_year = int(end_val[:4])
    elif len(start_val) >= 4 and start_val[:4].isdigit():
        target_year = int(start_val[:4])

    if target_year is None:
        return 0.5

    years_since = max(0, current_year - target_year)
    return max(0.1, 1.0 - (years_since / 15.0))


def retrieve_and_score_projects(
    wiki_dir: Path, keywords: list[str], retrieved_exp_slugs: list[str]
) -> list[str]:
    """Retrieve and score candidate projects by relevance, links, and age decay."""
    projects_dir = wiki_dir / "wiki" / "projects"
    scored_projects: list[tuple[float, str, str]] = []
    if not projects_dir.exists():
        return []

    for f in projects_dir.glob("*.md"):
        try:
            p_content = f.read_text(encoding="utf-8")
            base_score = float(score_by_keywords(p_content, keywords))
            for slug in retrieved_exp_slugs:
                if f"[[{slug}]]" in p_content or f": '{slug}'" in p_content or f": {slug}" in p_content:
                    base_score += 5.0
            fm = _parse_yaml_frontmatter_from_text(p_content)
            if fm.get("project_nature") in ["open_source", "side_project", "research_prototype"]:
                base_score += 2.0

            recency_factor = _calculate_project_recency_factor(fm)
            final_score = round(base_score * recency_factor, 2)
            scored_projects.append((final_score, f.name, p_content))
        except Exception:
            pass

    scored_projects.sort(key=lambda x: x[0], reverse=True)
    projects_entries: list[str] = []
    for p_score, p_name, p_content in scored_projects[:3]:
        projects_entries.append(
            f"--- PROJECT ENTRY: {p_name} (RELEVANCE SCORE: {p_score}) ---\n"
            f"{p_content}\n"
            f"--- END PROJECT ENTRY ---\n"
        )
    return projects_entries


def retrieve_and_score_patents(
    wiki_dir: Path, keywords: list[str], retrieved_exp_slugs: list[str]
) -> list[str]:
    """Retrieve and score candidate patents by relevance and links."""
    patents_dir = wiki_dir / "wiki" / "patents"
    scored_patents: list[tuple[int, str, str]] = []
    if not patents_dir.exists():
        return []

    for f in patents_dir.glob("*.md"):
        try:
            pat_content = f.read_text(encoding="utf-8")
            score = score_by_keywords(pat_content, keywords)
            for slug in retrieved_exp_slugs:
                if f"[[{slug}]]" in pat_content or f": '{slug}'" in pat_content or f": {slug}" in pat_content:
                    score += 5
            scored_patents.append((score, f.name, pat_content))
        except Exception:
            pass

    scored_patents.sort(key=lambda x: x[0], reverse=True)
    patents_entries: list[str] = []
    for pat_score, pat_name, pat_content in scored_patents[:3]:
        patents_entries.append(
            f"--- PATENT ENTRY: {pat_name} (KEYWORD RELEVANCE SCORE: {pat_score}) ---\n"
            f"{pat_content}\n"
            f"--- END PATENT ENTRY ---\n"
        )
    return patents_entries


def retrieve_and_score_notes(
    wiki_dir: Path, keywords: list[str], retrieved_exp_slugs: list[str]
) -> list[str]:
    """Retrieve and score performance notes."""
    notes_dir = wiki_dir / "wiki" / "notes"
    scored_notes: list[tuple[int, str, str]] = []
    if not notes_dir.exists():
        return []

    for f in notes_dir.glob("*.md"):
        try:
            note_content = f.read_text(encoding="utf-8")
            has_review_tag = "performance-review" in note_content.lower()
            has_relation = any(f"[[{slug}]]" in note_content for slug in retrieved_exp_slugs)

            if has_review_tag or has_relation:
                score = score_by_keywords(note_content, keywords)
                if has_review_tag:
                    score += 5
                scored_notes.append((score, f.name, note_content))
        except Exception:
            pass

    scored_notes.sort(key=lambda x: x[0], reverse=True)
    notes_entries: list[str] = []
    for n_score, n_name, n_content in scored_notes[:5]:
        notes_entries.append(
            f"--- NOTE ENTRY: {n_name} (RELEVANCE SCORE: {n_score}) ---\n"
            f"{n_content}\n"
            f"--- END NOTE ENTRY ---\n"
        )
    return notes_entries


def retrieve_and_score_case_studies(
    wiki_dir: Path, keywords: list[str], retrieved_exp_slugs: list[str]
) -> list[str]:
    """Retrieve and score candidate case studies by relevance and experience links."""
    case_studies_dir = wiki_dir / "wiki" / "case-studies"
    scored_case_studies: list[tuple[int, str, str]] = []
    if not case_studies_dir.exists():
        return []

    for f in case_studies_dir.glob("*.md"):
        try:
            cs_content = f.read_text(encoding="utf-8")
            score = score_by_keywords(cs_content, keywords)
            for slug in retrieved_exp_slugs:
                if f"[[{slug}]]" in cs_content:
                    score += 5
            scored_case_studies.append((score, f.name, cs_content))
        except Exception:
            pass

    scored_case_studies.sort(key=lambda x: x[0], reverse=True)
    case_studies_entries: list[str] = []
    for cs_score, cs_name, cs_content in scored_case_studies[:4]:
        pruned_content = cs_content if len(cs_content) <= 3500 else cs_content[:3500] + "\n... [TRUNCATED CASE STUDY] ..."
        case_studies_entries.append(
            f"--- CASE STUDY ENTRY: {cs_name} (RELEVANCE SCORE: {cs_score}) ---\n"
            f"{pruned_content}\n"
            f"--- END CASE STUDY ENTRY ---\n"
        )
    return case_studies_entries


def retrieve_few_shots(wiki_dir: Path, keywords: list[str]) -> list[str]:
    """Retrieve and score past successful few-shot resume examples from applications/ (or legacy wiki/synthesis/)."""
    candidate_files = [
        f for d in (wiki_dir / "applications", wiki_dir / "wiki" / "synthesis") if d.exists() for f in d.rglob("*.md")
    ]
    scored_examples: list[tuple[int, str, str]] = []
    for f in candidate_files:
        try:
            cv_content = f.read_text(encoding="utf-8")
            if re.search(r'status:\s*["\']?(Offer|Technical-Interview)["\']?', cv_content, re.IGNORECASE):
                scored_examples.append((score_by_keywords(cv_content, keywords), f.name, cv_content))
        except Exception:
            pass

    scored_examples.sort(key=lambda x: x[0], reverse=True)
    few_shot_examples: list[str] = []
    for fs_score, fs_name, fs_content in scored_examples[:1]:
        fs_content_pruned = (
            fs_content[:12000] + "\n\n... [TRUNCATED SUCCESSFUL PAST CV FOR BREVITY] ...\n"
            if len(fs_content) > 12000
            else fs_content
        )
        few_shot_examples.append(
            f"--- SUCCESSFUL PAST CV: {fs_name} (RELEVANCE SCORE: {fs_score}) ---\n"
            f"{fs_content_pruned}\n"
            f"--- END SUCCESSFUL PAST CV ---\n"
        )
    return few_shot_examples


def retrieve_languages(wiki_dir: Path) -> list[str]:
    """Retrieve and format spoken languages from wiki/languages."""
    languages_dir = wiki_dir / "wiki" / "languages"
    if not languages_dir.exists():
        return []

    languages_content = []
    for f in sorted(languages_dir.glob("*.md")):
        try:
            content = f.read_text(encoding="utf-8")
            fm = _parse_yaml_frontmatter_from_text(content)
            title = fm.get("title", f.stem.replace("lang-", "").capitalize())
            proficiency = fm.get("proficiency", "")
            cefr = fm.get("cefr", "")

            detail = f" ({cefr})" if cefr else ""
            if proficiency:
                languages_content.append(f"- **{title}**: {proficiency}{detail}")
            else:
                languages_content.append(f"- **{title}**")
        except Exception as e:
            logger.error("Error parsing language file %s: %s", f.name, e)

    return languages_content


def retrieve_voice_guide(wiki_dir: Path) -> str:
    """Retrieve the candidate's personal voice & style guide from wiki/voice/my-voice.md."""
    candidates = [
        wiki_dir / "wiki" / "voice" / "my-voice.md",
        wiki_dir / "wiki" / "notes" / "my-voice.md",
    ]
    for path in candidates:
        if path.exists():
            try:
                return path.read_text(encoding="utf-8").strip()
            except Exception as e:
                logger.warning("Failed to read voice guide at %s: %s", path, e)
    return ""


def retrieve_company_entity(wiki_dir: Path, org_slug: str) -> str:
    """Retrieve 1-line company context from wiki/entities/{org_slug}.md if available."""
    if not org_slug:
        return ""
    entity_path = wiki_dir / "wiki" / "entities" / f"{org_slug}.md"
    if not entity_path.exists():
        return ""
    try:
        content = entity_path.read_text(encoding="utf-8")
        fm = _parse_yaml_frontmatter_from_text(content)
        summary = str(fm.get("summary") or fm.get("description") or "").strip()
        if summary:
            return summary
        body = re.sub(r"^---\n.*?\n---", "", content, flags=re.DOTALL).strip()
        for line in body.splitlines():
            clean = line.strip()
            if clean and not clean.startswith("#"):
                return strip_wikilinks(clean)[:240]
    except Exception as e:
        logger.debug("Failed to read company entity %s: %s", org_slug, e)
    return ""


def _read_linked_markdown_bodies(directory: Path, slugs: list[str]) -> list[str]:
    """Read and strip frontmatter from linked markdown files by slug."""
    results: list[str] = []
    if not directory.exists():
        return results
    for slug in slugs:
        clean_slug = extract_wikilink_slug(slug)
        if not clean_slug:
            continue
        file_path = directory / f"{clean_slug}.md"
        if file_path.exists():
            try:
                raw = file_path.read_text(encoding="utf-8")
                body = re.sub(r"^---\n.*?\n---", "", raw, flags=re.DOTALL).strip()
                results.append(strip_wikilinks(body or raw))
            except Exception:
                pass
    return results


def assemble_role_evidence_bundles(wiki_dir: Path, selected_entries: list[str]) -> list[dict[str, Any]]:
    """Assemble Hub-and-Spoke RoleEvidenceBundles linking each role to its company entity and child spokes."""
    bundles: list[dict[str, Any]] = []
    for idx, entry in enumerate(selected_entries):
        name_match = re.search(r"CAREER ENTRY:\s*([^\s|]+)", entry)
        role_slug = name_match.group(1).replace(".md", "") if name_match else f"role-{idx}"
        score_match = re.search(r"SEMANTIC RELEVANCE SCORE:\s*(\d+)", entry)
        rel_score = int(score_match.group(1)) if score_match else 75
        fm = _parse_yaml_frontmatter_from_text(entry)
        org_slug = extract_wikilink_slug(fm.get("organization"))
        raw_scope = fm.get("scope")
        scope_dict: dict[str, Any] = raw_scope if isinstance(raw_scope, dict) else {}
        company_ctx = str(scope_dict.get("company_context", "")).strip() or retrieve_company_entity(wiki_dir, org_slug)

        cs_links = extract_wikilink_list(fm.get("case_studies", []))
        proj_links = extract_wikilink_list(fm.get("projects", []))
        pat_links = extract_wikilink_list(fm.get("patents", []))
        note_links = extract_wikilink_list(fm.get("notes", []))
        raw_dates = fm.get("dates")
        dates: dict[str, Any] = raw_dates if isinstance(raw_dates, dict) else {}
        bullets = [
            strip_wikilinks(line.strip("- *•\t "))
            for line in entry.splitlines()
            if line.strip().startswith(("- ", "* ", "• "))
        ]
        scope_obj = ExperienceScope.model_validate({str(k): str(v) for k, v in scope_dict.items() if v is not None})
        bundle = RoleEvidenceBundle(
            slug=role_slug,
            title=str(fm.get("title", role_slug)),
            organization_slug=org_slug,
            organization_name=org_slug.replace("-", " ").title() if org_slug else "Organization",
            organization_overview=company_ctx,
            location=str(fm.get("location", "")),
            start_date=str(dates.get("start", "")),
            end_date=str(dates.get("end", "Present")),
            employment_type=str(fm.get("employment_type", "Permanent")),
            scope=scope_obj,
            achievements=bullets,
            linked_case_studies=_read_linked_markdown_bodies(wiki_dir / "wiki" / "case-studies", cs_links),
            linked_projects=_read_linked_markdown_bodies(wiki_dir / "wiki" / "projects", proj_links),
            linked_patents=_read_linked_markdown_bodies(wiki_dir / "wiki" / "patents", pat_links),
            linked_notes=_read_linked_markdown_bodies(wiki_dir / "wiki" / "notes", note_links),
            skills=[str(s) for s in fm.get("skills", []) if s] if isinstance(fm.get("skills"), list) else [],
            relevance_score=min(100, max(0, rel_score)),
        )
        bundles.append(bundle.model_dump())

    return bundles
