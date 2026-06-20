import argparse
import logging
import sys
import json
from pathlib import Path
from pdf_generator import generate_pdf

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main():
    parser = argparse.ArgumentParser(description="Standalone Markdown to PDF Generator")
    parser.add_argument("--input", required=True, help="Path to the Markdown file")
    parser.add_argument("--out", help="Output path for the PDF (defaults to input path with .pdf extension)")
    parser.add_argument("--template", help="Path to the CSS template (overrides default or detected template)")
    
    args = parser.parse_args()
    
    input_path = Path(args.input)
    if not input_path.exists():
        logging.error(f"Input file not found: {args.input}")
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
                    logging.info(f"Detected template from context: {template_path}")
            except Exception as e:
                logging.warning(f"Failed to parse context for template detection: {e}")

    success = generate_pdf(md_content, str(pdf_path), template_path)
    
    if success:
        logging.info(f"PDF generated successfully: {pdf_path}")
    else:
        logging.error("PDF generation failed.")
        sys.exit(1)

if __name__ == "__main__":
    main()
