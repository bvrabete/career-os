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
    _get_org_slug,
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


def _resolve_employment_type_multiplier(emp_type: str, type_multipliers: dict[str, Any]) -> float:
    """Resolve employment type multiplier with case-insensitive fallback."""
    if emp_type in type_multipliers:
        return float(type_multipliers[emp_type])
    norm = emp_type.lower()
    for key, mult in type_multipliers.items():
        k_norm = key.lower()
        if norm == k_norm or k_norm in norm or norm in k_norm:
            return float(mult)
    return 1.0


def _resolve_culture_multiplier(
    emp_type: str, org_culture: str, culture_multipliers: dict[str, Any]
) -> float:
    """Resolve org-culture multiplier based on track culture and employment type."""
    culture_key = org_culture.lower()
    culture_map = culture_multipliers.get(culture_key)
    if not isinstance(culture_map, dict):
        return 1.0
    return _resolve_employment_type_multiplier(emp_type, culture_map)


def calculate_experience_weight(
    score: int,
    fm: dict[str, Any],
    employment_type: str = "Permanent",
    org_culture: str = "corporate",
) -> float:
    """
    Calculate a normalized weight (0.0 to 1.0) for an experience entry based on:
    1. ATS Score Factor (50%)
    2. Recency Factor (30%) - decays linearly over a 15-year period
    3. Duration Factor (20%) - scales linearly up to a 3-year cap
    4. Employment Type Multiplier (Contract: 0.85, Advisory: 0.75, etc.)
    5. Culture Alignment Multiplier (Corporate vs Startup targets)
    """
    scoring_cfg = kb_config.get_scoring_config()
    factors = scoring_cfg.get("FACTORS", {})
    w_ats = float(factors.get("ATS_SCORE", 0.50))
    w_recency = float(factors.get("RECENCY", 0.30))
    w_duration = float(factors.get("DURATION", 0.20))
    dur_cap = float(scoring_cfg.get("DURATION_CAP_YEARS", 3.0))
    recency_horizon = float(scoring_cfg.get("RECENCY_HORIZON_YEARS", 15.0))

    score_factor = max(0.0, min(1.0, score / 100.0))

    end_date_str = _extract_end_date_normalized(fm)
    try:
        end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()
    except Exception:
        end_date = datetime.date.today()

    current_year = datetime.date.today().year
    years_since_end = max(0, current_year - end_date.year)
    recency_factor = max(0.0, 1.0 - (years_since_end / recency_horizon))

    start_date_str = _extract_start_date_normalized(fm)
    try:
        start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except Exception:
        start_date = datetime.date.today()

    duration_days = (end_date - start_date).days
    duration_years = max(0.0, duration_days / 365.25)
    duration_factor = min(duration_years / dur_cap, 1.0)

    base_score = (w_ats * score_factor) + (w_recency * recency_factor) + (w_duration * duration_factor)

    resolved_type = employment_type
    if (resolved_type == "Permanent" or not resolved_type) and fm:
        detected = _detect_employment_type(fm, "")
        if detected and detected != "Permanent":
            resolved_type = detected

    type_mult = _resolve_employment_type_multiplier(
        resolved_type, scoring_cfg.get("EMPLOYMENT_TYPE_MULTIPLIERS", {})
    )
    cult_mult = _resolve_culture_multiplier(
        resolved_type, org_culture, scoring_cfg.get("CULTURE_MULTIPLIERS", {})
    )

    final_weight = min(1.0, base_score * type_mult * cult_mult)
    return round(final_weight, 4)


def _compress_and_wrap_single_experience(
    score: int,
    name: str,
    content: str,
    justification: str,
    keywords: list[str],
    max_pages: int = 1,
    target_track: str = "engineering-management",
    org_culture: str = "corporate",
) -> str:
    """Helper to smart-compress or prune a single experience entry and return wrapped string."""
    fm = _parse_yaml_frontmatter_from_text(content)
    emp_type = _detect_employment_type(fm, content)
    is_startup = _is_parallel_startup_track(fm)

    weight = calculate_experience_weight(score, fm, employment_type=emp_type, org_culture=org_culture)
    logger.info(f"Experience '{name}' calculated weight: {weight:.3f} (Score: {score})")

    end_date_str = _extract_end_date_normalized(fm)
    try:
        end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()
    except Exception:
        end_date = datetime.date.today()
    current_year = datetime.date.today().year
    years_since_end = max(0, current_year - end_date.year)

    scoring_cfg = kb_config.get_scoring_config()
    tiers = scoring_cfg.get("TIERS", {})
    tier_1 = float(tiers.get("TIER_1_EXPANDED", 0.70))
    tier_2 = float(tiers.get("TIER_2_BALANCED", 0.45))
    tier_3 = float(tiers.get("TIER_3_COMPRESSED", 0.30))

    if name.startswith("grouped-"):
        content = compress_grouped_experience_llm(content)
    elif "group" in name.lower() or "grouped" in name.lower():
        pass
    elif years_since_end >= 15 or weight < tier_3:
        content = compress_experience_to_one_liner_llm(content)
    elif weight >= tier_1 and years_since_end < 10:
        content = prune_recent_experience(content, keywords, emp_type, max_pages=3)
    elif weight >= tier_2 and years_since_end < 15:
        content = prune_recent_experience(content, keywords, emp_type, max_pages=2)
    else:
        content = compress_experience_llm(content)

    start_date_str = _extract_start_date_normalized(fm)
    return (
        f"--- CAREER ENTRY: {name} | START_DATE: {start_date_str} | "
        f"EMPLOYMENT_TYPE: {emp_type} | IS_STARTUP_TRACK: {is_startup} | "
        f"(SEMANTIC RELEVANCE SCORE: {score}) ---\n"
        f"JUSTIFICATION: {justification}\n"
        f"{content}\n"
        f"--- END CAREER ENTRY ---\n"
    )


def _compress_and_wrap_experiences(
    deduplicated: list[tuple[int, str, str, str]],
    keywords: list[str],
    max_pages: int = 1,
    target_track: str = "engineering-management",
    org_culture: str = "corporate",
) -> tuple[list[str], list[str]]:
    """Helper to perform smart-compression or pruning on deduplicated experiences."""
    selected_content: list[str] = []
    retrieved_exp_slugs: list[str] = []

    grouped_deduplicated = _group_old_experiences_by_company(deduplicated)

    for score, name, content, justification in grouped_deduplicated:
        slug = name.replace(".md", "")
        retrieved_exp_slugs.append(slug)
        wrapped = _compress_and_wrap_single_experience(
            score,
            name,
            content,
            justification,
            keywords,
            max_pages,
            target_track=target_track,
            org_culture=org_culture,
        )
        selected_content.append(wrapped)

    for item in deduplicated:
        orig_slug = item[1].replace(".md", "")
        if orig_slug not in retrieved_exp_slugs:
            retrieved_exp_slugs.append(orig_slug)
        fm = _parse_yaml_frontmatter_from_text(item[2])
        org_slug = _get_org_slug(item[1], fm)
        if org_slug and org_slug not in retrieved_exp_slugs:
            retrieved_exp_slugs.append(org_slug)

    return selected_content, retrieved_exp_slugs


def retrieve_and_score_experiences(
    llm: Any,
    keywords: list[str],
    persona: str,
    jd: str,
    max_pages: int = 1,
    target_track: str = "engineering-management",
    org_culture: str = "corporate",
) -> tuple[list[str], list[str]]:
    """Retrieve, score, deduplicate, and smart-compress candidate experiences."""
    score_template = _resolve_prompt("retriever_score.txt")
    scored = _score_experiences_list(llm, keywords, persona, jd, score_template)

    def _calc_weight(item: tuple[int, str, str, str]) -> float:
        s, _, c, _ = item
        item_fm = _parse_yaml_frontmatter_from_text(c)
        emp_t = _detect_employment_type(item_fm, c)
        return calculate_experience_weight(s, item_fm, employment_type=emp_t, org_culture=org_culture)

    scored.sort(key=_calc_weight, reverse=True)
    deduplicated = _deduplicate_scored_experiences(scored)
    deduplicated.sort(key=_calc_weight, reverse=True)
    return _compress_and_wrap_experiences(
        deduplicated,
        keywords,
        max_pages,
        target_track=target_track,
        org_culture=org_culture,
    )
