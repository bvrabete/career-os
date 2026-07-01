import argparse
from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Any
import warnings

from generation import build_graph

# Suppress annoying logging from httpx if possible
logging.getLogger("httpx").setLevel(logging.WARNING)

SUGGESTION_STR = "💡 Suggestion:"


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


def parse_arguments() -> argparse.Namespace:
    """
    Parses command-line arguments for the CV generator.
    """
    parser = argparse.ArgumentParser(description="Agentic AI CV Generator")
    parser.add_argument("--jd", required=True,
                        help="Path to the Job Description text file")
    parser.add_argument("--out", default=None,
                        help="Output path for the Markdown CV (defaults to LLM-Wiki synthesis folder if omitted)")
    parser.add_argument(
        "--wiki-dir", help="Path to the llm-wiki folder (defaults to LLM_WIKI_DIR env var or 'llm-wiki')")
    parser.add_argument("--strategy", help="Strategy key slug to override analyzer's suggested strategy")
    parser.add_argument("--generate-pdf", action="store_true", help="Automatically generate PDF CV from Markdown using final stylesheet")
    parser.add_argument("--generate-docx", action="store_true", help="Automatically generate Word (docx) CV from Markdown")
    return parser.parse_args()


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
            json.dump(state_to_save, f, indent=2)
        print(f"📦 Context/State backed up to {context_path}")

        # Also write archived duplicate with frontmatter tracking to LLM-Wiki Synthesis folder
        try:
            safe_synthesis_path = validate_path(synthesis_path)
            with open(safe_synthesis_path, "w", encoding="utf-8") as f:
                f.write(synthesis_content)
            print(f"🗂️ CRM Synthesis copy archived to {synthesis_path}")
        except Exception as e:
            print(f"⚠️ Failed to write CRM synthesis copy: {e}")
    else:
        # Default: Write the frontmatter-tracked file directly to LLM-Wiki Synthesis directory
        out_path = validate_path(synthesis_path)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(synthesis_content)
        print(f"\n✅ Build complete! Frontmatter-tracked CV saved directly to LLM-Wiki: {out_path}")
    
    return out_path


def compile_optional_formats(
    args: argparse.Namespace,
    draft: str,
    out_path: Path,
    final_state: dict[str, Any]
) -> None:
    """
    Compiles PDF and DOCX files if requested via arguments.
    """
    # Generate PDF if requested
    if args.generate_pdf:
        try:
            from pdf_generator import generate_pdf
            pdf_template = final_state.get("pdf_template", "templates/base.css")
            pdf_out_path = out_path.with_suffix(".pdf")
            print(f"📄 Compiling beautiful PDF using template: {pdf_template}...")
            # Note: For PDF compilation, compile using the clean draft (without raw YAML frontmatter)
            success = generate_pdf(draft, str(pdf_out_path), pdf_template)
            if success:
                print(f"🎨 PDF saved successfully to {pdf_out_path}")
            else:
                print("❌ PDF generation failed.")
        except Exception as e:
            print(f"❌ Error during PDF generation: {e}")

    # Generate DOCX if requested
    if args.generate_docx:
        try:
            from docx_generator import generate_docx
            docx_out_path = out_path.with_suffix(".docx")
            print("📄 Compiling Word document (docx) CV...")
            success = generate_docx(draft, str(docx_out_path))
            if success:
                print(f"🎨 Word (docx) saved successfully to {docx_out_path}")
            else:
                print("❌ Word (docx) generation failed.")
        except Exception as e:
            print(f"❌ Error during Word (docx) generation: {e}")


def main() -> None:
    """
    Main entry point for CV generator.
    """
    args = parse_arguments()

    import os
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

    initial_state: dict[str, Any] = {
        "job_description": jd_content,
        "iteration_count": 0
    }
    if args.strategy:
        initial_state["strategy_override"] = args.strategy

    print("⏳ Running pipeline using configured models. This may take a few minutes...\n")
    try:
        final_state = app.invoke(initial_state)
    except Exception as e:
        print("\n❌ Pipeline execution failed with an unhandled exception:")
        print(f"   Error: {e}\n")
        
        err_msg = str(e).lower()
        
        # Analyze the error and provide actionable suggestions
        if any(keyword in err_msg for keyword in ["resource_exhausted", "429", "billing", "credits", "quota", "prepayment"]):
            print(SUGGESTION_STR)
            print("   The cloud API rate limit or billing/prepayment credits have been exhausted.")
            print("   - To continue running locally & offline, ensure you configure the step to use a local model.")
            print("     Update the corresponding step (e.g., DRAFTING) inside config.yaml to:")
            print("       TYPE: \"ollama\"")
            print("       MODEL_NAME: \"qwen2.5:7b\"")
            print("   - Alternatively, check your cloud provider console (e.g., Google AI Studio or OpenAI dashboard) to top up credits.")
            
        elif any(keyword in err_msg for keyword in ["api_key", "api key", "apikey", "unauthorized", "credentials", "invalid_api_key", "api-key"]):
            print(SUGGESTION_STR)
            print("   There is an issue with your API credentials.")
            print("   - Check that your .env file contains the correct keys: OPENAI_API_KEY or GEMINI_API_KEY.")
            print("   - To run 100% offline without API keys, update config.yaml to use TYPE: \"ollama\" for all steps.")
            
        elif any(keyword in err_msg for keyword in ["connection", "refused", "connect", "11434", "localhost", "httpx"]):
            print(SUGGESTION_STR)
            print("   Could not connect to the local Ollama instance.")
            print("   - Verify that Ollama is currently running on your system (e.g., run `ollama serve` in a terminal).")
            print("   - Check that the OLLAMA_BASE_URL in config.yaml is correct (default: http://localhost:11434).")
            
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
        import sys
        sys.exit(1)

    draft = final_state.get("draft_cv", "")

    # Retrieve synthesis paths and metadata
    from kb_config import get_wiki_dir

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
status: Applied
applied_date: {today_str}
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
