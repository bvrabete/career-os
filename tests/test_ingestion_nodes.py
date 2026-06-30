"""Unit tests for the ingestion pipeline nodes and parser logic."""
import unittest
import json
import yaml
from pathlib import Path
from unittest.mock import patch, MagicMock
from langchain_core.messages import AIMessage

# Ensure src is in python path
import sys
sys.path.append(str(Path(__file__).parent.parent / "src"))

from ingestion.nodes import (
    _parse_via_pypdf, _parse_via_docling, _parse_fallback,
    node_parser, node_classifier, node_entity_resolver, node_validator
)
from ingestion.state import IngestionState


class TestIngestionNodes(unittest.TestCase):
    """Deterministic offline unit tests for LangGraph Ingestion Nodes."""

    def test_parse_via_pypdf_success(self):
        """Test _parse_via_pypdf successfully extracts text."""
        mock_reader = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "This is extracted test PDF text content. " + "A" * 300
        mock_reader.pages = [mock_page]
        
        with patch("pypdf.PdfReader", return_value=mock_reader):
            text = _parse_via_pypdf(Path("mock.pdf"))
            self.assertIsNotNone(text)
            self.assertIn("extracted test PDF text", text)

    def test_parse_via_pypdf_failure(self):
        """Test _parse_via_pypdf returns None on exception."""
        with patch("pypdf.PdfReader", side_effect=Exception("Read error")):
            text = _parse_via_pypdf(Path("mock.pdf"))
            self.assertIsNone(text)

    @patch("ingestion.nodes.DocumentConverter")
    def test_parse_via_docling_success(self, mock_converter_cls):
        """Test _parse_via_docling successfully converts PDF to markdown."""
        mock_instance = MagicMock()
        mock_result = MagicMock()
        mock_result.document.export_to_markdown.return_value = "# Markdown Text"
        mock_instance.convert.return_value = mock_result
        mock_converter_cls.return_value = mock_instance

        text = _parse_via_docling(Path("mock.pdf"), ".pdf")
        self.assertEqual(text, "# Markdown Text")

    @patch("ingestion.nodes.DocumentConverter")
    def test_parse_via_docling_failure(self, mock_converter_cls):
        """Test _parse_via_docling returns None on convert error."""
        mock_instance = MagicMock()
        mock_instance.convert.side_effect = Exception("Convert error")
        mock_converter_cls.return_value = mock_instance

        text = _parse_via_docling(Path("mock.pdf"), ".pdf")
        self.assertIsNone(text)

    def test_parse_fallback_text_success(self):
        """Test _parse_fallback reads standard text file."""
        with patch("pathlib.Path.read_text", return_value="plain text content") as mock_read:
            text = _parse_fallback(Path("mock.txt"), ".txt")
            self.assertEqual(text, "plain text content")

    @patch("pypdf.PdfReader")
    def test_node_parser_pdf_pypdf_flow(self, mock_pdf_reader_cls):
        """Test node_parser parses via pypdf when sufficient text is extracted."""
        mock_reader = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "A" * 300  # More than 200 chars
        mock_reader.pages = [mock_page]
        mock_pdf_reader_cls.return_value = mock_reader

        state: IngestionState = {
            "source_file": "mock_doc.pdf",
            "raw_text": "",
            "doc_type": "skip",
            "extracted_roles": [],
            "extracted_education": [],
            "extracted_skills": [],
            "extracted_projects": [],
            "extracted_patents": [],
            "extracted_notes": [],
            "extracted_cover_letters": [],
            "resolved_entities": {},
            "validation_errors": {},
            "written_paths": []
        }

        result = node_parser(state)
        self.assertEqual(result["raw_text"], "A" * 300)

    @patch("ingestion.nodes.get_model_for_step")
    @patch("ingestion.nodes.load_prompt")
    def test_node_classifier_success(self, mock_load_prompt, mock_get_model):
        """Test node_classifier extracts JSON correctly from model output."""
        mock_load_prompt.return_value = "Classifier System Instruction"
        
        mock_llm = MagicMock()
        mock_response = AIMessage(content='```json\n{"doc_type": "experience", "reason": "Looks like CV resume"}\n```')
        mock_llm.invoke.return_value = mock_response
        mock_get_model.return_value = mock_llm

        state: IngestionState = {
            "source_file": "doc.md",
            "raw_text": "Experienced Python Developer with deep technical skills.",
            "doc_type": "skip",
            "extracted_roles": [],
            "extracted_education": [],
            "extracted_skills": [],
            "extracted_projects": [],
            "extracted_patents": [],
            "extracted_notes": [],
            "extracted_cover_letters": [],
            "resolved_entities": {},
            "validation_errors": {},
            "written_paths": []
        }

        result = node_classifier(state)
        self.assertEqual(result["doc_type"], "experience")

    @patch("ingestion.nodes.get_model_for_step")
    def test_node_classifier_empty_text(self, mock_get_model):
        """Test node_classifier handles empty text by skipping."""
        state: IngestionState = {
            "source_file": "empty.md",
            "raw_text": "   \n  ",
            "doc_type": "",
            "extracted_roles": [],
            "extracted_education": [],
            "extracted_skills": [],
            "extracted_projects": [],
            "extracted_patents": [],
            "extracted_notes": [],
            "extracted_cover_letters": [],
            "resolved_entities": {},
            "validation_errors": {},
            "written_paths": []
        }

        result = node_classifier(state)
        self.assertEqual(result["doc_type"], "skip")

    @patch("ingestion.nodes.parse_mappings")
    def test_node_entity_resolver(self, mock_parse_mappings):
        """Test node_entity_resolver resolves raw org names to canonical slugs."""
        mock_parse_mappings.return_value = {
            "intel corp": "intel-corporation",
            "google inc": "google-inc"
        }

        state: IngestionState = {
            "source_file": "doc.md",
            "raw_text": "...",
            "doc_type": "experience",
            "extracted_roles": [{"raw_org_name": "Intel Corp"}, {"raw_org_name": "Unknown Corp"}],
            "extracted_education": [{"raw_inst_name": "Google Inc"}],
            "extracted_skills": [],
            "extracted_projects": [{"raw_org_name": "Intel Corp"}],
            "extracted_patents": [],
            "extracted_notes": [],
            "extracted_cover_letters": [],
            "resolved_entities": {},
            "validation_errors": {},
            "written_paths": []
        }

        result = node_entity_resolver(state)
        resolved = result["resolved_entities"]
        
        self.assertEqual(resolved.get("Intel Corp"), "intel-corporation")
        self.assertEqual(resolved.get("Google Inc"), "google-inc")
        self.assertEqual(resolved.get("Unknown Corp"), "unknown-corp")

    def test_node_validator_success(self):
        """Test node_validator with correct experience frontmatter blocks."""
        state: IngestionState = {
            "source_file": "doc.md",
            "raw_text": "",
            "doc_type": "experience",
            "extracted_roles": [],
            "extracted_education": [],
            "extracted_skills": [],
            "extracted_projects": [],
            "extracted_patents": [],
            "extracted_notes": [],
            "extracted_cover_letters": [],
            "resolved_entities": {},
            "validation_errors": {},
            "written_paths": [],
            "wiki_outputs": [
                {
                    "path": "wiki/experiences/intel.md",
                    "content": """---
type: experience
title: Staff Engineer
organization: "[[intel-corporation]]"
dates:
  start: 2020-01-01
  end: Present
tracks:
  - Engineering
skills:
  - Python
---
Some body text.
""",
                    "validation_errors": []
                }
            ]
        }

        result = node_validator(state)
        self.assertEqual(result["wiki_outputs"][0]["validation_errors"], [])


if __name__ == "__main__":
    unittest.main()
