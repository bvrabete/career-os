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

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice
from docling.pipeline.simple_pipeline import SimplePipeline
from langchain_core.messages import HumanMessage, SystemMessage

from kb_config import get_model_for_step
from ingestion.state import IngestionState
from ingestion.helpers import (
    load_prompt, llm_text, strip_fences, clean_frontmatter,
    parse_mappings, resolve_org, slugify, get_schema_path, get_wiki_root,
    find_existing_experience, find_existing_education
)

# Shared date pattern for validator
DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$|^Present$')


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
    try:
        if suffix == ".pdf":
            pdf_opts = PdfPipelineOptions()
            pdf_opts.do_table_structure = True
            pdf_opts.do_ocr = True
            pdf_opts.allow_external_plugins = True
            pdf_opts.accelerator_options = AcceleratorOptions(
                num_threads=8, device=AcceleratorDevice.CPU
            )
            converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_opts)
                }
            )
        else:
            converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_cls=SimplePipeline)
                }
            )
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
        else:
            raw_name = item.get(key_or_none or "") if key_or_none else ""
        if raw_name:
            slug = resolve_org(raw_name, mappings)
            resolved[raw_name] = slug
            logging.info(log_template.format(raw_name=raw_name, slug=slug))


def node_entity_resolver(state: IngestionState) -> dict[str, Any]:
    """Pure Python: map raw organization/institution names to canonical slugs from mappings.md."""
    logging.info("--- NODE: ENTITY RESOLVER (Python) ---")
    mappings = parse_mappings()
    resolved: dict[str, str] = {}

    _resolve_key_and_log(state.get("extracted_roles"), "raw_org_name", mappings, resolved, "  '{raw_name}' → '[[{slug}]]'")
    _resolve_key_and_log(state.get("extracted_education"), "raw_inst_name", mappings, resolved, "  Education institution '{raw_name}' → '[[{slug}]]'")
    _resolve_key_and_log(state.get("extracted_projects"), "raw_org_name", mappings, resolved, "  Project org '{raw_name}' → '[[{slug}]]'")
    _resolve_key_and_log(state.get("extracted_patents"), "raw_org_name", mappings, resolved, "  Patent org '{raw_name}' → '[[{slug}]]'")

    for note in state.get("extracted_notes", []):
        _resolve_key_and_log(note.get("related_raw_orgs"), None, mappings, resolved, "  Note org '{raw_name}' → '[[{slug}]]'")

    _resolve_key_and_log(state.get("extracted_cover_letters"), "target_organization_raw", mappings, resolved, "  Cover letter org '{raw_name}' → '[[{slug}]]'")

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


# ---------------------------------------------------------------------------
# Validation sub-helpers to maintain cyclomatic complexity < 15
# ---------------------------------------------------------------------------

def _validate_dates(dates: Any, errors: list[str]) -> None:
    """Validate start and end fields in frontmatter dates dictionary."""
    if isinstance(dates, dict):
        for field in ("start", "end"):
            raw_val = str(dates.get(field, ""))
            val = raw_val.split()[0] if raw_val else ""
            if val and not DATE_PATTERN.match(val):
                errors.append(f"dates.{field} invalid format: '{raw_val}'")


def _validate_experience(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate experience type frontmatter schema."""
    EXP_REQUIRED = {"type", "title", "organization", "dates", "tracks", "skills"}
    missing = EXP_REQUIRED - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

    org = str(fm.get("organization", ""))
    if "[[" not in org or "]]" not in org:
        errors.append(f"organization field missing [[slug]] syntax: '{org}'")

    _validate_dates(fm.get("dates"), errors)

    emp_type = fm.get("employment_type")
    if emp_type and str(emp_type).strip().capitalize() not in ("Permanent", "Contract"):
        errors.append(f"employment_type must be either 'Permanent' or 'Contract', got '{emp_type}'")


def _validate_education(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate education type frontmatter schema."""
    EDU_REQUIRED = {"type", "title", "institution", "dates", "status", "major", "minor"}
    missing = EDU_REQUIRED - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

    inst = str(fm.get("institution", ""))
    if "[[" not in inst or "]]" not in inst:
        errors.append(f"institution field missing [[slug]] syntax: '{inst}'")

    _validate_dates(fm.get("dates"), errors)


def _validate_skill(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate skill type frontmatter schema."""
    SKILL_REQUIRED = {"type", "title", "category", "proficiency"}
    missing = SKILL_REQUIRED - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")
        
    category = fm.get("category", "")
    valid_categories = ("Language-Code", "Framework", "Infrastructure", "Leadership", "Spoken-Language")
    if category not in valid_categories:
        errors.append(f"Invalid skill category: '{category}'")


def _validate_language(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate language type frontmatter schema."""
    LANG_REQUIRED = {"type", "title", "proficiency"}
    missing = LANG_REQUIRED - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")


def _validate_project(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate project type frontmatter schema."""
    PROJ_REQUIRED = {"type", "title", "organization", "dates", "skills"}
    missing = PROJ_REQUIRED - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

    org = str(fm.get("organization", ""))
    if "[[" not in org or "]]" not in org:
        errors.append(f"organization field missing [[slug]] syntax: '{org}'")

    _validate_dates(fm.get("dates"), errors)


def _validate_patent(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate patent type frontmatter schema."""
    PAT_REQUIRED = {"type", "title", "id", "inventors", "organization", "skills"}
    missing = PAT_REQUIRED - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

    org = str(fm.get("organization", ""))
    if "[[" not in org or "]]" not in org:
        errors.append(f"organization field missing [[slug]] syntax: '{org}'")


def _validate_note(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate note type frontmatter schema."""
    NOTE_REQUIRED = {"type", "title", "related", "perspective", "tags"}
    missing = NOTE_REQUIRED - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")


def _validate_cover_letter(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate cover letter type frontmatter schema."""
    CL_REQUIRED = {"type", "title", "target_organization", "related_synthesis"}
    missing = CL_REQUIRED - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

    org = str(fm.get("target_organization", ""))
    if "[[" not in org or "]]" not in org:
        errors.append(f"target_organization field missing [[slug]] syntax: '{org}'")


def _validate_entity(fm: dict[str, Any], errors: list[str]) -> None:
    """Validate entity type frontmatter schema."""
    ENTITY_REQUIRED = {"type", "title", "tags", "sources"}
    missing = ENTITY_REQUIRED - set(fm.keys())
    if missing:
        errors.append(f"Missing frontmatter fields: {sorted(missing)}")


def _validate_by_type(page_type: str, fm: dict[str, Any], errors: list[str]) -> None:
    """Invokes the specific validator function based on page_type."""
    validators = {
        "experience": _validate_experience,
        "education": _validate_education,
        "skill": _validate_skill,
        "language": _validate_language,
        "project": _validate_project,
        "patent": _validate_patent,
        "note": _validate_note,
        "cover-letter": _validate_cover_letter,
        "entity": _validate_entity,
    }
    validator = validators.get(page_type)
    if validator:
        validator(fm, errors)
    else:
        errors.append(f"Unknown frontmatter type: '{page_type}'")


def _validate_single_output(output: dict[str, Any]) -> dict[str, Any]:
    """Validates the frontmatter and content of a single wiki output."""
    errors: list[str] = list(output.get("validation_errors", []))
    content = clean_frontmatter(output.get("content", ""))
    output["content"] = content

    if not content:
        errors.append("Empty content — generation may have failed")
        return {**output, "validation_errors": errors}

    fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not fm_match:
        errors.append("No valid YAML frontmatter block found")
    else:
        try:
            fm = yaml.safe_load(fm_match.group(1)) or {}
            page_type = fm.get("type", "unknown")
            _validate_by_type(page_type, fm, errors)
        except yaml.YAMLError as e:
            errors.append(f"YAML parse error: {e}")

    if errors:
        logging.warning(f"Validation issues for {output['path']}: {errors}")
    else:
        logging.info(f"Validation passed: {output['path']}")

    return {**output, "validation_errors": errors}


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
