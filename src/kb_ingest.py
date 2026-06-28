import argparse
import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)

def validate_path(path: Path | str) -> Path:
    """
    Validates and canonicalizes file paths to prevent traversal and security risks.
    """
    import os
    base_dir = os.path.realpath(os.path.expanduser("~")) + os.sep
    canonical_path = os.path.realpath(os.path.abspath(path))
    if not canonical_path.startswith(base_dir):
        raise ValueError(f"Security Warning: Path traversal or escape detected: {path}")
    return Path(canonical_path)


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".md", ".txt"}


def get_status_file() -> Path:
    from kb_config import get_wiki_dir
    return get_wiki_dir() / "ingestion_status.json"


def get_log_file() -> Path:
    from kb_config import get_wiki_dir
    return get_wiki_dir() / "wiki" / "log.md"


def load_status() -> dict:
    status_file = get_status_file()
    if status_file.exists():
        with open(status_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"processed": {}}


def save_status(status: dict):
    status_file = get_status_file()
    status_file.parent.mkdir(parents=True, exist_ok=True)
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)


def append_log(written_paths: list[str]):
    log_file = get_log_file()
    if not log_file.exists() or not written_paths:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"\n## {today}\n"] + [f"- Ingested: `{p}`" for p in written_paths]
    with open(log_file, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def file_hash(path: Path) -> str:
    """MD5 of file contents — used to detect changes since last ingestion."""
    h = hashlib.md5()
    safe_path = validate_path(path)
    with open(safe_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in SUPPORTED_EXTENSIONS else []
    return sorted(
        f for f in path.rglob("*")
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def _report_and_save_status(
    rel_path: str,
    current_hash: str,
    outputs: list[dict[str, Any]],
    status: dict[str, Any],
    dry_run: bool
) -> tuple[int, int]:
    """
    Reports the ingestion results on the console, updates the status dict,
    and returns a tuple of (written_count, error_count).
    """
    written = [o for o in outputs if o.get("written")]
    dry_run_outputs = [o for o in outputs if o.get("dry_run")]
    failed = [o for o in outputs if o.get("validation_errors") and not o.get(
        "written") and not o.get("dry_run")]
    duplicates = [o for o in outputs if o.get(
        "skipped_reason") == "duplicate"]

    for o in written:
        label = "Updated" if o.get("merged") else "Created"
        print(f"  ✅ {label}: {o['path']}")
    for o in dry_run_outputs:
        action = "update" if o.get("merged") else "create"
        print(f"  [DRY RUN] Would {action}: {o['path']}")
    for o in duplicates:
        print(f"  ⏭️  Duplicate skipped: {o['path']}")
    for o in failed:
        print(
            f"  ❌ Validation failed: {o['path']} — {o['validation_errors']}")

    if written:
        status["processed"][rel_path] = {
            "status": "SUCCESS",
            "file_hash": current_hash,
            "outputs": [o["path"] for o in written],
            "processed_at": datetime.now().isoformat(),
        }
        if not dry_run:
            append_log([o["path"] for o in written])
    elif failed:
        status["processed"][rel_path] = {
            "status": "FAILED",
            "file_hash": current_hash,
            "errors": [str(o["validation_errors"]) for o in failed],
            "processed_at": datetime.now().isoformat(),
        }

    return len(written), len(failed)


def _process_file(
    file_path: Path,
    app: Any,
    status: dict[str, Any],
    force: bool,
    dry_run: bool
) -> tuple[int, int, int]:
    """
    Processes a single file in the ingestion pipeline, invoking the LangGraph graph
    and updating the status cache.
    """
    rel_path = str(file_path)
    existing = status["processed"].get(rel_path, {})
    current_hash = file_hash(file_path)
    stored_hash = existing.get("file_hash")

    if not force and stored_hash == current_hash:
        # File unchanged — skip regardless of previous status
        reason = "already processed" if existing.get(
            "status") == "SUCCESS" else "unchanged since last attempt"
        print(f"  ⏭️  Skipping ({reason}): {file_path.name}")
        return 0, 1, 0

    print(f"\n📄 Processing: {file_path.name}")

    try:
        final_state = app.invoke({"source_file": rel_path})
    except Exception as e:
        print(f"  ❌ Pipeline error: {e}")
        status["processed"][rel_path] = {
            "status": "ERROR",
            "file_hash": current_hash,
            "error": str(e),
            "processed_at": datetime.now().isoformat(),
        }
        save_status(status)
        return 0, 0, 1

    doc_type = final_state.get("doc_type", "unknown")
    outputs = final_state.get("wiki_outputs", [])

    if doc_type == "skip":
        print("  ⏭️  Skipped (classified as: skip)")
        status["processed"][rel_path] = {
            "status": "SKIPPED",
            "file_hash": current_hash,
            "processed_at": datetime.now().isoformat(),
        }
        if not dry_run:
            save_status(status)
        return 0, 0, 0

    written_count, error_count = _report_and_save_status(
        rel_path=rel_path,
        current_hash=current_hash,
        outputs=outputs,
        status=status,
        dry_run=dry_run
    )

    if not dry_run:
        save_status(status)

    return written_count, 0, error_count


def main() -> None:
    """
    Main entrypoint for the ingestion pipeline command-line interface.
    """
    parser = argparse.ArgumentParser(
        description="Agentic Wiki Ingestion Pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--file", help="Path to a single raw document to ingest")
    group.add_argument(
        "--dir", help="Path to a directory of raw documents to ingest")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and extract but do not write wiki files")
    parser.add_argument("--force", action="store_true",
                        help="Re-process files already recorded in ingestion_status.json")
    parser.add_argument(
        "--wiki-dir", help="Path to the llm-wiki folder (defaults to LLM_WIKI_DIR env var or 'llm-wiki')")
    args = parser.parse_args()

    if args.wiki_dir:
        os.environ["LLM_WIKI_DIR"] = args.wiki_dir

    from kb_config import get_wiki_dir
    from kb_ingest_graph import _bootstrap_wiki_structure
    _bootstrap_wiki_structure(get_wiki_dir())

    target = validate_path(args.file or args.dir)
    if not target.exists():
        print(f"❌ Path not found: {target}")
        return

    files = collect_files(target)
    if not files:
        print(f"No supported files found at {target}")
        return

    print(f"🔍 Found {len(files)} file(s) to process")

    # Import graph here so we don't pay startup cost before arg validation
    from kb_ingest_graph import build_ingest_graph
    app = build_ingest_graph(dry_run=args.dry_run)
    status = load_status()

    total_written = 0
    total_skipped = 0
    total_errors = 0

    for file_path in files:
        w, s, e = _process_file(
            file_path=file_path,
            app=app,
            status=status,
            force=args.force,
            dry_run=args.dry_run
        )
        total_written += w
        total_skipped += s
        total_errors += e

    print(f"\n{'=' * 50}")
    print(
        f"✅ Written: {total_written}  ⏭️ Skipped: {total_skipped}  ❌ Errors: {total_errors}")
    if args.dry_run:
        print("ℹ️  Dry-run mode — no files were written")


if __name__ == "__main__":
    main()
