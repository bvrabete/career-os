"""
Standalone Markdown to PDF Generator Command Line Interface.
Allows converting compiled CV Markdown files into styled PDFs.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from pdf_generator import generate_pdf

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

logger = logging.getLogger(__name__)


def main() -> None:
    """
    Main execution routine for the Markdown to PDF generator CLI.
    """
    parser = argparse.ArgumentParser(description="Standalone Markdown to PDF Generator")
    parser.add_argument("--input", required=True, help="Path to the Markdown file")
    parser.add_argument("--out", help="Output path for the PDF (defaults to input path with .pdf extension)")
    parser.add_argument("--template", help="Path to the CSS template (overrides default or detected template)")
    
    args = parser.parse_args()
    
    input_path = validate_path(args.input)
    if not input_path.exists():
        print(f"❌ Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)
        
    md_content = input_path.read_text(encoding="utf-8")
    
    # Resolve output path
    if args.out:
        pdf_path = validate_path(args.out)
    else:
        pdf_path = validate_path(input_path.with_suffix(".pdf"))
        
    # Resolve template
    template_path = args.template
    if template_path:
        template_path = str(validate_path(template_path))
    else:
        # Try to detect template from context.json if it exists
        context_path = input_path.with_name(f"{input_path.stem}_context.json")
        if context_path.exists():
            try:
                context_data = json.loads(context_path.read_text(encoding="utf-8"))
                template_path = context_data.get("pdf_template")
                if template_path:
                    print(f"✨ Detected template from context: {template_path}")
            except Exception as e:
                print(f"⚠️ Failed to parse context for template detection: {e}", file=sys.stderr)

    success = generate_pdf(md_content, str(pdf_path), template_path)
    
    if success:
        print(f"✅ PDF generated successfully: {pdf_path}")
    else:
        print("❌ PDF generation failed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    # Configure logging for standalone execution
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    main()
