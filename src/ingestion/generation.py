"""Generation functions and generation node for the Ingestion Pipeline."""
from datetime import date
import logging
from typing import Any

from ingestion.generators.cover_letters import generate_cover_letters
from ingestion.generators.education import generate_education, generate_languages
from ingestion.generators.experiences import generate_experiences
from ingestion.generators.notes import generate_notes
from ingestion.generators.profile import generate_profile
from ingestion.generators.projects import generate_patents, generate_projects
from ingestion.helpers import get_persona_slug, get_schema_path, get_wiki_root, load_prompt
from ingestion.state import IngestionState
from kb_config import get_model_for_step


def _generate_experiences(
    llm: Any,
    roles: list[dict[str, Any]],
    resolved: dict[str, str],
    today_str: str,
    schema_text: str,
    wiki_outputs: list[dict[str, Any]],
) -> None:
    """Generate experience files and append them to wiki_outputs."""
    generate_experiences(
        llm, roles, resolved, today_str, schema_text, wiki_outputs,
        load_prompt_fn=load_prompt, get_wiki_root_fn=get_wiki_root
    )


def _generate_education(
    llm: Any,
    education: list[dict[str, Any]],
    resolved: dict[str, str],
    today_str: str,
    wiki_outputs: list[dict[str, Any]],
) -> None:
    """Generate education files and append them to wiki_outputs."""
    generate_education(
        llm, education, resolved, today_str, wiki_outputs,
        load_prompt_fn=load_prompt, get_wiki_root_fn=get_wiki_root
    )


def _generate_languages(
    llm: Any,
    languages: list[dict[str, Any]],
    today_str: str,
    wiki_outputs: list[dict[str, Any]],
) -> None:
    """Generate language skill files and append them to wiki_outputs."""
    generate_languages(
        llm, languages, today_str, wiki_outputs,
        load_prompt_fn=load_prompt, get_wiki_root_fn=get_wiki_root
    )


def _generate_projects(
    llm: Any,
    projects: list[dict[str, Any]],
    resolved: dict[str, str],
    today_str: str,
    wiki_outputs: list[dict[str, Any]],
) -> None:
    """Generate standalone project files and append them to wiki_outputs."""
    generate_projects(
        llm, projects, resolved, today_str, wiki_outputs,
        load_prompt_fn=load_prompt, get_wiki_root_fn=get_wiki_root
    )


def _generate_patents(
    llm: Any,
    patents: list[dict[str, Any]],
    resolved: dict[str, str],
    today_str: str,
    wiki_outputs: list[dict[str, Any]],
) -> None:
    """Generate standalone patent files and append them to wiki_outputs."""
    generate_patents(
        llm, patents, resolved, today_str, wiki_outputs,
        load_prompt_fn=load_prompt, get_wiki_root_fn=get_wiki_root
    )


def _generate_notes(
    llm: Any,
    notes: list[dict[str, Any]],
    resolved: dict[str, str],
    today_str: str,
    wiki_outputs: list[dict[str, Any]],
) -> None:
    """Generate standalone note/feedback files and append them to wiki_outputs."""
    generate_notes(
        llm, notes, resolved, today_str, wiki_outputs,
        load_prompt_fn=load_prompt, get_wiki_root_fn=get_wiki_root
    )


def _generate_cover_letters(
    llm: Any,
    cover_letters: list[dict[str, Any]],
    resolved: dict[str, str],
    today_str: str,
    wiki_outputs: list[dict[str, Any]],
) -> None:
    """Generate cover letter files and append them to wiki_outputs."""
    generate_cover_letters(
        llm, cover_letters, resolved, today_str, wiki_outputs,
        load_prompt_fn=load_prompt, get_wiki_root_fn=get_wiki_root
    )


def _generate_profile(
    profile: dict[str, Any],
    source_file: str,
    today_str: str,
    wiki_outputs: list[dict[str, Any]],
) -> None:
    """Generate candidate profile markdown (person entity) and add to wiki_outputs."""
    generate_profile(
        profile, source_file, today_str, wiki_outputs,
        get_wiki_root_fn=get_wiki_root,
        get_persona_slug_fn=get_persona_slug,
    )


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
