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
    
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"❌ Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)
        
    md_content = input_path.read_text(encoding="utf-8")
    
    # Resolve output path
    if args.out:
        pdf_path = Path(args.out)
    else:
        pdf_path = input_path.with_suffix(".pdf")
        
    # Resolve template
    template_path = args.template
    if not template_path:
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
