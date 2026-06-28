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

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')


def get_wiki_root() -> Path:
    from kb_config import get_wiki_dir
    return get_wiki_dir() / "wiki"


def get_schema_path() -> Path:
    from kb_config import get_wiki_dir
    return get_wiki_dir() / "schema.md"


def get_mappings_path() -> Path:
    from kb_config import get_wiki_dir
    return get_wiki_dir() / "mappings.md"


def _bootstrap_wiki_structure(wiki_dir: Path):
    """Seed directory structure, schema.md, and mappings.md if empty or missing."""
    import shutil
    wiki_root = wiki_dir / "wiki"
    subdirs = [
        "experiences", "education", "entities", "projects", "skills",
        "sources", "synthesis", "concepts", "notes", "patents",
        "strategies", "queries", "media", "cover-letters"
    ]
    
    # Check if bootstrapping is needed (e.g. if wiki_root is empty or has no standard subdirs)
    needs_bootstrap = (
        not wiki_dir.exists() 
        or not wiki_root.exists() 
        or not any(wiki_root.iterdir() if wiki_root.exists() else [])
    )
    
    if not needs_bootstrap:
        return

    logging.info(f"--- BOOTSTRAPPING WIKI STRUCTURE AT {wiki_dir} ---")
    wiki_dir.mkdir(parents=True, exist_ok=True)
    wiki_root.mkdir(parents=True, exist_ok=True)

    for subdir in subdirs:
        (wiki_root / subdir).mkdir(parents=True, exist_ok=True)

    # 1. Copy schema.md from template if present
    template_schema = Path(__file__).parent.parent / "templates" / "schema.md"
    target_schema = wiki_dir / "schema.md"
    if template_schema.exists() and not target_schema.exists():
        try:
            shutil.copy(template_schema, target_schema)
            logging.info(f"Copied schema.md template from {template_schema}")
        except Exception as e:
            logging.warning(f"Failed to copy schema.md: {e}")
    elif not target_schema.exists():
        target_schema.write_text("# Wiki Schema\n\nEmpty placeholder schema.\n", encoding="utf-8")

    # 2. Write generic mappings.md template (no personal info)
    target_mappings = wiki_dir / "mappings.md"
    if not target_mappings.exists():
        mappings_template = """# Entity Aliases & Mappings

Use this file to define known typos, variations, and aliases for entities in the Knowledge Graph. 
The LLM Wiki tool must consult this file during ingestion to prevent duplicate or erroneous entity creation.

## Organization Mappings

- **Canonical:** [[example-corporation]]
  - Aliases: `Example Corp`, `Example Inc`, `Example`
"""
        target_mappings.write_text(mappings_template, encoding="utf-8")
        logging.info("Created clean, generic mappings.md template")

    # 3. Create default log.md if missing
    target_log = wiki_root / "log.md"
    if not target_log.exists():
        target_log.write_text("# Wiki Activity Log\n\nAll ingestion actions are logged here.\n", encoding="utf-8")
        logging.info("Created default log.md")

    # 4. Copy CSS templates to external wiki templates directory for user customization
    repo_templates_dir = Path(__file__).parent.parent / "templates"
    target_templates_dir = wiki_dir / "templates"
    if repo_templates_dir.exists():
        target_templates_dir.mkdir(parents=True, exist_ok=True)
        for css_file in repo_templates_dir.glob("*.css"):
            # Avoid copying schema.md as it is already copied directly to the wiki root
            if css_file.name == "schema.md":
                continue
            target_css = target_templates_dir / css_file.name
            if not target_css.exists():
                try:
                    shutil.copy(css_file, target_css)
                    logging.info(f"Bootstrapped CSS template: {css_file.name}")
                except Exception as e:
                    logging.warning(f"Failed to copy CSS template {css_file.name}: {e}")



class IngestionState(TypedDict):
    source_file: str
    raw_text: str
    doc_type: str
    extracted_roles: List[dict]
    extracted_education: List[dict]
    extracted_languages: List[dict]
    extracted_projects: List[dict]
    extracted_patents: List[dict]
    extracted_notes: List[dict]
    extracted_cover_letters: List[dict]
    extracted_profile: dict
    resolved_entities: dict
    wiki_outputs: List[dict]


SLUG_PATTERN = r'[^a-z0-9]+'


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
    return re.sub(SLUG_PATTERN, '-', text.lower()).strip('-')


def _resolve_org(raw_name: str, mappings: dict) -> str:
    """Map a raw org name to a canonical slug, falling back to a generated slug."""
    lower = raw_name.lower().strip()
    if lower in mappings:
        return mappings[lower]

    raw_slug = _slugify(raw_name)
    slugified_mappings = {
        _slugify(alias): slug for alias, slug in mappings.items()}

    if raw_slug in slugified_mappings:
        return slugified_mappings[raw_slug]

    for slug_alias, slug in slugified_mappings.items():
        if slug_alias and (slug_alias in raw_slug or raw_slug in slug_alias):
            return slug

    return raw_slug


def _get_persona_slug_from_mappings() -> str | None:
    """Parse mappings.md to find the canonical persona slug from ## Persona Mappings section."""
    mappings_path = get_mappings_path()
    if not mappings_path.exists():
        return None
    
    with open(mappings_path, "r", encoding="utf-8") as f:
        in_persona_section = False
        for line in f:
            if "## Persona Mappings" in line:
                in_persona_section = True
                continue
            elif line.startswith("## ") and in_persona_section:
                in_persona_section = False
                
            if in_persona_section and "**Canonical:**" in line:
                m = re.search(r'\[\[([^\]]+)\]\]', line)
                if m:
                    return m.group(1).strip()
    return None


def _add_persona_mapping_if_missing(name: str, slug: str):
    """Automatically append a new Persona Mapping to mappings.md if not already present."""
    mappings_path = get_mappings_path()
    if not mappings_path.exists():
        return
    
    content = mappings_path.read_text(encoding="utf-8")
    
    # Check if slug is already mentioned in mappings.md
    if f"[[{slug}]]" in content:
        return
        
    lines = content.splitlines()
    new_lines = []
    in_section = False
    added = False
    
    for line in lines:
        if "## Persona Mappings" in line:
            in_section = True
            new_lines.append(line)
            continue
        elif line.startswith("## ") and in_section:
            # We reached the next section without having written our new mapping.
            # Append it right here before continuing.
            new_lines.append(f"- **Canonical:** [[{slug}]]")
            new_lines.append(f"  - Aliases: `{name}`")
            new_lines.append("")
            added = True
            in_section = False
        
        new_lines.append(line)
            
    if in_section and not added:
        # Persona section was at the end, append it
        new_lines.append(f"- **Canonical:** [[{slug}]]")
        new_lines.append(f"  - Aliases: `{name}`")
        new_lines.append("")
        added = True
        
    if not added:
        # Persona section didn't exist at all, append it to the end
        new_lines.append("")
        new_lines.append("## Persona Mappings")
        new_lines.append("")
        new_lines.append(f"- **Canonical:** [[{slug}]]")
        new_lines.append(f"  - Aliases: `{name}`")
        new_lines.append("")
        
    mappings_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    logging.info(f"Added new persona mapping to mappings.md: [[{slug}]] -> {name}")


def _get_persona_slug(profile_name: str) -> str:
    """Robustly find or generate the canonical persona slug, and ensure mappings.md is seeded."""
    # 1. Look for existing canonical persona slug
    persona_slug = _get_persona_slug_from_mappings()
    if persona_slug:
        return persona_slug
        
    # 2. Look up in general mappings if name is mapped
    mappings = _parse_mappings()
    resolved = _resolve_org(profile_name, mappings)
    if resolved != _slugify(profile_name):
        _add_persona_mapping_if_missing(profile_name, resolved)
        return resolved
        
    # 3. Fallback: slugify name and append -person to distinguish it from organizations
    slug = _slugify(profile_name)
    if not slug.endswith("-person") and slug != "brad-vrabete":
        slug = f"{slug}-person"
        
    _add_persona_mapping_if_missing(profile_name, slug)
    return slug


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


def _clean_frontmatter(content: str) -> str:
    """Strip code fences, HTML comments and trailing annotations from frontmatter block."""
    content = content.strip()
    
    # Handle LLM wrapping frontmatter or entire file in markdown code blocks (e.g. ```yaml ... ```)
    if content.startswith("```"):
        lines = content.splitlines()
        first_line = lines[0].strip()
        closing_idx = -1
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "```" or lines[idx].strip() == "```markdown":
                closing_idx = idx
                break
        if closing_idx != -1:
            fm_lines = lines[1:closing_idx]
            body_lines = lines[closing_idx+1:]
            
            # Clean fm_lines of any inner ---
            fm_lines_cleaned = [l for l in fm_lines if l.strip() != "---"]
            fm_content = "\n".join(fm_lines_cleaned)
            body_content = "\n".join(body_lines)
            content = f"---\n{fm_content}\n---\n\n{body_content}"

    lines = content.splitlines()
    boundary_indices = [i for i, line in enumerate(lines) if line.strip() == "---"]
    
    if len(boundary_indices) < 2:
        return content

    i, j = boundary_indices[0], boundary_indices[1]
    fm_lines = lines[i+1:j]
    body_lines = lines[j+1:]

    # Clean frontmatter lines
    cleaned_fm_lines = []
    for line in fm_lines:
        line_stripped = line.strip()
        # Skip any markdown code block lines that might have been wrapped inside the dashes
        if line_stripped.startswith("```"):
            continue
        cleaned_line = re.sub(r'(?s)<!--.*?-->', '', line).strip()
        cleaned_line = cleaned_line.split('<!--')[0].strip()
        cleaned_fm_lines.append(cleaned_line)
        
    cleaned_fm = "\n".join(cleaned_fm_lines)

    # Clean body lines (remove leading/trailing code fences or empty lines)
    while body_lines and (body_lines[0].strip() == "```" or not body_lines[0].strip()):
        body_lines.pop(0)
    while body_lines and (body_lines[-1].strip() == "```" or not body_lines[-1].strip()):
        body_lines.pop()

    body = "\n".join(body_lines)
    return f"---\n{cleaned_fm}\n---\n\n{body}"


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
                raw_text = "\n".join(page.extract_text()
                                     or "" for page in reader.pages)
                if len(raw_text.strip()) > 200:
                    logging.info(
                        f"Parsed via pypdf (primary): {len(raw_text)} chars")
                    return {"raw_text": raw_text}
                else:
                    logging.info(
                        "pypdf extracted very little text, falling back to docling")
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
                    format_options={InputFormat.PDF: PdfFormatOption(
                        pipeline_options=pdf_opts)}
                )
            else:
                converter = DocumentConverter(
                    format_options={InputFormat.PDF: PdfFormatOption(
                        pipeline_cls=SimplePipeline)}
                )
            result = converter.convert(str(path))
            raw_text = result.document.export_to_markdown()
            logging.info(f"Parsed via docling: {len(raw_text)} chars")
        except Exception as e:
            logging.warning(f"docling failed ({e}), trying fallback")
            if suffix == ".pdf":
                try:
                    reader = pypdf.PdfReader(str(path))
                    raw_text = "\n".join(
                        page.extract_text() or "" for page in reader.pages)
                    logging.info(
                        f"Parsed via pypdf fallback: {len(raw_text)} chars")
                except Exception as e2:
                    logging.exception(f"pypdf fallback failed: {e2}")
            elif suffix in (".docx", ".doc"):
                try:
                    doc = docx.Document(str(path))
                    raw_text = "\n".join(p.text for p in doc.paragraphs)
                    logging.info(
                        f"Parsed via python-docx fallback: {len(raw_text)} chars")
                except Exception as e2:
                    logging.exception(f"python-docx fallback failed: {e2}")
    else:
        try:
            raw_text = path.read_text(encoding="utf-8", errors="replace")
            logging.info(f"Read as text: {len(raw_text)} chars")
        except Exception as e:
            logging.exception(f"Text read failed: {e}")

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
        logging.info(
            f"Classified as: {doc_type} — {result.get('reason', '')[:80]}")
    except Exception as e:
        logging.warning(
            f"Could not parse classifier JSON: {e} — defaulting to 'skip'")
        doc_type = "skip"

    return {"doc_type": doc_type}


def _extract_experience(llm, raw_text: str) -> dict:
    system_prompt = """You are a strict Career Data Extraction Agent.

CRITICAL CONSTRAINTS:
1. Extract ONLY information EXPLICITLY stated in the document. NEVER infer or assume.
2. Extract organization and institution names EXACTLY as they appear — do NOT normalize (keep "Intel Corp", not "Intel Corporation").
3. NEVER fabricate metrics, dates, or achievements not present in the source text.
4. If a date is approximate (e.g. "2020"), output "2020-01-01" as best estimate. If a date is completely missing, output an empty string.
5. CAREER BREAKS: Do NOT ignore or skip explicitly listed career breaks, childcare leave, parental leave, sabbaticals, or extended gaps on the resume. Extract them as entries in the "roles" array: use "Career Break" or "Self" for raw_org_name, the type of break (e.g. "Childcare Leave", "Sabbatical") for title, provide the start and end dates, set tracks to ["Engineering"] (or appropriate track), and describe the break context (e.g. "Childcare Leave" or "Sabbatical").
6. Output ONLY valid JSON with no markdown fences and no explanation.

Output format:
{
  "profile": {
    "name": "<full legal or preferred candidate name, e.g. Amalia Vrabete>",
    "email": "<email address>",
    "phone": "<phone number>",
    "linkedin": "<linkedin profile URL or empty string>",
    "location": "<address, city, country, or location, e.g. Veldleeuwerik 8, IJsselstein, Utrecht, Netherlands>",
    "overview": "<overview/professional summary paragraph from the resume or a concise 1-2 sentence career description if no explicit summary is found>",
    "tags": ["<relevant high-level skill/domain tags like 'supply chain', 'logistics', 'data analytics', etc.>"]
  },
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
  ],
  "education": [
    {
      "raw_inst_name": "<exact institution, school, or university name from document>",
      "title": "<exact degree, certification, course, or program name>",
      "start": "<YYYY-MM-DD or YYYY-01-01 estimate, or empty string>",
      "end": "<YYYY-MM-DD, YYYY-01-01 estimate, or empty string>",
      "status": "Completed" | "In-Progress" | "Abandoned",
      "major": "<field of study or empty string>",
      "minor": "<secondary field of study or empty string>",
      "description": "<verbatim description, bullet points, courses, or projects from this program>"
    }
  ],
  "languages": [
    {
      "language": "<spoken language name, e.g. English, Romanian, Dutch>",
      "proficiency": "Expert" | "Proficient" | "Familiar" | "Native" | "Professional-Working"
    }
  ],
  "projects": [
    {
      "raw_org_name": "<exact company/institution name where project was done>",
      "title": "<project name>",
      "start": "<YYYY-MM-DD or YYYY-01-01 estimate, or empty string>",
      "end": "<YYYY-MM-DD, YYYY-01-01 estimate, or empty string>",
      "skills": ["skill1", "skill2"],
      "overview": "<executive summary of the project scope and deliverables>",
      "tech_stack": {"LayerName": "tool/tech name"},
      "contribution_raw": "<metric-backed achievements or STAR bullets representing contributions>"
    }
  ],
  "patents": [
    {
      "raw_org_name": "<exact company/institution name where patent was conceived>",
      "title": "<patent title>",
      "id": "<patent id, e.g. US-12345678-B2>",
      "inventors": ["Inventor Name"],
      "link": "<url to patent or empty string>",
      "skills": ["skill1", "skill2"],
      "abstract": "<summary of the technical invention>",
      "technical_mechanism": "<deep-dive details of how the hardware/software architecture operates>",
      "related_work_value": "<business impact of the patent>"
    }
  ]
}"""

    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Extract candidate personal profile, all roles, education history, spoken languages, projects, and patents from this document:\n\n{raw_text}")
    ])
    
    raw = _llm_text(response.content).strip()
    try:
        return json.loads(_strip_fences(raw))
    except Exception as e:
        logging.warning(f"Could not parse extractor JSON for experience: {e}")
        logging.warning(f"Response was: {raw[:500]}")
        return {}


def _extract_cover_letter(llm, raw_text: str) -> dict:
    system_prompt = """You are a strict Career Data Extraction Agent.

Extract cover letter fields and return them as valid JSON with no markdown fences and no explanation.

Output format:
{
  "cover_letters": [
    {
      "title": "Cover Letter for [Role] at [Company]",
      "target_organization_raw": "<exact company name from letter>",
      "related_synthesis_raw": "<any referenced synthesis/variant or empty string>",
      "salutation": "<Dear ...>",
      "role_fit": "<role & organization fit paragraph>",
      "highlights": "<career highlights alignment paragraph>",
      "closing": "<professional closing and signature>"
    }
  ]
}"""

    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Extract cover letter details from this document:\n\n{raw_text}")
    ])
    
    raw = _llm_text(response.content).strip()
    try:
        return json.loads(_strip_fences(raw))
    except Exception as e:
        logging.warning(f"Could not parse extractor JSON for cover_letter: {e}")
        logging.warning(f"Response was: {raw[:500]}")
        return {}


def _extract_supplemental(llm, raw_text: str) -> dict:
    system_prompt = """You are a strict Career Data Extraction Agent.

Extract performance feedback, reviews, and achievements into structured note formats. Return them as valid JSON with no markdown fences and no explanation.

Output format:
{
  "notes": [
    {
      "title": "<descriptive title for feedback note, e.g., Intel Performance Review 2024>",
      "related_raw_orgs": ["<exact company name this relates to>"],
      "perspective": "Third-Party",
      "tags": ["performance-review", "reflection", "leadership", "engineering"],
      "content": "<feedback text, peer praise, or performance commentary verbatim>"
    }
  ]
}"""

    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Extract feedback/performance reviews from this document:\n\n{raw_text}")
    ])
    
    raw = _llm_text(response.content).strip()
    try:
        return json.loads(_strip_fences(raw))
    except Exception as e:
        logging.warning(f"Could not parse extractor JSON for supplemental: {e}")
        logging.warning(f"Response was: {raw[:500]}")
        return {}


def node_extractor(state: IngestionState) -> dict:
    """Pass 1: Extract raw structured data based on doc_type. No canonicalization yet."""
    logging.info("--- NODE: EXTRACTOR (Pass 1) ---")
    doc_type = state.get("doc_type", "")
    raw_text = state.get("raw_text", "")
    
    roles = []
    education = []
    languages = []
    projects = []
    patents = []
    notes = []
    cover_letters = []
    profile = {}

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
        logging.info(f"Extracted {len(roles)} role(s), {len(education)} education entry(ies), {len(languages)} language(s), {len(projects)} project(s), {len(patents)} patent(s)")
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


def node_entity_resolver(state: IngestionState) -> dict:
    """Pure Python: map raw org/inst names from Pass 1 to canonical slugs from mappings.md."""
    logging.info("--- NODE: ENTITY RESOLVER (Python) ---")
    mappings = _parse_mappings()
    resolved: dict = {}

    for role in state.get("extracted_roles", []):
        raw_name = role.get("raw_org_name", "")
        if raw_name:
            slug = _resolve_org(raw_name, mappings)
            resolved[raw_name] = slug
            logging.info(f"  '{raw_name}' → '[[{slug}]]'")

    for edu in state.get("extracted_education", []):
        raw_name = edu.get("raw_inst_name", "")
        if raw_name:
            slug = _resolve_org(raw_name, mappings)
            resolved[raw_name] = slug
            logging.info(f"  Education institution '{raw_name}' → '[[{slug}]]'")

    for proj in state.get("extracted_projects", []):
        raw_name = proj.get("raw_org_name", "")
        if raw_name:
            slug = _resolve_org(raw_name, mappings)
            resolved[raw_name] = slug
            logging.info(f"  Project org '{raw_name}' → '[[{slug}]]'")

    for pat in state.get("extracted_patents", []):
        raw_name = pat.get("raw_org_name", "")
        if raw_name:
            slug = _resolve_org(raw_name, mappings)
            resolved[raw_name] = slug
            logging.info(f"  Patent org '{raw_name}' → '[[{slug}]]'")

    for note in state.get("extracted_notes", []):
        for raw_name in note.get("related_raw_orgs", []):
            if raw_name:
                slug = _resolve_org(raw_name, mappings)
                resolved[raw_name] = slug
                logging.info(f"  Note org '{raw_name}' → '[[{slug}]]'")

    for cl in state.get("extracted_cover_letters", []):
        raw_name = cl.get("target_organization_raw", "")
        if raw_name:
            slug = _resolve_org(raw_name, mappings)
            resolved[raw_name] = slug
            logging.info(f"  Cover letter org '{raw_name}' → '[[{slug}]]'")

    return {"resolved_entities": resolved}


def _generate_experiences(llm, roles: List[dict], resolved: dict, today_str: str, schema_text: str, wiki_outputs: List[dict]):
    """Generate experience files and append them to wiki_outputs."""
    entity_map_lines = "\n".join(f'  "{raw}" → use [[{slug}]]' for raw, slug in resolved.items())
    system_prompt = f"""You are a strict Data Normalization Agent building experience wiki entries for a Career Single Source of Truth.

CRITICAL CONSTRAINTS:
1. LANGUAGE: Write EXCLUSIVELY in English. Translate any non-English content entirely.
2. ENTITY RESOLUTION: Use ONLY the canonical slugs listed in the mapping below. NEVER put raw company name strings in the `organization` frontmatter field.
3. SOURCE INTEGRITY: Use ONLY data explicitly provided. NEVER fabricate dates, metrics, titles, or achievements.
4. FORMAT: Do NOT wrap the output or any sections (including the YAML frontmatter) in markdown code blocks or code fences (such as ``` or ```yaml). Output the raw markdown content directly.
5. SCHEMA: Follow the exact frontmatter + body structure from the schema reference below.
6. STAR FORMAT: Structure achievements under thematic H3 headers as nested Situation → Task → Action → Result bullets.
7. COMPLETENESS: Include ALL achievements from the source. Do not summarize or truncate bullet points.
8. DATES: Use ISO format YYYY-MM-DD in frontmatter. Use "Present" for current roles.

CANONICAL ENTITY MAPPING (these are the ONLY valid organization slugs):
{entity_map_lines}

SCHEMA REFERENCE (use this as the template):
{schema_text[:3000]}"""

    for role in roles:
        raw_org = role.get("raw_org_name", "")
        canonical_slug = resolved.get(raw_org, _slugify(raw_org))
        title = role.get("title", "").strip() or "role"
        title_slug = _slugify(title)
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
            content = _clean_frontmatter(_llm_text(response.content))
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


def _generate_education(llm, education: List[dict], resolved: dict, today_str: str, wiki_outputs: List[dict]):
    """Generate education files and append them to wiki_outputs."""
    entity_map_lines = "\n".join(f'  "{raw}" → use [[{slug}]]' for raw, slug in resolved.items())
    edu_system_prompt = f"""You are a strict Data Normalization Agent building education wiki entries for a Career Single Source of Truth.

CRITICAL CONSTRAINTS:
1. LANGUAGE: Write EXCLUSIVELY in English. Translate any non-English content entirely.
2. ENTITY RESOLUTION: Use ONLY the canonical slugs listed in the mapping below. NEVER put raw institution name strings in the `institution` frontmatter field.
3. SOURCE INTEGRITY: Use ONLY data explicitly provided. NEVER fabricate dates, majors, or courses.
4. FORMAT: Do NOT wrap the output or any sections (including the YAML frontmatter) in markdown code blocks or code fences (such as ``` or ```yaml). Output the raw markdown content directly.
5. SCHEMA: Follow the exact frontmatter + body structure from the schema reference below.
6. DATES: Use ISO format YYYY-MM-DD in frontmatter.

CANONICAL ENTITY MAPPING (these are the ONLY valid organization/institution slugs):
{entity_map_lines}

SCHEMA REFERENCE (Education Page):
### Education Page
---
type: education
title: "Degree Name at Institution"
institution: [[institution-slug]]
dates: 
  start: YYYY-MM-DD
  end: YYYY-MM-DD
status: [Completed, In-Progress, Abandoned]
major: "Field of Study"
minor: "Secondary Field"
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# [Degree Name] at [Institution]

## Description
[Summary of the degree/program structure.]

## Key Courses & Projects
- **[Topic]**: [Core learnings, thesis work, or academic achievements]

## My Voice
[Personal reflection on academic growth and key lessons.]"""

    for edu in education:
        raw_inst = edu.get("raw_inst_name", "")
        canonical_slug = resolved.get(raw_inst, _slugify(raw_inst))
        title = edu.get("title", "").strip() or "degree"
        title_slug = _slugify(title)
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
            content = _clean_frontmatter(_llm_text(response.content))
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


def _generate_languages(llm, languages: List[dict], today_str: str, wiki_outputs: List[dict]):
    """Generate language skill files and append them to wiki_outputs."""
    lang_system_prompt = f"""You are a strict Data Normalization Agent building language skill wiki entries for a Career Single Source of Truth.

CRITICAL CONSTRAINTS:
1. LANGUAGE: Write EXCLUSIVELY in English.
2. FORMAT: Do NOT wrap the output or any sections (including the YAML frontmatter) in markdown code blocks or code fences (such as ``` or ```yaml). Output the raw markdown content directly.
3. SCHEMA: Follow the exact frontmatter + body structure from the schema reference below.
4. DATES: Set `created` and `updated` to today's date ({today_str}).

SCHEMA REFERENCE (Language/Skill Page):
### Skill Page
---
type: skill
title: <Language Name, e.g. English>
category: Spoken-Language
proficiency: <Expert | Proficient | Familiar | Native | Professional-Working>
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# [Language Name]

## Description
[1 paragraph defining the language and its core proficiency context.]

## Evidence & Accomplishments
[Description of language usage, certifications, or native proficiency context.]"""

    for lang in languages:
        lang_name = lang.get("language", "").strip() or "unknown-language"
        lang_slug = _slugify(lang_name)
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
            content = _clean_frontmatter(_llm_text(response.content))
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


def _generate_projects(llm, projects: List[dict], resolved: dict, today_str: str, wiki_outputs: List[dict]):
    """Generate standalone project files and append them to wiki_outputs."""
    entity_map_lines = "\n".join(f'  "{raw}" → use [[{slug}]]' for raw, slug in resolved.items())
    system_prompt = f"""You are a strict Data Normalization Agent building project wiki entries for a Career Single Source of Truth.

CRITICAL CONSTRAINTS:
1. LANGUAGE: Write EXCLUSIVELY in English.
2. ENTITY RESOLUTION: Use ONLY canonical slugs from mapping below in `organization` field. Format: [[entity-slug]].
3. FORMAT: Output the raw markdown content directly, DO NOT wrap the output in markdown code blocks or fences (``` or ```yaml).
4. SCHEMA: Follow the project page template exactly.
5. DATES: Use ISO format YYYY-MM-DD. Set `created` and `updated` to today's date ({today_str}).

CANONICAL ENTITY MAPPING:
{entity_map_lines}

SCHEMA REFERENCE (Project Page):
### Project Page
---
type: project
title: "Project Name"
organization: [[entity-slug]]
dates:
  start: YYYY-MM-DD
  end: YYYY-MM-DD
skills: [skill-slug]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# [Project Name]

## Overview
[Executive summary of the project scope and deliverables.]

## Tech Stack & Architecture
- **[Layer]**: [[entity-slug]] (e.g. AWS, React, etc.)

## Contribution & Outcomes
[Metric-backed achievements or STAR bullets representing your contributions.]"""

    for proj in projects:
        raw_org = proj.get("raw_org_name", "")
        canonical_slug = resolved.get(raw_org, _slugify(raw_org))
        title = proj.get("title", "").strip() or "project"
        title_slug = _slugify(title)
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
            content = _clean_frontmatter(_llm_text(response.content))
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


def _generate_patents(llm, patents: List[dict], resolved: dict, today_str: str, wiki_outputs: List[dict]):
    """Generate standalone patent files and append them to wiki_outputs."""
    entity_map_lines = "\n".join(f'  "{raw}" → use [[{slug}]]' for raw, slug in resolved.items())
    system_prompt = f"""You are a strict Data Normalization Agent building patent wiki entries for a Career Single Source of Truth.

CRITICAL CONSTRAINTS:
1. LANGUAGE: English only.
2. ENTITY RESOLUTION: Use ONLY canonical slugs from mapping in `organization` field. Format: [[entity-slug]].
3. FORMAT: Output raw markdown directly, NO markdown code blocks or fences.
4. SCHEMA: Follow the patent page template exactly.
5. DATES: Set `created` and `updated` to today's date ({today_str}).

CANONICAL ENTITY MAPPING:
{entity_map_lines}

SCHEMA REFERENCE (Patent Page):
### Patent Page
---
type: patent
title: "Patent Title"
id: "Patent ID"
inventors: ["Jane Doe", "Co-Inventor"]
organization: [[entity-slug]]
link: "URL to patent"
skills: [skill-slug]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# [Patent Title]

## Abstract
[Summary of the technical invention.]

## Technical Mechanism
[Deep-dive details of how the hardware/software architecture operates.]

## Related Work & Value
[Business impact of the patent, links to [[experiences]] where it was conceived.]"""

    for pat in patents:
        raw_org = pat.get("raw_org_name", "")
        canonical_slug = resolved.get(raw_org, _slugify(raw_org))
        title = pat.get("title", "").strip() or "patent"
        pat_id = pat.get("id", "").strip()
        id_slug = _slugify(pat_id) if pat_id else _slugify(title)
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
            content = _clean_frontmatter(_llm_text(response.content))
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


def _generate_notes(llm, notes: List[dict], resolved: dict, today_str: str, wiki_outputs: List[dict]):
    """Generate standalone note/feedback files and append them to wiki_outputs."""
    entity_map_lines = "\n".join(f'  "{raw}" → use [[{slug}]]' for raw, slug in resolved.items())
    system_prompt = f"""You are a strict Data Normalization Agent building note/feedback wiki entries for a Career Single Source of Truth.

CRITICAL CONSTRAINTS:
1. LANGUAGE: English only.
2. RELATED LINKS: Use double-brackets [[entity-slug]] for links in the `related` field.
3. FORMAT: Output raw markdown directly, NO markdown code blocks or fences.
4. SCHEMA: Follow note page template.
5. DATES: Set `created` and `updated` to today's date ({today_str}).

CANONICAL ENTITY MAPPING:
{entity_map_lines}

SCHEMA REFERENCE (Note Page):
### Note Page
---
type: note
title: "Descriptive Title"
related: [[[experience-slug]], [[skill-slug]]]
perspective: [Self, Third-Party]
tags: [reflection, leadership, engineering, recruiter-commentary, performance-review, thought-leadership, technical-strategy]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# Note: [Title]

## Context & Thoughts
[Unstructured, raw thoughts, feedback praise, or peer comments.]"""

    for note in notes:
        title = note.get("title", "").strip() or "note"
        title_slug = _slugify(title)
        filename = f"note-{title_slug}.md"
        output_path = str(get_wiki_root() / "notes" / filename)

        # Resolve related experiences/orgs
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
            content = _clean_frontmatter(_llm_text(response.content))
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


def _generate_cover_letters(llm, cover_letters: List[dict], resolved: dict, today_str: str, wiki_outputs: List[dict]):
    """Generate cover letter files and append them to wiki_outputs."""
    entity_map_lines = "\n".join(f'  "{raw}" → use [[{slug}]]' for raw, slug in resolved.items())
    system_prompt = f"""You are a strict Data Normalization Agent building cover letter wiki entries for a Career Single Source of Truth.

CRITICAL CONSTRAINTS:
1. LANGUAGE: English only.
2. FORMAT: Output raw markdown directly, NO markdown code blocks or fences.
3. SCHEMA: Follow cover letter template.
4. DATES: Set `created` and `updated` to today's date ({today_str}).

CANONICAL ENTITY MAPPING:
{entity_map_lines}

SCHEMA REFERENCE (Cover Letter Page):
### Cover Letter Page
---
type: cover-letter
title: "Cover Letter for [Role] at [Company]"
target_organization: [[entity-slug]]
related_synthesis: [[synthesis-slug]]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# Cover Letter: [Role] at [Company]

## Salutation
Dear [Hiring Manager / Recruiter],

## Role & Organization Fit
[Highly personalized paragraph articulating excitement for this specific company and domain.]

## Career Highlights Map
- **Core Narrative:** [Narrative paragraph showing alignment with target JD.]

## Professional Closing
Sincerely,
Jane Doe"""

    for cl in cover_letters:
        raw_org = cl.get("target_organization_raw", "")
        canonical_slug = resolved.get(raw_org, _slugify(raw_org))
        title = cl.get("title", "").strip() or "cover-letter"
        title_slug = _slugify(title)
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
            content = _clean_frontmatter(_llm_text(response.content))
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


def _generate_profile(profile: dict, source_file: str, today_str: str, wiki_outputs: List[dict]):
    """Generate candidate profile markdown (person entity) and add to wiki_outputs."""
    name = profile.get("name", "").strip()
    if not name:
        logging.warning("No profile name extracted; skipping profile generation")
        return

    slug = _get_persona_slug(name)
    target_path = get_wiki_root() / "entities" / f"{slug}.md"
    
    # Preserve existing profile created/updated dates if file exists
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

    # Coerce tags to list of strings
    tags_str = json.dumps(tags)
    
    # Basename of source file
    source_basename = Path(source_file).name
    
    # Build clean markdown
    overview_text = profile.get("overview", "").strip()
    if not overview_text:
        overview_text = f"{name} is a professional specializing in {', '.join(tags[1:4]) if len(tags) > 1 else 'their field'}."

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


def node_generator(state: IngestionState) -> dict:
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

    wiki_outputs = []

    # 1. Experience Generation
    if roles:
        _generate_experiences(llm, roles, resolved, today_str, schema_text, wiki_outputs)

    # 2. Education Generation
    if education:
        _generate_education(llm, education, resolved, today_str, wiki_outputs)

    # 3. Language Generation
    if languages:
        _generate_languages(llm, languages, today_str, wiki_outputs)

    # 4. Project Generation
    if projects:
        _generate_projects(llm, projects, resolved, today_str, wiki_outputs)

    # 5. Patent Generation
    if patents:
        _generate_patents(llm, patents, resolved, today_str, wiki_outputs)

    # 6. Note/Feedback Generation
    if notes:
        _generate_notes(llm, notes, resolved, today_str, wiki_outputs)

    # 7. Cover Letter Generation
    if cover_letters:
        _generate_cover_letters(llm, cover_letters, resolved, today_str, wiki_outputs)

    # 8. Profile/Persona Entity Generation
    if profile:
        _generate_profile(profile, state.get("source_file", ""), today_str, wiki_outputs)

    return {"wiki_outputs": wiki_outputs}


def _find_existing_experience(org_slug: str, generated_path: Path, role_start: str = "") -> Path | None:
    """
    Find the best matching existing experience file for this org slug.
    Always searches by frontmatter `organization:` field first — reliable
    regardless of filename conventions. Falls back to the generated path
    only when no frontmatter match exists (truly new experience).
    """
    experiences_dir = get_wiki_root() / "experiences"
    if not experiences_dir.exists():
        return None
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
            fm = yaml.safe_load(fm_text) or {}
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


def _find_existing_education(inst_slug: str, generated_path: Path, edu_start: str = "") -> Path | None:
    """
    Find the best matching existing education file for this institution slug.
    Matches by frontmatter `institution:` field first.
    """
    education_dir = get_wiki_root() / "education"
    if not education_dir.exists():
        return None
    candidates: list[tuple[Path, str]] = []  # (path, dates.start)

    for f in education_dir.glob("*.md"):
        try:
            content = f.read_text(encoding="utf-8")
            fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
            if not fm_match:
                continue
            fm_text = fm_match.group(1)
            if f"[[{inst_slug}]]" not in fm_text:
                continue
            fm = yaml.safe_load(fm_text) or {}
            start = str(fm.get("dates", {}).get("start", ""))
            candidates.append((f, start))
        except Exception:
            pass

    if not candidates:
        return generated_path if generated_path.exists() else None

    # Match by start year if edu_start is provided
    if edu_start:
        try:
            target_year = int(edu_start[:4])
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
                return generated_path if generated_path.exists() else None
        except ValueError:
            pass

    if len(candidates) == 1:
        return candidates[0][0]

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
        page_type = "experience"
        # Try to extract page type and start date from generated content for date-based matching
        fm_match = re.match(r'^---\n(.*?)\n---',
                            output.get("content", ""), re.DOTALL)
        if fm_match:
            try:
                fm = yaml.safe_load(fm_match.group(1)) or {}
                role_start = str(fm.get("dates", {}).get("start", ""))
                page_type = fm.get("type", "experience")
            except Exception:
                pass

        if page_type == "experience":
            existing = _find_existing_experience(
                output.get("org_slug", ""), path, role_start)
        elif page_type == "education":
            existing = _find_existing_education(
                output.get("org_slug", ""), path, role_start)
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

        if page_type == "experience":
            system_prompt = f"""You are a strict Wiki Maintenance Agent merging new evidence into an existing career wiki page.
     
CRITICAL CONSTRAINTS:
1. PRESERVE & MERGE: Retain all professional accomplishments. Intelligently combine and merge overlapping or highly similar bullet points from both versions into single, rich, information-dense STAR bullets. Never delete a distinct claim, but do not allow the same achievement to be repeated under different phrasings or headings.
2. DYNAMIC THEMATIC PARTITIONING: Analyze the complete, combined set of accomplishments from both the existing file and the new evidence. Identify the optimal 3 to 5 core thematic categories (H3 headings) that best partition and capture the unique focus areas of this specific role. Avoid rigid hardcoded headings if they do not fit the role's level, track, or seniority (e.g., an early developer shouldn't have management headings; a CTO should have business/board headings). Do not create more than 5 headings, and do not use more than 1 category containing only a single bullet. Categorize all achievements under these custom H3 headings.
3. CONCRETE DETAILS: Never lose or dilute any precise metrics, numbers, technologies, specific tool names, or physical document/meeting/evidence references (e.g., PowerPoint filenames, email subjects, meeting names like 'Daily stand-up', 'Red Foundation', etc.). Merge the details of both versions to maximize density, authenticity, and credibility.
4. FRONTMATTER INTEGRATION: Merge the lists of `sources`, `skills`, and `tags` from both the existing page and the new evidence, removing any duplicates and keeping the fields sorted. Set the `updated:` field to {today}. Ensure the resulting frontmatter block is perfectly clean, valid YAML with no inline comments, no explanations, and no markdown wrapping.
5. RECONCILE: If there are clear, irreconcilable contradictions (such as conflicting employment dates or locations), add an inline comment next to the contradictory claims in the markdown body, never in the frontmatter.
6. LANGUAGE & FORMAT: Output English only (translating any non-English content). Output raw markdown only — do NOT wrap the output or any sections in markdown code blocks, backticks, or fences. No explanations."""
        elif page_type == "education":
            system_prompt = f"""You are a strict Wiki Maintenance Agent merging new academic evidence into an existing education page.
     
CRITICAL CONSTRAINTS:
1. PRESERVE: Keep ALL existing description, courses, and reflections. NEVER remove or shorten existing info.
2. ENRICH: Add new courses, projects, or certification details that are NOT already present.
3. DEDUPLICATE: If new details are identical to existing ones, skip them.
4. UPDATE: Set the frontmatter `updated:` field to {today}.
5. LANGUAGE: English only. Translate any non-English content.
6. FORMAT: Output raw markdown only — do NOT wrap the output or any sections in markdown code blocks or fences. No explanation."""
        elif page_type == "project":
            system_prompt = f"""You are a strict Wiki Maintenance Agent merging new project evidence into an existing project page.
     
CRITICAL CONSTRAINTS:
1. PRESERVE: Keep all existing overview, tech stack, and contribution outcomes verbatim.
2. ENRICH: Add new achievements or tech layers from the new content not already present.
3. DEDUPLICATE: Skip identical details.
4. UPDATE: Set the frontmatter `updated:` field to {today}.
5. LANGUAGE: English only.
6. FORMAT: Output raw markdown only — do NOT wrap the output or any sections in markdown code blocks or fences. No explanation."""
        elif page_type == "patent":
            system_prompt = f"""You are a strict Wiki Maintenance Agent merging new patent evidence into an existing patent page.
     
CRITICAL CONSTRAINTS:
1. PRESERVE: Keep all existing abstract, technical mechanism, and related work details verbatim.
2. ENRICH: Add new co-inventors, skills, or link updates.
3. UPDATE: Set the frontmatter `updated:` field to {today}.
4. LANGUAGE: English only.
5. FORMAT: Output raw markdown only — do NOT wrap the output or any sections in markdown code blocks or fences. No explanation."""
        elif page_type == "note":
            system_prompt = f"""You are a strict Wiki Maintenance Agent merging new note evidence into an existing note page.
     
CRITICAL CONSTRAINTS:
1. PRESERVE: Keep all existing thoughts, reflections, and tags verbatim.
2. ENRICH: Append new comments or feedback verbatim.
3. UPDATE: Set the frontmatter `updated:` field to {today}.
4. LANGUAGE: English only.
5. FORMAT: Output raw markdown only — do NOT wrap the output or any sections in markdown code blocks or fences. No explanation."""
        elif page_type == "entity":
            system_prompt = f"""You are a strict Wiki Maintenance Agent merging new evidence into an existing entity page.
     
CRITICAL CONSTRAINTS:
1. PRESERVE: Keep all existing overview, contact details (if any), legal name, and key contributions/core value details verbatim.
2. ENRICH: Add new contact details, tags, sources, or contributions that are NOT already present.
3. DEDUPLICATE: Skip identical details.
4. UPDATE: Set the frontmatter `updated:` field to {today}. Combine the lists of `tags` and `sources` from both files, removing duplicates and preserving clean YAML syntax.
5. LANGUAGE: English only.
6. FORMAT: Output raw markdown only — do NOT wrap the output or any sections in markdown code blocks or fences. No explanation."""
        elif page_type == "cover-letter":
            system_prompt = f"""You are a strict Wiki Maintenance Agent merging cover letter variants.
     
CRITICAL CONSTRAINTS:
1. PRESERVE: Keep existing salutation, fit, highlights, and closing intact.
2. UPDATE: Set the frontmatter `updated:` field to {today}.
3. LANGUAGE: English only.
4. FORMAT: Output raw markdown only — do NOT wrap the output or any sections in markdown code blocks or fences. No explanation."""
        else:
            system_prompt = f"""You are a strict Wiki Maintenance Agent merging new evidence into an existing language skill page.
     
CRITICAL CONSTRAINTS:
1. PRESERVE: Keep ALL existing description, proficiency details, and evidence.
2. ENRICH: If the new document lists a higher proficiency or additional certifications/use-cases, update/add them.
3. UPDATE: Set the frontmatter `updated:` field to {today}.
4. LANGUAGE: English only.
5. FORMAT: Output raw markdown only — do NOT wrap the output or any sections in markdown code blocks or fences. No explanation."""

        prompt = f"""Merge the new evidence into the existing wiki page. Output the complete merged file.

EXISTING PAGE:
{existing_content}

NEW EVIDENCE TO INTEGRATE:
{output['content']}"""

        try:
            response = llm.invoke(
                [SystemMessage(content=system_prompt), HumanMessage(content=prompt)])
            merged_content = _clean_frontmatter(_llm_text(response.content))
            logging.info(f"Merged successfully: {path.name}")
            merged_outputs.append(
                {**output, "content": merged_content, "merged": True})
        except Exception as e:
            logging.exception(
                f"Merge failed for {path.name}: {e} — keeping generated version as-is")
            merged_outputs.append(
                {**output, "merged": False, "merge_error": str(e)})

    return {"wiki_outputs": merged_outputs}



def node_validator(state: IngestionState) -> dict:
    """Pure Python: validate frontmatter schema compliance."""
    logging.info("--- NODE: VALIDATOR ---")
    
    EXP_REQUIRED_FIELDS = {"type", "title", "organization", "dates", "tracks", "skills"}
    EDU_REQUIRED_FIELDS = {"type", "title", "institution", "dates", "status", "major", "minor"}
    SKILL_REQUIRED_FIELDS = {"type", "title", "category", "proficiency"}
    PROJ_REQUIRED_FIELDS = {"type", "title", "organization", "dates", "skills"}
    PAT_REQUIRED_FIELDS = {"type", "title", "id", "inventors", "organization", "skills"}
    NOTE_REQUIRED_FIELDS = {"type", "title", "related", "perspective", "tags"}
    CL_REQUIRED_FIELDS = {"type", "title", "target_organization", "related_synthesis"}
    
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
                fm = yaml.safe_load(fm_match.group(1)) or {}
                page_type = fm.get("type", "unknown")
                
                if page_type == "experience":
                    missing = EXP_REQUIRED_FIELDS - set(fm.keys())
                    if missing:
                        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

                    org = str(fm.get("organization", ""))
                    if "[[" not in org or "]]" not in org:
                        errors.append(f"organization field missing [[slug]] syntax: '{org}'")

                    dates = fm.get("dates", {})
                    if isinstance(dates, dict):
                        for field in ("start", "end"):
                            raw_val = str(dates.get(field, ""))
                            val = raw_val.split()[0] if raw_val else ""
                            if val and not DATE_PATTERN.match(val):
                                errors.append(f"dates.{field} invalid format: '{raw_val}'")
                                
                elif page_type == "education":
                    missing = EDU_REQUIRED_FIELDS - set(fm.keys())
                    if missing:
                        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

                    inst = str(fm.get("institution", ""))
                    if "[[" not in inst or "]]" not in inst:
                        errors.append(f"institution field missing [[slug]] syntax: '{inst}'")

                    dates = fm.get("dates", {})
                    if isinstance(dates, dict):
                        for field in ("start", "end"):
                            raw_val = str(dates.get(field, ""))
                            val = raw_val.split()[0] if raw_val else ""
                            if val and not DATE_PATTERN.match(val):
                                errors.append(f"dates.{field} invalid format: '{raw_val}'")
                                
                elif page_type == "skill":
                    missing = SKILL_REQUIRED_FIELDS - set(fm.keys())
                    if missing:
                        errors.append(f"Missing frontmatter fields: {sorted(missing)}")
                        
                    category = fm.get("category", "")
                    if category not in ("Language-Code", "Framework", "Infrastructure", "Leadership", "Spoken-Language"):
                        errors.append(f"Invalid skill category: '{category}'")
                        
                elif page_type == "project":
                    missing = PROJ_REQUIRED_FIELDS - set(fm.keys())
                    if missing:
                        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

                    org = str(fm.get("organization", ""))
                    if "[[" not in org or "]]" not in org:
                        errors.append(f"organization field missing [[slug]] syntax: '{org}'")

                    dates = fm.get("dates", {})
                    if isinstance(dates, dict):
                        for field in ("start", "end"):
                            raw_val = str(dates.get(field, ""))
                            val = raw_val.split()[0] if raw_val else ""
                            if val and not DATE_PATTERN.match(val):
                                errors.append(f"dates.{field} invalid format: '{raw_val}'")

                elif page_type == "patent":
                    missing = PAT_REQUIRED_FIELDS - set(fm.keys())
                    if missing:
                        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

                    org = str(fm.get("organization", ""))
                    if "[[" not in org or "]]" not in org:
                        errors.append(f"organization field missing [[slug]] syntax: '{org}'")

                elif page_type == "note":
                    missing = NOTE_REQUIRED_FIELDS - set(fm.keys())
                    if missing:
                        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

                elif page_type == "cover-letter":
                    missing = CL_REQUIRED_FIELDS - set(fm.keys())
                    if missing:
                        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

                    org = str(fm.get("target_organization", ""))
                    if "[[" not in org or "]]" not in org:
                        errors.append(f"target_organization field missing [[slug]] syntax: '{org}'")

                elif page_type == "entity":
                    ENTITY_REQUIRED_FIELDS = {"type", "title", "tags", "sources"}
                    missing = ENTITY_REQUIRED_FIELDS - set(fm.keys())
                    if missing:
                        errors.append(f"Missing frontmatter fields: {sorted(missing)}")

                else:
                    errors.append(f"Unknown frontmatter type: '{page_type}'")

            except yaml.YAMLError as e:
                errors.append(f"YAML parse error: {e}")

        if errors:
            logging.warning(
                f"Validation issues for {output['path']}: {errors}")
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
            logging.warning(
                f"Skipping {output['path']} (validation errors: {errors})")
            written_outputs.append({**output, "written": False})
            continue

        path = Path(output["path"])
        is_merge = output.get("merged", False)

        if path.exists() and not is_merge:
            # File exists but merger didn't run (e.g. merge_error) — skip to be safe
            logging.warning(
                f"File exists and was not merged — skipping: {path.name}")
            written_outputs.append(
                {**output, "written": False, "skipped_reason": "duplicate"})
            continue

        action = "update" if is_merge else "create"
        if dry_run:
            logging.info(f"[DRY RUN] Would {action}: {path}")
            written_outputs.append(
                {**output, "written": False, "dry_run": True})
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
