import tempfile
from pathlib import Path
from docx import Document
from docx.shared import RGBColor

from docx_generator import (
    generate_docx,
    normalize_markdown_tables,
    add_hyperlink,
    add_formatted_runs,
    _process_part,
    _add_title_header,
    _add_section_header,
    _add_subsection_header,
    _add_role_header,
    _add_horizontal_rule,
    _add_bullet_item,
    _add_standard_paragraph
)


class TestDocxGenerator:

    def setup_method(self) -> None:
        self.doc = Document()
        self.color_primary = RGBColor(15, 34, 64)
        self.color_secondary = RGBColor(80, 80, 80)
        self.color_text = RGBColor(30, 30, 30)

    def test_add_hyperlink(self) -> None:
        p = self.doc.add_paragraph()
        add_hyperlink(p, "https://example.com", "Example Link")
        assert len(p.runs) == 0 # Hyperlink run is appended under OxmlElement child nodes
        assert "Example Link" in p._p.xml

    def test_process_part_styles(self) -> None:
        p = self.doc.add_paragraph()
        _process_part(p, "***bold italic***")
        assert p.runs[0].text == "bold italic"
        assert p.runs[0].bold
        assert p.runs[0].italic

        p2 = self.doc.add_paragraph()
        _process_part(p2, "**bold**")
        assert p2.runs[0].text == "bold"
        assert p2.runs[0].bold

        p3 = self.doc.add_paragraph()
        _process_part(p3, "*italic*")
        assert p3.runs[0].text == "italic"
        assert p3.runs[0].italic

        p4 = self.doc.add_paragraph()
        _process_part(p4, "[link](https://test.org)")
        assert "link" in p4._p.xml

        p5 = self.doc.add_paragraph()
        _process_part(p5, "[broken_link")
        assert p5.runs[0].text == "[broken_link"

    def test_add_formatted_runs(self) -> None:
        p = self.doc.add_paragraph()
        add_formatted_runs(p, "Standard text **bold** and *italic* and [link](https://test.org).")
        assert len(p.runs) >= 4

    def test_add_headers(self) -> None:
        _add_title_header(self.doc, "Main Title", self.color_primary)
        _add_section_header(self.doc, "Section Header", self.color_primary)
        _add_subsection_header(self.doc, "Subsection Header", self.color_primary)
        _add_role_header(self.doc, "Role Header", self.color_primary)

        assert self.doc.paragraphs[0].text == "Main Title"
        assert self.doc.paragraphs[1].text == "Section Header"
        assert self.doc.paragraphs[2].text == "Subsection Header"
        assert self.doc.paragraphs[3].text == "Role Header"

    def test_add_horizontal_rule(self) -> None:
        _add_horizontal_rule(self.doc)
        assert "_____" in self.doc.paragraphs[0].text

    def test_add_bullet_item(self) -> None:
        _add_bullet_item(self.doc, "Bullet text **bold**", self.color_text)
        p = self.doc.paragraphs[0]
        style_name = getattr(p.style, "name", None)
        assert style_name == "List Bullet"

    def test_add_standard_paragraph(self) -> None:
        _add_standard_paragraph(self.doc, "Standard text line", 1, self.color_secondary, self.color_text)
        assert self.doc.paragraphs[0].text == "Standard text line"

    def test_add_standard_paragraph_contact(self) -> None:
        _add_standard_paragraph(self.doc, "London, UK | +44 | email@address.com", 2, self.color_secondary, self.color_text)
        p = self.doc.paragraphs[0]
        # Should center align contact-like lines at indices under 8
        assert p.alignment == 1 # WD_ALIGN_PARAGRAPH.CENTER is 1

    def test_generate_docx_success(self) -> None:
        test_md = """# Title
London, UK | +44 | email@address.com

---

## Experience
### Job Title - Company (Present)
- Bullets go here **bold**
- Bullet 2 *italic* and [link](https://google.com)

#### Subrole Header
Paragraph here."""

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_path = Path(tmp_dir) / "output.docx"
            res = generate_docx(test_md, str(out_path))
            assert res
    def test_generate_docx_themed(self) -> None:
        test_md = "# Executive CV\n\n## Summary\n- High impact leadership."
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_exec = Path(tmp_dir) / "exec.docx"
            out_comp = Path(tmp_dir) / "comp.docx"
            assert generate_docx(test_md, str(out_exec), template="executive")
            assert generate_docx(test_md, str(out_comp), template="compact")
            assert out_exec.exists()
            assert out_comp.exists()

    def test_generate_docx_failure(self) -> None:
        # Invalid output location (e.g. writing to empty string filename or locked path)
        res = generate_docx("# Simple MD", "")
        assert not res

    def test_cli_directory_out(self) -> None:
        from unittest.mock import patch
        from generate_document_cli import main as doc_cli_main
        test_md = "# Title\n\nContent"
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_file = Path(tmp_dir) / "My_CV.md"
            input_file.write_text(test_md, encoding="utf-8")
            out_dir = Path(tmp_dir) / "docx_outputs"
            out_dir.mkdir(parents=True, exist_ok=True)

            with patch("sys.argv", ["doc-gen", "--input", str(input_file), "--out", str(out_dir), "--format", "docx"]):
                doc_cli_main()

            expected_file = out_dir / "My_CV.docx"
            assert expected_file.exists()

    def test_normalize_markdown_tables(self) -> None:
        raw_md = (
            "## Key Skills\n"
            "| Cloud Strategy | DevOps |\n"
            "| :--- | :--- |\n"
            "| Multi-Cloud (AWS, Azure) | Kubernetes |\n"
            "| FinOps | Terraform |\n\n"
            "| Languages |\n"
            "| :--- |\n"
            "| **English:** Proficient (C2) |\n"
            "| **Romanian:** Native |\n"
        )
        normalized = normalize_markdown_tables(raw_md)
        assert "| :--- |" not in normalized
        assert "- **Cloud Strategy:** Multi-Cloud (AWS, Azure), FinOps" in normalized
        assert "- **DevOps:** Kubernetes, Terraform" in normalized
        assert "- **English:** Proficient (C2)" in normalized
        assert "- **Romanian:** Native" in normalized
