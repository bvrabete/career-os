import argparse
import dataclasses
from datetime import datetime
import json
import logging
from pathlib import Path
import re
import sys
from typing import Any

from generation import build_graph
from ingestion.bootstrapping import is_wiki_initialized
from kb_config import get_wiki_dir, set_wiki_dir
from tools.crm import record_application
from utils import validate_path
from pdf_generator import generate_pdf
from docx_generator import generate_docx

logger = logging.getLogger("cv_gen")
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
        "--wiki-dir", help="Path to the llm-wiki folder (defaults to PATHS.WIKI_DIR in config.yaml)")
    args_parser.add_argument(
        "--strategy",
        default=None,
        help="Location strategy override ('ireland', 'emea', 'us-tech', 'germany', 'netherlands', etc.)",
    )
    args_parser.add_argument(
        "--track",
        default=None,
        help="Career track override ('engineering-management', 'staff-principal', 'executive', 'startup-founding-engineer', 'general-engineering')",
    )
    args_parser.add_argument(
        "--template",
        help="Document template/theme to use ('base', 'executive', 'compact', or path to CSS)",
    )
    args_parser.add_argument(
        "--interactive", action="store_true", help="Prompt interactively if the auditor flags issues"
    )
    args_parser.add_argument(
        "--generate-pdf",
        action="store_true",
        help="Automatically generate PDF CV from Markdown using final stylesheet",
    )
    args_parser.add_argument(
        "--generate-docx", action="store_true", help="Automatically generate Word (docx) CV from Markdown"
    )
    args_parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level for console output (default: INFO)",
    )
    args_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose DEBUG logging",
    )
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
        logger.info("Build complete! Clean Markdown saved to %s", out_path)

        # Save Context (Graph State) for debugging
        context_path = validate_path(out_path.with_name(f"{out_path.stem}_context.json"))
        state_to_save = {k: v for k, v in final_state.items() if k != "draft_cv"}

        with open(context_path, "w", encoding="utf-8") as f:
            json.dump(state_to_save, f, indent=2, cls=EnhancedJSONEncoder)
        logger.info("Context State saved to %s", context_path)
        return out_path

    # Also automatically save to synthesis-archive in LLM-Wiki
    synthesis_path.parent.mkdir(parents=True, exist_ok=True)
    with open(synthesis_path, "w", encoding="utf-8") as f:
        f.write(synthesis_content)
    logger.info("Synthesis archive auto-saved to Wiki: %s", synthesis_path)

    return synthesis_path


def compile_optional_formats(args: argparse.Namespace, draft: str, out_path: Path, final_state: dict[str, Any]) -> None:
    """
    Compiles PDF and DOCX formats if requested.
    """
    if args.generate_pdf:
        logger.info("Compiling to PDF format...")
        try:
            pdf_template = args.template or final_state.get("pdf_template", "templates/base.css")
            pdf_path = out_path.with_suffix(".pdf")
            success = generate_pdf(draft, str(pdf_path), pdf_template)
            if success:
                logger.info("Beautiful PDF generated at %s", pdf_path)
            else:
                logger.error("PDF generation failed.")
        except Exception as e:
            logger.warning("PDF Generation failed: %s", e)

    if args.generate_docx:
        logger.info("Compiling to Word (docx) format...")
        try:
            docx_template = args.template or final_state.get("docx_template", "base")
            docx_path = out_path.with_suffix(".docx")
            success = generate_docx(draft, str(docx_path), template=docx_template)
            if success:
                logger.info("Clean DOCX generated at %s", docx_path)
            else:
                logger.error("Word (docx) generation failed.")
        except Exception as e:
            logger.warning("DOCX Generation failed: %s", e)


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


def _setup_logging(log_level: str = "INFO") -> None:
    """Configures the root logging handlers and logging levels."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    root_logger.handlers.clear()

    file_handler = logging.FileHandler(log_dir / "generation_run.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - [%(levelname)s] - %(name)s - %(message)s"))
    root_logger.addHandler(file_handler)

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    root_logger.addHandler(console_handler)

    for noisy_lib in ["httpx", "httpcore", "openai", "urllib3", "google", "google_genai"]:
        logging.getLogger(noisy_lib).setLevel(logging.WARNING)


def _load_job_description(args: argparse.Namespace) -> str | None:
    """Validates the JD file and returns its content, or None if not found."""
    if args.wiki_dir:
        set_wiki_dir(args.wiki_dir)

    jd_path = validate_path(args.jd)
    if not jd_path.exists():
        logger.error("Job Description file not found at %s", jd_path)
        return None

    with open(jd_path, "r", encoding="utf-8") as f:
        return f.read()


def _triage_pipeline_exception(e: Exception) -> None:
    """Analyzes pipeline exception and logs user-friendly suggestion triage."""
    err_msg = str(e).lower()
    logger.error("Pipeline failed with exception: %s", e)

    if any(keyword in err_msg for keyword in ["api_key", "unauthorized", "credentials", "401"]):
        logger.info("%s", SUGGESTION_STR)
        logger.info("   Your API keys might be invalid or expired.")
        logger.info("   - Verify that OPENAI_API_KEY and GEMINI_API_KEY are correctly set in your environment or .env file.")

    elif any(keyword in err_msg for keyword in ["connection", "timeout", "rate limit", "429"]):
        logger.info("%s", SUGGESTION_STR)
        logger.info("   Network connection timeout or API rate limits exceeded.")
        logger.info("   - Wait a moment and retry.")
        logger.info("   - Check if Ollama is running (`curl http://localhost:11434`) if you are using local models.")

    elif any(keyword in err_msg for keyword in ["model not found", "not found", "does not exist", "pull"]):
        logger.info("%s", SUGGESTION_STR)
        logger.info("   The specified local model was not found in Ollama.")
        logger.info("   - Run `ollama pull <model_name>` (e.g., `ollama pull qwen2.5:7b`) to download the required model.")
        logger.info("   - Check the MODEL_NAME settings in your config.yaml.")

    else:
        logger.info("%s", SUGGESTION_STR)
        logger.info(
            "   - Double-check your config.yaml configuration and ensure that local services "
            "(like Ollama) are fully operational."
        )
        logger.info("   - Review your log files or run with verbose logging for more details.")


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
        logger.info("Reusing active 'Generated' synthesis file: %s", existing_path.name)
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
    draft = re.sub(r'^(#{1,6})\s*#{1,6}\s+', r'\1 ', draft, flags=re.MULTILINE)
    final_state["draft_cv"] = draft
    company = final_state.get("target_organization_slug", "unknown-company")
    role = final_state.get("target_role", "unknown-role")
    track_val = final_state.get("target_track") or "engineering-management"
    location_val = final_state.get("target_region", "general")

    synthesis_content = f"""---
type: synthesis
title: "Tailored CV for {role} at {company}"
track: {track_val}
location_strategy: {location_val}
target_role: "{role}"
target_organization: [[{company}]]
status: Generated
created: {created_date}
updated: {today_str}
---

{draft}
"""

    out_path = save_outputs(args, draft, final_state, synthesis_path, synthesis_content)
    logger.info("Audit iterations required: %s", final_state.get("iteration_count"))
    compile_optional_formats(args, draft, out_path, final_state)

    ats_score = None
    ats_card = final_state.get("ats_scorecard")
    if isinstance(ats_card, dict) and "total_score" in ats_card:
        ats_score = ats_card["total_score"]

    pdf_file = str(out_path.with_suffix(".pdf")) if args.generate_pdf else None
    docx_file = str(out_path.with_suffix(".docx")) if args.generate_docx else None

    crm_record = {
        "company": company,
        "job_title": role,
        "date": today_str,
        "status": "drafted",
        "strategy": final_state.get("strategy_info", ""),
        "ats_score": ats_score,
        "output_markdown": str(out_path),
        "output_pdf": pdf_file,
        "output_docx": docx_file,
    }
    try:
        record_application(get_wiki_dir(), crm_record)
        logger.info("Application logged to CRM registry: %s", get_wiki_dir() / "wiki" / "applications.yaml")
    except Exception as ex:
        logger.warning("Failed to record application to CRM: %s", ex)


def _print_node_feedback(node_name: str, node_state: dict[str, Any]) -> None:
    """Logs user-facing status for an individual executed node."""
    if node_name == "analyzer":
        role = node_state.get("target_role", "N/A")
        company = node_state.get("target_organization_slug", "N/A")
        strategy = node_state.get("target_region", "N/A")
        track = node_state.get("target_track", "N/A")
        logger.info(
            "  🔍 [Node A: Analyzer] Completed -> Target Role: '%s', Org: '%s', Strategy: '%s', Track: '%s'",
            role, company, strategy, track
        )
    elif node_name == "retriever":
        exps = len(node_state.get("retrieved_experiences", []))
        skills = len(node_state.get("skills_entries", []))
        logger.info("  📦 [Node B: Retriever] Completed -> Selected %d experiences, %d skills", exps, skills)
    elif node_name == "drafter":
        draft_len = len(node_state.get("draft_cv", ""))
        logger.info("  ✍️ [Node C: Drafter] Completed -> Draft CV generated (%d chars)", draft_len)
    elif node_name == "refiner":
        feedback = node_state.get("refiner_feedback", "")
        status_msg = "Page budget exceeded -> routing to compressor" if feedback else "Page budget OK"
        logger.info("  📐 [Refiner Guard] %s", status_msg)
    elif node_name == "compressor":
        pass_num = node_state.get("compression_count", 1)
        logger.info("  🗜️ [Compressor] Applied compression pass %d/2", pass_num)
    elif node_name == "auditor":
        score = node_state.get("ats_scorecard", {}).get("total_score", "N/A")
        feedback = node_state.get("audit_feedback", "")
        iter_num = node_state.get("iteration_count", 1)
        verdict = "PASS" if "PASS" in feedback else "REWRITE REQUESTED"
        logger.info("  🧐 [Node D: Auditor] Iteration %d/3 -> ATS Score: %s/100 | Verdict: %s", iter_num, score, verdict)
        if "PASS" not in feedback and iter_num < 3:
            logger.warning("  🔄 Looping back to Drafter with auditor rewrite checklist...")


def _execute_pipeline_with_feedback(app: Any, inputs: dict[str, Any]) -> dict[str, Any]:
    """Executes the graph with live step-by-step progress logging."""
    logger.info("⏳ Executing Agentic Graph Pipeline (Streaming Step Feedback)...")
    final_state: dict[str, Any] = dict(inputs)

    for step_output in app.stream(inputs):
        for node_name, node_state in step_output.items():
            if isinstance(node_state, dict):
                final_state.update(node_state)
                _print_node_feedback(node_name, node_state)

    return final_state


def main() -> None:
    """
    Main entry point orchestrating state execution and error recovery.
    """
    args = parse_arguments()
    log_level = "DEBUG" if args.verbose else args.log_level
    _setup_logging(log_level)

    wiki_dir = get_wiki_dir()
    if not is_wiki_initialized(wiki_dir):
        logger.error(
            "The wiki at '%s' is not initialized. "
            "Please run: 'uv run kb-init --wiki-dir %s' first.",
            wiki_dir,
            wiki_dir,
        )
        return

    jd_content = _load_job_description(args)
    if jd_content is None:
        return

    # Use args.jd to print actual file name from argparse namespace
    jd_name = Path(args.jd).name
    logger.info("🚀 Initializing LangGraph CV Generator Pipeline against `%s`...", jd_name)
    app = build_graph()

    inputs = {
        "job_description": jd_content,
        "job_description_raw": jd_content,
        "iteration_count": 0,
        "compression_count": 0,
        "max_iterations": 3,
        "strategy_override": args.strategy,
        "track_override": args.track,
        "interactive": args.interactive,
    }

    try:
        final_state = _execute_pipeline_with_feedback(app, inputs)
    except Exception as e:
        _triage_pipeline_exception(e)
        logger.info("🧹 Gracefully exiting...")
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
