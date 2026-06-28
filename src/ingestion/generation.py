"""Generation functions and generation node for the Ingestion Pipeline."""
import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage
from kb_config import get_model_for_step
from ingestion.helpers import (
    load_prompt, get_schema_path, get_wiki_root, get_persona_slug,
    llm_text, clean_frontmatter, slugify, add_persona_mapping_if_missing
)
from ingestion.state import IngestionState



def _generate_experiences(
    llm: Any, roles: list[dict[str, Any]], resolved: dict[str, str],
    today_str: str, schema_text: str, wiki_outputs: list[dict[str, Any]]
) -> None:
    """Generate experience files and append them to wiki_outputs."""
    entity_map_lines = "\n".join(f'  "{raw}" → use [[{slug}]]' for raw, slug in resolved.items())
    
    # Load and format external system prompt template
    system_template = load_prompt("generate_experience.txt")
    system_prompt = (
        system_template
        .replace("{ENTITY_MAP_LINES}", entity_map_lines)
        .replace("{SCHEMA_TEXT}", schema_text[:3000])
    )

    for role in roles:
        raw_org = role.get("raw_org_name", "")
        canonical_slug = resolved.get(raw_org, slugify(raw_org))
        title = role.get("title", "").strip() or "role"
        title_slug = slugify(title)
        if not title_slug:
            title_slug = "role"
        filename = f"{canonical_slug}-{title_slug}.md"
        output_path = str(get_wiki_root() / "experiences" / filename)

        prompt = f"""Generate a complete wiki experience entry using ONLY the data provided below.

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


def _generate_education(
    llm: Any, education: list[dict[str, Any]], resolved: dict[str, str],
    today_str: str, wiki_outputs: list[dict[str, Any]]
) -> None:
    """Generate education files and append them to wiki_outputs."""
    entity_map_lines = "\n".join(f'  "{raw}" → use [[{slug}]]' for raw, slug in resolved.items())
    
    system_template = load_prompt("generate_education.txt")
    edu_system_prompt = system_template.replace("{ENTITY_MAP_LINES}", entity_map_lines)

    for edu in education:
        raw_inst = edu.get("raw_inst_name", "")
        canonical_slug = resolved.get(raw_inst, slugify(raw_inst))
        title = edu.get("title", "").strip() or "degree"
        title_slug = slugify(title)
        if not title_slug:
            title_slug = "degree"
        filename = f"{canonical_slug}-{title_slug}.md"
        output_path = str(get_wiki_root() / "education" / filename)

        prompt = f"""Generate a complete wiki education entry using ONLY the data provided below.

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


def _generate_languages(
    llm: Any, languages: list[dict[str, Any]], today_str: str, wiki_outputs: list[dict[str, Any]]
) -> None:
    """Generate language skill files and append them to wiki_outputs."""
    system_template = load_prompt("generate_language.txt")
    lang_system_prompt = system_template.replace("{TODAY_STR}", today_str)

    for lang in languages:
        lang_name = lang.get("language", "").strip() or "unknown-language"
        lang_slug = slugify(lang_name)
        if not lang_slug:
            lang_slug = "unknown"
        filename = f"lang-{lang_slug}.md"
        output_path = str(get_wiki_root() / "skills" / filename)

        prompt = f"""Generate a complete wiki language skill entry using ONLY the data provided below.

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


def _generate_projects(
    llm: Any, projects: list[dict[str, Any]], resolved: dict[str, str],
    today_str: str, wiki_outputs: list[dict[str, Any]]
) -> None:
    """Generate standalone project files and append them to wiki_outputs."""
    entity_map_lines = "\n".join(f'  "{raw}" → use [[{slug}]]' for raw, slug in resolved.items())
    
    system_template = load_prompt("generate_project.txt")
    system_prompt = (
        system_template
        .replace("{ENTITY_MAP_LINES}", entity_map_lines)
        .replace("{TODAY_STR}", today_str)
    )

    for proj in projects:
        raw_org = proj.get("raw_org_name", "")
        canonical_slug = resolved.get(raw_org, slugify(raw_org))
        title = proj.get("title", "").strip() or "project"
        title_slug = slugify(title)
        if not title_slug:
            title_slug = "project"
        filename = f"project-{title_slug}.md"
        output_path = str(get_wiki_root() / "projects" / filename)

        prompt = f"""Generate a complete wiki project entry using ONLY the data provided below.

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


def _generate_patents(
    llm: Any, patents: list[dict[str, Any]], resolved: dict[str, str],
    today_str: str, wiki_outputs: list[dict[str, Any]]
) -> None:
    """Generate standalone patent files and append them to wiki_outputs."""
    entity_map_lines = "\n".join(f'  "{raw}" → use [[{slug}]]' for raw, slug in resolved.items())
    
    system_template = load_prompt("generate_patent.txt")
    system_prompt = (
        system_template
        .replace("{ENTITY_MAP_LINES}", entity_map_lines)
        .replace("{TODAY_STR}", today_str)
    )

    for pat in patents:
        raw_org = pat.get("raw_org_name", "")
        canonical_slug = resolved.get(raw_org, slugify(raw_org))
        title = pat.get("title", "").strip() or "patent"
        pat_id = pat.get("id", "").strip()
        id_slug = slugify(pat_id) if pat_id else slugify(title)
        filename = f"patent-{id_slug}.md"
        output_path = str(get_wiki_root() / "patents" / filename)

        prompt = f"""Generate a complete wiki patent entry using ONLY the data provided below.

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


def _generate_notes(
    llm: Any, notes: list[dict[str, Any]], resolved: dict[str, str],
    today_str: str, wiki_outputs: list[dict[str, Any]]
) -> None:
    """Generate standalone note/feedback files and append them to wiki_outputs."""
    entity_map_lines = "\n".join(f'  "{raw}" → use [[{slug}]]' for raw, slug in resolved.items())
    
    system_template = load_prompt("generate_note.txt")
    system_prompt = (
        system_template
        .replace("{ENTITY_MAP_LINES}", entity_map_lines)
        .replace("{TODAY_STR}", today_str)
    )

    for note in notes:
        title = note.get("title", "").strip() or "note"
        title_slug = slugify(title)
        filename = f"note-{title_slug}.md"
        output_path = str(get_wiki_root() / "notes" / filename)

        related_raw = note.get("related_raw_orgs", [])
        related_slugs = [f"[[{resolved[r]}]]" for r in related_raw if r in resolved]
        
        prompt = f"""Generate a complete wiki note entry using ONLY the data provided below.

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


def _generate_cover_letters(
    llm: Any, cover_letters: list[dict[str, Any]], resolved: dict[str, str],
    today_str: str, wiki_outputs: list[dict[str, Any]]
) -> None:
    """Generate cover letter files and append them to wiki_outputs."""
    entity_map_lines = "\n".join(f'  "{raw}" → use [[{slug}]]' for raw, slug in resolved.items())
    
    system_template = load_prompt("generate_cover_letter.txt")
    system_prompt = (
        system_template
        .replace("{ENTITY_MAP_LINES}", entity_map_lines)
        .replace("{TODAY_STR}", today_str)
    )

    for cl in cover_letters:
        raw_org = cl.get("target_organization_raw", "")
        canonical_slug = resolved.get(raw_org, slugify(raw_org))
        title = cl.get("title", "").strip() or "cover-letter"
        title_slug = slugify(title)
        filename = f"cover-letter-{title_slug}.md"
        output_path = str(get_wiki_root() / "cover-letters" / filename)

        prompt = f"""Generate a complete wiki cover letter entry using ONLY the data provided below.

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


def _generate_profile(
    profile: dict[str, Any], source_file: str, today_str: str, wiki_outputs: list[dict[str, Any]]
) -> None:
    """Generate candidate profile markdown (person entity) and add to wiki_outputs."""
    name = profile.get("name", "").strip()
    if not name:
        logging.warning("No profile name extracted; skipping profile generation")
        return

    slug = get_persona_slug(name)
    target_path = get_wiki_root() / "entities" / f"{slug}.md"
    
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
        "path": str(target_path),
        "content": content,
        "org_slug": slug,
        "title": name,
        "type": "entity",
        "merged": target_path.exists(),
        "validation_errors": [],
    })
    logging.info(f"Generated profile entity for {name} ({slug})")


def node_generator(state: IngestionState) -> dict[str, Any]:
    """Pass 2: Generate schema-compliant wiki markdown using canonical slugs."""
    logging.info("--- NODE: GENERATOR (Pass 2) ---")
    roles = state.get("extracted_roles", [])
    education = state.get("extracted_education", [])
    languages = state.get("extracted_languages", [])
    projects = state.get("extracted_projects", [])
    patents = state.get("extracted_patents", [])
    notes = state.get("extracted_notes", [])
    cover_letters = state.get("extracted_cover_letters", [])
    profile = state.get("extracted_profile", {})

    if not any([roles, education, languages, projects, patents, notes, cover_letters, profile]):
        logging.info("No content to generate")
        return {"wiki_outputs": []}

    llm = get_model_for_step("INGESTION_GENERATE")
    resolved = state.get("resolved_entities", {})
    schema_path = get_schema_path()
    schema_text = schema_path.read_text(encoding="utf-8") if schema_path.exists() else ""
    today_str = date.today().isoformat()

    wiki_outputs: list[dict[str, Any]] = []

    if roles:
        _generate_experiences(llm, roles, resolved, today_str, schema_text, wiki_outputs)

    if education:
        _generate_education(llm, education, resolved, today_str, wiki_outputs)

    if languages:
        _generate_languages(llm, languages, today_str, wiki_outputs)

    if projects:
        _generate_projects(llm, projects, resolved, today_str, wiki_outputs)

    if patents:
        _generate_patents(llm, patents, resolved, today_str, wiki_outputs)

    if notes:
        _generate_notes(llm, notes, resolved, today_str, wiki_outputs)

    if cover_letters:
        _generate_cover_letters(llm, cover_letters, resolved, today_str, wiki_outputs)

    if profile:
        _generate_profile(profile, state.get("source_file", ""), today_str, wiki_outputs)

    return {"wiki_outputs": wiki_outputs}
