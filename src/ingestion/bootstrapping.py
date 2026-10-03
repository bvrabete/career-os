"""Bootstrapping logic for initial Wiki folder structures and template assets."""
import logging
import shutil
from pathlib import Path

SCHEMA_MD = "schema.md"
MAPPINGS_FILE_NAME = "mappings.md"


def _bootstrap_subdirs(wiki_root: Path) -> None:
    """Create all standard subdirectories under the wiki root."""
    subdirs = [
        "experiences", "education", "entities", "projects", "skills",
        "sources", "synthesis", "concepts", "notes", "patents",
        "strategies", "queries", "media", "cover-letters", "case-studies"
    ]
    for subdir in subdirs:
        (wiki_root / subdir).mkdir(parents=True, exist_ok=True)


def _bootstrap_templates_and_schema(wiki_dir: Path, wiki_root: Path) -> None:
    """Bootstrap schemas, mappings, and log file."""
    repo_llm_wiki = Path(__file__).resolve().parent.parent.parent / "llm-wiki.template"

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
    repo_templates_dir = Path(__file__).resolve().parent.parent.parent / "llm-wiki.template" / "templates"
    if not repo_templates_dir.exists():
        repo_templates_dir = Path(__file__).resolve().parent.parent.parent / "llm-wiki" / "templates"
    if not repo_templates_dir.exists():
        repo_templates_dir = Path(__file__).resolve().parent.parent.parent / "templates"
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
