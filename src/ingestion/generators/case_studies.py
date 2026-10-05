"""Case studies generator module for the ingestion pipeline."""
import logging
from pathlib import Path
from typing import Any, Callable
import yaml

from ingestion.helpers import clean_frontmatter, get_wiki_root, load_prompt, slugify


def generate_case_studies(
    llm: Any,
    case_studies: list[dict[str, Any]],
    resolved: dict[str, str],
    today_str: str,
    wiki_outputs: list[dict[str, Any]],
    source_file: str = "",
    load_prompt_fn: Callable[[str], str] = load_prompt,
    get_wiki_root_fn: Callable[[], Any] = get_wiki_root,
) -> None:
    """Generate case study markdown files and append them to wiki_outputs."""
    for cs in case_studies:
        title = cs.get("title", "").strip() or "Case Study"
        raw_org = cs.get("related_raw_org", "")
        org_slug = resolved.get(raw_org, slugify(raw_org))
        title_slug = slugify(title)

        # Build file slug
        slug = title_slug if org_slug and title_slug.startswith(org_slug) else f"{org_slug}-{title_slug}"
        filename = f"{slug}.md"
        output_path = (get_wiki_root_fn() / "case-studies" / filename).as_posix()

        raw_text = cs.get("raw_text", "")
        # Strip existing frontmatter if present to ensure canonical formatting
        body = raw_text
        if raw_text.startswith("---"):
            parts = raw_text.split("---", 2)
            if len(parts) >= 3:
                body = parts[2].strip()

        # Build frontmatter dict
        fm_data: dict[str, Any] = {
            "type": "case_study",
            "title": title,
            "organization": f"[[{org_slug}]]" if org_slug else "",
            "skills": cs.get("skills", []),
            "tags": cs.get("tags", ["architecture"]),
            "created": today_str,
            "updated": today_str,
            "sources": [Path(source_file).name] if source_file else ["ingestion"],
        }
        fm_yaml = yaml.dump(fm_data, default_flow_style=False, sort_keys=False).strip()
        full_content = clean_frontmatter(f"---\n{fm_yaml}\n---\n\n{body}\n")

        wiki_outputs.append({
            "path": output_path,
            "content": full_content,
            "org_slug": org_slug,
            "title": title,
            "validation_errors": [],
        })
        logging.info(f"Generated case study: {filename}")
