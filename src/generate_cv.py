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


def main() -> None:
    """
    Main entry point orchestrating state execution and error recovery.
    """
    args = parse_arguments()
    
    # Simple direct file logging, no extra complex configurations
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    file_handler = logging.FileHandler(log_dir / "generation_run.log", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    root_logger.addHandler(file_handler)
    
    # Console handler (warnings & errors only to keep console clean)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    root_logger.addHandler(console_handler)

    # Suppress httpx and third-party chatty logs in the file too
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    if args.wiki_dir:
        os.environ["LLM_WIKI_DIR"] = args.wiki_dir

    jd_path = validate_path(args.jd)
    if not jd_path.exists():
        print(f"❌ Error: Job Description file not found at {jd_path}")
        return

    with open(jd_path, "r", encoding="utf-8") as f:
        jd_content = f.read()

    print(f"🚀 Initializing LangGraph CV Generator Pipeline against `{jd_path.name}`...")
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
        err_msg = str(e).lower()
        print(f"\n❌ Pipeline failed with exception: {e}")
        
        # User-friendly triage guide
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
            
        print("\n🧹 Gracefully exiting...")
        sys.exit(1)

    draft = final_state.get("draft_cv", "")

    company: str = final_state.get("target_organization_slug", "unknown-company")
    role: str = final_state.get("target_role", "unknown-role")

    company_clean = "".join(c if c.isalnum() or c in "-_" else "_" for c in company).lower()
    role_clean = "".join(c if c.isalnum() or c in "-_" else "_" for c in role).lower()
    today_str = datetime.now().date().isoformat()

    synthesis_filename = f"synthesis-cv-{company_clean}-{role_clean}-{today_str}.md"
    synthesis_dir = get_wiki_dir() / "wiki" / "synthesis"
    synthesis_dir.mkdir(parents=True, exist_ok=True)
    synthesis_path = synthesis_dir / synthesis_filename

    track_val = final_state.get("target_region", "general").upper()

    synthesis_content = f"""---
type: synthesis
title: "Tailored CV for {role} at {company}"
track: {track_val}
target_role: "{role}"
target_organization: [[{company}]]
status: Generated
created: {today_str}
updated: {today_str}
---

{draft}
"""

    out_path = save_outputs(args, draft, final_state, synthesis_path, synthesis_content)

    print(f"🔄 Audit iterations required: {final_state.get('iteration_count')}")

    compile_optional_formats(args, draft, out_path, final_state)


if __name__ == "__main__":
    main()
