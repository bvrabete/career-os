"""Notes and qualitative artifacts generator module for the ingestion pipeline."""
import json
import logging
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage

from ingestion.helpers import clean_frontmatter, get_wiki_root, llm_text, load_prompt, slugify


def generate_notes(
    llm: Any,
    notes: list[dict[str, Any]],
    resolved: dict[str, str],
    today_str: str,
    wiki_outputs: list[dict[str, Any]],
    load_prompt_fn: Callable[[str], str] = load_prompt,
    get_wiki_root_fn: Callable[[], Any] = get_wiki_root,
) -> None:
    """Generate standalone note/feedback files and append them to wiki_outputs."""
    entity_map_lines = "\n".join(f'  "{raw}" → use [[{slug}]]' for raw, slug in resolved.items())
    system_prompt = load_prompt_fn("generate_note.txt")

    for note in notes:
        title = note.get("title", "").strip() or "note"
        title_slug = slugify(title)
        filename = f"note-{title_slug}.md"
        output_path = (get_wiki_root_fn() / "notes" / filename).as_posix()

        related_raw = note.get("related_raw_orgs", [])
        related_slugs = [f"[[{resolved[r]}]]" for r in related_raw if r in resolved]

        prompt = f"""CANONICAL ENTITY MAPPING:
{entity_map_lines}

TODAY'S DATE: {today_str}

Generate a complete wiki note entry using ONLY the data provided below.

Required output filename: {filename}
Required related slugs in frontmatter: {json.dumps(related_slugs)}
Required perspective: "{note.get('perspective', 'Third-Party')}"
Required tags: {json.dumps(note.get('tags', ['performance-review']))}

Note data:
{json.dumps(note, indent=2, ensure_ascii=False)}

Output the complete wiki markdown file content (frontmatter block then body):"""

        try:
            response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=prompt)])
            content = clean_frontmatter(llm_text(response.content))
            wiki_outputs.append({
                "path": output_path,
                "content": content,
                "org_slug": "",
                "title": title,
                "validation_errors": [],
            })
            logging.info(f"Generated note: {filename}")
        except Exception as e:
            logging.exception(f"Generator failed for note '{title}': {e}")
            wiki_outputs.append({
                "path": output_path,
                "content": "",
                "org_slug": "",
                "title": title,
                "validation_errors": [f"Generation failed: {e}"],
            })
