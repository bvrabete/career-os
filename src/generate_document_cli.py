"""
Standalone Markdown to PDF/DOCX Document Generator Command Line Interface.
Allows converting compiled CV Markdown files into styled PDF or Word (.docx) documents.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from docx_generator import generate_docx
from pdf_generator import generate_pdf
from utils import validate_path

logger = logging.getLogger(__name__)


def main() -> None:
    """
    Main execution routine for the Markdown to Document generator CLI.
    """
    parser = argparse.ArgumentParser(description="Standalone Markdown to PDF/DOCX Document Generator")
    parser.add_argument("--input", required=True, help="Path to the Markdown file")
    parser.add_argument(
        "--out",
        help="Output path for the compiled document (defaults to input path with designated extension)",
    )
    parser.add_argument(
        "--format",
        choices=["pdf", "docx"],
        help="Output format (defaults to 'pdf' or is inferred from the --out extension)",
    )
    parser.add_argument(
        "--template",
        help="Path to the CSS template (only applicable for PDF format; overrides default/detected templates)",
    )
    parser.add_argument(
        "--wiki-dir",
        "--llm-wiki",
        dest="wiki_dir",
        help="Path to the llm-wiki folder (defaults to LLM_WIKI_DIR env var or 'llm-wiki')",
    )

    args = parser.parse_args()

    if args.wiki_dir:
        os.environ["LLM_WIKI_DIR"] = args.wiki_dir

    # Validate input path
    try:
        input_path = validate_path(args.input)
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)

    if not input_path.exists():
        print(f"❌ Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    # Determine format
    doc_format = args.format
    if not doc_format:
        if args.out:
            out_suffix = Path(args.out).suffix.lower()
            if out_suffix == ".docx":
                doc_format = "docx"
            elif out_suffix == ".pdf":
                doc_format = "pdf"
            else:
                doc_format = "pdf"
        else:
            doc_format = "pdf"

    # Resolve output path
    try:
        if args.out:
            output_path = validate_path(args.out)
        else:
            output_path = validate_path(input_path.with_suffix(f".{doc_format}"))
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)

    md_content = input_path.read_text(encoding="utf-8")

    if doc_format == "pdf":
        # Resolve CSS template
        template_path = args.template
        if template_path:
            try:
                template_path = str(validate_path(template_path))
            except ValueError as e:
                print(f"❌ {e}", file=sys.stderr)
                sys.exit(1)
        else:
            # Try to detect template from context.json if it exists
            context_path = input_path.with_name(f"{input_path.stem}_context.json")
            if context_path.exists():
                try:
                    context_data = json.loads(context_path.read_text(encoding="utf-8"))
                    template_path = context_data.get("pdf_template")
                    if template_path:
                        print(f"✨ Detected PDF template from context: {template_path}")
                except Exception as e:
                    print(f"⚠️ Failed to parse context for template detection: {e}", file=sys.stderr)

        success = generate_pdf(md_content, str(output_path), template_path)
    else:
        if args.template:
            print("⚠️ Warning: --template is ignored for Word Document (.docx) generation.", file=sys.stderr)
        success = generate_docx(md_content, str(output_path))

    if success:
        print(f"✅ Document generated successfully: {output_path}")
    else:
        print(f"❌ {doc_format.upper()} generation failed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    # Configure logging for standalone execution
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    main()
