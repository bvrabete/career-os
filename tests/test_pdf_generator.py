"""
Unit tests for pdf_generator.py and docx_generator.py.
"""

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import os

from pdf_generator import (
    _clean_markdown_wrapper as pdf_clean,
    generate_pdf,
    _extract_frontmatter,
    _build_header_html,
)
from docx_generator import _clean_markdown_wrapper as docx_clean, generate_docx


class TestPdfAndDocxGenerator(unittest.TestCase):
    def test_clean_markdown_wrapper(self):
        """Test stripping markdown code blocks from content."""
        wrapped_md_1 = "```markdown\n# Brad Vrabete\nSome content\n```"
        wrapped_md_2 = "```md\n# Brad Vrabete\nSome content\n```"
        wrapped_md_3 = "```\n# Brad Vrabete\nSome content\n```"
        unwrapped_md = "# Brad Vrabete\nSome content"
        mixed_md = "```python\nprint('hello')\n```\n# Brad\n```bash\necho\n```"

        self.assertEqual(pdf_clean(wrapped_md_1), "# Brad Vrabete\nSome content")
        self.assertEqual(pdf_clean(wrapped_md_2), "# Brad Vrabete\nSome content")
        self.assertEqual(pdf_clean(wrapped_md_3), "# Brad Vrabete\nSome content")
        self.assertEqual(pdf_clean(unwrapped_md), "# Brad Vrabete\nSome content")
        self.assertEqual(pdf_clean(mixed_md), "```python\nprint('hello')\n```\n# Brad\n```bash\necho\n```")

        # Do the same for docx_clean
        self.assertEqual(docx_clean(wrapped_md_1), "# Brad Vrabete\nSome content")
        self.assertEqual(docx_clean(wrapped_md_2), "# Brad Vrabete\nSome content")
        self.assertEqual(docx_clean(wrapped_md_3), "# Brad Vrabete\nSome content")
        self.assertEqual(docx_clean(unwrapped_md), "# Brad Vrabete\nSome content")
        self.assertEqual(docx_clean(mixed_md), "```python\nprint('hello')\n```\n# Brad\n```bash\necho\n```")

    def test_extract_frontmatter_single(self):
        """Test extracting single YAML frontmatter."""
        content = "---\nname: Brad Vrabete\nrole: Engineer\n---\n# Title\nBody text"
        body, metadata = _extract_frontmatter(content)
        self.assertEqual(body, "# Title\nBody text")
        self.assertEqual(metadata, {"name": "Brad Vrabete", "role": "Engineer"})

    def test_extract_frontmatter_multiple(self):
        """Test extracting multiple sequential frontmatters (synthesis + cv profile)."""
        content = "---\ntype: synthesis\ntarget_role: Architect\n---\n---\nname: Brad Vrabete\n---\n# Title"
        body, metadata = _extract_frontmatter(content)
        self.assertEqual(body, "# Title")
        self.assertEqual(metadata, {"type": "synthesis", "target_role": "Architect", "name": "Brad Vrabete"})

    def test_build_header_html(self):
        """Test building HTML header from metadata."""
        metadata = {
            "name": "Brad Vrabete",
            "position": "Engineer",
            "email": "brad@example.com",
            "phone": "12345"
        }
        header_html = _build_header_html(metadata)
        self.assertIn("<h1>Brad Vrabete</h1>", header_html)
        self.assertIn("Engineer &nbsp;|&nbsp; brad@example.com &nbsp;|&nbsp; 12345", header_html)

        # No name
        self.assertEqual(_build_header_html({"position": "Engineer"}), "")

    @patch("pdf_generator.HTML")
    @patch("pdf_generator.CSS")
    def test_generate_pdf(self, mock_css, mock_html):
        """Test generate_pdf with and without CSS."""
        mock_html_instance = MagicMock()
        mock_html.return_value = mock_html_instance

        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = os.path.join(temp_dir, "test.pdf")
            success = generate_pdf("# Test CV\nWith some text.", pdf_path)
            self.assertTrue(success)
            mock_html.assert_called_once()

    def test_generate_docx(self):
        """Test generate_docx successfully creates a document without mocking Inches."""
        with tempfile.TemporaryDirectory() as temp_dir:
            docx_path = os.path.join(temp_dir, "test.docx")
            success = generate_docx("```markdown\n# Test CV\n- Bullet point\n```", docx_path)
            self.assertTrue(success)
            self.assertTrue(os.path.exists(docx_path))


if __name__ == "__main__":
    unittest.main()
