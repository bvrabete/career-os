"""
Tool to synchronize deep-dive case studies into parent company experience records.
Ensures every file in wiki/case-studies/ has a corresponding STAR achievement one-liner
indexed inside its parent experience file ending with an in-line wikilink:
([[case-studies/{slug}]])
"""

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Any
import yaml

from kb_config import get_wiki_dir
from utils import validate_path, safe_read_text, safe_write_text

logger = logging.getLogger(__name__)


def _extract_frontmatter_and_body(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter and separate body text."""
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    try:
        fm = yaml.safe_load(parts[1]) or {}
        return (fm if isinstance(fm, dict) else {}), parts[2].strip()
    except Exception as e:
        logger.warning(f"Error parsing frontmatter: {e}")
        return {}, content


def _clean_slug(raw_ref: Any) -> str:
    """Extract clean slug from string, list, or wikilink [[slug]]."""
    if not raw_ref:
        return ""
    if isinstance(raw_ref, (list, tuple)):
        if len(raw_ref) > 0:
            return _clean_slug(raw_ref[0])
        return ""
    val = str(raw_ref).strip().strip("'\"")
    m = re.search(r'\[*\[([^\]]+)\]\]*', val)
    if m:
        val = m.group(1).strip().strip("'\"")
    return val


def _extract_case_study_bullet(fm: dict[str, Any], body: str, slug: str) -> str:
    """Extract or construct a STAR one-liner achievement ending with a wikilink."""
    title = fm.get("title", slug.replace("-", " ").title())

    # Try finding quantified results first
    results_match = re.search(r'##\s*Quantified Impact & Results\s*\n+([^#\n]+)', body)
    if results_match:
        raw_bullet = results_match.group(1).strip().lstrip("-* \t")
        if raw_bullet:
            return f"- **{title}**: {raw_bullet} ([[case-studies/{slug}]])"

    # Try finding architecture summary
    arch_pattern = (
        r'##\s*(?:Architecture & Technical Implementation|'
        r'Architecture & System Design|System Architecture)\s*\n+([^#\n]+)'
    )
    arch_match = re.search(arch_pattern, body, re.IGNORECASE)
    if arch_match:
        raw_bullet = arch_match.group(1).strip().lstrip("-* \t")
        if raw_bullet:
            return f"- **{title}**: {raw_bullet} ([[case-studies/{slug}]])"

    # Fallback to title
    return f"- **{title}**: Spearheaded technical architecture and implementation. ([[case-studies/{slug}]])"


def _extract_related_slugs(raw_related: Any) -> list[str]:
    """Recursively extract and clean slugs from related frontmatter."""
    slugs: list[str] = []
    if isinstance(raw_related, str):
        cleaned = _clean_slug(raw_related)
        if cleaned:
            slugs.append(cleaned)
    elif isinstance(raw_related, (list, tuple)):
        for item in raw_related:
            slugs.extend(_extract_related_slugs(item))
    return slugs


def _find_parent_experience_file(experiences_dir: Path, fm: dict[str, Any], body: str = "") -> Path | None:
    """Locate the target experience file matching tenure, organization, or related slugs."""
    # 1. Exact tenure slug match
    tenure_slug = _clean_slug(fm.get("tenure"))
    if tenure_slug:
        clean_tenure = tenure_slug.replace("experiences/", "").replace("experience/", "")
        direct_path = experiences_dir / f"{clean_tenure}.md"
        if direct_path.exists():
            return direct_path

    # 2. Organization slug match
    org_slug = _clean_slug(fm.get("organization"))
    if org_slug:
        candidates = list(experiences_dir.glob(f"{org_slug}*.md"))
        if candidates:
            candidates.sort(reverse=True)
            return candidates[0]

    # 3. Related slugs match
    for rel_slug in _extract_related_slugs(fm.get("related")):
        candidates = list(experiences_dir.glob(f"{rel_slug}*.md"))
        if candidates:
            candidates.sort(reverse=True)
            return candidates[0]

    # 4. Text title/body heuristic against experience file stems
    title = str(fm.get("title", "")).lower()
    for exp_file in experiences_dir.glob("*.md"):
        company_prefix = exp_file.stem.split("-")[0]
        if len(company_prefix) >= 4 and (company_prefix in title or company_prefix in body.lower()):
            return exp_file

    return None


def _append_bullet_to_content(exp_content: str, bullet: str) -> str:
    """Inject bullet under Key Achievements or appropriate section."""
    lines = exp_content.splitlines()
    target_idx = -1

    # Look for Key Achievements section
    for idx, line in enumerate(lines):
        if re.search(r'^\s*###?\s*Key Achievements', line, re.IGNORECASE):
            target_idx = idx + 1
            break

    if target_idx != -1:
        while target_idx < len(lines):
            line_stripped = lines[target_idx].strip()
            if not (line_stripped.startswith(("-", "*")) or not line_stripped):
                break
            target_idx += 1
        lines.insert(target_idx, bullet)
        return "\n".join(lines) + "\n"

    # Fallback: append at the end with a new heading
    return exp_content.rstrip() + f"\n\n### Key Achievements\n{bullet}\n"


def sync_case_studies(wiki_dir: Path, dry_run: bool = False) -> dict[str, int]:
    """
    Synchronizes all case studies in wiki/case-studies/ with parent experience files.

    Returns:
        Summary dict containing counts of processed, synced, already_synced, and unmatched.
    """
    case_studies_dir = wiki_dir / "wiki" / "case-studies"
    experiences_dir = wiki_dir / "wiki" / "experiences"

    stats = {"total": 0, "total_case_studies": 0, "synced": 0, "already_synced": 0, "unmatched": 0}

    if not case_studies_dir.exists() or not experiences_dir.exists():
        logger.warning(f"Case studies or experiences directory missing under {wiki_dir}")
        return stats

    case_files = sorted(case_studies_dir.glob("*.md"))
    stats["total"] = len(case_files)
    stats["total_case_studies"] = len(case_files)

    for case_file in case_files:
        slug = case_file.stem
        case_content = safe_read_text(case_file)
        fm, body = _extract_frontmatter_and_body(case_content)

        parent_exp = _find_parent_experience_file(experiences_dir, fm, body=body)
        if not parent_exp:
            logger.warning(f"No matching parent experience found for case study: {case_file.name}")
            stats["unmatched"] += 1
            continue

        exp_content = safe_read_text(parent_exp)
        wikilink_pattern = f"case-studies/{slug}"

        if wikilink_pattern in exp_content:
            stats["already_synced"] += 1
            continue

        bullet = _extract_case_study_bullet(fm, body, slug)
        updated_content = _append_bullet_to_content(exp_content, bullet)

        if not dry_run:
            safe_write_text(parent_exp, updated_content)
            logger.info(f"Synced case study '{slug}' into '{parent_exp.name}'")

        stats["synced"] += 1

    return stats


def main() -> None:
    """CLI Entrypoint for case study synchronization."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="CareerOS Case Study to Experience Synchronizer")
    parser.add_argument("--wiki-dir", help="Path to llm-wiki directory (defaults to PATHS.WIKI_DIR in config.yaml)")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    args = parser.parse_args()

    wiki_dir = validate_path(Path(args.wiki_dir).resolve()) if args.wiki_dir else get_wiki_dir()

    print(f"🔍 Scanning case studies in: {wiki_dir / 'wiki' / 'case-studies'}")
    stats = sync_case_studies(wiki_dir, dry_run=args.dry_run)
    print("✨ Synchronization Summary:")
    print(f"   Total Case Studies : {stats['total']}")
    print(f"   Newly Synced       : {stats['synced']}")
    print(f"   Already Synced     : {stats['already_synced']}")
    print(f"   Unmatched          : {stats['unmatched']}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    main()
