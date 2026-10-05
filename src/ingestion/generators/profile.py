"""Candidate profile and entity generator module for the ingestion pipeline."""
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable

from ingestion.helpers import get_persona_slug, get_wiki_root


def generate_profile(
    profile: dict[str, Any],
    source_file: str,
    today_str: str,
    wiki_outputs: list[dict[str, Any]],
    get_wiki_root_fn: Callable[[], Any] = get_wiki_root,
    get_persona_slug_fn: Callable[[str], str] = get_persona_slug,
) -> None:
    """Generate candidate profile markdown (person entity) and add to wiki_outputs."""
    name = profile.get("name", "").strip()
    if not name:
        logging.warning("No profile name extracted; skipping profile generation")
        return

    slug = get_persona_slug_fn(name)
    target_path = get_wiki_root_fn() / "entities" / f"{slug}.md"

    created_str = today_str
    if target_path.exists():
        try:
            existing_content = target_path.read_text(encoding="utf-8")
            m_created = re.search(r'created:\s*([\d-]+)', existing_content)
            if m_created:
                created_str = m_created.group(1).strip()
        except Exception as e:
            logging.warning(f"Failed to read existing created date: {e}")

    tags = profile.get("tags", [])
    if "person" not in tags:
        tags = ["person"] + tags

    tags_str = json.dumps(tags)
    source_basename = Path(source_file).name

    overview_text = profile.get("overview", "").strip()
    if not overview_text:
        overview_text = (
            f"{name} is a professional specializing in "
            f"{', '.join(tags[1:4]) if len(tags) > 1 else 'their field'}."
        )

    content = f"""---
type: entity
title: {name}
created: {created_str}
updated: {today_str}
tags: {tags_str}
related: []
sources: ["{source_basename}"]
---
# {name}

- **Full Legal Name:** {name}
- **Preferred Name:** {name}
- **Email:** {profile.get("email", "").strip()}
- **LinkedIn:** {profile.get("linkedin", "").strip()}
- **Phone:** {profile.get("phone", "").strip()}
- **Location:** {profile.get("location", "").strip()}

## Overview
{overview_text}
"""
    wiki_outputs.append({
        "path": target_path.as_posix(),
        "content": content,
        "org_slug": slug,
        "title": name,
        "type": "entity",
        "merged": target_path.exists(),
        "validation_errors": [],
    })
    logging.info(f"Generated profile entity for {name} ({slug})")
