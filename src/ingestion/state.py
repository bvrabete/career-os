"""State definition for the ingestion pipeline."""
from typing import TypedDict, Any


class IngestionState(TypedDict):
    """The state dictionary passed between nodes in the ingestion LangGraph."""
    source_file: str
    raw_text: str
    doc_type: str
    extracted_roles: list[dict[str, Any]]
    extracted_education: list[dict[str, Any]]
    extracted_languages: list[dict[str, Any]]
    extracted_projects: list[dict[str, Any]]
    extracted_patents: list[dict[str, Any]]
    extracted_notes: list[dict[str, Any]]
    extracted_cover_letters: list[dict[str, Any]]
    extracted_profile: dict[str, Any]
    resolved_entities: dict[str, str]
    wiki_outputs: list[dict[str, Any]]
