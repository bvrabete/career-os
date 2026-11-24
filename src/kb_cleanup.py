"""
Administrative cleanup script for the Career Operating System's Wiki experiences.
This script performs a retroactive sweep across all experience files to dynamically
partition achievements, semantically deduplicate redundant bullets, and merge frontmatter fields.
"""

import argparse
import logging
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
import yaml

from kb_config import get_model_for_step, get_wiki_dir, set_wiki_dir
from tools.catalog import save_catalog
from tools.sync_case_studies import sync_case_studies
from utils import extract_wikilink_slug, format_wikilink, format_wikilink_list, validate_path

logger = logging.getLogger(__name__)


def _llm_text(content: str | list[Any]) -> str:
    """
    Coerce LLM content response into a standard string.
    """
    if isinstance(content, str):
        return content
    return " ".join(str(part) for part in content)


def _strip_outer_markdown_code_block(content: str) -> str:
    """
    If the content starts with markdown backticks, strips them and returns standard frontmatter/body.
    """
    if not content.startswith("```"):
        return content

    lines = content.splitlines()
    closing_idx = -1
    for idx in range(1, len(lines)):
        if lines[idx].strip() in ("```", "```markdown", "```yaml"):
            closing_idx = idx
            break

    if closing_idx == -1:
        return content

    fm_lines = lines[1:closing_idx]
    body_lines = lines[closing_idx+1:]
    fm_lines_cleaned = [line for line in fm_lines if line.strip() != "---"]
    fm_content = "\n".join(fm_lines_cleaned)
    body_content = "\n".join(body_lines)
    return f"---\n{fm_content}\n---\n\n{body_content}"


def _clean_frontmatter_lines(fm_lines: list[str]) -> str:
    """
    Removes comments and backticks from frontmatter lines and strips them.
    """
    cleaned_fm_lines = []
    for line in fm_lines:
        if line.strip().startswith("```"):
            continue
        cleaned_line = re.sub(r'(?s)<!--.*?-->', '', line).strip()
        cleaned_line = cleaned_line.split('<!--')[0].strip()
        cleaned_fm_lines.append(cleaned_line)
    return "\n".join(cleaned_fm_lines)


def _clean_body_lines(body_lines: list[str]) -> str:
    """
    Strips leading and trailing backticks or empty lines from body.
    """
    while body_lines and (body_lines[0].strip() == "```" or not body_lines[0].strip()):
        body_lines.pop(0)
    while body_lines and (body_lines[-1].strip() == "```" or not body_lines[-1].strip()):
        body_lines.pop()
    return "\n".join(body_lines)


def _clean_frontmatter(content: str) -> str:
    """
    Extracts and sanitizes the frontmatter block, and cleans up formatting issues.
    """
    content = _strip_outer_markdown_code_block(content.strip())

    lines = content.splitlines()
    boundary_indices = [i for i, line in enumerate(lines) if line.strip() == "---"]

    if len(boundary_indices) < 2:
        return content

    i, j = boundary_indices[0], boundary_indices[1]
    cleaned_fm = _clean_frontmatter_lines(lines[i+1:j])
    body = _clean_body_lines(lines[j+1:])

    return f"---\n{cleaned_fm}\n---\n\n{body}"


def run_cleanup(wiki_dir: Path, dry_run: bool = False) -> None:
    """
    Run retroactive clean-up sweep on all experience files in the wiki.
    """
    experiences_dir = wiki_dir / "wiki" / "experiences"
    if not experiences_dir.exists():
        print(f"❌ Experiences directory not found at: {experiences_dir}", file=sys.stderr)
        return

    experiences_dir_resolved = experiences_dir.resolve()

    # 1. Create a safe backup before doing anything in-place
    if not dry_run:
        backup_dir = wiki_dir / "wiki" / "experiences_backup"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        shutil.copytree(experiences_dir, backup_dir)
        print(f"📦 Created a safe backup of experience files in: {backup_dir.name}")

    files = sorted(experiences_dir.glob("*.md"))
    print(f"🧹 Found {len(files)} experience file(s) to process")

    llm = get_model_for_step("INGESTION_MERGE")
    today = date.today().isoformat()

    # Load prompts externalized to src/prompts/ingestion/
    prompts_dir = Path(__file__).parent / "prompts" / "ingestion"
    system_template = (prompts_dir / "cleanup_system.txt").read_text(encoding="utf-8")
    user_template = (prompts_dir / "cleanup_user.txt").read_text(encoding="utf-8")

    total_processed = 0
    total_errors = 0

    for f in files:
        # Skip backup directories or temporary files
        if "backup" in str(f.parent):
            continue

        print(f"\n✨ Consolidating and cleaning up: {f.name}")
        content = f.read_text(encoding="utf-8")

        system_prompt = system_template
        prompt = f"TODAY'S DATE: {today}\n\n" + user_template.replace("{content}", content)

        if dry_run:
            print(f"  [DRY RUN] Would rewrite: {f.name}")
            total_processed += 1
            continue

        try:
            response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=prompt)])
            cleaned_content = _clean_frontmatter(_llm_text(response.content))

            # Simple validation: ensure frontmatter dashes exist
            if cleaned_content.count("---") >= 2:
                # Securely construct file path to satisfy static code analysis (prevent path traversal)
                safe_file_path = (experiences_dir_resolved / f.name).resolve()
                if safe_file_path.parent != experiences_dir_resolved:
                    raise ValueError(f"Security Alert: Attempted path traversal via file name: {f.name}")
                validate_path(safe_file_path).write_text(cleaned_content, encoding="utf-8")
                print(f"  ✅ Successfully cleaned and consolidated: {f.name}")
                total_processed += 1
            else:
                raise ValueError("LLM response did not contain valid YAML frontmatter delimiters.")
        except Exception as e:
            print(f"  ❌ Error processing {f.name}: {e}", file=sys.stderr)
            total_errors += 1

    print(f"\n{'=' * 50}")
    print(f"🎉 Cleanup completed. Processed: {total_processed}  Errors: {total_errors}")
    if not dry_run:
        print("ℹ️  All cleaned files have been written directly to wiki/experiences/.")
        print("ℹ️  A backup is available in wiki/experiences_backup/ in case you need to revert any changes.")


def _normalize_single_file_frontmatter(md_file: Path, dry_run: bool) -> tuple[bool, str]:
    """Normalize YAML frontmatter wikilinks in a single markdown file and return (modified, org_slug)."""
    content = md_file.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return False, ""
    parts = content.split("---", 2)
    if len(parts) < 3:
        return False, ""
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except Exception:
        return False, ""
    if not isinstance(fm, dict):
        return False, ""

    modified = False
    org_slug = ""
    for single_key in ["organization", "institution", "target_organization", "related_experience", "tenure"]:
        if single_key in fm and fm[single_key]:
            slug = extract_wikilink_slug(fm[single_key])
            if slug:
                if single_key == "organization":
                    org_slug = slug
                formatted = format_wikilink(slug)
                if fm[single_key] != formatted:
                    fm[single_key] = formatted
                    modified = True

    for list_key in ["related_experiences", "related", "case_studies", "projects", "patents", "notes"]:
        if list_key in fm and fm[list_key]:
            formatted_list = format_wikilink_list(fm[list_key])
            if fm[list_key] != formatted_list:
                fm[list_key] = formatted_list
                modified = True

    if modified and not dry_run:
        new_fm = yaml.dump(fm, default_flow_style=False, sort_keys=False, allow_unicode=True).strip()
        body = parts[2].lstrip("\n")
        validate_path(md_file).write_text(f"---\n{new_fm}\n---\n\n{body}", encoding="utf-8")
    return modified, org_slug


def normalize_wiki_frontmatter(wiki_dir: Path, dry_run: bool = False) -> dict[str, int]:
    """Repair unquoted [[slug]] YAML nested lists across the wiki, migrate legacy root/app files, and create company entities."""
    vault_root = wiki_dir.parent if wiki_dir.name == "wiki" else wiki_dir
    wiki_root = vault_root / "wiki" if (vault_root / "wiki").is_dir() else vault_root
    stats = {"files_scanned": 0, "files_updated": 0, "entities_created": 0}
    org_to_experiences: dict[str, list[str]] = {}

    # Migrate legacy wiki/log.md, wiki/catalog.json, and wiki/applications.yaml out of wiki/ if present
    if not dry_run and wiki_root != vault_root:
        legacy_log = wiki_root / "log.md"
        if legacy_log.exists() and not (vault_root / "log.md").exists():
            shutil.move(str(legacy_log), str(vault_root / "log.md"))
        legacy_cat = wiki_root / "catalog.json"
        if legacy_cat.exists():
            shutil.move(str(legacy_cat), str(vault_root / "catalog.json"))
        legacy_crm = wiki_root / "applications.yaml"
        if legacy_crm.exists():
            apps_dir = vault_root / "applications"
            apps_dir.mkdir(parents=True, exist_ok=True)
            if not (apps_dir / "applications.yaml").exists():
                shutil.move(str(legacy_crm), str(apps_dir / "applications.yaml"))
        legacy_synth = wiki_root / "synthesis"
        if legacy_synth.is_dir():
            apps_dir = vault_root / "applications"
            apps_dir.mkdir(parents=True, exist_ok=True)
            for synth_file in legacy_synth.glob("*.md"):
                target_synth = apps_dir / synth_file.name
                if not target_synth.exists():
                    shutil.move(str(synth_file), str(target_synth))

    for md_file in sorted(wiki_root.rglob("*.md")):
        if "backup" in str(md_file):
            continue
        stats["files_scanned"] += 1
        updated, org_slug = _normalize_single_file_frontmatter(md_file, dry_run=dry_run)
        if updated:
            stats["files_updated"] += 1
        if org_slug and md_file.parent.name == "experiences":
            org_to_experiences.setdefault(org_slug, []).append(md_file.stem)

    entities_dir = wiki_root / "entities"
    if not dry_run:
        entities_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    for org_slug, exp_stems in sorted(org_to_experiences.items()):
        entity_file = entities_dir / f"{org_slug}.md"
        if not entity_file.exists():
            stats["entities_created"] += 1
            if not dry_run:
                title = org_slug.replace("-", " ").title()
                exp_links = [format_wikilink(s) for s in exp_stems]
                fm_dict = {
                    "type": "entity",
                    "entity_type": "company",
                    "title": title,
                    "summary": f"{title} — organization referenced in candidate career history.",
                    "experiences": exp_links,
                    "created": today,
                    "updated": today,
                    "tags": ["company", "employer"],
                    "sources": ["kb-cleanup"],
                }
                fm_yaml = yaml.dump(fm_dict, default_flow_style=False, sort_keys=False).strip()
                validate_path(entity_file).write_text(
                    f"---\n{fm_yaml}\n---\n\n# {title}\n\nCompany entity record.\n",
                    encoding="utf-8",
                )
    return stats


def extract_voice_profile(wiki_dir: Path, dry_run: bool = False) -> Path:
    """Synthesize or refresh wiki/voice/my-voice.md from cover letters and first-person notes."""
    wiki_root = wiki_dir / "wiki" if (wiki_dir / "wiki").is_dir() else wiki_dir
    voice_path = validate_path(wiki_root / "voice" / "my-voice.md")
    samples: list[str] = []
    for subdir in ["cover-letters", "notes"]:
        folder = wiki_root / subdir
        if not folder.is_dir():
            continue
        for md_file in sorted(folder.glob("*.md"))[:5]:
            raw = md_file.read_text(encoding="utf-8")
            body = re.sub(r"^---\n.*?\n---", "", raw, flags=re.DOTALL).strip()
            if body:
                samples.append(f"### Sample ({md_file.name})\n{body[:600]}")

    today = date.today().isoformat()
    sample_section = "\n\n".join(samples) if samples else "No cover letters or notes ingested yet."
    content = (
        f"---\ntype: voice\ntitle: \"Candidate Personal Voice & Style Guide\"\n"
        f"english_proficiency: \"Fluent Professional\"\npreferred_tone: \"Direct, evidence-led, pragmatic\"\n"
        f"created: {today}\nupdated: {today}\ntags: [\"voice\", \"style-guide\"]\nsources: [\"kb-cleanup\"]\n---\n\n"
        f"# My Voice & Writing Style Guide\n\n"
        f"## 1. Core Voice & Cadence\n"
        f"- Prefer concrete architectural nouns and verifiable metrics over generic AI adjectives.\n"
        f"- Keep bullet sentences direct (18-24 words).\n\n"
        f"## 2. Forbidden AI Clichés\n"
        f"- Never use: spearheaded, synergized, visionary, testament to, dynamic fast-paced environment.\n\n"
        f"## 3. Extracted Writing Samples\n{sample_section}\n"
    )
    if not dry_run:
        voice_path.parent.mkdir(parents=True, exist_ok=True)
        voice_path.write_text(content, encoding="utf-8")
    return voice_path


def main() -> None:
    """
    CLI Main entry point for the experiences cleanup tool.
    """
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    parser = argparse.ArgumentParser(description="Career OS Experiences Retroactive Cleanup Tool")
    parser.add_argument("--wiki-dir", help="Path to llm-wiki folder (defaults to PATHS.WIKI_DIR in config.yaml)")
    parser.add_argument("--dry-run", action="store_true", help="Analyze files but do not modify them")
    parser.add_argument(
        "--sync-case-studies", action="store_true",
        help="Synchronize deep-dive case studies into parent experience achievements"
    )
    parser.add_argument("--generate-catalog", action="store_true", help="Generate or update catalog.json index")
    parser.add_argument(
        "--normalize-frontmatter", action="store_true",
        help="Normalize unquoted [[slug]] wikilinks in YAML frontmatter and generate missing company entities"
    )
    parser.add_argument(
        "--extract-voice", action="store_true",
        help="Generate or refresh wiki/voice/my-voice.md from cover letters and notes"
    )
    args = parser.parse_args()

    if args.wiki_dir:
        set_wiki_dir(args.wiki_dir)

    wiki_dir = get_wiki_dir()

    if args.normalize_frontmatter:
        stats = normalize_wiki_frontmatter(wiki_dir, dry_run=args.dry_run)
        print(f"✨ Frontmatter normalization complete: {stats}")
        return

    if args.extract_voice:
        target = extract_voice_profile(wiki_dir, dry_run=args.dry_run)
        print(f"✨ Voice profile updated at: {target}")
        return

    if args.generate_catalog:
        print(f"📦 Generating catalog index for: {wiki_dir}")
        catalog_path = save_catalog(wiki_dir)
        print(f"✨ Catalog generated at: {catalog_path}")
        return

    if args.sync_case_studies:
        print(f"🔍 Running case study synchronization on: {wiki_dir}")
        stats = sync_case_studies(wiki_dir, dry_run=args.dry_run)
        print(f"✨ Case study synchronization complete: {stats}")
        return

    run_cleanup(wiki_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    # Add current directory and src/ to path to allow importing config correctly
    sys.path.insert(0, str(Path(__file__).parent))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    main()
