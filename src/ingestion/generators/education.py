"""Education and language generator module for the ingestion pipeline."""
import json
import logging
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage

from ingestion.helpers import clean_frontmatter, get_wiki_root, llm_text, load_prompt, slugify


def generate_education(
    llm: Any,
    education: list[dict[str, Any]],
    resolved: dict[str, str],
    today_str: str,
    wiki_outputs: list[dict[str, Any]],
    load_prompt_fn: Callable[[str], str] = load_prompt,
    get_wiki_root_fn: Callable[[], Any] = get_wiki_root,
) -> None:
    """Generate education files and append them to wiki_outputs."""
    entity_map_lines = "\n".join(f'  "{raw}" → use [[{slug}]]' for raw, slug in resolved.items())
    edu_system_prompt = load_prompt_fn("generate_education.txt")

    for edu in education:
        raw_inst = edu.get("raw_inst_name", "")
        canonical_slug = resolved.get(raw_inst, slugify(raw_inst))
        title = edu.get("title", "").strip() or "degree"
        title_slug = slugify(title)
        if not title_slug:
            title_slug = "degree"
        filename = f"{canonical_slug}-{title_slug}.md"
        output_path = (get_wiki_root_fn() / "education" / filename).as_posix()

        prompt = f"""CANONICAL ENTITY MAPPING:
{entity_map_lines}

Generate a complete wiki education entry using ONLY the data provided below.

Required output filename: {filename}
Required institution slug in frontmatter: [[{canonical_slug}]]
Required dates in frontmatter: start: "{edu.get('start', '')}", end: "{edu.get('end', '')}"
Required status in frontmatter: {edu.get('status', 'Completed')}
Required major in frontmatter: "{edu.get('major', '')}"
Required minor in frontmatter: "{edu.get('minor', '')}"
Today's date for created/updated: {today_str}

Education data:
{json.dumps(edu, indent=2, ensure_ascii=False)}

Output the complete wiki markdown file content (frontmatter block then body):"""

        try:
            response = llm.invoke([SystemMessage(content=edu_system_prompt), HumanMessage(content=prompt)])
            content = clean_frontmatter(llm_text(response.content))
            wiki_outputs.append({
                "path": output_path,
                "content": content,
                "org_slug": canonical_slug,
                "title": title,
                "validation_errors": [],
            })
            logging.info(f"Generated education: {filename}")
        except Exception as e:
            logging.exception(f"Generator failed for education '{title}' at '{raw_inst}': {e}")
            wiki_outputs.append({
                "path": output_path,
                "content": "",
                "org_slug": canonical_slug,
                "title": title,
                "validation_errors": [f"Generation failed: {e}"],
            })


def generate_languages(
    llm: Any,
    languages: list[dict[str, Any]],
    today_str: str,
    wiki_outputs: list[dict[str, Any]],
    load_prompt_fn: Callable[[str], str] = load_prompt,
    get_wiki_root_fn: Callable[[], Any] = get_wiki_root,
) -> None:
    """Generate language skill files and append them to wiki_outputs."""
    lang_system_prompt = load_prompt_fn("generate_language.txt")

    for lang in languages:
        lang_name = lang.get("language", "").strip() or "unknown-language"
        lang_slug = slugify(lang_name)
        if not lang_slug:
            lang_slug = "unknown"
        filename = f"lang-{lang_slug}.md"
        output_path = (get_wiki_root_fn() / "languages" / filename).as_posix()

        prompt = f"""TODAY'S DATE: {today_str}

Generate a complete wiki language skill entry using ONLY the data provided below.

Required output filename: {filename}
Required title in frontmatter: {lang_name}
Required category in frontmatter: Spoken-Language
Required proficiency in frontmatter: {lang.get('proficiency', 'Native')}
Today's date for created/updated: {today_str}

Language data:
{json.dumps(lang, indent=2, ensure_ascii=False)}

Output the complete wiki markdown file content (frontmatter block then body):"""

        try:
            response = llm.invoke([SystemMessage(content=lang_system_prompt), HumanMessage(content=prompt)])
            content = clean_frontmatter(llm_text(response.content))
            wiki_outputs.append({
                "path": output_path,
                "content": content,
                "org_slug": f"lang-{lang_slug}",
                "title": lang_name,
                "validation_errors": [],
            })
            logging.info(f"Generated language: {filename}")
        except Exception as e:
            logging.exception(f"Generator failed for language '{lang_name}': {e}")
            wiki_outputs.append({
                "path": output_path,
                "content": "",
                "org_slug": f"lang-{lang_slug}",
                "title": lang_name,
                "validation_errors": [f"Generation failed: {e}"],
            })
