"""Experience generator module for the ingestion pipeline."""
import json
import logging
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage

from ingestion.helpers import clean_frontmatter, get_wiki_root, llm_text, load_prompt, slugify


def generate_experiences(
    llm: Any,
    roles: list[dict[str, Any]],
    resolved: dict[str, str],
    today_str: str,
    schema_text: str,
    wiki_outputs: list[dict[str, Any]],
    load_prompt_fn: Callable[[str], str] = load_prompt,
    get_wiki_root_fn: Callable[[], Any] = get_wiki_root,
) -> None:
    """Generate experience files and append them to wiki_outputs."""
    entity_map_lines = "\n".join(f'  "{raw}" → use [[{slug}]]' for raw, slug in resolved.items())
    system_prompt = load_prompt_fn("generate_experience.txt")

    for role in roles:
        raw_org = role.get("raw_org_name", "")
        canonical_slug = resolved.get(raw_org, slugify(raw_org))
        title = role.get("title", "").strip() or "role"
        title_slug = slugify(title)
        if not title_slug:
            title_slug = "role"
        filename = f"{canonical_slug}-{title_slug}.md"
        output_path = (get_wiki_root_fn() / "experiences" / filename).as_posix()

        prompt = f"""TODAY'S DATE: {today_str}

CANONICAL ENTITY MAPPING:
{entity_map_lines}

SCHEMA REFERENCE:
{schema_text[:3000]}

Generate a complete wiki experience entry using ONLY the data provided below.

Required output filename: {filename}
Required organization slug in frontmatter: [[{canonical_slug}]]

Role data:
{json.dumps(role, indent=2, ensure_ascii=False)}

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
            logging.info(f"Generated experience: {filename}")
        except Exception as e:
            logging.exception(f"Generator failed for '{title}' at '{raw_org}': {e}")
            wiki_outputs.append({
                "path": output_path,
                "content": "",
                "org_slug": canonical_slug,
                "title": title,
                "validation_errors": [f"Generation failed: {e}"],
            })
