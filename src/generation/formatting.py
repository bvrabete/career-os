"""Formatting, JSON parsing, and LLM text generation utilities for CV generation."""

import json
import logging
from pathlib import Path
import re
import sys
from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage
import kb_config

logger = logging.getLogger(__name__)

BRACKET_LINK_PATTERN = re.compile(r'\[\[(.*?)\]\]')


def _get_model_for_step(step: str) -> Any:
    helpers = sys.modules.get("generation.helpers")
    if helpers and hasattr(helpers, "get_model_for_step"):
        return helpers.get_model_for_step(step)
    return kb_config.get_model_for_step(step)


def _get_fallback_model_for_step(step: str) -> Any:
    helpers = sys.modules.get("generation.helpers")
    if helpers and hasattr(helpers, "get_fallback_model_for_step"):
        return helpers.get_fallback_model_for_step(step)
    return kb_config.get_fallback_model_for_step(step)


def _resolve_prompt(filename: str) -> str:
    helpers = sys.modules.get("generation.helpers")
    if helpers and hasattr(helpers, "load_prompt"):
        return str(helpers.load_prompt(filename))
    return load_prompt(filename)


def llm_text(content: str | list[Any]) -> str:
    """Coerce a LangChain response.content value to a plain string."""
    if isinstance(content, str):
        return content
    return " ".join(str(part) for part in content)


def strip_wikilinks(text: str) -> str:
    """Strip [[wiki-link]] syntax and leave plain text or clean representation."""
    return BRACKET_LINK_PATTERN.sub(r'\1', text)


def _extract_json_block(text: str) -> str:
    """Extract the innermost JSON object or array string from text, stripping markdown code blocks."""
    text = text.strip()

    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    start_brace = text.find("{")
    start_bracket = text.find("[")

    if start_brace == -1 and start_bracket == -1:
        raise ValueError("No JSON object or array found in text")

    if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
        end_brace = text.rfind("}")
        if end_brace == -1:
            raise ValueError("Mismatched opening brace '{'")
        return text[start_brace:end_brace+1]

    end_bracket = text.rfind("]")
    if end_bracket == -1:
        raise ValueError("Mismatched opening bracket '['")
    return text[start_bracket:end_bracket+1]


def _clean_json_comments_and_commas(text: str) -> str:
    """Remove JS-style comments and trailing commas from a JSON string."""
    text = re.sub(r'(?<!:)\/\/.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\/\*.*?\*\/', '', text, flags=re.DOTALL)
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

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"Standard json.loads failed: {e}. Attempting last-resort recovery.")
        try:
            alt_text = text.replace("'", '"')
            return json.loads(alt_text)
        except Exception:
            raise e


def load_prompt(filename: str) -> str:
    """Load an external prompt file from src/prompts/cv_gen/."""
    current_dir = Path(__file__).resolve().parent
    prompt_path = current_dir.parent / "prompts" / "cv_gen" / filename
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt template not found at {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def compress_experience_llm(content: str) -> str:
    """
    Compresses an old, lower-relevance experience entry into a highly concise summary
    retaining metadata, company description/size, location, technologies, and 1 key achievement.
    """
    try:
        llm = _get_model_for_step("RETRIEVAL")
        system_template = _resolve_prompt("compress_experience.txt")
        prompt = system_template.replace("{CONTENT}", content)

        response = llm.invoke([HumanMessage(content=prompt)])
        return llm_text(response.content)
    except Exception as e:
        logger.warning(f"Failed to compress experience via LLM: {e}")
        return content


def compress_experience_to_one_liner_llm(content: str) -> str:
    """
    Compresses an extremely historic experience entry into a single highly optimized,
    ATS-aligned sentence while retaining its YAML frontmatter.
    """
    try:
        llm = _get_model_for_step("RETRIEVAL")
        system_template = _resolve_prompt("compress_to_one_liner.txt")
        prompt = system_template.replace("{CONTENT}", content)

        response = llm.invoke([HumanMessage(content=prompt)])
        return llm_text(response.content)
    except Exception as e:
        logger.warning(f"Failed to compress experience to one-liner via LLM: {e}")
        return content


def compress_grouped_experience_llm(content: str) -> str:
    """Compresses a grouped set of old experience entries into a structured nested list."""
    try:
        llm = _get_model_for_step("RETRIEVAL")
        system_template = _resolve_prompt("compress_grouped_experience.txt")
        prompt = system_template.replace("{CONTENT}", content)

        response = llm.invoke([HumanMessage(content=prompt)])
        return llm_text(response.content)
    except Exception as e:
        logger.warning(f"Failed to compress grouped experience via LLM: {e}")
        return content


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

        fallback_llm = _get_fallback_model_for_step("DRAFTING")
        if fallback_llm is None:
            logger.warning(
                f"DRAFTING LLM invocation failed due to rate limit: {e}. "
                "No valid fallback model configured or credentials missing. Re-raising error."
            )
            raise e

        logger.warning(
            f"DRAFTING LLM invocation failed due to rate limit: {e}. "
            "Attempting configured fallback model..."
        )
        try:
            return fallback_llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt)
            ])
        except Exception:
            logger.exception(
                "Configured fallback model failed. Re-raising original rate limit error."
            )
            raise e
