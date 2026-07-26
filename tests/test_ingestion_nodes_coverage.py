import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from ingestion.nodes import (
    _parse_via_pypdf,
    _parse_via_docling,
    _parse_fallback,
    node_parser,
    _validate_dates,
    _validate_experience,
    _validate_education,
    _validate_skill,
    _validate_language,
    _validate_project,
    _validate_patent,
    _validate_note,
    _validate_cover_letter,
    _validate_entity,
    _validate_single_output,
    node_writer
)


class TestIngestionNodesCoverage(unittest.TestCase):

    def test_parse_via_pypdf_exception(self) -> None:
        # Pass non-existent path to trigger exception and return None
        res = _parse_via_pypdf(Path("non_existent_file.pdf"))
        self.assertIsNone(res)

    @patch("ingestion.nodes.DocumentConverter")
    def test_parse_via_docling_pdf_success(self, mock_converter_cls: MagicMock) -> None:
        mock_converter = MagicMock()
        mock_result = MagicMock()
        mock_result.document.export_to_markdown.return_value = "Docling PDF parsed text"
        mock_converter.convert.return_value = mock_result
        mock_converter_cls.return_value = mock_converter

        res = _parse_via_docling(Path("dummy.pdf"), ".pdf")
        self.assertEqual(res, "Docling PDF parsed text")

    @patch("ingestion.nodes.DocumentConverter")
    def test_parse_via_docling_docx_success(self, mock_converter_cls: MagicMock) -> None:
        mock_converter = MagicMock()
        mock_result = MagicMock()
        mock_result.document.export_to_markdown.return_value = "Docling DOCX parsed text"
        mock_converter.convert.return_value = mock_result
        mock_converter_cls.return_value = mock_converter

        res = _parse_via_docling(Path("dummy.docx"), ".docx")
        self.assertEqual(res, "Docling DOCX parsed text")

    @patch("ingestion.nodes.DocumentConverter")
    def test_parse_via_docling_exception(self, mock_converter_cls: MagicMock) -> None:
        mock_converter_cls.side_effect = Exception("Docling conversion error")
        res = _parse_via_docling(Path("dummy.pdf"), ".pdf")
        self.assertIsNone(res)

    def test_parse_fallback_pdf_exception(self) -> None:
        res = _parse_fallback(Path("non_existent_file.pdf"), ".pdf")
        self.assertEqual(res, "")

    def test_parse_fallback_docx_exception(self) -> None:
        res = _parse_fallback(Path("non_existent_file.docx"), ".docx")
        self.assertEqual(res, "")

    def test_parse_fallback_text_success(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Fallback raw text content")
            f_path = Path(f.name)
        try:
            res = _parse_fallback(f_path, ".txt")
            self.assertEqual(res, "Fallback raw text content")
        finally:
            f_path.unlink()

    @patch("ingestion.nodes._parse_via_pypdf")
    @patch("ingestion.nodes._parse_via_docling")
    def test_node_parser_pdf_docling_path(self, mock_docling: MagicMock, mock_pypdf: MagicMock) -> None:
        mock_pypdf.return_value = None # Primary pypdf returns None to force docling path
        mock_docling.return_value = "Docling text"
        
        state = {"source_file": "dummy.pdf"}
        res = node_parser(state) # type: ignore
        self.assertEqual(res, {"raw_text": "Docling text"})

    def test_validate_dates(self) -> None:
        errors = []
        _validate_dates({"start": "2020-01-01", "end": "Present"}, errors)
        self.assertEqual(len(errors), 0)

        _validate_dates({"start": "invalid-date", "end": ""}, errors)
        self.assertTrue(len(errors) > 0)

    def test_validate_experience(self) -> None:
        errors = []
        fm = {
            "type": "experience",
            "title": "Engineer",
            "organization": "[[google]]",
            "dates": {"start": "2020-01-01", "end": "Present"},
            "tracks": ["tech-lead"],
            "skills": ["python"],
            "employment_type": "Permanent"
        }
        _validate_experience(fm, errors)
        self.assertEqual(len(errors), 0)

        # Missing organization [[slug]]
        fm["organization"] = "google"
        _validate_experience(fm, errors)
        self.assertTrue(any("organization field missing [[slug]]" in e for e in errors))

        # Invalid employment_type
        fm["employment_type"] = "Contractor"
        _validate_experience(fm, errors)
        self.assertTrue(any("employment_type must be either" in e for e in errors))

    def test_validate_education(self) -> None:
        errors = []
        fm = {
            "type": "education",
            "title": "MSc",
            "institution": "[[oxford]]",
            "dates": {"start": "2015-09-01", "end": "2017-06-01"},
            "status": "Completed",
            "major": "CS",
            "minor": ""
        }
        _validate_education(fm, errors)
        self.assertEqual(len(errors), 0)

        # Missing institution slug syntax
        fm["institution"] = "oxford"
        _validate_education(fm, errors)
        self.assertTrue(any("institution field missing [[slug]]" in e for e in errors))

    def test_validate_skill(self) -> None:
        errors = []
        fm = {
            "type": "skill",
            "title": "Python",
            "category": "Language-Code",
            "proficiency": "Expert"
        }
        _validate_skill(fm, errors)
        self.assertEqual(len(errors), 0)

        # Invalid category
        fm["category"] = "unsupported-category"
        _validate_skill(fm, errors)
        self.assertTrue(any("Invalid skill category" in e for e in errors))

    def test_validate_language(self) -> None:
        errors = []
        fm = {
            "type": "language",
            "title": "English",
            "proficiency": "Native"
        }
        _validate_language(fm, errors)
        self.assertEqual(len(errors), 0)

        # Missing title
        del fm["title"]
        _validate_language(fm, errors)
        self.assertTrue(any("Missing frontmatter fields" in e for e in errors))

    def test_validate_project(self) -> None:
        errors = []
        fm = {
            "type": "project",
            "title": "Carrier OS",
            "organization": "[[my-org]]",
            "dates": {"start": "2025-01-01", "end": "2025-06-01"},
            "skills": ["python"]
        }
        _validate_project(fm, errors)
        self.assertEqual(len(errors), 0)

        # Missing organization slug syntax
        fm["organization"] = "my-org"
        _validate_project(fm, errors)
        self.assertTrue(any("organization field missing [[slug]]" in e for e in errors))

    def test_validate_patent(self) -> None:
        errors = []
        fm = {
            "type": "patent",
            "title": "Secure AI Pipeline",
            "id": "US123456",
            "inventors": ["John Doe"],
            "organization": "[[intel]]",
            "skills": ["ai"]
        }
        _validate_patent(fm, errors)
        self.assertEqual(len(errors), 0)

        # Missing organization slug syntax
        fm["organization"] = "intel"
        _validate_patent(fm, errors)
        self.assertTrue(any("organization field missing [[slug]]" in e for e in errors))

    def test_validate_note(self) -> None:
        errors = []
        fm = {
            "type": "note",
            "title": "Review",
            "related": ["[[google]]"],
            "perspective": "First-Person",
            "tags": ["performance"]
        }
        _validate_note(fm, errors)
        self.assertEqual(len(errors), 0)

    def test_validate_cover_letter(self) -> None:
        errors = []
        fm = {
            "type": "cover-letter",
            "title": "Cover Letter Google",
            "target_organization": "[[google]]",
            "related_synthesis": "[[synthesis]]"
        }
        _validate_cover_letter(fm, errors)
        self.assertEqual(len(errors), 0)

        # Missing target_organization slug syntax
        fm["target_organization"] = "google"
        _validate_cover_letter(fm, errors)
        self.assertTrue(any("target_organization field missing [[slug]]" in e for e in errors))

    def test_validate_entity(self) -> None:
        errors = []
        fm = {
            "type": "entity",
            "title": "Google LLC",
            "tags": ["company"],
            "sources": ["website"]
        }
        _validate_entity(fm, errors)
        self.assertEqual(len(errors), 0)

    def test_validate_single_output_invalid_type(self) -> None:
        output = {
            "path": "dummy.md",
            "content": "---\ntype: unknown-type\ntitle: test\n---\nBody content"
        }
        res = _validate_single_output(output)
        self.assertTrue(any("Unknown frontmatter type" in e for e in res["validation_errors"]))

    def test_validate_single_output_no_frontmatter(self) -> None:
        output = {
            "path": "dummy.md",
            "content": "Just body content with no yaml block"
        }
        res = _validate_single_output(output)
        self.assertTrue(any("No valid YAML frontmatter block found" in e for e in res["validation_errors"]))

    def test_node_writer_conditions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "wiki_file.md"
            
            # Case 1: Skipped due to validation errors
            state1 = {
                "wiki_outputs": [{
                    "path": str(tmp_path),
                    "content": "Content",
                    "validation_errors": ["Some error"]
                }]
            }
            res1 = node_writer(state1) # type: ignore
            self.assertFalse(res1["wiki_outputs"][0]["written"])
            self.assertFalse(tmp_path.exists())

            # Case 2: Skipped because file already exists and was not merged
            tmp_path.write_text("Existing text")
            state2 = {
                "wiki_outputs": [{
                    "path": str(tmp_path),
                    "content": "New text to write",
                    "validation_errors": [],
                    "merged": False
                }]
            }
            res2 = node_writer(state2) # type: ignore
            self.assertFalse(res2["wiki_outputs"][0]["written"])
            self.assertEqual(res2["wiki_outputs"][0]["skipped_reason"], "duplicate")
            self.assertEqual(tmp_path.read_text(), "Existing text")

            # Case 3: Written because it was merged or doesn't exist
            state3 = {
                "wiki_outputs": [{
                    "path": str(tmp_path),
                    "content": "Merged text to write",
                    "validation_errors": [],
                    "merged": True
                }]
            }
            res3 = node_writer(state3) # type: ignore
            self.assertTrue(res3["wiki_outputs"][0]["written"])
            self.assertEqual(tmp_path.read_text(), "Merged text to write")

            # Case 4: Dry-run mode
            tmp_path.unlink()
            state4 = {
                "wiki_outputs": [{
                    "path": str(tmp_path),
                    "content": "Dry run text",
                    "validation_errors": [],
                    "merged": False
                }]
            }
            res4 = node_writer(state4, dry_run=True) # type: ignore
            self.assertFalse(res4["wiki_outputs"][0]["written"])
            self.assertTrue(res4["wiki_outputs"][0]["dry_run"])
            self.assertFalse(tmp_path.exists())


if __name__ == "__main__":
    unittest.main()
