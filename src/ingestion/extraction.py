"""Extraction functions and extraction node for the Ingestion Pipeline."""
import json
import logging
from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage
from kb_config import get_model_for_step
from ingestion.helpers import load_prompt, llm_text, strip_fences
from ingestion.state import IngestionState


def _extract_experience(llm: Any, raw_text: str) -> dict[str, Any]:
    """Extract experience fields from raw text using the LLM and external prompt."""
    system_prompt = load_prompt("extraction_experience.txt")
    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=(
            "Extract candidate personal profile, all roles, education history, "
            f"spoken languages, projects, and patents from this document:\n\n{raw_text}"
        ))
    ])
    
    raw = llm_text(response.content).strip()
    try:
        return json.loads(strip_fences(raw))  # type: ignore[no-any-return]
    except Exception as e:
        logging.warning(f"Could not parse extractor JSON for experience: {e}")
        logging.warning(f"Response was: {raw[:500]}")
        return {}


def _extract_cover_letter(llm: Any, raw_text: str) -> dict[str, Any]:
    """Extract cover letter fields from raw text using the LLM and external prompt."""
    system_prompt = load_prompt("extraction_cover_letter.txt")
    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Extract cover letter details from this document:\n\n{raw_text}")
    ])
    
    raw = llm_text(response.content).strip()
    try:
        return json.loads(strip_fences(raw))  # type: ignore[no-any-return]
    except Exception as e:
        logging.warning(f"Could not parse extractor JSON for cover_letter: {e}")
        logging.warning(f"Response was: {raw[:500]}")
        return {}


def _extract_supplemental(llm: Any, raw_text: str) -> dict[str, Any]:
    """Extract supplemental fields from raw text using the LLM and external prompt."""
    system_prompt = load_prompt("extraction_supplemental.txt")
    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Extract feedback/performance reviews from this document:\n\n{raw_text}")
    ])
    
    raw = llm_text(response.content).strip()
    try:
        return json.loads(strip_fences(raw))  # type: ignore[no-any-return]
    except Exception as e:
        logging.warning(f"Could not parse extractor JSON for supplemental: {e}")
        logging.warning(f"Response was: {raw[:500]}")
        return {}


def node_extractor(state: IngestionState) -> dict[str, Any]:
    """Pass 1: Extract raw structured data based on doc_type. No canonicalization yet."""
    logging.info("--- NODE: EXTRACTOR (Pass 1) ---")
    doc_type = state.get("doc_type", "")
    raw_text = state.get("raw_text", "")
    
    roles: list[dict[str, Any]] = []
    education: list[dict[str, Any]] = []
    languages: list[dict[str, Any]] = []
    projects: list[dict[str, Any]] = []
    patents: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    cover_letters: list[dict[str, Any]] = []
    profile: dict[str, Any] = {}

    if not raw_text.strip():
        logging.warning("Empty raw_text - skipping extraction")
        return {
            "extracted_roles": roles,
            "extracted_education": education,
            "extracted_languages": languages,
            "extracted_projects": projects,
            "extracted_patents": patents,
            "extracted_notes": notes,
            "extracted_cover_letters": cover_letters,
            "extracted_profile": profile
        }

    llm = get_model_for_step("INGESTION_EXTRACT")

    if doc_type == "experience":
        extracted = _extract_experience(llm, raw_text)
        roles = extracted.get("roles", [])
        education = extracted.get("education", [])
        languages = extracted.get("languages", [])
        projects = extracted.get("projects", [])
        patents = extracted.get("patents", [])
        profile = extracted.get("profile", {})
        logging.info(
            f"Extracted {len(roles)} role(s), {len(education)} education entry(ies), "
            f"{len(languages)} language(s), {len(projects)} project(s), {len(patents)} patent(s)"
        )
        if profile:
            logging.info(f"Extracted personal profile for: {profile.get('name')}")
        
    elif doc_type == "cover_letter":
        extracted = _extract_cover_letter(llm, raw_text)
        cover_letters = extracted.get("cover_letters", [])
        logging.info(f"Extracted {len(cover_letters)} cover letter(s)")
        
    elif doc_type == "supplemental":
        extracted = _extract_supplemental(llm, raw_text)
        notes = extracted.get("notes", [])
        logging.info(f"Extracted {len(notes)} note(s)")
        
    else:
        logging.info(f"doc_type='{doc_type}' — skipping extraction")

    return {
        "extracted_roles": roles,
        "extracted_education": education,
        "extracted_languages": languages,
        "extracted_projects": projects,
        "extracted_patents": patents,
        "extracted_notes": notes,
        "extracted_cover_letters": cover_letters,
        "extracted_profile": profile
    }
