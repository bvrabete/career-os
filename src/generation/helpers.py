"""Helper functions for the CV generation pipeline."""

import logging
import json
import re
from pathlib import Path
from typing import Any
import yaml
from langchain_core.messages import HumanMessage
from kb_config import get_model_for_step


def llm_text(content: str | list[Any]) -> str:
    """Coerce a LangChain response.content value to a plain string."""
    if isinstance(content, str):
        return content
    return " ".join(str(part) for part in content)


def robust_json_loads(text: str) -> Any:
    """Robustly parse a JSON string from LLM output, handling preambles, trailing commas, comments, and control characters."""
    if not text:
        raise ValueError("Empty input string")
        
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
        text = text[start_brace:end_brace+1]
    else:
        # Starts with an array
        end_bracket = text.rfind("]")
        if end_bracket == -1:
            raise ValueError("Mismatched opening bracket '['")
        text = text[start_bracket:end_bracket+1]
        
    # 3. Clean up comments (both // and /* */)
    text = re.sub(r'(?<!:)\/\/.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\/\*.*?\*\/', '', text, flags=re.DOTALL)
    
    # 4. Handle trailing commas before closing braces/brackets
    text = re.sub(r',\s*([\]}])', r'\1', text)
    
    # 5. Replace raw newlines and tabs inside string values
    def replace_control_chars(match: re.Match[str]) -> str:
        s = match.group(0)
        s_escaped = s.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
        return s_escaped
    
    string_pattern = r'"(?:[^"\\]|\\.)*"'
    text = re.sub(string_pattern, replace_control_chars, text)

    # 6. Try parsing with standard json.loads
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


def generate_skill_bridging_map(llm: Any, jd: str, skills: list[str], keywords: list[str]) -> dict[str, str]:
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


def prune_recent_experience(content: str, keywords: list[str] = []) -> str:
    """
    Prunes a recent experience file to reduce token bloat before sending it to the DRAFTER.
    - Strips comments (<!-- ... -->)
    - Removes unnecessary YAML fields (created, updated, sources, tags, tracks)
    - Strips the 'Narrative & Reflections' section to preserve token budget for Achievements.
    - Scores and retains only the top 4 achievements based on keyword overlap.
    """
    # 1. Strip HTML comments
    content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
    
    # 2. Extract and prune frontmatter
    fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if fm_match:
        try:
            fm_raw = fm_match.group(1)
            fm = yaml.safe_load(fm_raw) or {}
            
            # Heal dates if start/end are at top-level (common indentation error)
            if "dates" not in fm or not isinstance(fm["dates"], dict):
                start = fm.get("start") or fm.get("dates")
                end = fm.get("end")
                if start or end:
                    fm["dates"] = {
                        "start": start,
                        "end": end or "Present"
                    }
            
            # Keep only essential fields
            pruned_fm: dict[str, Any] = {}
            for key in ["type", "title", "organization", "location", "dates", "skills"]:
                if key in fm:
                    pruned_fm[key] = fm[key]
            
            # Reconstruct frontmatter
            pruned_fm_str = yaml.dump(pruned_fm, sort_keys=False)
            
            # Get body
            body = content[fm_match.end():].strip()
            
            # 3. Strip 'Narrative & Reflections' section if present
            body = re.sub(r'##\s*Narrative\s*&\s*Reflections.*?(?=##\s*|$)', '', body, flags=re.DOTALL)
            
            # 4. Extract and keep only the top 4 achievements
            ach_pattern = r'(^\s*-\s*\*\*Situation.*?(?=(^\s*-\s*\*\*Situation|^\s*##|^\s*###|\Z)))'
            achievements = [m.group(0) for m in re.finditer(ach_pattern, body, flags=re.MULTILINE | re.DOTALL)]
            if achievements:
                scored_ach: list[tuple[int, str]] = []
                for ach in achievements:
                    score = score_by_keywords(ach, keywords)
                    scored_ach.append((score, ach))
                # Sort by score descending
                scored_ach.sort(key=lambda x: x[0], reverse=True)
                top_ach = [x[1] for x in scored_ach[:4]]
                
                # Strip original achievements and append top ones
                clean_body = re.sub(ach_pattern, '', body, flags=re.MULTILINE | re.DOTALL)
                clean_body = re.sub(r'\n{3,}', '\n\n', clean_body).strip()
                body = f"{clean_body}\n\n## Key STAR Achievements\n\n" + "\n".join(top_ach)
            
            # Reconstruct content
            content = f"---\n{pruned_fm_str}---\n\n{body.strip()}"
        except Exception as e:
            logging.warning(f"Failed to prune recent experience: {e}")
            
    return content
