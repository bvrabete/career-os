"""CLI tool to initialize and scaffold a new LLM-Wiki career knowledge base."""
import argparse
import os
import sys

from ingestion.bootstrapping import bootstrap_wiki_structure, is_wiki_initialized
from utils import validate_path


def parse_arguments() -> argparse.Namespace:
    """Parse CLI arguments for kb-init."""
    parser = argparse.ArgumentParser(
        description="Bootstrap and scaffold a new LLM-Wiki career knowledge base."
    )
    parser.add_argument(
        "--wiki-dir",
        default=os.environ.get("LLM_WIKI_DIR", "llm-wiki"),
        help="Path to the knowledge base root folder (defaults to LLM_WIKI_DIR or 'llm-wiki')",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-check and creation of missing subdirectories and templates",
    )
    return parser.parse_args()


def main() -> None:
    """Entrypoint for kb-init CLI."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    args = parse_arguments()
    try:
        wiki_dir = validate_path(args.wiki_dir)
    except Exception as e:
        print(f"❌ Error validating wiki directory path: {e}")
        sys.exit(1)

    already_init = is_wiki_initialized(wiki_dir)
    if already_init and not args.force:
        print(f"ℹ️  Knowledge base at '{wiki_dir}' is already initialized.")
        print("💡 Use '--force' to scaffold missing subdirectories or template files without overwriting.")
        return

    action_label = "Refreshing" if already_init else "Scaffolding"
    print(f"🚀 {action_label} LLM-Wiki knowledge base at '{wiki_dir}'...")

    try:
        bootstrap_wiki_structure(wiki_dir, force=args.force)
        print(f"✅ LLM-Wiki successfully initialized at: {wiki_dir}")
        print("📁 Ready for raw resume ingestion: 'uv run kb-ingest --dir <sources>'")
    except Exception as e:
        print(f"❌ Failed to initialize knowledge base: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
