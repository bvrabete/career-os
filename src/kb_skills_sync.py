"""
Administrative tool to compile, deduplicate, and link all skills across the Wiki.
This script acts as a manual CLI wrapper that reuses the core sync engine.
"""

import argparse
import logging
import sys
from pathlib import Path

from generation.skills_helper import run_skills_sync
from kb_config import get_wiki_dir, set_wiki_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Career OS Skills Knowledge-Graph Compiler")
    parser.add_argument("--wiki-dir", help="Path to llm-wiki folder (defaults to PATHS.WIKI_DIR in config.yaml)")
    parser.add_argument("--dry-run", action="store_true", help="Analyze files but do not modify them")
    args = parser.parse_args()

    if args.wiki_dir:
        set_wiki_dir(args.wiki_dir)

    wiki_dir = get_wiki_dir()
    run_skills_sync(wiki_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    main()
