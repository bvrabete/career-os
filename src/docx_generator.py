"""
Module for generating Word Documents (.docx) from Markdown content.
Uses pure-Python python-docx library to ensure 100% OS-independence.
"""

import logging
from pathlib import Path
import re
from typing import Any

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from utils import clean_markdown_wrapper as _clean_markdown_wrapper

logger = logging.getLogger(__name__)


def _strip_yaml_frontmatter(content: str) -> str:
    """Strip leading YAML frontmatter blocks (--- ... ---) from markdown content before DOCX rendering."""
    remaining = content.strip()
    while remaining.startswith("---"):
        lines = remaining.splitlines()
        if len(lines) < 2:
            break
        closing_idx = -1
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                closing_idx = idx
                break
        if closing_idx == -1:
            break
        candidate_fm = "\n".join(lines[1:closing_idx])
        if ":" not in candidate_fm:
            break
        remaining = "\n".join(lines[closing_idx + 1:]).strip()
    return remaining


def add_hyperlink(paragraph: Any, url: str, text: str) -> Any:
    """
    Helper function for adding XML hyperlinks (clickable links) to a paragraph
    using standard RELATIONSHIP_TYPE in python-docx.
    """
    part = paragraph.part
    r_id = part.relate_to(url, RT.HYPERLINK, is_external=True)

    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)

    new_run = OxmlElement("w:r")
    r_pr = OxmlElement("w:rPr")

    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0056B3")
    r_pr.append(color)

    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    r_pr.append(u)

    new_run.append(r_pr)

    text_node = OxmlElement("w:t")
    text_node.text = text
    new_run.append(text_node)

    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)
    return hyperlink


def _process_part(paragraph: Any, part: str) -> None:
    """Applies inline formatting styles to a specific token part."""
    if part.startswith("***") and part.endswith("***"):
        run = paragraph.add_run(part[3:-3])
        run.bold = True
        run.italic = True
    elif part.startswith("**") and part.endswith("**"):
        run = paragraph.add_run(part[2:-2])
        run.bold = True
    elif part.startswith("*") and part.endswith("*"):
        run = paragraph.add_run(part[1:-1])
        run.italic = True
    elif part.startswith("[") and "]" in part and part.endswith(")"):
        match = re.match(r"\[([^\]]*)\]\(([^\)]*)\)", part)
        if match:
            link_text, url = match.groups()
            add_hyperlink(paragraph, url, link_text)
        else:
            paragraph.add_run(part)
    else:
        paragraph.add_run(part)


def add_formatted_runs(paragraph: Any, text: str) -> None:
    """
    Parses and appends inline formatting (bold, italic, links) to a paragraph.
    """
    pattern = re.compile(r"(\*\*\*[^\*]*\*\*\*|\*\*[^\*]*\*\*|\*[^\*]*\*|\[[^\]]*\]\([^\)]*\))")
    parts = pattern.split(text)

    for part in parts:
        if part:
            _process_part(paragraph, part)


def _add_title_header(doc: Any, text: str, color_primary: RGBColor, title_size: Any = Pt(22)) -> None:
    """Formats and adds the main title to the document."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(4)

    run = p.add_run(text)
    run.bold = True
    run.font.name = "Calibri"
    run.font.size = title_size
    run.font.color.rgb = color_primary


def _add_section_header(doc: Any, text: str, color_primary: RGBColor, heading_size: Any = Pt(13)) -> None:
    """Formats and adds a section header (Heading 2) to the document."""
    p = doc.add_heading(level=2)
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.left_indent = Inches(0)

    run = p.add_run(text)
    run.bold = True
    run.font.name = "Calibri"
    run.font.size = heading_size
    run.font.color.rgb = color_primary


def _add_subsection_header(doc: Any, text: str, color_primary: RGBColor) -> None:
    """Formats and adds a subsection header (Heading 3) to the document."""
    p = doc.add_paragraph()
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.space_before = Pt(9)
    p.paragraph_format.space_after = Pt(2)

    run = p.add_run(text)
    run.bold = True
    run.italic = True
    run.font.name = "Calibri"
    run.font.size = Pt(11.5)
    run.font.color.rgb = color_primary


def _add_role_header(doc: Any, text: str, color_primary: RGBColor) -> None:
    """Formats and adds a sub-header or role header to the document."""
    p = doc.add_paragraph()
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(2)

    run = p.add_run(text)
    run.bold = True
    run.font.name = "Calibri"
    run.font.size = Pt(10.5)
    run.font.color.rgb = color_primary


def _add_horizontal_rule(doc: Any) -> None:
    """Adds an elegant, centered horizontal rule separator."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = Pt(1)

    run = p.add_run("______________________________________________________________________")
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(210, 210, 210)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER


def _add_bullet_item(
    doc: Any, text: str, color_text: RGBColor, body_size: Any = Pt(10.5), space_after: Any = Pt(3)
) -> None:
    """Formats and adds a single list bullet item to the document."""
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = space_after
    p.paragraph_format.line_spacing = 1.2

    add_formatted_runs(p, text)
    for run in p.runs:
        run.font.name = "Calibri"
        run.font.size = body_size
        if not run.font.color.rgb:
            run.font.color.rgb = color_text


def _add_standard_paragraph(
    doc: Any,
    line: str,
    idx: int,
    color_secondary: RGBColor,
    color_text: RGBColor,
    body_size: Any = Pt(10.5),
) -> None:
    """Formats and adds a standard body paragraph or contact info line."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.2

    is_contact_line = (
        any(kw in line.lower() for kw in ["@ ", "phone", "linkedin", "address", "email", "github"])
        or "|" in line
        or "  " in line
    )

    if is_contact_line and idx < 8:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(8)

    add_formatted_runs(p, line)
    for run in p.runs:
        run.font.name = "Calibri"
        run.font.size = Pt(9.5) if is_contact_line else body_size
        if is_contact_line:
            run.font.color.rgb = color_secondary
        elif not run.font.color.rgb:
            run.font.color.rgb = color_text


def _resolve_docx_theme(template: str | None) -> dict[str, Any]:
    """Resolves margins, color tokens, and font sizes for the given DOCX template."""
    name = (template or "base").lower()
    if "compact" in name:
        return {
            "margin": Inches(0.55),
            "primary": RGBColor(26, 54, 93),
            "secondary": RGBColor(74, 85, 104),
            "text": RGBColor(45, 55, 72),
            "body_size": Pt(9.5),
            "title_size": Pt(18),
            "heading_size": Pt(11.5),
            "space_after": Pt(2),
        }
    if "executive" in name:
        return {
            "margin": Inches(0.75),
            "primary": RGBColor(15, 34, 64),
            "secondary": RGBColor(90, 101, 120),
            "text": RGBColor(45, 55, 72),
            "body_size": Pt(10.5),
            "title_size": Pt(22),
            "heading_size": Pt(13),
            "space_after": Pt(3),
        }
    return {
        "margin": Inches(0.75),
        "primary": RGBColor(19, 56, 75),
        "secondary": RGBColor(102, 109, 137),
        "text": RGBColor(40, 40, 40),
        "body_size": Pt(10.0),
        "title_size": Pt(20),
        "heading_size": Pt(12.5),
        "space_after": Pt(2.5),
    }


def _render_docx_line(doc: Any, line: str, idx: int, theme: dict[str, Any]) -> None:
    """Render a single cleaned Markdown line into the python-docx Document."""
    color_primary = theme["primary"]
    color_secondary = theme["secondary"]
    color_text = theme["text"]
    body_size = theme["body_size"]
    title_size = theme["title_size"]
    heading_size = theme["heading_size"]
    space_after = theme["space_after"]

    if line.startswith("# "):
        _add_title_header(doc, line[2:].strip(), color_primary, title_size=title_size)
    elif line.startswith("## "):
        _add_section_header(doc, line[3:].strip(), color_primary, heading_size=heading_size)
    elif line.startswith("### "):
        _add_subsection_header(doc, line[4:].strip(), color_primary)
    elif line.startswith("#### "):
        _add_role_header(doc, line[5:].strip(), color_primary)
    elif line.startswith("---") or (line.startswith("***") and len(line) >= 3 and not line.strip("* -")):
        _add_horizontal_rule(doc)
    elif line.startswith(("- ", "* ", "+ ")):
        _add_bullet_item(doc, line[2:].strip(), color_text, body_size=body_size, space_after=space_after)
    else:
        _add_standard_paragraph(doc, line, idx, color_secondary, color_text, body_size=body_size)


def generate_docx(md_content: str, output_path: str, template: str | None = None) -> bool:
    """
    Converts Markdown content to a Word Document (.docx) using pure-Python python-docx library,
    ensuring 100% OS-independence (no Pandoc system binary required).
    Supports selectable themes ('base', 'executive', 'compact').
    """
    logger.info(f"Generating pure-Python DOCX for {output_path} (theme: {template or 'base'})...")
    try:
        doc = docx.Document()
        theme = _resolve_docx_theme(template)

        for section in doc.sections:
            section.top_margin = theme["margin"]
            section.bottom_margin = theme["margin"]
            section.left_margin = theme["margin"]
            section.right_margin = theme["margin"]

        cleaned_md = _strip_yaml_frontmatter(_clean_markdown_wrapper(md_content))
        lines = cleaned_md.splitlines()

        for idx, raw_line in enumerate(lines):
            line = raw_line.strip()
            if line:
                _render_docx_line(doc, line, idx, theme)

        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(out_path))
        logger.info(f"Successfully saved pure-Python DOCX to {output_path}")
        return True

    except Exception as e:
        logger.exception(f"Failed to generate DOCX via python-docx: {str(e)}")
        return False
