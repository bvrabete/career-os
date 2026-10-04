"""Projects and patents generator module for the ingestion pipeline."""
import json
import logging
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage

from ingestion.helpers import clean_frontmatter, get_wiki_root, llm_text, load_prompt, slugify


def generate_projects(
    llm: Any,
    projects: list[dict[str, Any]],
    resolved: dict[str, str],
    today_str: str,
    wiki_outputs: list[dict[str, Any]],
    load_prompt_fn: Callable[[str], str] = load_prompt,
    get_wiki_root_fn: Callable[[], Any] = get_wiki_root,
) -> None:
    """Generate standalone project files and append them to wiki_outputs."""
    entity_map_lines = "\n".join(f'  "{raw}" → use [[{slug}]]' for raw, slug in resolved.items())
    system_prompt = load_prompt_fn("generate_project.txt")

    for proj in projects:
        raw_org = proj.get("raw_org_name", "")
        canonical_slug = resolved.get(raw_org, slugify(raw_org))
        title = proj.get("title", "").strip() or "project"
        title_slug = slugify(title)
        if not title_slug:
            title_slug = "project"
        filename = f"project-{title_slug}.md"
        output_path = (get_wiki_root_fn() / "projects" / filename).as_posix()

        prompt = f"""CANONICAL ENTITY MAPPING:
{entity_map_lines}

TODAY'S DATE: {today_str}

Generate a complete wiki project entry using ONLY the data provided below.

Required output filename: {filename}
Required organization slug in frontmatter: [[{canonical_slug}]]

Project data:
{json.dumps(proj, indent=2, ensure_ascii=False)}

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
            logging.info(f"Generated project: {filename}")
        except Exception as e:
            logging.exception(f"Generator failed for project '{title}': {e}")
            wiki_outputs.append({
                "path": output_path,
                "content": "",
                "org_slug": canonical_slug,
                "title": title,
                "validation_errors": [f"Generation failed: {e}"],
            })


def generate_patents(
    llm: Any,
    patents: list[dict[str, Any]],
    resolved: dict[str, str],
    today_str: str,
    wiki_outputs: list[dict[str, Any]],
    load_prompt_fn: Callable[[str], str] = load_prompt,
    get_wiki_root_fn: Callable[[], Any] = get_wiki_root,
) -> None:
    """Generate standalone patent files and append them to wiki_outputs."""
    entity_map_lines = "\n".join(f'  "{raw}" → use [[{slug}]]' for raw, slug in resolved.items())
    system_prompt = load_prompt_fn("generate_patent.txt")

    for pat in patents:
        raw_org = pat.get("raw_org_name", "")
        canonical_slug = resolved.get(raw_org, slugify(raw_org))
        title = pat.get("title", "").strip() or "patent"
        pat_id = pat.get("id", "").strip()
        id_slug = slugify(pat_id) if pat_id else slugify(title)
        filename = f"patent-{id_slug}.md"
        output_path = (get_wiki_root_fn() / "patents" / filename).as_posix()

        prompt = f"""CANONICAL ENTITY MAPPING:
{entity_map_lines}

TODAY'S DATE: {today_str}

Generate a complete wiki patent entry using ONLY the data provided below.

Required output filename: {filename}
Required organization slug in frontmatter: [[{canonical_slug}]]

Patent data:
{json.dumps(pat, indent=2, ensure_ascii=False)}

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
            logging.info(f"Generated patent: {filename}")
        except Exception as e:
            logging.exception(f"Generator failed for patent '{title}': {e}")
            wiki_outputs.append({
                "path": output_path,
                "content": "",
                "org_slug": canonical_slug,
                "title": title,
                "validation_errors": [f"Generation failed: {e}"],
            })
