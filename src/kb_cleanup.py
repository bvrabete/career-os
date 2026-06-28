"""
Administrative cleanup script for the Career Operating System's Wiki experiences.
This script performs a retroactive sweep across all experience files to dynamically
partition achievements, semantically deduplicate redundant bullets, and merge frontmatter fields.
"""

import sys
import os
import re
import shutil
import logging
from datetime import date
from pathlib import Path
from typing import Union

# Add current directory and src/ to path
sys.path.insert(0, str(Path(__file__).parent))

from kb_config import get_model_for_step, get_wiki_dir
from langchain_core.messages import SystemMessage, HumanMessage

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def _llm_text(content: Union[str, list]) -> str:
    if isinstance(content, str):
        return content
    return " ".join(str(part) for part in content)


def _clean_frontmatter(content: str) -> str:
    content = content.strip()
    
    if content.startswith("```"):
        lines = content.splitlines()
        closing_idx = -1
        for idx in range(1, len(lines)):
            if lines[idx].strip() in ("```", "```markdown", "```yaml"):
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
        if line.strip().startswith("```"):
            continue
        cleaned_line = re.sub(r'(?s)<!--.*?-->', '', line).strip()
        cleaned_line = cleaned_line.split('<!--')[0].strip()
        cleaned_fm_lines.append(cleaned_line)
        
    cleaned_fm = "\n".join(cleaned_fm_lines)

    while body_lines and (body_lines[0].strip() == "```" or not body_lines[0].strip()):
        body_lines.pop(0)
    while body_lines and (body_lines[-1].strip() == "```" or not body_lines[-1].strip()):
        body_lines.pop()

    body = "\n".join(body_lines)
    return f"---\n{cleaned_fm}\n---\n\n{body}"


def run_cleanup(wiki_dir: Path, dry_run: bool = False):
    experiences_dir = wiki_dir / "wiki" / "experiences"
    if not experiences_dir.exists():
        print(f"❌ Experiences directory not found at: {experiences_dir}")
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

    total_processed = 0
    total_errors = 0

    for f in files:
        # Skip backup directories or temporary files
        if "backup" in str(f.parent):
            continue

        print(f"\n✨ Consolidating and cleaning up: {f.name}")
        content = f.read_text(encoding="utf-8")

        system_prompt = f"""You are an elite Career Operating System Database Architect performing database-wide normalization on experience entries.

Your goal is to optimize and rewrite the given experience file in-place to ensure absolute factual density, zero verbal redundancy, and strict compliance with the dynamic schema standards.

CRITICAL CONSTRAINTS:
1. DYNAMIC THEMATIC PARTITIONING: Analyze the complete set of accomplishments currently present in the file. Identify the optimal 3 to 5 core thematic categories (H3 headings) that best partition and capture the unique focus areas of this specific role. Avoid rigid hardcoded headings if they do not fit the role's level, track, or seniority (e.g., an early developer shouldn't have management headings; a CTO should have business/board headings). Do not create more than 5 headings, and do not use more than 1 category containing only a single bullet.
2. SEMANTIC DEDUPLICATION: Intelligently merge and combine overlapping or highly similar accomplishments. If multiple bullet points describe the same project, system, tool implementation, or incident response (even if phrased differently), synthesize them into a single, high-impact, information-dense STAR bullet. Completely eliminate verbal repetition.
3. CONCRETE DETAILS: Never lose or dilute any precise metrics, dollar amounts, headcounts, numbers, technology names, specific tool names, or physical document/meeting/evidence references (e.g., PowerPoint filenames, email subjects, or meeting names like 'Daily stand-up', 'Red Foundation', etc.). Merge details to maximize factual weight and authenticity.
4. FRONTMATTER INTEGRATION: Keep the existing YAML frontmatter fields (type, title, organization, location, dates, tracks, skills, tags, created) intact, but clean up the `sources` list to combine all relevant sources, remove duplicates, and sort them. Set the `updated:` date to {today}. Keep the frontmatter perfectly valid, clean YAML with no markdown code blocks, backticks, or inline comments.
5. NARRATIVE & REFLECTIONS: Retain the entire Narrative & Reflections and Context sections verbatim. Do not truncate, summarize, or alter them unless there are explicit duplicates inside them.
6. LANGUAGE & FORMAT: Output English only. Output raw markdown only — do NOT wrap the output or any sections in markdown code blocks or fences. No explanations."""

        prompt = f"""Clean up, consolidate, and deduplicate the following career experience file. Output the complete optimized markdown:

{content}"""

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
            print(f"  ❌ Error processing {f.name}: {e}")
            total_errors += 1

    print(f"\n{'=' * 50}")
    print(f"🎉 Cleanup completed. Processed: {total_processed}  Errors: {total_errors}")
    if not dry_run:
        print(f"ℹ️  All cleaned files have been written directly to wiki/experiences/.")
        print(f"ℹ️  A backup is available in wiki/experiences_backup/ in case you need to revert any changes.")


def main():
    import argparse
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
    main()
