"""Pure Python helpers and utilities for the Ingestion Pipeline."""
import json
import logging
import re
import shutil
import yaml
from pathlib import Path
from typing import Any, Union


SLUG_PATTERN = r'[^a-z0-9]+'


def get_wiki_root() -> Path:
    """Get the absolute path to the wiki folder."""
    from kb_config import get_wiki_dir
    return get_wiki_dir() / "wiki"


def get_schema_path() -> Path:
    """Get the absolute path to the schema.md file."""
    from kb_config import get_wiki_dir
    return get_wiki_dir() / "schema.md"


def get_mappings_path() -> Path:
    """Get the absolute path to the mappings.md file."""
    from kb_config import get_wiki_dir
    return get_wiki_dir() / "mappings.md"


def load_prompt(filename: str) -> str:
    """Load an external prompt file from src/prompts/ingestion/."""
    current_dir = Path(__file__).resolve().parent
    prompt_path = current_dir.parent / "prompts" / "ingestion" / filename
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt template not found at {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def bootstrap_wiki_structure(wiki_dir: Path) -> None:
    """Seed directory structure, schema.md, and mappings.md if empty or missing."""
    wiki_root = wiki_dir / "wiki"
    subdirs = [
        "experiences", "education", "entities", "projects", "skills",
        "sources", "synthesis", "concepts", "notes", "patents",
        "strategies", "queries", "media", "cover-letters"
    ]
    
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

    template_schema = Path(__file__).resolve().parent.parent.parent / "templates" / "schema.md"
    target_schema = wiki_dir / "schema.md"
    if template_schema.exists() and not target_schema.exists():
        try:
            shutil.copy(template_schema, target_schema)
            logging.info(f"Copied schema.md template from {template_schema}")
        except Exception as e:
            logging.warning(f"Failed to copy schema.md: {e}")
    elif not target_schema.exists():
        target_schema.write_text("# Wiki Schema\n\nEmpty placeholder schema.\n", encoding="utf-8")

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

    target_log = wiki_root / "log.md"
    if not target_log.exists():
        target_log.write_text("# Wiki Activity Log\n\nAll ingestion actions are logged here.\n", encoding="utf-8")
        logging.info("Created default log.md")

    repo_templates_dir = Path(__file__).resolve().parent.parent.parent / "templates"
    target_templates_dir = wiki_dir / "templates"
    if repo_templates_dir.exists():
        target_templates_dir.mkdir(parents=True, exist_ok=True)
        for css_file in repo_templates_dir.glob("*.css"):
            if css_file.name == "schema.md":
                continue
            target_css = target_templates_dir / css_file.name
            if not target_css.exists():
                try:
                    shutil.copy(css_file, target_css)
                    logging.info(f"Bootstrapped CSS template: {css_file.name}")
                except Exception as e:
                    logging.warning(f"Failed to copy CSS template {css_file.name}: {e}")


def parse_mappings() -> dict[str, str]:
    """Parse mappings.md into {alias_lower: canonical_slug} dict."""
    mappings_path = get_mappings_path()
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
    slugified_mappings = {slugify(alias): slug for alias, slug in mappings.items()}

    if raw_slug in slugified_mappings:
        return slugified_mappings[raw_slug]

    for slug_alias, slug in slugified_mappings.items():
        if slug_alias and (slug_alias in raw_slug or raw_slug in slug_alias):
            return slug

    return raw_slug


def get_persona_slug_from_mappings() -> str | None:
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


def add_persona_mapping_if_missing(name: str, slug: str) -> None:
    """Automatically append a new Persona Mapping to mappings.md if not already present."""
    mappings_path = get_mappings_path()
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
        if "## Persona Mappings" in line:
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
        new_lines.append("## Persona Mappings")
        new_lines.append("")
        new_lines.append(f"- **Canonical:** [[{slug}]]")
        new_lines.append(f"  - Aliases: `{name}`")
        new_lines.append("")
        
    mappings_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    logging.info(f"Added new persona mapping to mappings.md: [[{slug}]] -> {name}")


def get_persona_slug(profile_name: str) -> str:
    """Robustly find or generate the canonical persona slug, and ensure mappings.md is seeded."""
    persona_slug = get_persona_slug_from_mappings()
    if persona_slug:
        return persona_slug
        
    mappings = parse_mappings()
    resolved = resolve_org(profile_name, mappings)
    if resolved != slugify(profile_name):
        add_persona_mapping_if_missing(profile_name, resolved)
        return resolved
        
    slug = slugify(profile_name)
    if not slug.endswith("-person") and slug != "brad-vrabete":
        slug = f"{slug}-person"
        
    add_persona_mapping_if_missing(profile_name, slug)
    return slug


def llm_text(content: Union[str, list[Any]]) -> str:
    """Coerce a LangChain response.content value to a plain string."""
    if isinstance(content, str):
        return content
    return " ".join(str(part) for part in content)


def strip_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences from LLM output."""
    text = re.sub(r'^```[a-z]*\n?', '', text.strip())
    text = re.sub(r'\n?```$', '', text)
    return text.strip()


def clean_frontmatter(content: str) -> str:
    """Strip code fences, HTML comments and trailing annotations from frontmatter block."""
    content = content.strip()
    
    if content.startswith("```"):
        lines = content.splitlines()
        closing_idx = -1
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "```" or lines[idx].strip() == "```markdown":
                closing_idx = idx
                break
        if closing_idx != -1:
            fm_lines = lines[1:closing_idx]
            body_lines = lines[closing_idx+1:]
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

    cleaned_fm_lines = []
    for line in fm_lines:
        line_stripped = line.strip()
        if line_stripped.startswith("```"):
            continue
        cleaned_line = re.sub(r'(?s)<!--.*?-->', '', line)
        cleaned_line = cleaned_line.split('<!--')[0].rstrip()
        cleaned_fm_lines.append(cleaned_line)
        
    cleaned_fm = "\n".join(cleaned_fm_lines)

    while body_lines and (body_lines[0].strip() == "```" or not body_lines[0].strip()):
        body_lines.pop(0)
    while body_lines and (body_lines[-1].strip() == "```" or not body_lines[-1].strip()):
        body_lines.pop()

    body = "\n".join(body_lines)
    return f"---\n{cleaned_fm}\n---\n\n{body}"


def find_existing_experience(org_slug: str, generated_path: Path, role_start: str = "") -> Path | None:
    """Find the best matching existing experience file for this org slug."""
    experiences_dir = get_wiki_root() / "experiences"
    if not experiences_dir.exists():
        return None
    candidates: list[tuple[Path, str]] = []

    for f in experiences_dir.glob("*.md"):
        try:
            content = f.read_text(encoding="utf-8")
            fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
            if not fm_match:
                continue
            fm_text = fm_match.group(1)
            if f"[[{org_slug}]]" not in fm_text:
                continue
            fm = yaml.safe_load(fm_text) or {}
            dates_val = fm.get("dates", {})
            if isinstance(dates_val, dict):
                start = str(dates_val.get("start", ""))
            else:
                start = str(fm.get("start", ""))
            candidates.append((f, start))
        except Exception:
            pass

    if not candidates:
        return generated_path if generated_path.exists() else None

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
                return generated_path if generated_path.exists() else None
        except ValueError:
            pass

    if len(candidates) == 1:
        return candidates[0][0]

    return max(candidates, key=lambda x: x[0].stat().st_mtime)[0]


def find_existing_education(inst_slug: str, generated_path: Path, edu_start: str = "") -> Path | None:
    """Find the best matching existing education file for this institution slug."""
    education_dir = get_wiki_root() / "education"
    if not education_dir.exists():
        return None
    candidates: list[tuple[Path, str]] = []

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
            dates_val = fm.get("dates", {})
            if isinstance(dates_val, dict):
                start = str(dates_val.get("start", ""))
            else:
                start = str(fm.get("start", ""))
            candidates.append((f, start))
        except Exception:
            pass

    if not candidates:
        return generated_path if generated_path.exists() else None

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
