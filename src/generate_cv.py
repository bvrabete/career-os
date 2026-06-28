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
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write clean draft to specified path
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(draft)
        print(f"\n✅ Build complete! Clean Markdown saved to {out_path}")

        # Save Context (Graph State) for debugging
        context_path = out_path.with_name(f"{out_path.stem}_context.json")
        state_to_save = {k: v for k, v in final_state.items() if k != "draft_cv"}
        with open(context_path, "w", encoding="utf-8") as f:
            json.dump(state_to_save, f, indent=2)
        print(f"📦 Context/State backed up to {context_path}")

        # Also write archived duplicate with frontmatter tracking to LLM-Wiki Synthesis folder
        try:
            with open(synthesis_path, "w", encoding="utf-8") as f:
                f.write(synthesis_content)
            print(f"🗂️ CRM Synthesis copy archived to {synthesis_path}")
        except Exception as e:
            print(f"⚠️ Failed to write CRM synthesis copy: {e}")
    else:
        # Default: Write the frontmatter-tracked file directly to LLM-Wiki Synthesis directory
        out_path = synthesis_path
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

    jd_path = Path(args.jd)
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
    final_state = app.invoke(initial_state)

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
