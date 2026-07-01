"""
Module for generating high-quality PDFs from Markdown content
using WeasyPrint and customizable CSS templates.
"""

import logging
import os
from pathlib import Path

import markdown2
from weasyprint import CSS, HTML

logger = logging.getLogger(__name__)


def _resolve_css_path(css_template_path: str) -> Path | None:
    """
    Resolves the CSS template path by checking several potential locations,
    prioritizing the external wiki directory, and falling back to the repository.
    """
    css_path = Path(css_template_path)
    if css_path.exists():
        return css_path

    # Try to resolve relative to the external wiki directory with higher priority
    try:
        from kb_config import get_wiki_dir
        wiki_dir = get_wiki_dir()
        # Check directly in the wiki dir, under wiki_dir/templates, or simple file name under templates
        paths_to_try = [
            wiki_dir / css_template_path,
            wiki_dir / "templates" / css_template_path,
            wiki_dir / "templates" / Path(css_template_path).name,
        ]
        for p in paths_to_try:
            if p.exists():
                return p
    except Exception as e:
        logger.debug(f"Could not resolve via external wiki_dir: {e}")

    # Fallback to repository location if still not found
    fallback_path = Path(__file__).parent.parent / css_template_path
    if fallback_path.exists():
        return fallback_path

    fallback_name_path = Path(__file__).parent.parent / "templates" / Path(css_template_path).name
    if fallback_name_path.exists():
        return fallback_name_path

    return None


def generate_pdf(md_content: str, output_path: str, css_template_path: str | None = None) -> bool:
    """
    Converts Markdown content to a PDF using WeasyPrint and an optional CSS template.
    
    Args:
        md_content: Markdown source string.
        output_path: Path where the resulting PDF will be saved.
        css_template_path: Optional path to a CSS template file for custom styling.
        
    Returns:
        bool: True if generation was successful, False otherwise.
    """
    logger.info(f"Generating PDF for {output_path}...")

    # 1. Convert Markdown to HTML
    # Use extras for common MD features (tables, code blocks, etc.)
    html_body: str = markdown2.markdown(
        md_content, extras=["fenced-code-blocks", "tables", "header-ids"])

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
    stylesheets: list[CSS] = []
    if css_template_path:
        css_path = _resolve_css_path(css_template_path)
        if css_path:
            stylesheets.append(CSS(filename=str(css_path)))
            logger.info(f"Using CSS template: {css_path}")
        else:
            logger.warning(
                f"CSS template not found at {css_template_path}, using default styling.")

    # 4. Generate PDF
    try:
        HTML(string=full_html, base_url=os.getcwd()).write_pdf(
            output_path, stylesheets=stylesheets)
        logger.info(f"Successfully saved PDF to {output_path}")
        return True
    except Exception as e:
        logger.exception(f"Failed to generate PDF: {str(e)}")
        return False


if __name__ == "__main__":
    # Test run
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    test_md = "# Test CV\n\nThis is a test PDF generation.\n\n- Point 1\n- Point 2"
    generate_pdf(test_md, "test_cv.pdf", "templates/base.css")
