import os
import logging
import markdown2
from pathlib import Path
from weasyprint import HTML, CSS

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def generate_pdf(md_content: str, output_path: str, css_template_path: str = None):
    """
    Converts Markdown content to a PDF using WeasyPrint and an optional CSS template.
    """
    logging.info(f"Generating PDF for {output_path}...")
    
    # 1. Convert Markdown to HTML
    # Use extras for common MD features (tables, code blocks, etc.)
    html_body = markdown2.markdown(md_content, extras=["fenced-code-blocks", "tables", "header-ids"])
    
    # 2. Wrap in basic HTML structure
    full_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Curriculum Vitae</title>
    </head>
    <body>
        <div class="cv-container">
            {html_body}
        </div>
    </body>
    </html>
    """
    
    # 3. Prepare CSS
    stylesheets = []
    if css_template_path:
        css_path = Path(css_template_path)
        if not css_path.exists():
            # Try to resolve relative to the engine package location
            fallback_path = Path(__file__).parent.parent / css_template_path
            if fallback_path.exists():
                css_path = fallback_path

        if css_path.exists():
            stylesheets.append(CSS(filename=str(css_path)))
            logging.info(f"Using CSS template: {css_path}")
        else:
            logging.warning(f"CSS template not found at {css_template_path}, using default styling.")
            
    # 4. Generate PDF
    try:
        HTML(string=full_html, base_url=os.getcwd()).write_pdf(output_path, stylesheets=stylesheets)
        logging.info(f"Successfully saved PDF to {output_path}")
        return True
    except Exception as e:
        logging.error(f"Failed to generate PDF: {str(e)}")
        return False

if __name__ == "__main__":
    # Test run
    test_md = "# Test CV\n\nThis is a test PDF generation.\n\n- Point 1\n- Point 2"
    generate_pdf(test_md, "test_cv.pdf", "templates/base.css")
