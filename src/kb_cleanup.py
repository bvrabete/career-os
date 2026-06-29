"""
Administrative cleanup script for the Career Operating System's Wiki experiences.
This script performs a retroactive sweep across all experience files to dynamically
partition achievements, semantically deduplicate redundant bullets, and merge frontmatter fields.
"""

import argparse
import logging
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from kb_config import get_model_for_step, get_wiki_dir

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
    fm_lines_cleaned = [l for l in fm_lines if l.strip() != "---"]
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
                f.write_text(cleaned_content, encoding="utf-8")
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


def main() -> None:
    """
    CLI Main entry point for the experiences cleanup tool.
    """
    parser = argparse.ArgumentParser(description="Career OS Experiences Retroactive Cleanup Tool")
    parser.add_argument("--wiki-dir", help="Path to llm-wiki folder (defaults to LLM_WIKI_DIR or 'llm-wiki')")
    parser.add_argument("--dry-run", action="store_true", help="Analyze files but do not modify them")
    args = parser.parse_args()

    if args.wiki_dir:
        os.environ["LLM_WIKI_DIR"] = args.wiki_dir

    from kb_config import get_wiki_dir
    wiki_dir = get_wiki_dir()

    run_cleanup(wiki_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    # Add current directory and src/ to path to allow importing config correctly
    sys.path.insert(0, str(Path(__file__).parent))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    main()
