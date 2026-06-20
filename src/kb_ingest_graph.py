"""LangGraph ingestion pipeline for the Career Operating System wiki.

Converts raw source documents (PDF, DOCX, DOC, MD) into schema-compliant
wiki experience entries. Pipeline nodes run in sequence:
  parser → classifier → extractor → entity_resolver → generator → merger → validator → writer

Inputs:  a single raw file path via IngestionState.source_file
Outputs: one or more markdown files written to llm-wiki/wiki/experiences/
"""
import json
import logging
import re
import yaml
import pypdf
import docx
from datetime import date
from pathlib import Path
from typing import TypedDict, List, Union
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice
from docling.pipeline.simple_pipeline import SimplePipeline
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from kb_config import get_model_for_step

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_wiki_root() -> Path:
    from kb_config import get_wiki_dir
    return get_wiki_dir() / "wiki"

def get_schema_path() -> Path:
    from kb_config import get_wiki_dir
    return get_wiki_dir() / "schema.md"

def get_mappings_path() -> Path:
    from kb_config import get_wiki_dir
    return get_wiki_dir() / "mappings.md"


class IngestionState(TypedDict):
    source_file: str
    raw_text: str
    doc_type: str
    extracted_roles: List[dict]
    resolved_entities: dict
    wiki_outputs: List[dict]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_mappings() -> dict:
    """Parse mappings.md into {alias_lower: canonical_slug} dict."""
    mappings_path = get_mappings_path()
    if not mappings_path.exists():
        return {}

    mappings: dict = {}
    canonical = None

    with open(mappings_path, "r", encoding="utf-8") as f:
        for line in f:
            if "**Canonical:**" in line:
                m = re.search(r'\[\[([^\]]+)\]\]', line)
                if m:
                    canonical = m.group(1).strip()
            elif "Aliases:" in line and canonical:
                for alias in re.findall(r'`([^`]+)`', line):
                    mappings[alias.lower()] = canonical

    return mappings


def _slugify(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def _resolve_org(raw_name: str, mappings: dict) -> str:
    """Map a raw org name to a canonical slug, falling back to a generated slug."""
    lower = raw_name.lower().strip()
    if lower in mappings:
        return mappings[lower]

    raw_slug = _slugify(raw_name)
    slugified_mappings = {_slugify(alias): slug for alias, slug in mappings.items()}

    if raw_slug in slugified_mappings:
        return slugified_mappings[raw_slug]

    for slug_alias, slug in slugified_mappings.items():
        if slug_alias and (slug_alias in raw_slug or raw_slug in slug_alias):
            return slug

    return raw_slug



def _llm_text(content: Union[str, list]) -> str:  # type: ignore[type-arg]
    """Coerce a LangChain response.content value to a plain string.

    LangChain returns str for simple text responses and list[...] for
    multi-modal or tool-use responses. Both cases are normalised here.
    """
    if isinstance(content, str):
        return content
    return " ".join(str(part) for part in content)


def _strip_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences from LLM output."""
    text = re.sub(r'^```[a-z]*\n?', '', text.strip())
    text = re.sub(r'\n?```$', '', text)
    return text.strip()


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def node_parser(state: IngestionState) -> dict:
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
                else:
                    logging.info("pypdf extracted very little text, falling back to docling")
            except Exception as e:
                logging.warning(f"pypdf failed ({e}), falling back to docling")

        try:
            if suffix == ".pdf":
                # SimplePipeline only supports declarative backends (DOCX/MD).
                # PDFs need the full pipeline but must run on CPU — the GPU is
                # shared with Ollama and doesn't have enough free VRAM.
                pdf_opts = PdfPipelineOptions()
                pdf_opts.do_table_structure = True
                pdf_opts.do_ocr = True
                pdf_opts.allow_external_plugins = True
                pdf_opts.accelerator_options = AcceleratorOptions(
                    num_threads=8, device=AcceleratorDevice.CPU
                )
                converter = DocumentConverter(
                    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_opts)}
                )
            else:
                converter = DocumentConverter(
                    format_options={InputFormat.PDF: PdfFormatOption(pipeline_cls=SimplePipeline)}
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
                    logging.error(f"pypdf fallback failed: {e2}")
            elif suffix in (".docx", ".doc"):
                try:
                    doc = docx.Document(str(path))
                    raw_text = "\n".join(p.text for p in doc.paragraphs)
                    logging.info(f"Parsed via python-docx fallback: {len(raw_text)} chars")
                except Exception as e2:
                    logging.error(f"python-docx fallback failed: {e2}")
    else:
        try:
            raw_text = path.read_text(encoding="utf-8", errors="replace")
            logging.info(f"Read as text: {len(raw_text)} chars")
        except Exception as e:
            logging.error(f"Text read failed: {e}")

    return {"raw_text": raw_text}


def node_classifier(state: IngestionState) -> dict:
    logging.info("--- NODE: CLASSIFIER ---")
    raw_text = state.get("raw_text", "")

    if not raw_text.strip():
        logging.warning("Empty document — classifying as skip")
        return {"doc_type": "skip"}

    llm = get_model_for_step("INGESTION_CLASSIFY")
    preview = raw_text[:4000]

    system_prompt = """You are a document classification agent. Classify the document type.

Output ONLY valid JSON with no explanation or markdown fences. Format:
{"doc_type": "<type>", "reason": "<brief reason>"}

Valid doc_type values:
- "experience": A CV, resume, or LinkedIn export listing past employment history
- "cover_letter": A cover letter, motivation letter, or job application letter
- "supplemental": An assessment report, performance review, feedback document, candidate profile, or thought-leadership article
- "skip": Unreadable, near-empty, or template-only document with no extractable career data"""

    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Classify this document:\n\n{preview}")
    ])

    try:
        result = json.loads(_strip_fences(_llm_text(response.content)))
        doc_type = result.get("doc_type", "skip")
        logging.info(f"Classified as: {doc_type} — {result.get('reason', '')[:80]}")
    except Exception as e:
        logging.warning(f"Could not parse classifier JSON: {e} — defaulting to 'skip'")
        doc_type = "skip"

    return {"doc_type": doc_type}


def node_extractor(state: IngestionState) -> dict:
    """Pass 1: Extract raw structured data (org names, titles, dates). No canonicalization yet."""
    logging.info("--- NODE: EXTRACTOR (Pass 1) ---")
    doc_type = state.get("doc_type", "")

    if doc_type != "experience":
        logging.info(f"doc_type='{doc_type}' — skipping extraction")
        return {"extracted_roles": []}

    llm = get_model_for_step("INGESTION_EXTRACT")
    raw_text = state.get("raw_text", "")

    system_prompt = """You are a strict Career Data Extraction Agent.

CRITICAL CONSTRAINTS:
1. Extract ONLY information EXPLICITLY stated in the document. NEVER infer or assume.
2. Extract organization names EXACTLY as they appear — do NOT normalize (keep "Intel Corp", not "Intel Corporation").
3. NEVER fabricate metrics, dates, or achievements not present in the source text.
4. If a date is approximate (e.g. "2020"), output "2020-01-01" as best estimate.
5. Output ONLY valid JSON with no markdown fences and no explanation.

Output format:
{
  "roles": [
    {
      "raw_org_name": "<exact company name from document>",
      "title": "<exact job title>",
      "location": "<city, country or empty string>",
      "start": "<YYYY-MM-DD or YYYY-01-01 estimate>",
      "end": "<YYYY-MM-DD, YYYY-01-01 estimate, or Present>",
      "tracks": ["Management", "Architecture", "Engineering", "Entrepreneurial"],
      "skills": ["skill1", "skill2"],
      "context": "<1-2 sentence company and role description>",
      "narrative": "<personal reflections, key challenges, leadership philosophy if available, else empty string>",
      "achievements_raw": "<verbatim bullet points or text describing achievements for this role>"
    }
  ]
}"""

    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Extract all employment roles from this document:\n\n{raw_text}")
    ])

    raw = _llm_text(response.content).strip()
    logging.debug(f"Extractor raw response (first 300 chars): {raw[:300]}")
    try:
        result = json.loads(_strip_fences(raw))
        roles = result.get("roles", [])
        logging.info(f"Extracted {len(roles)} role(s)")
    except Exception as e:
        logging.warning(f"Could not parse extractor JSON: {e}")
        logging.warning(f"Extractor response was: {raw[:500] or '(empty)'}")
        roles = []

    return {"extracted_roles": roles}


def node_entity_resolver(state: IngestionState) -> dict:
    """Pure Python: map raw org names from Pass 1 to canonical slugs from mappings.md."""
    logging.info("--- NODE: ENTITY RESOLVER (Python) ---")
    mappings = _parse_mappings()
    resolved: dict = {}

    for role in state.get("extracted_roles", []):
        raw_name = role.get("raw_org_name", "")
        if raw_name:
            slug = _resolve_org(raw_name, mappings)
            resolved[raw_name] = slug
            logging.info(f"  '{raw_name}' → '[[{slug}]]'")

    return {"resolved_entities": resolved}


def node_generator(state: IngestionState) -> dict:
    """Pass 2: Generate schema-compliant wiki markdown using canonical slugs."""
    logging.info("--- NODE: GENERATOR (Pass 2) ---")
    roles = state.get("extracted_roles", [])

    if not roles:
        logging.info("No roles to generate")
        return {"wiki_outputs": []}

    llm = get_model_for_step("INGESTION_GENERATE")
    resolved = state.get("resolved_entities", {})
    schema_path = get_schema_path()
    schema_text = schema_path.read_text(encoding="utf-8") if schema_path.exists() else ""
    entity_map_lines = "\n".join(f'  "{raw}" → use [[{slug}]]' for raw, slug in resolved.items())

    system_prompt = f"""You are a strict Data Normalization Agent building wiki entries for a Career Single Source of Truth.

CRITICAL CONSTRAINTS:
1. LANGUAGE: Write EXCLUSIVELY in English. Translate any non-English content entirely.
2. ENTITY RESOLUTION: Use ONLY the canonical slugs listed in the mapping below. NEVER put raw company name strings in the `organization` frontmatter field.
3. SOURCE INTEGRITY: Use ONLY data explicitly provided. NEVER fabricate dates, metrics, titles, or achievements.
4. FORMAT: Do NOT wrap output in markdown code fences. Output raw markdown only.
5. SCHEMA: Follow the exact frontmatter + body structure from the schema reference below.
6. STAR FORMAT: Structure achievements under thematic H3 headers as nested Situation → Task → Action → Result bullets.
7. COMPLETENESS: Include ALL achievements from the source. Do not summarize or truncate bullet points.
8. DATES: Use ISO format YYYY-MM-DD in frontmatter. Use "Present" for current roles.

CANONICAL ENTITY MAPPING (these are the ONLY valid organization slugs):
{entity_map_lines}

SCHEMA REFERENCE (use this as the template):
{schema_text[:3000]}"""

    wiki_outputs = []

    for role in roles:
        raw_org = role.get("raw_org_name", "")
        canonical_slug = resolved.get(raw_org, re.sub(r'[^a-z0-9]+', '-', raw_org.lower()).strip('-'))
        title = role.get("title", "unknown-role")

        title_slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
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
            content = _strip_fences(_llm_text(response.content))

            wiki_outputs.append({
                "path": output_path,
                "content": content,
                "org_slug": canonical_slug,
                "title": title,
                "validation_errors": [],
            })
            logging.info(f"Generated: {filename}")
        except Exception as e:
            logging.error(f"Generator failed for '{title}' at '{raw_org}': {e}")
            wiki_outputs.append({
                "path": output_path,
                "content": "",
                "org_slug": canonical_slug,
                "title": title,
                "validation_errors": [f"Generation failed: {e}"],
            })

    return {"wiki_outputs": wiki_outputs}


def _find_existing_experience(org_slug: str, generated_path: Path, role_start: str = "") -> Path | None:
    """
    Find the best matching existing experience file for this org slug.
    Always searches by frontmatter `organization:` field first — reliable
    regardless of filename conventions. Falls back to the generated path
    only when no frontmatter match exists (truly new experience).
    """
    experiences_dir = get_wiki_root() / "experiences"
    candidates: list[tuple[Path, str]] = []  # (path, dates.start)

    for f in experiences_dir.glob("*.md"):
        try:
            content = f.read_text(encoding="utf-8")
            fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
            if not fm_match:
                continue
            fm_text = fm_match.group(1)
            # Search raw text — YAML parses [[slug]] as nested list, not string
            if f"[[{org_slug}]]" not in fm_text:
                continue
            fm = yaml.safe_load(fm_text)
            start = str(fm.get("dates", {}).get("start", ""))
            candidates.append((f, start))
        except Exception:
            pass

    if not candidates:
        # No existing page for this org — use generated path if it exists, else None (new file)
        return generated_path if generated_path.exists() else None

    # Match by start year if role_start is provided
    if role_start:
        try:
            target_year = int(role_start[:4])
            matching_candidates = []
            for f, start in candidates:
                if start:
                    try:
                        c_year = int(str(start)[:4])
                        if abs(c_year - target_year) <= 1:
                            matching_candidates.append(f)
                    except ValueError:
                        pass
            if matching_candidates:
                return matching_candidates[0]
            else:
                # No matching experience for this period — it's a new experience/role
                return generated_path if generated_path.exists() else None
        except ValueError:
            pass

    if len(candidates) == 1:
        return candidates[0][0]

    # Fallback: most recently modified file for this org
    return max(candidates, key=lambda x: x[0].stat().st_mtime)[0]


def node_merger(state: IngestionState) -> dict:
    """For each generated output, merge with the existing wiki page if one already exists."""
    outputs = state.get("wiki_outputs", [])
    if not outputs:
        return {"wiki_outputs": outputs}

    today = date.today().isoformat()
    llm = get_model_for_step("INGESTION_MERGE")
    merged_outputs = []

    for output in outputs:
        if output.get("validation_errors"):
            merged_outputs.append(output)
            continue

        path = Path(output["path"])
        role_start = ""
        # Try to extract start date from generated content for date-based matching
        fm_match = re.match(r'^---\n(.*?)\n---', output.get("content", ""), re.DOTALL)
        if fm_match:
            try:
                fm = yaml.safe_load(fm_match.group(1))
                role_start = str(fm.get("dates", {}).get("start", ""))
            except Exception:
                pass

        existing = _find_existing_experience(output.get("org_slug", ""), path, role_start)

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

        system_prompt = f"""You are a strict Wiki Maintenance Agent merging new evidence into an existing career wiki page.
 
CRITICAL CONSTRAINTS:
1. PRESERVE: Keep ALL existing STAR achievements verbatim. NEVER remove or shorten existing bullet points.
2. ENRICH: Add achievements, context, or narrative from the new content that are NOT already present.
3. DEDUPLICATE: If new content describes an achievement already present (same action/result), skip it — no duplicates.
4. RECONCILE: If new content contradicts existing data (such as location, dates, metrics, title), add a comment inline next to both conflicting claims — but ONLY inside the markdown body, NEVER inside the YAML frontmatter block. The frontmatter block must remain strictly valid, clean YAML with NO comments, NO HTML annotations (e.g. do NOT append '<!-- comment -->' or similar), and NO explanations.
5. UPDATE: Set the frontmatter `updated:` field to {today}. All other frontmatter fields must stay as plain, clean values with no annotations.
6. LANGUAGE: English only. Translate any non-English content.
7. FORMAT: Output raw markdown only — no code fences, no explanation."""

        prompt = f"""Merge the new evidence into the existing wiki page. Output the complete merged file.

EXISTING PAGE:
{existing_content}

NEW EVIDENCE TO INTEGRATE:
{output['content']}"""

        try:
            response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=prompt)])
            merged_content = _strip_fences(_llm_text(response.content))
            logging.info(f"Merged successfully: {path.name}")
            merged_outputs.append({**output, "content": merged_content, "merged": True})
        except Exception as e:
            logging.error(f"Merge failed for {path.name}: {e} — keeping generated version as-is")
            merged_outputs.append({**output, "merged": False, "merge_error": str(e)})

    return {"wiki_outputs": merged_outputs}


def _clean_frontmatter(content: str) -> str:
    """Strip HTML comments and trailing annotations from frontmatter block."""
    fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not fm_match:
        return content
    fm_text = fm_match.group(1)
    cleaned_lines = []
    for line in fm_text.split("\n"):
        cleaned_line = re.sub(r'<!--.*?-->', '', line).strip()
        cleaned_line = cleaned_line.split('<!--')[0].strip()
        cleaned_lines.append(cleaned_line)
    cleaned_fm = "\n".join(cleaned_lines)
    return f"---\n{cleaned_fm}\n---" + content[fm_match.end():]


def node_validator(state: IngestionState) -> dict:
    """Pure Python: validate frontmatter schema compliance."""
    logging.info("--- NODE: VALIDATOR ---")
    REQUIRED_FIELDS = {"type", "title", "organization", "dates", "tracks", "skills"}
    DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$|^Present$')

    validated = []
    for output in state.get("wiki_outputs", []):
        errors = list(output.get("validation_errors", []))
        content = _clean_frontmatter(output.get("content", ""))
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
                fm = yaml.safe_load(fm_match.group(1))
                missing = REQUIRED_FIELDS - set(fm.keys())
                if missing:
                    errors.append(f"Missing frontmatter fields: {sorted(missing)}")

                org = str(fm.get("organization", ""))
                if "[[" not in org or "]]" not in org:
                    errors.append(f"organization field missing [[slug]] syntax: '{org}'")

                dates = fm.get("dates", {})
                if isinstance(dates, dict):
                    for field in ("start", "end"):
                        raw_val = str(dates.get(field, ""))
                        # Strip any trailing annotations (e.g. "[RECONCILE]") before validating
                        val = raw_val.split()[0] if raw_val else ""
                        if val and not DATE_PATTERN.match(val):
                            errors.append(f"dates.{field} invalid format: '{raw_val}'")

            except yaml.YAMLError as e:
                errors.append(f"YAML parse error: {e}")

        if errors:
            logging.warning(f"Validation issues for {output['path']}: {errors}")
        else:
            logging.info(f"Validation passed: {output['path']}")

        validated.append({**output, "validation_errors": errors})

    return {"wiki_outputs": validated}


def node_writer(state: IngestionState, dry_run: bool = False) -> dict:
    """Write validated wiki files; skip duplicates and validation failures."""
    logging.info("--- NODE: WRITER ---")
    written_outputs = []

    for output in state.get("wiki_outputs", []):
        errors = output.get("validation_errors", [])
        if errors:
            logging.warning(f"Skipping {output['path']} (validation errors: {errors})")
            written_outputs.append({**output, "written": False})
            continue

        path = Path(output["path"])
        is_merge = output.get("merged", False)

        if path.exists() and not is_merge:
            # File exists but merger didn't run (e.g. merge_error) — skip to be safe
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


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_ingest_graph(dry_run: bool = False):
    workflow = StateGraph(IngestionState)

    workflow.add_node("parser", node_parser)
    workflow.add_node("classifier", node_classifier)
    workflow.add_node("extractor", node_extractor)
    workflow.add_node("entity_resolver", node_entity_resolver)
    workflow.add_node("generator", node_generator)
    workflow.add_node("merger", node_merger)
    workflow.add_node("validator", node_validator)

    def writer_node(state):
        return node_writer(state, dry_run=dry_run)

    workflow.add_node("writer", writer_node)

    workflow.set_entry_point("parser")
    workflow.add_edge("parser", "classifier")

    workflow.add_conditional_edges(
        "classifier",
        lambda s: "extract" if s.get("doc_type") not in ("skip",) else "end",
        {"extract": "extractor", "end": END},
    )

    workflow.add_edge("extractor", "entity_resolver")
    workflow.add_edge("entity_resolver", "generator")
    workflow.add_edge("generator", "merger")
    workflow.add_edge("merger", "validator")
    workflow.add_edge("validator", "writer")
    workflow.add_edge("writer", END)

    return workflow.compile()
