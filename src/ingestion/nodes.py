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


def node_parser(state: IngestionState) -> dict[str, Any]:
    """Parse raw source documents (PDF, DOCX, DOC, MD) using Docling or standard fallbacks."""
    logging.info(f"--- NODE: PARSER ({state['source_file']}) ---")
    path = Path(state["source_file"])
    suffix = path.suffix.lower()
    raw_text = ""

    if suffix in (".pdf", ".docx", ".doc"):
        if suffix == ".pdf":
            # Try pypdf first (layout-accurate for digital PDFs and extremely fast)
            try:
                reader = pypdf.PdfReader(str(path))
                raw_text = "\n".join(page.extract_text() or "" for page in reader.pages)
                if len(raw_text.strip()) > 200:
                    logging.info(f"Parsed via pypdf (primary): {len(raw_text)} chars")
                    return {"raw_text": raw_text}
                logging.info("pypdf extracted very little text, falling back to docling")
            except Exception as e:
                logging.warning(f"pypdf failed ({e}), falling back to docling")

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
            raw_text = result.document.export_to_markdown()
            logging.info(f"Parsed via docling: {len(raw_text)} chars")
        except Exception as e:
            logging.warning(f"docling failed ({e}), trying fallback")
            if suffix == ".pdf":
                try:
                    reader = pypdf.PdfReader(str(path))
                    raw_text = "\n".join(page.extract_text() or "" for page in reader.pages)
                    logging.info(f"Parsed via pypdf fallback: {len(raw_text)} chars")
                except Exception as e2:
                    logging.exception(f"pypdf fallback failed: {e2}")
            elif suffix in (".docx", ".doc"):
                try:
                    doc = docx.Document(str(path))
                    raw_text = "\n".join(p.text for p in doc.paragraphs)
                    logging.info(f"Parsed via python-docx fallback: {len(raw_text)} chars")
                except Exception as e2:
                    logging.exception(f"python-docx fallback failed: {e2}")
    else:
        try:
            raw_text = path.read_text(encoding="utf-8", errors="replace")
            logging.info(f"Read as text: {len(raw_text)} chars")
        except Exception as e:
            logging.exception(f"Text read failed: {e}")

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


def node_entity_resolver(state: IngestionState) -> dict[str, Any]:
    """Pure Python: map raw organization/institution names to canonical slugs from mappings.md."""
    logging.info("--- NODE: ENTITY RESOLVER (Python) ---")
    mappings = parse_mappings()
    resolved: dict[str, str] = {}

    for role in state.get("extracted_roles", []):
        raw_name = role.get("raw_org_name", "")
        if raw_name:
            slug = resolve_org(raw_name, mappings)
            resolved[raw_name] = slug
            logging.info(f"  '{raw_name}' → '[[{slug}]]'")

    for edu in state.get("extracted_education", []):
        raw_name = edu.get("raw_inst_name", "")
        if raw_name:
            slug = resolve_org(raw_name, mappings)
            resolved[raw_name] = slug
            logging.info(f"  Education institution '{raw_name}' → '[[{slug}]]'")

    for proj in state.get("extracted_projects", []):
        raw_name = proj.get("raw_org_name", "")
        if raw_name:
            slug = resolve_org(raw_name, mappings)
            resolved[raw_name] = slug
            logging.info(f"  Project org '{raw_name}' → '[[{slug}]]'")

    for pat in state.get("extracted_patents", []):
        raw_name = pat.get("raw_org_name", "")
        if raw_name:
            slug = resolve_org(raw_name, mappings)
            resolved[raw_name] = slug
            logging.info(f"  Patent org '{raw_name}' → '[[{slug}]]'")

    for note in state.get("extracted_notes", []):
        for raw_name in note.get("related_raw_orgs", []):
            if raw_name:
                slug = resolve_org(raw_name, mappings)
                resolved[raw_name] = slug
                logging.info(f"  Note org '{raw_name}' → '[[{slug}]]'")

    for cl in state.get("extracted_cover_letters", []):
        raw_name = cl.get("target_organization_raw", "")
        if raw_name:
            slug = resolve_org(raw_name, mappings)
            resolved[raw_name] = slug
            logging.info(f"  Cover letter org '{raw_name}' → '[[{slug}]]'")

    return {"resolved_entities": resolved}


def node_merger(state: IngestionState) -> dict[str, Any]:
    """For each generated output, merge with the existing wiki page if one already exists."""
    outputs = state.get("wiki_outputs", [])
    if not outputs:
        return {"wiki_outputs": outputs}

    today = date.today().isoformat()
    llm = get_model_for_step("INGESTION_MERGE")
    merged_outputs: list[dict[str, Any]] = []

    for output in outputs:
        if output.get("validation_errors"):
            merged_outputs.append(output)
            continue

        path = Path(output["path"])
        role_start = ""
        page_type = "experience"
        
        fm_match = re.match(r'^---\n(.*?)\n---', output.get("content", ""), re.DOTALL)
        if fm_match:
            try:
                fm = yaml.safe_load(fm_match.group(1)) or {}
                role_start = str(fm.get("dates", {}).get("start", ""))
                page_type = fm.get("type", "experience")
            except Exception:
                pass

        if page_type == "experience":
            existing = find_existing_experience(output.get("org_slug", ""), path, role_start)
        elif page_type == "education":
            existing = find_existing_education(output.get("org_slug", ""), path, role_start)
        else:
            existing = path if path.exists() else None

        if existing is None:
            logging.info(f"New file — no merge needed: {path.name}")
            merged_outputs.append(output)
            continue

        if existing != path:
            logging.info(f"Redirecting merge: {path.name} → {existing.name}")
            output = {**output, "path": str(existing)}
            path = existing

        logging.info(f"--- MERGE: {path.name} ---")
        existing_content = path.read_text(encoding="utf-8")

        prompt_filename = f"merge_{page_type}.txt"
        if page_type not in ("experience", "education", "project", "patent", "note", "entity", "cover-letter"):
            prompt_filename = "merge_language.txt"

        system_template = load_prompt(prompt_filename)
        system_prompt = system_template.replace("{TODAY}", today).replace("{today}", today)

        prompt = f"""Merge the new evidence into the existing wiki page. Output the complete merged file.

EXISTING PAGE:
{existing_content}

NEW EVIDENCE TO INTEGRATE:
{output['content']}"""

        try:
            response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=prompt)])
            merged_content = clean_frontmatter(llm_text(response.content))
            logging.info(f"Merged successfully: {path.name}")
            merged_outputs.append({**output, "content": merged_content, "merged": True})
        except Exception as e:
            logging.exception(f"Merge failed for {path.name}: {e} — keeping generated version as-is")
            merged_outputs.append({**output, "merged": False, "merge_error": str(e)})

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


def node_validator(state: IngestionState) -> dict[str, Any]:
    """Pure Python: validate frontmatter schema compliance for all generated wiki outputs."""
    logging.info("--- NODE: VALIDATOR ---")
    
    validated: list[dict[str, Any]] = []
    for output in state.get("wiki_outputs", []):
        errors: list[str] = list(output.get("validation_errors", []))
        content = clean_frontmatter(output.get("content", ""))
        output["content"] = content

        if not content:
            errors.append("Empty content — generation may have failed")
            validated.append({**output, "validation_errors": errors})
            continue

        fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        if not fm_match:
            errors.append("No valid YAML frontmatter block found")
        else:
            try:
                fm = yaml.safe_load(fm_match.group(1)) or {}
                page_type = fm.get("type", "unknown")
                
                if page_type == "experience":
                    _validate_experience(fm, errors)
                elif page_type == "education":
                    _validate_education(fm, errors)
                elif page_type == "skill":
                    _validate_skill(fm, errors)
                elif page_type == "project":
                    _validate_project(fm, errors)
                elif page_type == "patent":
                    _validate_patent(fm, errors)
                elif page_type == "note":
                    _validate_note(fm, errors)
                elif page_type == "cover-letter":
                    _validate_cover_letter(fm, errors)
                elif page_type == "entity":
                    _validate_entity(fm, errors)
                else:
                    errors.append(f"Unknown frontmatter type: '{page_type}'")

            except yaml.YAMLError as e:
                errors.append(f"YAML parse error: {e}")

        if errors:
            logging.warning(f"Validation issues for {output['path']}: {errors}")
        else:
            logging.info(f"Validation passed: {output['path']}")

        validated.append({**output, "validation_errors": errors})

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
