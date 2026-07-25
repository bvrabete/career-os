"""Helper functions for the CV generation pipeline."""

import logging
import json
import re
from pathlib import Path
from typing import Any
import datetime
import yaml
from langchain_core.messages import HumanMessage, SystemMessage
from kb_config import (
    get_model_for_step,
    get_wiki_dir,
    get_strategy_default,
    get_fallback_model_for_step
)

BRACKET_LINK_PATTERN = re.compile(r'\[\[(.*?)\]\]')


def llm_text(content: str | list[Any]) -> str:
    """Coerce a LangChain response.content value to a plain string."""
    if isinstance(content, str):
        return content
    return " ".join(str(part) for part in content)


def _extract_json_block(text: str) -> str:
    """Extract the innermost JSON object or array string from text, stripping markdown code blocks."""
    text = text.strip()
    
    # 1. Strip markdown code blocks if present
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
        
    # 2. Locate the outermost JSON object/array
    start_brace = text.find("{")
    start_bracket = text.find("[")
    
    if start_brace == -1 and start_bracket == -1:
        raise ValueError("No JSON object or array found in text")
        
    if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
        # Starts with an object
        end_brace = text.rfind("}")
        if end_brace == -1:
            raise ValueError("Mismatched opening brace '{'")
        return text[start_brace:end_brace+1]
    
    # Starts with an array
    end_bracket = text.rfind("]")
    if end_bracket == -1:
        raise ValueError("Mismatched opening bracket '['")
    return text[start_bracket:end_bracket+1]


def _clean_json_comments_and_commas(text: str) -> str:
    """Remove JS-style comments and trailing commas from a JSON string."""
    # Clean up comments (both // and /* */)
    text = re.sub(r'(?<!:)\/\/.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\/\*.*?\*\/', '', text, flags=re.DOTALL)
    
    # Handle trailing commas before closing braces/brackets
    return re.sub(r',\s*([\]}])', r'\1', text)


def _escape_control_chars_in_strings(text: str) -> str:
    """Replace raw newlines and tabs inside string values in JSON text."""
    def replace_control_chars(match: re.Match[str]) -> str:
        s = match.group(0)
        s_escaped = s.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
        return s_escaped
    
    string_pattern = r'"(?:[^"\\]|\\.)*"'
    return re.sub(string_pattern, replace_control_chars, text)


def robust_json_loads(text: str) -> Any:
    """Robustly parse a JSON string from LLM output, handling preambles, trailing commas, comments, and control characters."""
    if not text:
        raise ValueError("Empty input string")
        
    text = _extract_json_block(text)
    text = _clean_json_comments_and_commas(text)
    text = _escape_control_chars_in_strings(text)

    # Try parsing with standard json.loads
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logging.warning(f"Standard json.loads failed: {e}. Attempting last-resort recovery.")
        try:
            alt_text = text.replace("'", '"')
            return json.loads(alt_text)
        except Exception:
            raise e


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


def load_prompt(filename: str) -> str:
    """Load an external prompt file from src/prompts/cv_gen/."""
    current_dir = Path(__file__).resolve().parent
    prompt_path = current_dir.parent / "prompts" / "cv_gen" / filename
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt template not found at {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def generate_skill_bridging_map(llm: Any, skills: list[str], keywords: list[str]) -> dict[str, str]:
    """Ask LLM to construct an explicit key-value mapping of required JD skills to sibling/equivalent candidate skills."""
    skills_summary = "\n".join(skills)
    
    try:
        system_template = load_prompt("skill_bridging_map.txt")
        # Populate template using replace to avoid literal curly brace issues
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
        logging.warning(f"Failed to generate skill bridging map: {e}")
        
    return {}


def compress_experience_llm(content: str) -> str:
    """
    Compresses an old, lower-relevance experience entry into a highly concise summary
    retaining metadata, company description/size, location, technologies, and 1 key achievement.
    """
    try:
        llm = get_model_for_step("RETRIEVAL")
        system_template = load_prompt("compress_experience.txt")
        prompt = system_template.replace("{CONTENT}", content)
        
        response = llm.invoke([HumanMessage(content=prompt)])
        return llm_text(response.content)
    except Exception as e:
        logging.warning(f"Failed to compress experience via LLM: {e}")
        return content


def _prune_recent_frontmatter(fm: dict[str, Any], employment_type: str = "Permanent") -> str:
    """Heal dates if needed and prune to essential fields, returning YAML string."""
    # Heal dates if start/end are at top-level (common indentation error)
    if "dates" not in fm or not isinstance(fm["dates"], dict):
        start = fm.get("start") or fm.get("dates")
        end = fm.get("end")
        if start or end:
            fm["dates"] = {
                "start": start,
                "end": end or "Present"
            }
    
    # Inject detected employment type
    fm["employment_type"] = employment_type
    
    # Keep only essential fields
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
        # Sort by score descending
        scored_ach.sort(key=lambda x: x[0], reverse=True)
        
        # Budget-aware achievement limits
        if max_pages >= 3:
            limit = len(scored_ach)  # Keep all achievements for large budgets
        elif max_pages == 2:
            limit = 7                # Relaxed pruning for mid budgets
        else:
            limit = 4                # Tighter pruning for 1-page budgets
            
        top_ach = [x[1] for x in scored_ach[:limit]]
        
        # Clean up multi-newlines in body and append achievements
        clean_body = re.sub(r'\n{3,}', '\n\n', clean_body).strip()
        body = f"{clean_body}\n\n## Key STAR Achievements\n\n" + "\n".join(top_ach)
        
    return body


def prune_recent_experience(content: str, keywords: list[str] = [], employment_type: str = "Permanent", max_pages: int = 1) -> str:
    """
    Prunes a recent experience file to reduce token bloat before sending it to the DRAFTER.
    - Strips comments (<!-- ... -->)
    - Removes unnecessary YAML fields (created, updated, sources, tags, tracks)
    - Strips the 'Narrative & Reflections' section to preserve token budget ONLY for 1 and 2-page budgets.
    - Scores and retains achievements based on keyword overlap and target page budget.
    """
    # 1. Strip HTML comments
    content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
    
    # 2. Extract and prune frontmatter
    fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if fm_match:
        try:
            fm_raw = fm_match.group(1)
            fm = yaml.safe_load(fm_raw) or {}
            
            pruned_fm_str = _prune_recent_frontmatter(fm, employment_type)
            
            # Get body
            body = content[fm_match.end():].strip()
            
            # 3. Strip 'Narrative & Reflections' section if present (ONLY for 1 and 2 page budgets)
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
            
            # Reconstruct content
            content = f"---\n{pruned_fm_str}---\n\n{body.strip()}"
        except Exception as e:
            logging.warning(f"Failed to prune recent experience: {e}")
            
    return content


def _parse_yaml_frontmatter_from_text(content: str) -> dict[str, Any]:
    """Extract and parse YAML frontmatter from markdown content."""
    fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not fm_match:
        return {}
    try:
        return yaml.safe_load(fm_match.group(1)) or {}
    except Exception:
        return {}


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
            logging.warning(
                f"Failed to parse LLM score for {entry_path.name}, defaulting to 0: {e}"
            )

        return (score, entry_path.name, experience_content, justification)
    except Exception as e:
        logging.warning(f"Error reading/scoring experience {entry_path.name}: {e}")
        return None


def _score_experiences_list(
    llm: Any, keywords: list[str], persona: str, jd: str, template: str
) -> list[tuple[int, str, str, str]]:
    """Helper to load and score all candidate experiences."""
    experiences_dir = get_wiki_dir() / "wiki" / "experiences"
    scored: list[tuple[int, str, str, str]] = []
    if not experiences_dir.exists():
        return scored

    for entry_path in experiences_dir.glob("*.md"):
        res = _score_single_experience(llm, entry_path, keywords, persona, jd, template)
        if res is not None:
            scored.append(res)

    return scored


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


def _detect_employment_type(fm: dict[str, Any], content: str) -> str:
    """Detect if the role is Contract, Permanent, or Self-Employed based on YAML frontmatter, tags, title, or body."""
    # First check explicit frontmatter field
    emp_type = fm.get("employment_type")
    if emp_type:
        emp_type_str = str(emp_type).strip().capitalize()
        if emp_type_str in ["Contract", "Permanent", "Self-employed"]:
            return emp_type_str

    tags = [str(t).lower() for t in fm.get("tags", [])]
    tracks = [str(tr).lower() for tr in fm.get("tracks", [])]
    title = str(fm.get("title", "")).lower()

    # Check for startup/co-founding tracks
    if "co-founder" in tags or "co-founder" in tracks or "entrepreneurial" in tracks or any(x in title for x in ["co-founder", "cofounder", "co founder"]):
        return "Self-Employed"

    if "contract" in tags:
        return "Contract"
    
    if "contract" in title:
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
    
    # Check for explicit co-founder/entrepreneurial tags or tracks
    if "co-founder" in tags or "co-founder" in tracks or "entrepreneurial" in tracks:
        return True
    # Also check if 'co-founder' (or close variants) is in the title
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
    if org_clean.startswith("intel"):
        return "intel"
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


def compress_grouped_experience_llm(content: str) -> str:
    """Compresses a grouped set of old experience entries into a beautifully structured nested list."""
    try:
        llm = get_model_for_step("RETRIEVAL")
        system_template = load_prompt("compress_grouped_experience.txt")
        prompt = system_template.replace("{CONTENT}", content)
        
        response = llm.invoke([HumanMessage(content=prompt)])
        return llm_text(response.content)
    except Exception as e:
        logging.warning(f"Failed to compress grouped experience via LLM: {e}")
        return content


def _compress_and_wrap_single_experience(
    score: int, name: str, content: str, justification: str, keywords: list[str], max_pages: int = 1
) -> str:
    """Helper to smart-compress or prune a single experience entry and return wrapped string."""
    fm = _parse_yaml_frontmatter_from_text(content)
    emp_type = _detect_employment_type(fm, content)
    is_startup = _is_parallel_startup_track(fm)
    
    if name.startswith("grouped-"):
        content = compress_grouped_experience_llm(content)
    elif _is_old_role(fm):
        content = compress_experience_llm(content)
    else:
        content = prune_recent_experience(content, keywords, emp_type, max_pages)

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

    # Programmatically group old roles by company first
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
    score_template = load_prompt("retriever_score.txt")
    scored = _score_experiences_list(llm, keywords, persona, jd, score_template)
    scored.sort(key=lambda x: x[0], reverse=True)
    deduplicated = _deduplicate_scored_experiences(scored)
    return _compress_and_wrap_experiences(deduplicated, keywords, max_pages)


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
    """Retrieve and score candidate projects by relevance and links."""
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
            logging.info(
                f"Few-shot example {fs_name} truncated to 12k characters to fit within TPM limits."
            )
        few_shot_examples.append(
            f"--- SUCCESSFUL PAST CV: {fs_name} (RELEVANCE SCORE: {fs_score}) ---\n"
            f"{fs_content_pruned}\n"
            f"--- END SUCCESSFUL PAST CV ---\n"
        )
    return few_shot_examples


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


def get_subject_info(wiki_dir: Path) -> str:
    """Retrieve subject personal/contact info from entities."""
    entities_dir = wiki_dir / "wiki" / "entities"
    if entities_dir.exists():
        for ent in entities_dir.glob("*.md"):
            try:
                c = ent.read_text(encoding="utf-8")
                if 'tags: ["person"' in c or 'tags: ["person",' in c:
                    return c
            except Exception:
                pass
    return ""


def _parse_start_date(entry_str: str) -> tuple[int, int]:
    """Parse start date from entry_str, fallback to (1970, 1) on failure."""
    date_start_match = re.search(r'START_DATE:\s*(\d{4}-\d{2}-\d{2})', entry_str)
    if date_start_match:
        try:
            year, month, _ = map(int, date_start_match.group(1).split('-'))
            return (year, month)
        except Exception:
            pass
            
    fallback_match = re.search(r'start:\s*[\'"]?(\d{4}-\d{1,2}-\d{1,2})[\'"]?', entry_str)
    if fallback_match:
        try:
            year, month, _ = map(int, fallback_match.group(1).split('-'))
            return (year, month)
        except Exception:
            pass
            
    return (1970, 1)


def parse_and_sort_chronological_entries(entries: list[str]) -> str:
    """Parse chronological experience entries, sort them by start date descending, and format them."""
    parsed_entries: list[dict[str, Any]] = []
    for entry_str in entries:
        name_match = re.search(r'CAREER ENTRY: (.*?\.md)', entry_str)
        if not name_match:
            continue
            
        score_match = re.search(r'SEMANTIC RELEVANCE SCORE: (\d+)', entry_str)
        score = int(score_match.group(1)) if score_match else 0
        entry_name = name_match.group(1)
        start_date = _parse_start_date(entry_str)

        parsed_entries.append({
            "name": entry_name,
            "start_date": start_date,
            "score": score,
            "content": entry_str
        })

    parsed_entries.sort(key=lambda x: x["start_date"], reverse=True)
    return "\n\n".join([str(entry["content"]) for entry in parsed_entries])


def invoke_drafter_llm_with_fallback(llm: Any, system_prompt: str, prompt: str) -> Any:
    """Invoke LLM for drafting, with custom handling and fallback for rate limits."""
    try:
        return llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt)
        ])
    except Exception as e:
        err_msg = str(e).lower()
        is_rate_limit = any(
            keyword in err_msg
            for keyword in ["rate_limit", "rate limit", "limit_exceeded", "429"]
        )
        if not is_rate_limit:
            raise e

        fallback_llm = get_fallback_model_for_step("DRAFTING")
        if fallback_llm is None:
            logging.warning(
                f"DRAFTING LLM invocation failed due to rate limit: {e}. "
                "No valid fallback model configured or credentials missing. Re-raising error."
            )
            raise e

        logging.warning(
            f"DRAFTING LLM invocation failed due to rate limit: {e}. "
            "Attempting configured fallback model..."
        )
        try:
            return fallback_llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt)
            ])
        except Exception:
            logging.exception(
                "Configured fallback model failed. Re-raising original rate limit error."
            )
            raise e
