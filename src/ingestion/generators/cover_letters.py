"""Cover letter generator module for the ingestion pipeline."""
import json
import logging
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage

from ingestion.helpers import clean_frontmatter, get_wiki_root, llm_text, load_prompt, slugify


def generate_cover_letters(
    llm: Any,
    cover_letters: list[dict[str, Any]],
    resolved: dict[str, str],
    today_str: str,
    wiki_outputs: list[dict[str, Any]],
    load_prompt_fn: Callable[[str], str] = load_prompt,
    get_wiki_root_fn: Callable[[], Any] = get_wiki_root,
) -> None:
    """Generate cover letter files and append them to wiki_outputs."""
    entity_map_lines = "\n".join(f'  "{raw}" → use [[{slug}]]' for raw, slug in resolved.items())
    system_prompt = load_prompt_fn("generate_cover_letter.txt")

    for cl in cover_letters:
        raw_org = cl.get("target_organization_raw", "")
        canonical_slug = resolved.get(raw_org, slugify(raw_org))
        title = cl.get("title", "").strip() or "cover-letter"
        title_slug = slugify(title)
        filename = f"cover-letter-{title_slug}.md"
        output_path = (get_wiki_root_fn() / "cover-letters" / filename).as_posix()

        prompt = f"""CANONICAL ENTITY MAPPING:
{entity_map_lines}

TODAY'S DATE: {today_str}

Generate a complete wiki cover letter entry using ONLY the data provided below.

Required output filename: {filename}
Required target organization in frontmatter: [[{canonical_slug}]]

Cover letter data:
{json.dumps(cl, indent=2, ensure_ascii=False)}

Output the complete wiki markdown file content (frontmatter block then body):"""

        try:
            response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=prompt)])
            content = clean_frontmatter(llm_text(response.content))
            wiki_outputs.append({
                "path": output_path,
                "content": content,
                "org_slug": canonical_slug,
                "title": title,
                "validation_errors": [],
            })
            logging.info(f"Generated cover letter: {filename}")
        except Exception as e:
            logging.exception(f"Generator failed for cover letter '{title}': {e}")
            wiki_outputs.append({
                "path": output_path,
                "content": "",
                "org_slug": canonical_slug,
                "title": title,
                "validation_errors": [f"Generation failed: {e}"],
            })
