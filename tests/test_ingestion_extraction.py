"""Unit tests for the ingestion pipeline extraction logic."""
import unittest
from unittest.mock import patch, MagicMock
from ingestion.extraction import (
    _extract_experience, _extract_cover_letter, _extract_supplemental, node_extractor
)
from ingestion.state import IngestionState


class TestIngestionExtraction(unittest.TestCase):
    """Deterministic offline tests for Ingestion Pipeline extraction."""

    @patch("ingestion.extraction.load_prompt")
    def test_extract_experience_success(self, mock_load_prompt):
        """Test _extract_experience extracts standard fields correctly on success."""
        mock_load_prompt.return_value = "Mock system prompt"
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '```json\n{"roles": [{"title": "Software Engineer"}], "profile": {"name": "Alice"}}\n```'
        mock_llm.invoke.return_value = mock_response

        result = _extract_experience(mock_llm, "Some raw resume text")
        self.assertEqual(result.get("profile", {}).get("name"), "Alice")
        self.assertEqual(len(result.get("roles", [])), 1)
        self.assertEqual(result["roles"][0]["title"], "Software Engineer")

    @patch("ingestion.extraction.load_prompt")
    def test_extract_experience_json_error(self, mock_load_prompt):
        """Test _extract_experience returns empty dict on JSON parsing error."""
        mock_load_prompt.return_value = "Mock system prompt"
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Invalid non-json output"
        mock_llm.invoke.return_value = mock_response

        result = _extract_experience(mock_llm, "Some raw resume text")
        self.assertEqual(result, {})

    @patch("ingestion.extraction.load_prompt")
    def test_extract_cover_letter_success(self, mock_load_prompt):
        """Test _extract_cover_letter extracts fields correctly on success."""
        mock_load_prompt.return_value = "Mock system prompt"
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"cover_letters": [{"recipient": "Google"}]}'
        mock_llm.invoke.return_value = mock_response

        result = _extract_cover_letter(mock_llm, "Cover letter text")
        self.assertEqual(len(result.get("cover_letters", [])), 1)
        self.assertEqual(result["cover_letters"][0]["recipient"], "Google")

    @patch("ingestion.extraction.load_prompt")
    def test_extract_cover_letter_json_error(self, mock_load_prompt):
        """Test _extract_cover_letter returns empty dict on JSON parsing error."""
        mock_load_prompt.return_value = "Mock system prompt"
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Not a json"
        mock_llm.invoke.return_value = mock_response

        result = _extract_cover_letter(mock_llm, "Cover letter text")
        self.assertEqual(result, {})

    @patch("ingestion.extraction.load_prompt")
    def test_extract_supplemental_success(self, mock_load_prompt):
        """Test _extract_supplemental extracts fields correctly on success."""
        mock_load_prompt.return_value = "Mock system prompt"
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"notes": [{"content": "Excellent performer"}]}'
        mock_llm.invoke.return_value = mock_response

        result = _extract_supplemental(mock_llm, "Performance review text")
        self.assertEqual(len(result.get("notes", [])), 1)
        self.assertEqual(result["notes"][0]["content"], "Excellent performer")

    @patch("ingestion.extraction.load_prompt")
    def test_extract_supplemental_json_error(self, mock_load_prompt):
        """Test _extract_supplemental returns empty dict on JSON parsing error."""
        mock_load_prompt.return_value = "Mock system prompt"
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Malformed content"
        mock_llm.invoke.return_value = mock_response

        result = _extract_supplemental(mock_llm, "Performance review text")
        self.assertEqual(result, {})

    def test_node_extractor_empty_text(self):
        """Test node_extractor skips extraction when raw_text is empty or blank."""
        state = IngestionState(doc_type="experience", raw_text="   ")
        outputs = node_extractor(state)
        self.assertEqual(outputs["extracted_roles"], [])
        self.assertEqual(outputs["extracted_profile"], {})

    @patch("ingestion.extraction.get_model_for_step")
    @patch("ingestion.extraction._extract_experience")
    def test_node_extractor_experience(self, mock_extract, mock_get_model):
        """Test node_extractor with doc_type experience."""
        mock_get_model.return_value = MagicMock()
        mock_extract.return_value = {
            "roles": [{"title": "Staff Engineer"}],
            "education": [{"degree": "BS CS"}],
            "languages": [{"name": "French"}],
            "projects": [{"name": "My Project"}],
            "patents": [{"title": "A patent"}],
            "profile": {"name": "Alice"}
        }
        state = IngestionState(doc_type="experience", raw_text="Experienced candidate")
        outputs = node_extractor(state)
        self.assertEqual(outputs["extracted_profile"]["name"], "Alice")
        self.assertEqual(len(outputs["extracted_roles"]), 1)
        self.assertEqual(outputs["extracted_roles"][0]["title"], "Staff Engineer")
        self.assertEqual(len(outputs["extracted_education"]), 1)
        self.assertEqual(len(outputs["extracted_languages"]), 1)
        self.assertEqual(len(outputs["extracted_projects"]), 1)
        self.assertEqual(len(outputs["extracted_patents"]), 1)

    @patch("ingestion.extraction.get_model_for_step")
    @patch("ingestion.extraction._extract_cover_letter")
    def test_node_extractor_cover_letter(self, mock_extract, mock_get_model):
        """Test node_extractor with doc_type cover_letter."""
        mock_get_model.return_value = MagicMock()
        mock_extract.return_value = {
            "cover_letters": [{"recipient": "Meta"}]
        }
        state = IngestionState(doc_type="cover_letter", raw_text="Dear Hiring Manager...")
        outputs = node_extractor(state)
        self.assertEqual(len(outputs["extracted_cover_letters"]), 1)
        self.assertEqual(outputs["extracted_cover_letters"][0]["recipient"], "Meta")

    @patch("ingestion.extraction.get_model_for_step")
    @patch("ingestion.extraction._extract_supplemental")
    def test_node_extractor_supplemental(self, mock_extract, mock_get_model):
        """Test node_extractor with doc_type supplemental."""
        mock_get_model.return_value = MagicMock()
        mock_extract.return_value = {
            "notes": [{"content": "Outstanding leadership"}]
        }
        state = IngestionState(doc_type="supplemental", raw_text="Review: Outstanding leadership")
        outputs = node_extractor(state)
        self.assertEqual(len(outputs["extracted_notes"]), 1)
        self.assertEqual(outputs["extracted_notes"][0]["content"], "Outstanding leadership")

    @patch("ingestion.extraction.get_model_for_step")
    def test_node_extractor_unknown_doc_type(self, mock_get_model):
        """Test node_extractor with an unknown doc_type."""
        mock_get_model.return_value = MagicMock()
        state = IngestionState(doc_type="unknown_type", raw_text="Hello world")
        outputs = node_extractor(state)
        self.assertEqual(outputs["extracted_roles"], [])
        self.assertEqual(outputs["extracted_profile"], {})


if __name__ == "__main__":
    unittest.main()
