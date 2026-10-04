"""Retrieval functions for wiki candidate information, education, projects, patents, and regional strategy."""

import logging
from pathlib import Path
import re
import sys
from typing import Any
import yaml
from langchain_core.messages import HumanMessage
from kb_config import get_strategy_default
from generation.formatting import BRACKET_LINK_PATTERN, llm_text, load_prompt, robust_json_loads

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
    """Extract and parse YAML frontmatter from markdown content."""
    fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not fm_match:
        return {}
    try:
        return yaml.safe_load(fm_match.group(1)) or {}
    except Exception:
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


def resolve_regional_strategy(wiki_dir: Path, region: str) -> tuple[str, str]:
    """Resolve the regional strategy file and template css."""
    strategy_file = wiki_dir / "wiki" / "strategies" / f"strategy-{region}.md"
    if not strategy_file.exists():
        if any(kw in region for kw in ["uk", "london", "united kingdom", "ireland"]):
            strategy_file = wiki_dir / "wiki" / "strategies" / "strategy-ireland.md"
        elif any(kw in region for kw in ["emea", "europe", "global", "remote"]):
            strategy_file = wiki_dir / "wiki" / "strategies" / "strategy-emea.md"
        else:
            default_strategy = get_strategy_default()
            strategy_file = (
                wiki_dir / "wiki" / "strategies" / f"strategy-{default_strategy}.md"
            )
            if not strategy_file.exists():
                strategy_file = wiki_dir / "wiki" / "strategies" / "strategy-emea.md"

    strategy_text = ""
    pdf_template = "templates/base.css"
    if strategy_file.exists():
        strategy_text = strategy_file.read_text(encoding="utf-8")
        if strategy_text.startswith("---"):
            fm = _parse_yaml_frontmatter_from_text(strategy_text)
            if fm and "pdf_template" in fm:
                pdf_template = str(fm["pdf_template"]).strip()
    return strategy_text, pdf_template


def generate_skill_bridging_map(llm: Any, skills: list[str], keywords: list[str]) -> dict[str, str]:
    """Ask LLM to construct an explicit key-value mapping of required JD skills to sibling/equivalent candidate skills."""
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


def retrieve_and_score_projects(
    wiki_dir: Path, keywords: list[str], retrieved_exp_slugs: list[str]
) -> list[str]:
    """Retrieve and score candidate projects by relevance and links, supporting open-source and side projects."""
    projects_dir = wiki_dir / "wiki" / "projects"
    scored_projects: list[tuple[int, str, str]] = []
    if not projects_dir.exists():
        return []

    for f in projects_dir.glob("*.md"):
        try:
            p_content = f.read_text(encoding="utf-8")
            score = score_by_keywords(p_content, keywords)
            for slug in retrieved_exp_slugs:
                if f"[[{slug}]]" in p_content:
                    score += 5
            fm = _parse_yaml_frontmatter_from_text(p_content)
            if fm.get("project_nature") in ["open_source", "side_project", "research_prototype"]:
                score += 2
            scored_projects.append((score, f.name, p_content))
        except Exception:
            pass

    scored_projects.sort(key=lambda x: x[0], reverse=True)
    projects_entries: list[str] = []
    for p_score, p_name, p_content in scored_projects[:3]:
        projects_entries.append(
            f"--- PROJECT ENTRY: {p_name} (KEYWORD RELEVANCE SCORE: {p_score}) ---\n"
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
                if f"[[{slug}]]" in pat_content:
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


def retrieve_few_shots(wiki_dir: Path, keywords: list[str]) -> list[str]:
    """Retrieve and score past successful few-shot resume examples."""
    synthesis_dir = wiki_dir / "wiki" / "synthesis"
    scored_examples: list[tuple[int, str, str]] = []
    if not synthesis_dir.exists():
        return []

    for f in synthesis_dir.glob("*.md"):
        try:
            cv_content = f.read_text(encoding="utf-8")
            status_match = re.search(
                r'status:\s*["\']?(Offer|Technical-Interview)["\']?', cv_content, re.IGNORECASE
            )
            if status_match:
                score = score_by_keywords(cv_content, keywords)
                scored_examples.append((score, f.name, cv_content))
        except Exception:
            pass

    scored_examples.sort(key=lambda x: x[0], reverse=True)
    few_shot_examples: list[str] = []
    for fs_score, fs_name, fs_content in scored_examples[:1]:
        fs_content_pruned = fs_content
        if len(fs_content) > 12000:
            fs_content_pruned = (
                fs_content[:12000]
                + "\n\n... [TRUNCATED SUCCESSFUL PAST CV FOR BREVITY] ...\n"
            )
            logger.info(
                f"Few-shot example {fs_name} truncated to 12k characters to fit within TPM limits."
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
