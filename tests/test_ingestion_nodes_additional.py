import logging
from pathlib import Path
import tempfile
from typing import cast
from unittest.mock import MagicMock, patch

from ingestion.nodes import (
    _parse_fallback,
    _validate_by_type,
    node_classifier,
    node_merger,
    node_parser,
    node_validator,
    node_writer,
)
from ingestion.state import IngestionState
from langchain_core.messages import AIMessage

# Suppress debug/info logging during tests
logging.basicConfig(level=logging.ERROR)


class TestIngestionNodesAdditional:
    """Deterministic offline unit tests for remaining ingestion nodes paths."""

    def setup_method(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=".")
        self.temp_path = Path(self.temp_dir.name)

    def teardown_method(self):
        self.temp_dir.cleanup()

    # 1. Fallback Parser Tests
    def test_parse_fallback_pdf_success_and_exception(self):
        """Test _parse_fallback with PDF files."""
        # Success
        mock_reader = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "PDF fallback text"
        mock_reader.pages = [mock_page]
        with patch("pypdf.PdfReader", return_value=mock_reader):
            res = _parse_fallback(Path("dummy.pdf"), ".pdf")
            assert res == "PDF fallback text"

        # Exception
        with patch("pypdf.PdfReader", side_effect=Exception("PDF error")):
            res = _parse_fallback(Path("dummy.pdf"), ".pdf")
            assert res == ""

    def test_parse_fallback_docx_success_and_exception(self):
        """Test _parse_fallback with docx files."""
        # Success
        mock_doc = MagicMock()
        mock_p = MagicMock()
        mock_p.text = "Docx fallback text"
        mock_doc.paragraphs = [mock_p]
        with patch("docx.Document", return_value=mock_doc):
            res = _parse_fallback(Path("dummy.docx"), ".docx")
            assert res == "Docx fallback text"

        # Exception
        with patch("docx.Document", side_effect=Exception("Docx error")):
            res = _parse_fallback(Path("dummy.docx"), ".docx")
            assert res == ""

    def test_parse_fallback_text_exception(self):
        """Test _parse_fallback handles read_text exceptions."""
        mock_path = MagicMock(spec=Path)
        mock_path.read_text.side_effect = Exception("Read error")
        res = _parse_fallback(mock_path, ".txt")
        assert res == ""

    # 2. Node Parser Fallback Flows
    @patch("ingestion.nodes._parse_via_pypdf", return_value=None)
    @patch("ingestion.nodes._parse_via_docling", return_value=None)
    @patch("ingestion.nodes._parse_fallback", return_value="Fallback extraction")
    def test_node_parser_pypdf_to_docling_to_fallback(self, mock_fallback, mock_docling, mock_pypdf):
        """Test node_parser falling back all the way to _parse_fallback."""
        state = cast(IngestionState, {"source_file": "dummy.pdf"})
        res = node_parser(state)
        assert res["raw_text"] == "Fallback extraction"
        mock_pypdf.assert_called_once()
        mock_docling.assert_called_once()
        mock_fallback.assert_called_once()

    # 3. Classifier Error Handling
    @patch("ingestion.nodes.get_model_for_step")
    @patch("ingestion.nodes.load_prompt", return_value="prompt")
    def test_node_classifier_json_error(self, mock_load, mock_get_model):
        """Test classifier falling back to skip when LLM returns invalid JSON."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="invalid json output")
        mock_get_model.return_value = mock_llm

        state = cast(IngestionState, {"source_file": "dummy.md", "raw_text": "Resume text"})
        res = node_classifier(state)
        assert res["doc_type"] == "skip"

    # 4. Merger Tests
    @patch("ingestion.nodes.get_model_for_step")
    @patch("ingestion.nodes.load_prompt", return_value="Merge instructions")
    @patch("ingestion.nodes._find_existing_page")
    def test_node_merger_scenarios(self, mock_find_page, mock_load, mock_get_model):
        """Test different merging paths in node_merger."""
        mock_llm = MagicMock()
        mock_get_model.return_value = mock_llm

        # Case 1: Outputs with validation errors should skip merging
        state_err = cast(IngestionState, {
            "source_file": "dummy.md",
            "wiki_outputs": [{"path": "wiki/experiences/org.md", "validation_errors": ["Some error"]}]
        })
        res = node_merger(state_err)
        assert res["wiki_outputs"][0].get("merged") is None

        # Case 2: New file (no existing page)
        mock_find_page.return_value = None
        state_new = cast(IngestionState, {
            "source_file": "dummy.md",
            "wiki_outputs": [{"path": "wiki/experiences/org.md", "content": "---\ntype: experience\n---\n"}]
        })
        res = node_merger(state_new)
        assert "merged" not in res["wiki_outputs"][0]

        # Case 3: Merge with redirecting file path (existing path != current path)
        existing_file = self.temp_path / "old_org.md"
        existing_file.write_text("---\ntype: experience\ntitle: Old Experience\n---\nOld Body")
        mock_find_page.return_value = existing_file

        mock_llm.invoke.return_value = AIMessage(content="---\ntype: experience\ntitle: Merged\n---\nMerged Body")

        state_redirect = cast(IngestionState, {
            "source_file": "dummy.md",
            "wiki_outputs": [{
                "path": str(self.temp_path / "new_org.md"),
                "content": "---\ntype: experience\ntitle: New Experience\n---\nNew Body"
            }]
        })
        res = node_merger(state_redirect)
        output = res["wiki_outputs"][0]
        assert output["path"] == str(existing_file)
        assert output["merged"]
        assert "Merged Body" in output["content"]

        # Case 4: Merge exception path
        mock_llm.invoke.side_effect = Exception("LLM failure")
        state_fail = cast(IngestionState, {
            "source_file": "dummy.md",
            "wiki_outputs": [{
                "path": str(existing_file),
                "content": "---\ntype: experience\ntitle: New Experience\n---\nNew Body"
            }]
        })
        res = node_merger(state_fail)
        output = res["wiki_outputs"][0]
        assert not output["merged"]
        assert output["merge_error"] == "LLM failure"

        # Case 5: Empty wiki_outputs list
        assert node_merger({"source_file": "dummy.md", "wiki_outputs": []}) == {"wiki_outputs": []}

    # 5. Schema Type Validators (via node_validator)
    def test_node_validator_empty_and_yaml_parse_errors(self):
        """Test validator handling empty content and malformed YAML frontmatter."""
        state = cast(IngestionState, {
            "source_file": "dummy.md",
            "wiki_outputs": [
                {"path": "wiki/experiences/test.md", "content": ""},
                {"path": "wiki/experiences/test2.md", "content": "---\ntype: experience\n  invalid yaml:\n  - unmatched\n---\nBody"}
            ]
        })
        res = node_validator(state)
        assert "Empty content" in res["wiki_outputs"][0]["validation_errors"][0]
        assert "YAML parse error" in res["wiki_outputs"][1]["validation_errors"][0]

    def test_node_validator_unknown_type(self):
        """Test validator handling unknown page type."""
        state = cast(IngestionState, {
            "source_file": "dummy.md",
            "wiki_outputs": [
                {"path": "wiki/experiences/test.md", "content": "---\ntype: magic_type\n---\nBody"}
            ]
        })
        res = node_validator(state)
        assert "Unknown frontmatter type" in res["wiki_outputs"][0]["validation_errors"][0]

    def test_validator_experience_rules(self):
        """Test experience validation specific rules (org syntax, dates, employment_type)."""
        # Missing fields
        errors = []
        _validate_by_type("experience", {}, errors)
        assert any("Missing frontmatter fields" in e for e in errors)

        # Missing [[slug]] syntax in organization
        errors = []
        _validate_by_type("experience", {
            "type": "experience", "title": "SE", "organization": "intel-corp",
            "dates": {"start": "2020-01-01"}, "tracks": ["Eng"], "skills": ["Python"]
        }, errors)
        assert any("organization field missing [[slug]] syntax" in e for e in errors)

        # Invalid start date format
        errors = []
        _validate_by_type("experience", {
            "type": "experience", "title": "SE", "organization": "[[intel-corp]]",
            "dates": {"start": "2020/01/01"}, "tracks": ["Eng"], "skills": ["Python"]
        }, errors)
        assert any("dates.start invalid format" in e for e in errors)

        # Invalid employment_type
        errors = []
        _validate_by_type("experience", {
            "type": "experience", "title": "SE", "organization": "[[intel-corp]]",
            "dates": {"start": "2020-01-01"}, "tracks": ["Eng"], "skills": ["Python"],
            "employment_type": "Freelance"
        }, errors)
        assert any("employment_type must be either 'Permanent' or 'Contract'" in e for e in errors)

    def test_validator_education_rules(self):
        """Test education validator specific rules."""
        # Missing institution slug syntax
        errors = []
        _validate_by_type("education", {
            "type": "education", "title": "BS", "institution": "stanford",
            "dates": {"start": "2016-09-01"}, "status": "Completed", "major": "CS", "minor": "Math"
        }, errors)
        assert any("institution field missing" in e for e in errors)

    def test_validator_skill_rules(self):
        """Test skill validator specific rules."""
        # Invalid skill category
        errors = []
        _validate_by_type("skill", {
            "type": "skill", "title": "C++", "category": "Superpower", "proficiency": "Expert"
        }, errors)
        assert any("Invalid skill category" in e for e in errors)

    def test_validator_project_rules(self):
        """Test project validator specific rules."""
        # Missing organization slug syntax
        errors = []
        _validate_by_type("project", {
            "type": "project", "title": "AI Search", "organization": "gcp",
            "dates": {"start": "2022-01-01"}, "skills": ["TensorFlow"]
        }, errors)
        assert any("organization field missing" in e for e in errors)

    def test_validator_patent_rules(self):
        """Test patent validator specific rules."""
        # Missing organization slug syntax
        errors = []
        _validate_by_type("patent", {
            "type": "patent", "title": "Search System", "id": "US123",
            "inventors": ["Me"], "organization": "gcp", "skills": ["Patent law"]
        }, errors)
        assert any("organization field missing" in e for e in errors)

    def test_validator_cover_letter_rules(self):
        """Test cover letter validator specific rules."""
        # Missing target_organization slug syntax
        errors = []
        _validate_by_type("cover-letter", {
            "type": "cover-letter", "title": "Google Letter", "target_organization": "google",
            "related_synthesis": "gcp"
        }, errors)
        assert any("target_organization field missing" in e for e in errors)

    # 6. Writer Node Tests
    def test_node_writer_dry_run_and_success_flows(self):
        """Test node_writer behavior in different dry-run, normal, duplicate, and validation-error configurations."""
        out_path = self.temp_path / "wiki/experiences/test_writer.md"

        # Case 1: Validation errors present
        state_err = cast(IngestionState, {
            "source_file": "dummy.md",
            "wiki_outputs": [{"path": str(out_path), "content": "Body", "validation_errors": ["Error"]}]
        })
        res_err = node_writer(state_err)
        output = res_err["wiki_outputs"][0]
        assert not output["written"]
        assert not out_path.exists()

        # Case 2: Duplicate file exists on disk and is not merged
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("Existing body")
        state_dup = cast(IngestionState, {
            "source_file": "dummy.md",
            "wiki_outputs": [{"path": str(out_path), "content": "New Body", "validation_errors": [], "merged": False}]
        })
        res_dup = node_writer(state_dup)
        output = res_dup["wiki_outputs"][0]
        assert not output["written"]
        assert output["skipped_reason"] == "duplicate"

        # Case 3: Dry run mode enabled
        out_path.unlink()  # Remove existing
        state_dry = cast(IngestionState, {
            "source_file": "dummy.md",
            "wiki_outputs": [{"path": str(out_path), "content": "New Body", "validation_errors": [], "merged": False}]
        })
        res_dry = node_writer(state_dry, dry_run=True)
        output = res_dry["wiki_outputs"][0]
        assert not output["written"]
        assert output["dry_run"]
        assert not out_path.exists()

        # Case 4: Normal successful write
        res_success = node_writer(state_dry, dry_run=False)
        output = res_success["wiki_outputs"][0]
        assert output["written"]
        assert out_path.exists()
        assert out_path.read_text() == "New Body"
