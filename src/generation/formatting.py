"""Formatting, JSON parsing, and LLM text generation utilities for CV generation."""

import json
import logging
from pathlib import Path
import re
import sys
import time
from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
import kb_config
from schemas.cv_models import CompressedSummaryOutput

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
    """Robustly parse a JSON string from LLM output, handling preambles, trailing commas,
    comments, and control characters."""
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


def _extract_compressed_summary(raw_response: str) -> str:
    """Validate and extract clean summary text via CompressedSummaryOutput Pydantic schema."""
    cleaned = raw_response.strip()
    if "{" in cleaned and "}" in cleaned:
        try:
            data = robust_json_loads(cleaned)
            parsed = CompressedSummaryOutput.model_validate(data)
            if parsed.summary.strip():
                cleaned = parsed.summary.strip()
        except Exception:
            pass
    cleaned = re.sub(r"^---\n.*?\n---\s*", "", cleaned, flags=re.DOTALL).strip()
    return strip_wikilinks(cleaned)


def _deterministic_one_liner_fallback(content: str, keywords: list[str] | None = None) -> str:
    """Deterministic fallback that extracts the highest-matching single bullet when LLM socket fails."""
    body = re.sub(r"^---\n.*?\n---\s*", "", content, flags=re.DOTALL).strip()
    bullets = [
        strip_wikilinks(line.strip())
        for line in body.splitlines()
        if line.strip().startswith(("- ", "* ", "• "))
    ]
    if bullets:
        if keywords:
            kw_low = [k.lower() for k in keywords if k]
            bullets.sort(key=lambda b: sum(1 for k in kw_low if k in b.lower()), reverse=True)
        return bullets[0]
    first_para = next((p.strip() for p in body.split("\n\n") if p.strip() and not p.strip().startswith("#")), "")
    return strip_wikilinks(first_para[:220]) if first_para else content


def compress_experience_llm(content: str, keywords: list[str] | None = None, llm: Any = None) -> str:
    """
    Compresses an old, lower-relevance experience entry into a highly concise summary
    retaining metadata, company description/size, location, technologies, and 1 key achievement.
    """
    try:
        model = llm if llm is not None else _get_model_for_step("RETRIEVAL")
        system_template = _resolve_prompt("compress_experience.txt")
        kw_str = ", ".join(keywords) if keywords else "general leadership and technical impact"
        prompt = system_template.replace("{CONTENT}", content).replace("{KEYWORDS}", kw_str)

        response = model.invoke([HumanMessage(content=prompt)])
        return _extract_compressed_summary(llm_text(response.content))
    except Exception as e:
        logger.warning(f"Failed to compress experience via LLM: {e}")
        return content


def compress_experience_to_one_liner_llm(content: str, keywords: list[str] | None = None, llm: Any = None) -> str:
    """
    Compresses an extremely historic experience entry into a single highly optimized,
    ATS-aligned sentence while Python retains its YAML frontmatter deterministically.
    """
    try:
        model = llm if llm is not None else _get_model_for_step("RETRIEVAL")
        system_template = _resolve_prompt("compress_to_one_liner.txt")
        kw_str = ", ".join(keywords) if keywords else "general leadership and technical impact"
        prompt = system_template.replace("{CONTENT}", content).replace("{KEYWORDS}", kw_str)

        response = model.invoke([HumanMessage(content=prompt)])
        return _extract_compressed_summary(llm_text(response.content))
    except Exception as e:
        logger.warning(f"Failed to compress experience to one-liner via LLM: {e}")
        return _deterministic_one_liner_fallback(content, keywords=keywords)


def compress_grouped_experience_llm(content: str, keywords: list[str] | None = None, llm: Any = None) -> str:
    """Compresses a grouped set of old experience entries into a structured nested list."""
    try:
        model = llm if llm is not None else _get_model_for_step("RETRIEVAL")
        system_template = _resolve_prompt("compress_grouped_experience.txt")
        kw_str = ", ".join(keywords) if keywords else "general leadership and technical impact"
        prompt = system_template.replace("{CONTENT}", content).replace("{KEYWORDS}", kw_str)

        response = model.invoke([HumanMessage(content=prompt)])
        return _extract_compressed_summary(llm_text(response.content))
    except Exception as e:
        logger.warning(f"Failed to compress grouped experience via LLM: {e}")
        return content


def invoke_structured_llm(llm: Any, schema: type[Any], messages: list[Any]) -> Any:
    """Invoke an LLM and validate the response into the target Pydantic schema."""
    is_mock = type(llm).__module__.startswith("unittest.mock")
    if not is_mock and hasattr(llm, "with_structured_output"):
        try:
            structured_llm = (
                llm.with_structured_output(schema, method="function_calling")
                if isinstance(llm, ChatOpenAI)
                else llm.with_structured_output(schema)
            )
            res = structured_llm.invoke(messages)
            if isinstance(res, schema):
                return res
            if isinstance(res, dict):
                return schema.model_validate(res)
        except Exception as e:
            logger.debug("with_structured_output fallback triggered for %s: %s", getattr(schema, "__name__", schema), e)

    response = llm.invoke(messages)
    if isinstance(response, schema):
        return response
    if isinstance(response, dict):
        return schema.model_validate(response)
    raw_text = llm_text(response.content)
    data = robust_json_loads(raw_text)
    return schema.model_validate(data)


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
    """Invoke LLM for drafting, with retry for transient Windows socket errors and fallback for rate limits."""
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=prompt),
    ]
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            return llm.invoke(messages)
        except Exception as e:
            last_err = e
            err_msg = str(e).lower()
            is_socket_err = "10013" in err_msg or "connecterror" in err_msg or "socket" in err_msg
            if is_socket_err and attempt < 2:
                logger.warning("Transient socket error on drafting attempt %d/3 (%s); retrying in 1.5s...", attempt + 1, e)
                time.sleep(1.5)
                continue
            break

    assert last_err is not None
    err_msg = str(last_err).lower()
    is_rate_limit = any(
        keyword in err_msg
        for keyword in ["rate_limit", "rate limit", "limit_exceeded", "429"]
    )
    if not is_rate_limit:
        raise last_err

    fallback_llm = _get_fallback_model_for_step("DRAFTING")
    if fallback_llm is None:
        logger.warning(
            f"DRAFTING LLM invocation failed due to rate limit: {last_err}. "
            "No valid fallback model configured or credentials missing. Re-raising error."
        )
        raise last_err

    logger.warning(
        f"DRAFTING LLM invocation failed due to rate limit: {last_err}. "
        "Attempting configured fallback model..."
    )
    try:
        return fallback_llm.invoke(messages)
    except Exception:
        logger.exception(
            "Configured fallback model failed. Re-raising original rate limit error."
        )
        raise last_err


def check_typesetting_budget(draft: str, max_pages: int) -> tuple[bool, str, int, int]:
    """Evaluate whether the drafted CV fits within the calibrated typesetting page budget."""
    words = len(draft.split())
    bullet_lines = sum(
        1 for line in draft.splitlines()
        if line.strip().startswith(("- ", "* ", "• "))
    )
    char_count = len(draft)

    if max_pages == 1:
        word_limit, bullet_limit, char_limit = 500, 20, 4500
    elif max_pages == 3:
        word_limit, bullet_limit, char_limit = 1550, 62, 12500
    elif max_pages >= 4:
        word_limit = max_pages * 500
        bullet_limit = max_pages * 20
        char_limit = 12500 + (max_pages - 3) * 4000
    else:
        word_limit, bullet_limit, char_limit = 1050, 42, 8500

    if words > word_limit or bullet_lines > bullet_limit or char_count > char_limit:
        excess_words = max(0, words - word_limit)
        excess_bullets = max(0, bullet_lines - bullet_limit)
        feedback = (
            f"DENSITY ERROR: The CV is too long. DENSITY OVERFLOW: CV exceeds the {max_pages}-page budget. "
            f"Words: {words}/{word_limit} (+{excess_words}), "
            f"Bullet lines: {bullet_lines}/{bullet_limit} (+{excess_bullets}), "
            f"Characters: {char_count}/{char_limit}. "
            "Compress wordy STAR achievement bullets, eliminate fluff, and trim secondary "
            "accomplishments from older roles."
        )
        return True, feedback, words, bullet_lines

    return False, "", words, bullet_lines


def handle_interactive_audit(checklist: list[str], ats_score: dict[str, Any]) -> tuple[bool, str]:
    """Interactive CLI prompt allowing the user to review the scorecard and guide the audit."""
    _ = ats_score
    if not sys.stdin.isatty():
        return False, ""

    sys.stdout.write(
        "\n" + "=" * 50 + "\nINTERACTIVE AUDITOR REVIEW\n" + "=" * 50 + "\n"
        "[1] Accept Draft (override audit and mark PASS)\n"
        "[2] Provide Custom Revision Guidance\n"
        "[3] Proceed with Automatic Rewrite Checklist\n"
    )
    try:
        choice = input("Select an option [1-3] (default 3): ").strip()
    except (EOFError, KeyboardInterrupt):
        return False, ""

    if choice == "1":
        return True, "PASS"
    if choice == "2":
        try:
            custom_note = input("Enter your custom revision directive for the drafter: ").strip()
        except (EOFError, KeyboardInterrupt):
            custom_note = ""
        if custom_note:
            feedback = f"USER REVISION DIRECTIVE:\n- {custom_note}\n\nORIGINAL AUDIT CHECKLIST:\n" + "\n".join(
                [f"- [ ] {item}" for item in checklist]
            )
            return True, feedback
    return False, ""
