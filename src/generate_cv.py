import argparse
import dataclasses
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any
import warnings

from generation import build_graph
from kb_config import get_wiki_dir
from utils import validate_path
from pdf_generator import generate_pdf
from docx_generator import generate_docx

# Suppress annoying logging from httpx if possible
logging.getLogger("httpx").setLevel(logging.WARNING)

SUGGESTION_STR = "💡 Suggestion:"


def parse_arguments() -> argparse.Namespace:
    """
    Parses command-line arguments for the CV generator.
    """
    args_parser = argparse.ArgumentParser(description="Agentic AI CV Generator")
    args_parser.add_argument("--jd", required=True,
                             help="Path to the Job Description text file")
    args_parser.add_argument("--out", default=None,
                             help="Output path for the Markdown CV (defaults to LLM-Wiki synthesis folder if omitted)")
    args_parser.add_argument(
        "--wiki-dir", help="Path to the llm-wiki folder (defaults to LLM_WIKI_DIR env var or 'llm-wiki')")
    args_parser.add_argument("--strategy", help="Strategy key slug to override analyzer's suggested strategy")
    args_parser.add_argument("--generate-pdf", action="store_true", help="Automatically generate PDF CV from Markdown using final stylesheet")
    args_parser.add_argument("--generate-docx", action="store_true", help="Automatically generate Word (docx) CV from Markdown")
    return args_parser.parse_args()


class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            return dataclasses.asdict(o)
        return super().default(o)


def save_outputs(
    args: argparse.Namespace,
    draft: str,
    final_state: dict[str, Any],
    synthesis_path: Path,
    synthesis_content: str
) -> Path:
    """
    Saves the generated CV (Markdown draft), contexts, and archives to the appropriate paths.
    """
    if args.out:
        out_path = validate_path(args.out)
        
        # Check if the output path is a directory or has no file extension
        if out_path.is_dir() or args.out.endswith("/") or args.out.endswith("\\") or not out_path.suffix:
            jd_filename = Path(args.jd).with_suffix(".md").name
            out_path = out_path / jd_filename
            
        out_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write clean draft to specified path
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(draft)
        print(f"\n✅ Build complete! Clean Markdown saved to {out_path}")

        # Save Context (Graph State) for debugging
        context_path = validate_path(out_path.with_name(f"{out_path.stem}_context.json"))
        state_to_save = {k: v for k, v in final_state.items() if k != "draft_cv"}
        
        with open(context_path, "w", encoding="utf-8") as f:
            json.dump(state_to_save, f, indent=2, cls=EnhancedJSONEncoder)
        print(f"📦 Context State saved to {context_path}")

        # Always save to synthesis-archive in LLM-Wiki for application CRM tracking
        synthesis_path.parent.mkdir(parents=True, exist_ok=True)
        with open(synthesis_path, "w", encoding="utf-8") as f:
            f.write(synthesis_content)
        print(f"✨ Synthesis archive auto-saved to Wiki: {synthesis_path}")

        return out_path

    # Also automatically save to synthesis-archive in LLM-Wiki
    synthesis_path.parent.mkdir(parents=True, exist_ok=True)
    with open(synthesis_path, "w", encoding="utf-8") as f:
        f.write(synthesis_content)
    print(f"✨ Synthesis archive auto-saved to Wiki: {synthesis_path}")

    return synthesis_path


def compile_optional_formats(args: argparse.Namespace, draft: str, out_path: Path, final_state: dict[str, Any]) -> None:
    """
    Compiles PDF and DOCX formats if requested.
    """
    if args.generate_pdf:
        print("\n🎨 Compiling to PDF format...")
        try:
            pdf_template = final_state.get("pdf_template", "templates/base.css")
            pdf_path = out_path.with_suffix(".pdf")
            success = generate_pdf(draft, str(pdf_path), pdf_template)
            if success:
                print(f"✅ Beautiful PDF generated at {pdf_path}")
            else:
                print("❌ PDF generation failed.")
        except Exception as e:
            print(f"⚠️ PDF Generation failed: {e}")

    if args.generate_docx:
        print("\n📝 Compiling to Word (docx) format...")
        try:
            docx_path = out_path.with_suffix(".docx")
            success = generate_docx(draft, str(docx_path))
            if success:
                print(f"✅ Clean DOCX generated at {docx_path}")
            else:
                print("❌ Word (docx) generation failed.")
        except Exception as e:
            print(f"⚠️ DOCX Generation failed: {e}")


def _parse_synthesis_metadata(file_path: Path) -> dict[str, str]:
    """
    Parses status and created date from an existing synthesis file's frontmatter.
    """
    metadata = {"status": "", "created": ""}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return metadata

    if not content.startswith("---"):
        return metadata

    end_idx = content.find("---", 3)
    if end_idx == -1:
        return metadata

    frontmatter = content[3:end_idx]
    for line in frontmatter.splitlines():
        if ":" not in line:
            continue
        parts = line.split(":", 1)
        key = parts[0].strip().lower()
        if key not in metadata:
            continue
        metadata[key] = parts[1].strip()

    return metadata


def _setup_logging() -> None:
    """Configures the root logging handlers and logging levels."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    file_handler = logging.FileHandler(log_dir / "generation_run.log", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    root_logger.addHandler(file_handler)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    root_logger.addHandler(console_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _load_job_description(args: argparse.Namespace) -> str | None:
    """Validates the JD file and returns its content, or None if not found."""
    if args.wiki_dir:
        os.environ["LLM_WIKI_DIR"] = args.wiki_dir

    jd_path = validate_path(args.jd)
    if not jd_path.exists():
        print(f"❌ Error: Job Description file not found at {jd_path}")
        return None

    with open(jd_path, "r", encoding="utf-8") as f:
        return f.read()


def _triage_pipeline_exception(e: Exception) -> None:
    """Analyzes pipeline exception and prints user-friendly suggestion triage."""
    err_msg = str(e).lower()
    print(f"\n❌ Pipeline failed with exception: {e}")
    
    if any(keyword in err_msg for keyword in ["api_key", "unauthorized", "credentials", "401"]):
        print(SUGGESTION_STR)
        print("   Your API keys might be invalid or expired.")
        print("   - Verify that OPENAI_API_KEY and GEMINI_API_KEY are correctly set in your environment or .env file.")
        
    elif any(keyword in err_msg for keyword in ["connection", "timeout", "rate limit", "429"]):
        print(SUGGESTION_STR)
        print("   Network connection timeout or API rate limits exceeded.")
        print("   - Wait a moment and retry.")
        print("   - Check if Ollama is running (`curl http://localhost:11434`) if you are using local models.")
        
    elif any(keyword in err_msg for keyword in ["model not found", "not found", "does not exist", "pull"]):
        print(SUGGESTION_STR)
        print("   The specified local model was not found in Ollama.")
        print("   - Run `ollama pull <model_name>` (e.g., `ollama pull qwen2.5:7b`) to download the required model.")
        print("   - Check the MODEL_NAME settings in your config.yaml.")
        
    else:
        print(SUGGESTION_STR)
        print("   - Double-check your config.yaml configuration and ensure that local services (like Ollama) are fully operational.")
        print("   - Review your log files or run with verbose logging for more details.")


def _resolve_synthesis_path(company_clean: str, role_clean: str, today_str: str) -> tuple[Path, str]:
    """Finds or constructs the appropriate synthesis file path and its creation date."""
    synthesis_dir = get_wiki_dir() / "wiki" / "synthesis"
    synthesis_dir.mkdir(parents=True, exist_ok=True)

    existing_path: Path | None = None
    created_date = today_str

    prefix = f"synthesis-cv-{company_clean}-{role_clean}"
    for child in synthesis_dir.glob(f"{prefix}*.md"):
        meta = _parse_synthesis_metadata(child)
        if meta.get("status") == "Generated":
            existing_path = child
            if meta.get("created"):
                created_date = meta["created"]
            break

    if existing_path:
        print(f"🔄 Reusing active 'Generated' synthesis file: {existing_path.name}")
        return existing_path, created_date

    synthesis_filename = f"synthesis-cv-{company_clean}-{role_clean}-{today_str}.md"
    return synthesis_dir / synthesis_filename, created_date


def _save_and_compile_outputs(
    args: argparse.Namespace,
    final_state: dict[str, Any],
    synthesis_path: Path,
    created_date: str,
    today_str: str,
) -> None:
    """Formats and writes the final CV draft and its synthesis file, then compiles other outputs."""
    draft = final_state.get("draft_cv", "")
    company = final_state.get("target_organization_slug", "unknown-company")
    role = final_state.get("target_role", "unknown-role")
    track_val = final_state.get("target_region", "general").upper()

    synthesis_content = f"""---
type: synthesis
title: "Tailored CV for {role} at {company}"
track: {track_val}
target_role: "{role}"
target_organization: [[{company}]]
status: Generated
created: {created_date}
updated: {today_str}
---

{draft}
"""

    out_path = save_outputs(args, draft, final_state, synthesis_path, synthesis_content)
    print(f"🔄 Audit iterations required: {final_state.get('iteration_count')}")
    compile_optional_formats(args, draft, out_path, final_state)


def main() -> None:
    """
    Main entry point orchestrating state execution and error recovery.
    """
    args = parse_arguments()
    _setup_logging()

    jd_content = _load_job_description(args)
    if jd_content is None:
        return

    # Use args.jd to print actual file name from argparse namespace
    jd_name = Path(args.jd).name
    print(f"🚀 Initializing LangGraph CV Generator Pipeline against `{jd_name}`...")
    app = build_graph()
    
    inputs = {
        "job_description_raw": jd_content,
        "iteration_count": 0,
        "max_iterations": 3,
        "strategy_override": args.strategy
    }
    
    try:
        final_state = app.invoke(inputs)
    except Exception as e:
        _triage_pipeline_exception(e)
        print("\n🧹 Gracefully exiting...")
        sys.exit(1)

    company: str = final_state.get("target_organization_slug", "unknown-company")
    role: str = final_state.get("target_role", "unknown-role")

    company_clean = "".join(c if c.isalnum() or c in "-_" else "_" for c in company).lower()
    role_clean = "".join(c if c.isalnum() or c in "-_" else "_" for c in role).lower()
    today_str = datetime.now().date().isoformat()

    synthesis_path, created_date = _resolve_synthesis_path(company_clean, role_clean, today_str)
    _save_and_compile_outputs(args, final_state, synthesis_path, created_date, today_str)


if __name__ == "__main__":
    main()
