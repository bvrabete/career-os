"""LangGraph orchestration nodes for the Ingestion Pipeline."""
import json
import logging
import re
import yaml
import pypdf
import docx
from datetime import date
from pathlib import Path
from typing import Any

try:
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice
    from docling.pipeline.simple_pipeline import SimplePipeline
    HAS_DOCLING = True
except ImportError:
    HAS_DOCLING = False
    DocumentConverter = None  # type: ignore[assignment, misc]
    PdfFormatOption = None  # type: ignore[assignment, misc]
    InputFormat = None  # type: ignore[assignment, misc]
    PdfPipelineOptions = None  # type: ignore[assignment, misc]
    AcceleratorOptions = None  # type: ignore[assignment, misc]
    AcceleratorDevice = None  # type: ignore[assignment, misc]
    SimplePipeline = None  # type: ignore[assignment, misc]
from langchain_core.messages import HumanMessage, SystemMessage

from ingestion.helpers import (
    clean_frontmatter,
    find_existing_education,
    find_existing_experience,
    llm_text,
    load_prompt,
    parse_mappings,
    resolve_org,
    strip_fences,
)
from ingestion.state import IngestionState
from ingestion.validators import (
    _validate_by_type as _validate_by_type,
    _validate_case_study as _validate_case_study,
    _validate_cover_letter as _validate_cover_letter,
    _validate_dates as _validate_dates,
    _validate_education as _validate_education,
    _validate_entity as _validate_entity,
    _validate_experience as _validate_experience,
    _validate_language as _validate_language,
    _validate_note as _validate_note,
    _validate_patent as _validate_patent,
    _validate_project as _validate_project,
    _validate_single_output as _validate_single_output,
    _validate_skill as _validate_skill,
)
from kb_config import get_model_for_step


def _parse_via_pypdf(path: Path) -> str | None:
    """Attempts to parse a PDF file using pypdf. Returns None if it fails or extracts insufficient text."""
    try:
        reader = pypdf.PdfReader(str(path))
        raw_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if len(raw_text.strip()) > 200:
            return raw_text
    except Exception as e:
        logging.warning(f"pypdf failed ({e}), falling back to docling")
    return None


def _parse_via_docling(path: Path, suffix: str) -> str | None:
    """Attempts to parse a PDF or DOC/DOCX file using Docling. Returns None if it fails."""
    if DocumentConverter is None:
        logging.info("Docling optional dependency not installed; skipping docling parser")
        return None
    try:
        if suffix == ".pdf":
            opts: dict[Any, Any] = {}
            if callable(PdfPipelineOptions) and callable(PdfFormatOption) and InputFormat is not None:
                pdf_opts = PdfPipelineOptions()
                pdf_opts.do_table_structure = True
                pdf_opts.do_ocr = True
                pdf_opts.allow_external_plugins = True
                if callable(AcceleratorOptions) and AcceleratorDevice is not None:
                    pdf_opts.accelerator_options = AcceleratorOptions(
                        num_threads=8, device=AcceleratorDevice.CPU
                    )
                opts = {
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_opts)
                }
            converter = DocumentConverter(format_options=opts)
        else:
            simple_opts: dict[Any, Any] = {}
            if callable(PdfFormatOption) and callable(SimplePipeline) and InputFormat is not None:
                simple_opts = {
                    InputFormat.PDF: PdfFormatOption(pipeline_cls=SimplePipeline)
                }
            converter = DocumentConverter(format_options=simple_opts)
        result = converter.convert(str(path))
        return result.document.export_to_markdown()
    except Exception as e:
        logging.warning(f"docling failed ({e}), trying fallback")
    return None


def _parse_fallback(path: Path, suffix: str) -> str:
    """Fallback parser for PDF, DOCX, and text files when other tools fail."""
    if suffix == ".pdf":
        try:
            reader = pypdf.PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            logging.exception(f"pypdf fallback failed: {e}")
    elif suffix in (".docx", ".doc"):
        try:
            doc = docx.Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as e:
            logging.exception(f"python-docx fallback failed: {e}")
    else:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logging.exception(f"Text read failed: {e}")
    return ""


def node_parser(state: IngestionState) -> dict[str, Any]:
    """Parse raw source documents (PDF, DOCX, DOC, MD) using Docling or standard fallbacks."""
    logging.info(f"--- NODE: PARSER ({state['source_file']}) ---")
    path = Path(state["source_file"])
    suffix = path.suffix.lower()

    if suffix in (".pdf", ".docx", ".doc"):
        if suffix == ".pdf":
            raw_text = _parse_via_pypdf(path)
            if raw_text is not None:
                logging.info(f"Parsed via pypdf (primary): {len(raw_text)} chars")
                return {"raw_text": raw_text}
            logging.info("pypdf extracted very little text, falling back to docling")

        raw_text = _parse_via_docling(path, suffix)
        if raw_text is not None:
            logging.info(f"Parsed via docling: {len(raw_text)} chars")
            return {"raw_text": raw_text}

    raw_text = _parse_fallback(path, suffix)
    logging.info(f"Parsed via fallback: {len(raw_text)} chars")
    return {"raw_text": raw_text}


def node_classifier(state: IngestionState) -> dict[str, Any]:
    """Classify the input document type into: experience, cover_letter, supplemental, or skip."""
    logging.info("--- NODE: CLASSIFIER ---")
    raw_text = state.get("raw_text", "")

    if not raw_text.strip():
        logging.warning("Empty document — classifying as skip")
        return {"doc_type": "skip"}

    llm = get_model_for_step("INGESTION_CLASSIFY")
    preview = raw_text[:4000]

    system_prompt = load_prompt("classifier.txt")
    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Classify this document:\n\n{preview}")
    ])

    try:
        result = json.loads(strip_fences(llm_text(response.content)))
        doc_type = result.get("doc_type", "skip")
        logging.info(f"Classified as: {doc_type} — {result.get('reason', '')[:80]}")
    except Exception as e:
        logging.warning(f"Could not parse classifier JSON: {e} — defaulting to 'skip'")
        doc_type = "skip"

    return {"doc_type": doc_type}


def _resolve_key_and_log(
    items: list[dict[str, Any]] | list[str] | None,
    key_or_none: str | None,
    mappings: dict[str, str],
    resolved: dict[str, str],
    log_template: str
) -> None:
    """Helper to resolve a key or direct string against mappings and log the translation."""
    if not items:
        return
    for item in items:
        if isinstance(item, str):
            raw_name = item
        elif isinstance(item, dict) and key_or_none:
            val = item.get(key_or_none)
            raw_name = str(val) if val is not None else ""
        else:
            raw_name = ""
        if raw_name:
            slug = resolve_org(raw_name, mappings)
            resolved[raw_name] = slug
            logging.info(log_template.format(raw_name=raw_name, slug=slug))


def node_entity_resolver(state: IngestionState) -> dict[str, Any]:
    """Pure Python: map raw organization/institution names to canonical slugs from mappings.md."""
    logging.info("--- NODE: ENTITY RESOLVER (Python) ---")
    mappings = parse_mappings()
    resolved: dict[str, str] = {}

    specs = [
        (state.get("extracted_roles"), "raw_org_name", "  '{raw_name}' → '[[{slug}]]'"),
        (
            state.get("extracted_education"),
            "raw_inst_name",
            "  Education institution '{raw_name}' → '[[{slug}]]'",
        ),
        (state.get("extracted_projects"), "raw_org_name", "  Project org '{raw_name}' → '[[{slug}]]'"),
        (state.get("extracted_patents"), "raw_org_name", "  Patent org '{raw_name}' → '[[{slug}]]'"),
        (
            state.get("extracted_cover_letters"),
            "target_organization_raw",
            "  Cover letter org '{raw_name}' → '[[{slug}]]'",
        ),
        (
            state.get("extracted_case_studies"),
            "related_raw_org",
            "  Case study org '{raw_name}' → '[[{slug}]]'",
        ),
    ]
    for items, key, log_tmpl in specs:
        _resolve_key_and_log(items, key, mappings, resolved, log_tmpl)

    for note in state.get("extracted_notes", []):
        _resolve_key_and_log(
            note.get("related_raw_orgs"), None, mappings, resolved, "  Note org '{raw_name}' → '[[{slug}]]'"
        )

    return {"resolved_entities": resolved}


def _get_page_info(content: str) -> tuple[str, str]:
    """Extracts (role_start, page_type) from frontmatter of output content."""
    fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if fm_match:
        try:
            fm = yaml.safe_load(fm_match.group(1)) or {}
            role_start = str(fm.get("dates", {}).get("start", ""))
            page_type = fm.get("type", "experience")
            return role_start, page_type
        except Exception:
            pass
    return "", "experience"


def _find_existing_page(page_type: str, org_slug: str, path: Path, role_start: str) -> Path | None:
    """Finds existing wiki page path based on page_type."""
    if page_type == "experience":
        return find_existing_experience(org_slug, path, role_start)
    if page_type == "education":
        return find_existing_education(org_slug, path, role_start)
    return path if path.exists() else None


def _merge_single_output(output: dict[str, Any], today: str, llm: Any) -> dict[str, Any]:
    """Merges a single wiki output with its existing counterpart using the LLM."""
    if output.get("validation_errors"):
        return output

    path = Path(output["path"])
    role_start, page_type = _get_page_info(output.get("content", ""))
    existing = _find_existing_page(page_type, output.get("org_slug", ""), path, role_start)

    if existing is None:
        logging.info(f"New file — no merge needed: {path.name}")
        return output

    if existing != path:
        logging.info(f"Redirecting merge: {path.name} → {existing.name}")
        output = {**output, "path": str(existing)}
        path = existing

    logging.info(f"--- MERGE: {path.name} ---")
    existing_content = path.read_text(encoding="utf-8")

    prompt_filename = f"merge_{page_type}.txt"
    if page_type not in ("experience", "education", "project", "patent", "note", "entity", "cover-letter"):
        prompt_filename = "merge_language.txt"

    system_prompt = load_prompt(prompt_filename)

    prompt = f"""TODAY'S DATE: {today}

Merge the new evidence into the existing wiki page. Output the complete merged file.

EXISTING PAGE:
{existing_content}

NEW EVIDENCE TO INTEGRATE:
{output['content']}"""

    try:
        response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=prompt)])
        merged_content = clean_frontmatter(llm_text(response.content))
        logging.info(f"Merged successfully: {path.name}")
        return {**output, "content": merged_content, "merged": True}
    except Exception as e:
        logging.exception(f"Merge failed for {path.name}: {e} — keeping generated version as-is")
        return {**output, "merged": False, "merge_error": str(e)}


def node_merger(state: IngestionState) -> dict[str, Any]:
    """For each generated output, merge with the existing wiki page if one already exists."""
    outputs = state.get("wiki_outputs", [])
    if not outputs:
        return {"wiki_outputs": outputs}

    today = date.today().isoformat()
    llm = get_model_for_step("INGESTION_MERGE")
    merged_outputs = [_merge_single_output(o, today, llm) for o in outputs]
    return {"wiki_outputs": merged_outputs}

def node_validator(state: IngestionState) -> dict[str, Any]:
    """Pure Python: validate frontmatter schema compliance for all generated wiki outputs."""
    logging.info("--- NODE: VALIDATOR ---")
    wiki_outputs = state.get("wiki_outputs", [])
    validated = [_validate_single_output(o) for o in wiki_outputs]
    return {"wiki_outputs": validated}



def node_writer(state: IngestionState, dry_run: bool = False) -> dict[str, Any]:
    """Write validated wiki files; skip duplicates and validation failures."""
    logging.info("--- NODE: WRITER ---")
    written_outputs: list[dict[str, Any]] = []

    for output in state.get("wiki_outputs", []):
        errors = output.get("validation_errors", [])
        if errors:
            logging.warning(f"Skipping {output['path']} (validation errors: {errors})")
            written_outputs.append({**output, "written": False})
            continue

        path = Path(output["path"])
        is_merge = output.get("merged", False)

        if path.exists() and not is_merge:
            logging.warning(f"File exists and was not merged — skipping: {path.name}")
            written_outputs.append({**output, "written": False, "skipped_reason": "duplicate"})
            continue

        action = "update" if is_merge else "create"
        if dry_run:
            logging.info(f"[DRY RUN] Would {action}: {path}")
            written_outputs.append({**output, "written": False, "dry_run": True})
            continue

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output["content"], encoding="utf-8")
        logging.info(f"{'Updated' if is_merge else 'Created'}: {path}")
        written_outputs.append({**output, "written": True})

    return {"wiki_outputs": written_outputs}
