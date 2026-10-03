"""Pruning, scoring, achievement filtering, and experience weight calculations."""

import datetime
import json
import logging
from pathlib import Path
import re
import sys
from typing import Any
import yaml
from langchain_core.messages import HumanMessage
import kb_config
from generation.formatting import (
    BRACKET_LINK_PATTERN,
    compress_experience_llm,
    compress_experience_to_one_liner_llm,
    compress_grouped_experience_llm,
    llm_text,
    load_prompt,
    robust_json_loads,
)
from generation.grouping import (
    _detect_employment_type,
    _extract_end_date_normalized,
    _extract_start_date_normalized,
    _extract_start_year,
    _group_old_experiences_by_company,
    _is_parallel_startup_track,
)
from generation.retrieval import _parse_yaml_frontmatter_from_text, score_by_keywords

logger = logging.getLogger(__name__)


def _get_wiki_dir() -> Path:
    helpers = sys.modules.get("generation.helpers")
    if helpers and hasattr(helpers, "get_wiki_dir"):
        return Path(helpers.get_wiki_dir())
    return kb_config.get_wiki_dir()


def _resolve_prompt(filename: str) -> str:
    helpers = sys.modules.get("generation.helpers")
    if helpers and hasattr(helpers, "load_prompt"):
        return str(helpers.load_prompt(filename))
    return load_prompt(filename)


def _prune_recent_frontmatter(fm: dict[str, Any], employment_type: str = "Permanent") -> str:
    """Heal dates if needed and prune to essential fields, returning YAML string."""
    if "dates" not in fm or not isinstance(fm["dates"], dict):
        start = fm.get("start") or fm.get("dates")
        end = fm.get("end")
        if start or end:
            fm["dates"] = {
                "start": start,
                "end": end or "Present"
            }
    
    fm["employment_type"] = employment_type
    
    pruned_fm: dict[str, Any] = {}
    for key in ["type", "title", "organization", "location", "dates", "skills", "employment_type"]:
        if key in fm:
            pruned_fm[key] = fm[key]
            
    return yaml.dump(pruned_fm, sort_keys=False)


def _extract_and_clean_achievements(body: str) -> tuple[list[str], str]:
    """Extract STAR achievements and return a cleaned body without them, avoiding complex regexes."""
    achievements: list[str] = []
    clean_lines: list[str] = []
    current_ach: list[str] = []
    
    for line in body.splitlines():
        is_new_ach = bool(re.match(r'^\s*-\s*\*\*Situation', line))
        is_header = line.strip().startswith("##") or line.strip().startswith("###")
        
        if (is_new_ach or is_header) and current_ach:
            achievements.append("\n".join(current_ach))
            current_ach = []
                
        if (is_new_ach or current_ach) and not is_header:
            current_ach.append(line)
        else:
            clean_lines.append(line)
            
    if current_ach:
        achievements.append("\n".join(current_ach))
        
    clean_body = "\n".join(clean_lines).strip()
    return achievements, clean_body


def _select_top_achievements(body: str, keywords: list[str], max_pages: int = 1) -> str:
    """Extract, score, and select only the top achievements based on keyword overlap and page budget."""
    achievements, clean_body = _extract_and_clean_achievements(body)
    
    if achievements:
        scored_ach: list[tuple[int, str]] = []
        for ach in achievements:
            score = score_by_keywords(ach, keywords)
            scored_ach.append((score, ach))
        scored_ach.sort(key=lambda x: x[0], reverse=True)
        
        if max_pages >= 3:
            limit = len(scored_ach)
        elif max_pages == 2:
            limit = 7
        else:
            limit = 4
            
        top_ach = [x[1] for x in scored_ach[:limit]]
        clean_body = re.sub(r'\n{3,}', '\n\n', clean_body).strip()
        body = f"{clean_body}\n\n## Key STAR Achievements\n\n" + "\n".join(top_ach)
        
    return body


def prune_recent_experience(
    content: str, keywords: list[str] = [], employment_type: str = "Permanent", max_pages: int = 1
) -> str:
    """Prunes a recent experience file to reduce token bloat before sending it to the DRAFTER."""
    content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
    
    fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if fm_match:
        try:
            fm_raw = fm_match.group(1)
            fm = yaml.safe_load(fm_raw) or {}
            pruned_fm_str = _prune_recent_frontmatter(fm, employment_type)
            body = content[fm_match.end():].strip()
            
            if max_pages < 3:
                narrative_header = "## Narrative & Reflections"
                idx = body.find(narrative_header)
                if idx != -1:
                    next_header_idx = body.find("##", idx + len(narrative_header))
                    if next_header_idx != -1:
                        body = body[:idx] + body[next_header_idx:]
                    else:
                        body = body[:idx]
                    
            body = _select_top_achievements(body, keywords, max_pages)
            return f"---\n{pruned_fm_str}---\n\n{body}"
        except Exception as e:
            logger.warning(f"Failed to prune frontmatter: {e}")
            
    return content


def _score_single_experience(
    llm: Any, entry_path: Path, keywords: list[str], persona: Any, jd: str, template: str
) -> tuple[int, str, str, str] | None:
    """Load and score a single experience file."""
    try:
        experience_content = entry_path.read_text(encoding="utf-8")
        if len(experience_content) < 50:
            return None

        persona_str = persona if isinstance(persona, str) else json.dumps(persona, indent=2)

        score_prompt = (
            template
            .replace("{JOB_DESCRIPTION}", jd)
            .replace("{TARGET_PERSONA}", persona_str)
            .replace("{KEYWORDS}", ", ".join(keywords))
            .replace("{EXPERIENCE_CONTENT}", experience_content)
        )

        response = llm.invoke([HumanMessage(content=score_prompt)])
        content = llm_text(response.content)

        score = 0
        justification = "N/A"
        try:
            data = robust_json_loads(content)
            score = int(data.get("score", 0))
            justification = data.get("justification", "N/A")
        except Exception as e:
            logger.warning(
                f"Failed to parse LLM score for {entry_path.name}, defaulting to 0: {e}"
            )

        return (score, entry_path.name, experience_content, justification)
    except Exception as e:
        logger.warning(f"Error reading/scoring experience {entry_path.name}: {e}")
        return None


def _score_experiences_list(
    llm: Any, keywords: list[str], persona: str, jd: str, template: str
) -> list[tuple[int, str, str, str]]:
    """Helper to load and score all candidate experiences."""
    experiences_dir = _get_wiki_dir() / "wiki" / "experiences"
    scored: list[tuple[int, str, str, str]] = []
    if not experiences_dir.exists():
        return scored

    for entry_path in experiences_dir.glob("*.md"):
        res = _score_single_experience(llm, entry_path, keywords, persona, jd, template)
        if res is not None:
            scored.append(res)

    return scored


def _get_experience_key(name: str, content: str) -> tuple[str, str]:
    """Extract a deduplication key (organization, start_year) from an experience entry."""
    fm = _parse_yaml_frontmatter_from_text(content)
    org_raw = str(fm.get("organization", ""))
    org_match = BRACKET_LINK_PATTERN.search(org_raw)
    org = org_match.group(1) if org_match else org_raw.strip().lower()
    if not org:
        org = name.replace(".md", "").split("-")[0]

    start_year = _extract_start_year(fm)
    return org, start_year


def _deduplicate_scored_experiences(
    scored: list[tuple[int, str, str, str]]
) -> list[tuple[int, str, str, str]]:
    """Helper to deduplicate scored experiences."""
    deduplicated: list[tuple[int, str, str, str]] = []
    seen_roles: set[tuple[str, str]] = set()

    for item in scored:
        _, name, content, _ = item
        key = _get_experience_key(name, content)
        if key not in seen_roles:
            seen_roles.add(key)
            deduplicated.append(item)

    return deduplicated


def calculate_experience_weight(score: int, fm: dict[str, Any]) -> float:
    """
    Calculate a normalized weight (0.0 to 1.0) for an experience entry based on:
    1. ATS Score Factor (50%)
    2. Recency Factor (30%) - decays linearly over a 15-year period
    3. Duration Factor (20%) - scales linearly up to a 3-year cap
    """
    score_factor = max(0.0, min(1.0, score / 100.0))

    end_date_str = _extract_end_date_normalized(fm)
    try:
        end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()
    except Exception:
        end_date = datetime.date.today()
    
    current_year = datetime.date.today().year
    end_year = end_date.year
    years_since_end = max(0, current_year - end_year)
    recency_factor = max(0.0, 1.0 - (years_since_end / 15.0))

    start_date_str = _extract_start_date_normalized(fm)
    try:
        start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except Exception:
        start_date = datetime.date.today()
        
    duration_days = (end_date - start_date).days
    duration_years = max(0.0, duration_days / 365.25)
    duration_factor = min(duration_years / 3.0, 1.0)

    weight = 0.5 * score_factor + 0.3 * recency_factor + 0.2 * duration_factor
    return weight


def _compress_and_wrap_single_experience(
    score: int, name: str, content: str, justification: str, keywords: list[str], max_pages: int = 1
) -> str:
    """Helper to smart-compress or prune a single experience entry and return wrapped string."""
    fm = _parse_yaml_frontmatter_from_text(content)
    emp_type = _detect_employment_type(fm, content)
    is_startup = _is_parallel_startup_track(fm)
    
    weight = calculate_experience_weight(score, fm)
    logger.info(f"Experience '{name}' calculated weight: {weight:.3f} (Score: {score})")

    end_date_str = _extract_end_date_normalized(fm)
    try:
        end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()
    except Exception:
        end_date = datetime.date.today()
    current_year = datetime.date.today().year
    years_since_end = max(0, current_year - end_date.year)

    if name.startswith("grouped-"):
        content = compress_grouped_experience_llm(content)
    elif "group" in name.lower() or "grouped" in name.lower():
        pass
    elif years_since_end >= 15 or weight < 0.30:
        content = compress_experience_to_one_liner_llm(content)
    elif weight >= 0.70 and years_since_end < 10:
        content = prune_recent_experience(content, keywords, emp_type, max_pages=3)
    elif weight >= 0.45 and years_since_end < 15:
        content = prune_recent_experience(content, keywords, emp_type, max_pages=2)
    else:
        content = compress_experience_llm(content)

    start_date_str = _extract_start_date_normalized(fm)
    return (
        f"--- CAREER ENTRY: {name} | START_DATE: {start_date_str} | EMPLOYMENT_TYPE: {emp_type} | IS_STARTUP_TRACK: {is_startup} | (SEMANTIC RELEVANCE SCORE: {score}) ---\n"
        f"JUSTIFICATION: {justification}\n"
        f"{content}\n"
        f"--- END CAREER ENTRY ---\n"
    )


def _compress_and_wrap_experiences(
    deduplicated: list[tuple[int, str, str, str]], keywords: list[str], max_pages: int = 1
) -> tuple[list[str], list[str]]:
    """Helper to perform smart-compression or pruning on deduplicated experiences."""
    selected_content: list[str] = []
    retrieved_exp_slugs: list[str] = []

    grouped_deduplicated = _group_old_experiences_by_company(deduplicated)

    for score, name, content, justification in grouped_deduplicated:
        slug = name.replace(".md", "")
        retrieved_exp_slugs.append(slug)
        wrapped = _compress_and_wrap_single_experience(score, name, content, justification, keywords, max_pages)
        selected_content.append(wrapped)

    return selected_content, retrieved_exp_slugs


def retrieve_and_score_experiences(
    llm: Any, keywords: list[str], persona: str, jd: str, max_pages: int = 1
) -> tuple[list[str], list[str]]:
    """Retrieve, score, deduplicate, and smart-compress candidate experiences."""
    score_template = _resolve_prompt("retriever_score.txt")
    scored = _score_experiences_list(llm, keywords, persona, jd, score_template)
    scored.sort(key=lambda x: x[0], reverse=True)
    deduplicated = _deduplicate_scored_experiences(scored)
    return _compress_and_wrap_experiences(deduplicated, keywords, max_pages)
