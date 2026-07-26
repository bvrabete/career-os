"""Pure Python helpers and utilities for the Ingestion Pipeline."""
import json
import logging
import os
import re
import shutil
import tempfile
import yaml
from pathlib import Path
from typing import Any


SLUG_PATTERN = r'[^a-z0-9]+'
SCHEMA_MD = "schema.md"
PERSONA_MAPPINGS_HEADER = "## Persona Mappings"
MAPPINGS_FILE_NAME = "mappings.md"
PATH_TRAVERSAL_ERROR = "Attempted Path Traversal outside home directory"
INVALID_MAPPINGS_ERROR = "Security Warning: Invalid mappings path or directory traversal detected"


from utils import validate_path






def get_wiki_root() -> Path:
    """Get the absolute path to the wiki folder."""
    from kb_config import get_wiki_dir
    return get_wiki_dir() / "wiki"


def get_schema_path() -> Path:
    """Get the absolute path to the schema.md file."""
    from kb_config import get_wiki_dir
    return get_wiki_dir() / SCHEMA_MD


def get_mappings_path() -> Path:
    """Get the absolute path to the mappings.md file."""
    from kb_config import get_wiki_dir
    return get_wiki_dir() / MAPPINGS_FILE_NAME


def load_prompt(filename: str) -> str:
    """Load an external prompt file from src/prompts/ingestion/."""
    current_dir = Path(__file__).resolve().parent
    prompt_path = current_dir.parent / "prompts" / "ingestion" / filename
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt template not found at {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def _bootstrap_subdirs(wiki_root: Path) -> None:
    """Create all standard subdirectories under the wiki root."""
    subdirs = [
        "experiences", "education", "entities", "projects", "skills",
        "sources", "synthesis", "concepts", "notes", "patents",
        "strategies", "queries", "media", "cover-letters"
    ]
    for subdir in subdirs:
        (wiki_root / subdir).mkdir(parents=True, exist_ok=True)


def _bootstrap_templates_and_schema(wiki_dir: Path, wiki_root: Path) -> None:
    """Bootstrap schemas, mappings, and log file."""
    repo_llm_wiki = Path(__file__).resolve().parent.parent.parent / "llm-wiki"

    # 1. Schema
    target_schema = wiki_dir / SCHEMA_MD
    if not target_schema.exists():
        copied_schema = False
        repo_schema = repo_llm_wiki / SCHEMA_MD
        if repo_schema.exists():
            try:
                shutil.copy(repo_schema, target_schema)
                logging.info(f"Copied schema.md template from {repo_schema}")
                copied_schema = True
            except Exception as e:
                logging.warning(f"Failed to copy schema.md: {e}")

        if not copied_schema:
            legacy_schema = Path(__file__).resolve().parent.parent.parent / "templates" / SCHEMA_MD
            if legacy_schema.exists():
                try:
                    shutil.copy(legacy_schema, target_schema)
                    logging.info(f"Copied schema.md template from {legacy_schema}")
                    copied_schema = True
                except Exception as e:
                    logging.warning(f"Failed to copy schema.md from legacy templates: {e}")

        if not copied_schema and not target_schema.exists():
            target_schema.write_text(
                "# Wiki Schema\n\nEmpty placeholder schema.\n", encoding="utf-8")

    # 2. Mappings
    target_mappings = wiki_dir / MAPPINGS_FILE_NAME
    if not target_mappings.exists():
        copied_mappings = False
        repo_mappings = repo_llm_wiki / MAPPINGS_FILE_NAME
        if repo_mappings.exists():
            try:
                shutil.copy(repo_mappings, target_mappings)
                logging.info(f"Copied mappings.md template from {repo_mappings}")
                copied_mappings = True
            except Exception as e:
                logging.warning(f"Failed to copy mappings.md: {e}")

        if not copied_mappings and not target_mappings.exists():
            mappings_template = """# Entity Aliases & Mappings

Use this file to define known typos, variations, and aliases for entities in the Knowledge Graph. 
The LLM Wiki tool must consult this file during ingestion to prevent duplicate or erroneous entity creation.

## Organization Mappings

- **Canonical:** [[example-corporation]]
  - Aliases: `Example Corp`, `Example Inc`, `Example`
"""
            target_mappings.write_text(mappings_template, encoding="utf-8")
            logging.info("Created clean, generic mappings.md template (fallback)")

    # 3. Log
    target_log = wiki_root / "log.md"
    if not target_log.exists():
        copied_log = False
        repo_log = repo_llm_wiki / "wiki" / "log.md"
        if repo_log.exists():
            try:
                shutil.copy(repo_log, target_log)
                logging.info(f"Copied log.md template from {repo_log}")
                copied_log = True
            except Exception as e:
                logging.warning(f"Failed to copy log.md: {e}")

        if not copied_log and not target_log.exists():
            target_log.write_text(
                "# Wiki Activity Log\n\nAll ingestion actions are logged here.\n", encoding="utf-8")
            logging.info("Created default log.md (fallback)")

    # 4. Purpose
    target_purpose = wiki_dir / "purpose.md"
    if not target_purpose.exists():
        repo_purpose = repo_llm_wiki / "purpose.md"
        if repo_purpose.exists():
            try:
                shutil.copy(repo_purpose, target_purpose)
                logging.info(f"Copied purpose.md template from {repo_purpose}")
            except Exception as e:
                logging.warning(f"Failed to copy purpose.md: {e}")


def _bootstrap_css_templates(wiki_dir: Path) -> None:
    """Bootstrap default CSS templates from the repository."""
    repo_templates_dir = Path(__file__).resolve(
    ).parent.parent.parent / "llm-wiki" / "templates"
    if not repo_templates_dir.exists():
        repo_templates_dir = Path(__file__).resolve(
        ).parent.parent.parent / "templates"
    target_templates_dir = wiki_dir / "templates"
    if repo_templates_dir.exists():
        target_templates_dir.mkdir(parents=True, exist_ok=True)
        for css_file in repo_templates_dir.glob("*.css"):
            if css_file.name == SCHEMA_MD:
                continue
            target_css = target_templates_dir / css_file.name
            if not target_css.exists():
                try:
                    shutil.copy(css_file, target_css)
                    logging.info(f"Bootstrapped CSS template: {css_file.name}")
                except Exception as e:
                    logging.warning(
                        f"Failed to copy CSS template {css_file.name}: {e}")


def _bootstrap_strategies(wiki_root: Path) -> None:
    """Bootstrap default, generic, strongly-typed regional strategies from the llm-wiki repository directory."""
    repo_strategies_dir = Path(__file__).resolve().parent.parent.parent / "llm-wiki" / "wiki" / "strategies"
    target_strategies_dir = wiki_root / "strategies"

    if repo_strategies_dir.exists():
        target_strategies_dir.mkdir(parents=True, exist_ok=True)
        for strategy_file in repo_strategies_dir.glob("strategy-*.md"):
            target_file = target_strategies_dir / strategy_file.name
            if not target_file.exists():
                try:
                    shutil.copy(strategy_file, target_file)
                    logging.info(f"Bootstrapped regional strategy: {strategy_file.name}")
                except Exception as e:
                    logging.warning(f"Failed to copy strategy template {strategy_file.name}: {e}")


def bootstrap_wiki_structure(wiki_dir: Path) -> None:
    """Seed directory structure, schema.md, and mappings.md if empty or missing."""
    wiki_root = wiki_dir / "wiki"

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

    _bootstrap_subdirs(wiki_root)
    _bootstrap_templates_and_schema(wiki_dir, wiki_root)
    _bootstrap_css_templates(wiki_dir)
    _bootstrap_strategies(wiki_root)


def get_safe_mappings_path() -> Path:
    """Securely resolve mappings.md, validating against path traversal and satisfying SonarQube taint analysis."""
    raw_path = get_mappings_path().resolve()

    # Identify the matching trusted parent directory to support various environments and unit testing
    trusted_parents = [
        Path.home().resolve(),
        Path.cwd().resolve(),
        Path(tempfile.gettempdir()).resolve(),
    ]

    base_dir = None
    for parent in trusted_parents:
        if raw_path.is_relative_to(parent):
            base_dir = parent
            break

    if base_dir is None:
        raise PermissionError(PATH_TRAVERSAL_ERROR)

    if raw_path.name != MAPPINGS_FILE_NAME:
        raise ValueError(INVALID_MAPPINGS_ERROR)

    # Reconstruct the path from safe, validated parts to satisfy SonarQube's taint tracker
    parts = list(raw_path.relative_to(base_dir).parts)
    for part in parts:
        if not re.match(r'^[a-zA-Z0-9_\-\.]+$', part):
            raise ValueError(INVALID_MAPPINGS_ERROR)

    return validate_path(base_dir.joinpath(*parts))



def parse_mappings() -> dict[str, str]:
    """Parse mappings.md into {alias_lower: canonical_slug} dict."""
    mappings_path = get_safe_mappings_path()

    if not mappings_path.exists():
        return {}

    mappings: dict[str, str] = {}
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


def slugify(text: str) -> str:
    """Convert text into lower-cased hyphenated slug format."""
    return re.sub(SLUG_PATTERN, '-', text.lower()).strip('-')


def resolve_org(raw_name: str, mappings: dict[str, str]) -> str:
    """Map a raw org name to a canonical slug, falling back to a generated slug."""
    lower = raw_name.lower().strip()
    if lower in mappings:
        return mappings[lower]

    raw_slug = slugify(raw_name)
    slugified_mappings = {
        slugify(alias): slug for alias, slug in mappings.items()}

    if raw_slug in slugified_mappings:
        return slugified_mappings[raw_slug]

    for slug_alias, slug in slugified_mappings.items():
        if slug_alias and (slug_alias in raw_slug or raw_slug in slug_alias):
            return slug

    return raw_slug


def get_persona_slug_from_mappings() -> str | None:
    """Parse mappings.md to find the canonical persona slug from ## Persona Mappings section."""
    mappings_path = get_safe_mappings_path()

    if not mappings_path.exists():
        return None

    with open(mappings_path, "r", encoding="utf-8") as f:
        in_persona_section = False
        for line in f:
            if PERSONA_MAPPINGS_HEADER in line:
                in_persona_section = True
                continue
            elif line.startswith("## ") and in_persona_section:
                in_persona_section = False

            if in_persona_section and "**Canonical:**" in line:
                m = re.search(r'\[\[([^\]]+)\]\]', line)
                if m:
                    return m.group(1).strip()
    return None


def add_persona_mapping_if_missing(name: str, slug: str) -> None:
    """Automatically append a new Persona Mapping to mappings.md if not already present."""
    mappings_path = validate_path(get_safe_mappings_path())

    if not mappings_path.exists():
        return

    content = mappings_path.read_text(encoding="utf-8")
    if f"[[{slug}]]" in content:
        return

    lines = content.splitlines()
    new_lines = []
    in_section = False
    added = False

    for line in lines:
        if PERSONA_MAPPINGS_HEADER in line:
            in_section = True
            new_lines.append(line)
            continue
        elif line.startswith("## ") and in_section:
            new_lines.append(f"- **Canonical:** [[{slug}]]")
            new_lines.append(f"  - Aliases: `{name}`")
            new_lines.append("")
            added = True
            in_section = False

        new_lines.append(line)

    if in_section and not added:
        new_lines.append(f"- **Canonical:** [[{slug}]]")
        new_lines.append(f"  - Aliases: `{name}`")
        new_lines.append("")
        added = True

    if not added:
        new_lines.append("")
        new_lines.append(PERSONA_MAPPINGS_HEADER)
        new_lines.append("")
        new_lines.append(f"- **Canonical:** [[{slug}]]")
        new_lines.append(f"  - Aliases: `{name}`")
        new_lines.append("")

    mappings_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    logging.info(
        f"Added new persona mapping to mappings.md: [[{slug}]] -> {name}")


def get_persona_slug(profile_name: str) -> str:
    """Robustly find or generate the canonical persona slug, and ensure mappings.md is seeded."""
    # Sanitize inputs with basename to prevent path traversal/injection taint from propagating
    profile_name = os.path.basename(profile_name).strip()

    persona_slug = get_persona_slug_from_mappings()
    if persona_slug:
        return persona_slug

    mappings = parse_mappings()
    resolved = resolve_org(profile_name, mappings)
    if resolved != slugify(profile_name):
        add_persona_mapping_if_missing(profile_name, resolved)
        return resolved

    slug = slugify(profile_name)
    persona_slug_canonical = get_persona_slug_from_mappings()
    if not slug.endswith("-person") and slug != persona_slug_canonical:
        slug = f"{slug}-person"

    add_persona_mapping_if_missing(profile_name, slug)
    return slug


def llm_text(content: str | list[Any]) -> str:
    """Coerce a LangChain response.content value to a plain string."""
    if isinstance(content, str):
        return content
    return " ".join(str(part) for part in content)


def strip_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences from LLM output."""
    text = re.sub(r'^```[a-z]*\n?', '', text.strip())
    text = re.sub(r'\n?```$', '', text)
    return text.strip()


def _extract_frontmatter_from_fence(content: str) -> str:
    """If the content starts with ```, extract frontmatter block and return standard string."""
    if not content.startswith("```"):
        return content
    lines = content.splitlines()
    closing_idx = -1
    for idx in range(1, len(lines)):
        stripped = lines[idx].strip()
        if stripped in ("```", "```markdown"):
            closing_idx = idx
            break
    if closing_idx != -1:
        fm_lines = [l for l in lines[1:closing_idx] if l.strip() != "---"]
        body_lines = lines[closing_idx+1:]
        return f"---\n{'\n'.join(fm_lines)}\n---\n\n{'\n'.join(body_lines)}"
    return content


def _clean_frontmatter_lines(fm_lines: list[str]) -> str:
    """Clean frontmatter lines by stripping code fences and HTML comments."""
    cleaned_fm_lines = []
    for line in fm_lines:
        line_stripped = line.strip()
        if line_stripped.startswith("```"):
            continue
        cleaned_line = re.sub(r'(?s)<!--.*?-->', '', line)
        cleaned_line = cleaned_line.split('<!--')[0].rstrip()
        cleaned_fm_lines.append(cleaned_line)
    return "\n".join(cleaned_fm_lines)


def _clean_body_lines(body_lines: list[str]) -> str:
    """Clean leading and trailing fences/whitespace from body lines."""
    while body_lines and (body_lines[0].strip() == "```" or not body_lines[0].strip()):
        body_lines.pop(0)
    while body_lines and (body_lines[-1].strip() == "```" or not body_lines[-1].strip()):
        body_lines.pop()
    return "\n".join(body_lines)


def clean_frontmatter(content: str) -> str:
    """Strip code fences, HTML comments and trailing annotations from frontmatter block."""
    content = _extract_frontmatter_from_fence(content.strip())
    lines = content.splitlines()
    boundary_indices = [i for i, line in enumerate(
        lines) if line.strip() == "---"]

    if len(boundary_indices) < 2:
        return content

    i, j = boundary_indices[0], boundary_indices[1]
    cleaned_fm = _clean_frontmatter_lines(lines[i+1:j])
    body = _clean_body_lines(lines[j+1:])
    return f"---\n{cleaned_fm}\n---\n\n{body}"


def _extract_start_date_from_file(f: Path, slug: str) -> str | None:
    """Read file, verify slug in frontmatter, and return the start date string if found."""
    try:
        content = f.read_text(encoding="utf-8")
        fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        if not fm_match:
            return None
        fm_text = fm_match.group(1)
        if f"[[{slug}]]" not in fm_text:
            return None
        fm = yaml.safe_load(fm_text) or {}
        dates_val = fm.get("dates", {})
        if isinstance(dates_val, dict):
            return str(dates_val.get("start", ""))
        return str(fm.get("start", ""))
    except Exception:
        return None


def _filter_by_matching_year(candidates: list[tuple[Path, str]], target_year: int) -> list[Path]:
    """Filter candidates whose start year is within 1 year of target_year."""
    matching = []
    for f, start in candidates:
        if not start:
            continue
        try:
            c_year = int(str(start)[:4])
            if abs(c_year - target_year) <= 1:
                matching.append(f)
        except ValueError:
            pass
    return matching


def _find_existing_wiki_file(
    subdir: str,
    slug: str,
    generated_path: Path,
    start_date: str = ""
) -> Path | None:
    """Generic helper to find the best matching existing wiki file based on directory, slug, and start year."""
    target_dir = get_wiki_root() / subdir
    if not target_dir.exists():
        return None

    candidates: list[tuple[Path, str]] = []
    for f in target_dir.glob("*.md"):
        start = _extract_start_date_from_file(f, slug)
        if start is not None:
            candidates.append((f, start))

    if not candidates:
        return generated_path if generated_path.exists() else None

    if start_date:
        try:
            target_year = int(start_date[:4])
            matching = _filter_by_matching_year(candidates, target_year)
            if matching:
                return matching[0]
            return generated_path if generated_path.exists() else None
        except ValueError:
            pass

    if len(candidates) == 1:
        return candidates[0][0]

    return max(candidates, key=lambda x: x[0].stat().st_mtime)[0]


def find_existing_experience(org_slug: str, generated_path: Path, role_start: str = "") -> Path | None:
    """Find the best matching existing experience file for this org slug."""
    return _find_existing_wiki_file("experiences", org_slug, generated_path, role_start)


def find_existing_education(inst_slug: str, generated_path: Path, edu_start: str = "") -> Path | None:
    """Find the best matching existing education file for this institution slug."""
    return _find_existing_wiki_file("education", inst_slug, generated_path, edu_start)
