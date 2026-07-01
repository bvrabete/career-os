"""Unit tests for the ingestion pipeline generation logic."""
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock
from ingestion.generation import (
    _generate_experiences, _generate_education, _generate_languages,
    _generate_projects, _generate_patents, _generate_notes,
    _generate_cover_letters, _generate_profile, node_generator
)
from ingestion.state import IngestionState


class TestIngestionGeneration(unittest.TestCase):
    """Deterministic offline tests for Ingestion Pipeline generation."""

    def setUp(self):
        self.mock_llm = MagicMock()
        self.mock_response = MagicMock()
        self.mock_response.content = "---\ntitle: Sample\n---\nBody content"
        self.mock_llm.invoke.return_value = self.mock_response

    @patch("ingestion.generation.load_prompt")
    @patch("ingestion.generation.get_wiki_root")
    def test_generate_experiences_success(self, mock_get_wiki_root, mock_load_prompt):
        """Test _generate_experiences successfully processes role details."""
        mock_load_prompt.return_value = "System prompt template"
        mock_get_wiki_root.return_value = Path("/mock/wiki")

        roles = [{"raw_org_name": "Intel Corp", "title": "Staff Engineer"}]
        resolved = {"Intel Corp": "intel-corp"}
        wiki_outputs = []

        _generate_experiences(self.mock_llm, roles, resolved, "2026-06-30", "Schema text", wiki_outputs)

        self.assertEqual(len(wiki_outputs), 1)
        self.assertEqual(wiki_outputs[0]["path"], "/mock/wiki/experiences/intel-corp-staff-engineer.md")
        self.assertEqual(wiki_outputs[0]["org_slug"], "intel-corp")
        self.assertEqual(wiki_outputs[0]["title"], "Staff Engineer")
        self.assertIn("Body content", wiki_outputs[0]["content"])

    @patch("ingestion.generation.load_prompt")
    @patch("ingestion.generation.get_wiki_root")
    def test_generate_experiences_exception(self, mock_get_wiki_root, mock_load_prompt):
        """Test _generate_experiences handles exception gracefully on LLM failure."""
        mock_load_prompt.return_value = "System prompt template"
        mock_get_wiki_root.return_value = Path("/mock/wiki")
        self.mock_llm.invoke.side_effect = Exception("LLM failure")

        roles = [{"raw_org_name": "Intel Corp", "title": "Staff Engineer"}]
        resolved = {"Intel Corp": "intel-corp"}
        wiki_outputs = []

        _generate_experiences(self.mock_llm, roles, resolved, "2026-06-30", "Schema text", wiki_outputs)

        self.assertEqual(len(wiki_outputs), 1)
        self.assertEqual(wiki_outputs[0]["content"], "")
        self.assertEqual(len(wiki_outputs[0]["validation_errors"]), 1)
        self.assertIn("Generation failed", wiki_outputs[0]["validation_errors"][0])

    @patch("ingestion.generation.load_prompt")
    @patch("ingestion.generation.get_wiki_root")
    def test_generate_education_success(self, mock_get_wiki_root, mock_load_prompt):
        """Test _generate_education successfully processes education details."""
        mock_load_prompt.return_value = "Education prompt"
        mock_get_wiki_root.return_value = Path("/mock/wiki")

        education = [{
            "raw_inst_name": "Stanford", "title": "BS CS",
            "start": "2018", "end": "2022", "status": "Completed",
            "major": "Computer Science", "minor": "Math"
        }]
        resolved = {"Stanford": "stanford-university"}
        wiki_outputs = []

        _generate_education(self.mock_llm, education, resolved, "2026-06-30", wiki_outputs)

        self.assertEqual(len(wiki_outputs), 1)
        self.assertEqual(wiki_outputs[0]["path"], "/mock/wiki/education/stanford-university-bs-cs.md")
        self.assertEqual(wiki_outputs[0]["title"], "BS CS")

    @patch("ingestion.generation.load_prompt")
    @patch("ingestion.generation.get_wiki_root")
    def test_generate_education_exception(self, mock_get_wiki_root, mock_load_prompt):
        """Test _generate_education handles exception gracefully on LLM failure."""
        mock_load_prompt.return_value = "Education prompt"
        mock_get_wiki_root.return_value = Path("/mock/wiki")
        self.mock_llm.invoke.side_effect = Exception("LLM failure")

        education = [{"raw_inst_name": "Stanford", "title": "BS CS"}]
        resolved = {"Stanford": "stanford-university"}
        wiki_outputs = []

        _generate_education(self.mock_llm, education, resolved, "2026-06-30", wiki_outputs)

        self.assertEqual(len(wiki_outputs), 1)
        self.assertEqual(wiki_outputs[0]["content"], "")
        self.assertEqual(len(wiki_outputs[0]["validation_errors"]), 1)

    @patch("ingestion.generation.load_prompt")
    @patch("ingestion.generation.get_wiki_root")
    def test_generate_languages_success(self, mock_get_wiki_root, mock_load_prompt):
        """Test _generate_languages successfully processes languages."""
        mock_load_prompt.return_value = "Language prompt"
        mock_get_wiki_root.return_value = Path("/mock/wiki")

        languages = [{"language": "Spanish", "proficiency": "Fluent"}]
        wiki_outputs = []

        _generate_languages(self.mock_llm, languages, "2026-06-30", wiki_outputs)

        self.assertEqual(len(wiki_outputs), 1)
        self.assertEqual(wiki_outputs[0]["path"], "/mock/wiki/skills/lang-spanish.md")
        self.assertEqual(wiki_outputs[0]["org_slug"], "lang-spanish")

    @patch("ingestion.generation.load_prompt")
    @patch("ingestion.generation.get_wiki_root")
    def test_generate_languages_exception(self, mock_get_wiki_root, mock_load_prompt):
        """Test _generate_languages handles exception gracefully on LLM failure."""
        mock_load_prompt.return_value = "Language prompt"
        mock_get_wiki_root.return_value = Path("/mock/wiki")
        self.mock_llm.invoke.side_effect = Exception("LLM failure")

        languages = [{"language": "Spanish"}]
        wiki_outputs = []

        _generate_languages(self.mock_llm, languages, "2026-06-30", wiki_outputs)

        self.assertEqual(len(wiki_outputs), 1)
        self.assertEqual(wiki_outputs[0]["content"], "")
        self.assertEqual(len(wiki_outputs[0]["validation_errors"]), 1)

    @patch("ingestion.generation.load_prompt")
    @patch("ingestion.generation.get_wiki_root")
    def test_generate_projects_success(self, mock_get_wiki_root, mock_load_prompt):
        """Test _generate_projects successfully processes projects."""
        mock_load_prompt.return_value = "Projects prompt"
        mock_get_wiki_root.return_value = Path("/mock/wiki")

        projects = [{"raw_org_name": "Google", "title": "Search AI"}]
        resolved = {"Google": "google-inc"}
        wiki_outputs = []

        _generate_projects(self.mock_llm, projects, resolved, "2026-06-30", wiki_outputs)

        self.assertEqual(len(wiki_outputs), 1)
        self.assertEqual(wiki_outputs[0]["path"], "/mock/wiki/projects/project-search-ai.md")

    @patch("ingestion.generation.load_prompt")
    @patch("ingestion.generation.get_wiki_root")
    def test_generate_projects_exception(self, mock_get_wiki_root, mock_load_prompt):
        """Test _generate_projects handles exception gracefully on LLM failure."""
        mock_load_prompt.return_value = "Projects prompt"
        mock_get_wiki_root.return_value = Path("/mock/wiki")
        self.mock_llm.invoke.side_effect = Exception("LLM failure")

        projects = [{"raw_org_name": "Google", "title": "Search AI"}]
        resolved = {"Google": "google-inc"}
        wiki_outputs = []

        _generate_projects(self.mock_llm, projects, resolved, "2026-06-30", wiki_outputs)

        self.assertEqual(len(wiki_outputs), 1)
        self.assertEqual(wiki_outputs[0]["content"], "")
        self.assertEqual(len(wiki_outputs[0]["validation_errors"]), 1)

    @patch("ingestion.generation.load_prompt")
    @patch("ingestion.generation.get_wiki_root")
    def test_generate_patents_success(self, mock_get_wiki_root, mock_load_prompt):
        """Test _generate_patents successfully processes patents with ID."""
        mock_load_prompt.return_value = "Patents prompt"
        mock_get_wiki_root.return_value = Path("/mock/wiki")

        patents = [{"raw_org_name": "Google", "title": "Method for Search", "id": "US12345"}]
        resolved = {"Google": "google-inc"}
        wiki_outputs = []

        _generate_patents(self.mock_llm, patents, resolved, "2026-06-30", wiki_outputs)

        self.assertEqual(len(wiki_outputs), 1)
        self.assertEqual(wiki_outputs[0]["path"], "/mock/wiki/patents/patent-us12345.md")

    @patch("ingestion.generation.load_prompt")
    @patch("ingestion.generation.get_wiki_root")
    def test_generate_patents_no_id_success(self, mock_get_wiki_root, mock_load_prompt):
        """Test _generate_patents processes patents correctly when no ID is available."""
        mock_load_prompt.return_value = "Patents prompt"
        mock_get_wiki_root.return_value = Path("/mock/wiki")

        patents = [{"raw_org_name": "Google", "title": "Method for Search"}]
        resolved = {"Google": "google-inc"}
        wiki_outputs = []

        _generate_patents(self.mock_llm, patents, resolved, "2026-06-30", wiki_outputs)

        self.assertEqual(len(wiki_outputs), 1)
        self.assertEqual(wiki_outputs[0]["path"], "/mock/wiki/patents/patent-method-for-search.md")

    @patch("ingestion.generation.load_prompt")
    @patch("ingestion.generation.get_wiki_root")
    def test_generate_patents_exception(self, mock_get_wiki_root, mock_load_prompt):
        """Test _generate_patents handles exception gracefully on LLM failure."""
        mock_load_prompt.return_value = "Patents prompt"
        mock_get_wiki_root.return_value = Path("/mock/wiki")
        self.mock_llm.invoke.side_effect = Exception("LLM failure")

        patents = [{"raw_org_name": "Google", "title": "Method for Search"}]
        resolved = {"Google": "google-inc"}
        wiki_outputs = []

        _generate_patents(self.mock_llm, patents, resolved, "2026-06-30", wiki_outputs)

        self.assertEqual(len(wiki_outputs), 1)
        self.assertEqual(wiki_outputs[0]["content"], "")
        self.assertEqual(len(wiki_outputs[0]["validation_errors"]), 1)

    @patch("ingestion.generation.load_prompt")
    @patch("ingestion.generation.get_wiki_root")
    def test_generate_notes_success(self, mock_get_wiki_root, mock_load_prompt):
        """Test _generate_notes successfully processes notes."""
        mock_load_prompt.return_value = "Notes prompt"
        mock_get_wiki_root.return_value = Path("/mock/wiki")

        notes = [{
            "title": "Review 2024", "perspective": "Manager",
            "tags": ["annual-review"], "related_raw_orgs": ["Google"]
        }]
        resolved = {"Google": "google-inc"}
        wiki_outputs = []

        _generate_notes(self.mock_llm, notes, resolved, "2026-06-30", wiki_outputs)

        self.assertEqual(len(wiki_outputs), 1)
        self.assertEqual(wiki_outputs[0]["path"], "/mock/wiki/notes/note-review-2024.md")

    @patch("ingestion.generation.load_prompt")
    @patch("ingestion.generation.get_wiki_root")
    def test_generate_notes_exception(self, mock_get_wiki_root, mock_load_prompt):
        """Test _generate_notes handles exception gracefully on LLM failure."""
        mock_load_prompt.return_value = "Notes prompt"
        mock_get_wiki_root.return_value = Path("/mock/wiki")
        self.mock_llm.invoke.side_effect = Exception("LLM failure")

        notes = [{"title": "Review 2024"}]
        resolved = {}
        wiki_outputs = []

        _generate_notes(self.mock_llm, notes, resolved, "2026-06-30", wiki_outputs)

        self.assertEqual(len(wiki_outputs), 1)
        self.assertEqual(wiki_outputs[0]["content"], "")
        self.assertEqual(len(wiki_outputs[0]["validation_errors"]), 1)

    @patch("ingestion.generation.load_prompt")
    @patch("ingestion.generation.get_wiki_root")
    def test_generate_cover_letters_success(self, mock_get_wiki_root, mock_load_prompt):
        """Test _generate_cover_letters successfully processes cover letters."""
        mock_load_prompt.return_value = "Cover Letter prompt"
        mock_get_wiki_root.return_value = Path("/mock/wiki")

        cover_letters = [{"target_organization_raw": "Google", "title": "Google Staff Swe"}]
        resolved = {"Google": "google-inc"}
        wiki_outputs = []

        _generate_cover_letters(self.mock_llm, cover_letters, resolved, "2026-06-30", wiki_outputs)

        self.assertEqual(len(wiki_outputs), 1)
        self.assertEqual(wiki_outputs[0]["path"], "/mock/wiki/cover-letters/cover-letter-google-staff-swe.md")

    @patch("ingestion.generation.load_prompt")
    @patch("ingestion.generation.get_wiki_root")
    def test_generate_cover_letters_exception(self, mock_get_wiki_root, mock_load_prompt):
        """Test _generate_cover_letters handles exception gracefully on LLM failure."""
        mock_load_prompt.return_value = "Cover Letter prompt"
        mock_get_wiki_root.return_value = Path("/mock/wiki")
        self.mock_llm.invoke.side_effect = Exception("LLM failure")

        cover_letters = [{"target_organization_raw": "Google", "title": "Google Staff Swe"}]
        resolved = {"Google": "google-inc"}
        wiki_outputs = []

        _generate_cover_letters(self.mock_llm, cover_letters, resolved, "2026-06-30", wiki_outputs)

        self.assertEqual(len(wiki_outputs), 1)
        self.assertEqual(wiki_outputs[0]["content"], "")
        self.assertEqual(len(wiki_outputs[0]["validation_errors"]), 1)

    def test_generate_profile_skip(self):
        """Test _generate_profile skips generation when profile has no name."""
        wiki_outputs = []
        _generate_profile({}, "source.pdf", "2026-06-30", wiki_outputs)
        self.assertEqual(wiki_outputs, [])

    @patch("ingestion.generation.get_persona_slug")
    @patch("ingestion.generation.get_wiki_root")
    def test_generate_profile_new_and_existing(self, mock_get_wiki_root, mock_get_persona_slug):
        """Test _generate_profile handles both a new profile and reading existing created date on update."""
        mock_get_wiki_root.return_value = Path("/mock/wiki")
        mock_get_persona_slug.return_value = "alice-developer-person"
        
        # Scenario 1: New profile (no existing file)
        with patch("pathlib.Path.exists", return_value=False):
            wiki_outputs = []
            profile = {"name": "Alice Developer", "email": "alice@example.com"}
            _generate_profile(profile, "source.pdf", "2026-06-30", wiki_outputs)
            
            self.assertEqual(len(wiki_outputs), 1)
            self.assertEqual(wiki_outputs[0]["path"], "/mock/wiki/entities/alice-developer-person.md")
            self.assertIn("created: 2026-06-30", wiki_outputs[0]["content"])
            self.assertIn("updated: 2026-06-30", wiki_outputs[0]["content"])
            self.assertFalse(wiki_outputs[0]["merged"])

        # Scenario 2: Existing profile (preserves original created date)
        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.read_text", return_value="created: 2024-01-15\ntype: entity\ntags: []"):
            wiki_outputs = []
            profile = {"name": "Alice Developer", "email": "alice@example.com", "overview": "Experienced SWE"}
            _generate_profile(profile, "source.pdf", "2026-06-30", wiki_outputs)
            
            self.assertEqual(len(wiki_outputs), 1)
            self.assertIn("created: 2024-01-15", wiki_outputs[0]["content"])
            self.assertIn("updated: 2026-06-30", wiki_outputs[0]["content"])
            self.assertTrue(wiki_outputs[0]["merged"])

    def test_node_generator_short_circuit(self):
        """Test node_generator short-circuits and returns empty list when state has no extracted contents."""
        state = IngestionState()
        result = node_generator(state)
        self.assertEqual(result, {"wiki_outputs": []})

    @patch("ingestion.generation.get_persona_slug")
    @patch("ingestion.generation.get_model_for_step")
    @patch("ingestion.generation.get_schema_path")
    @patch("ingestion.generation.load_prompt")
    @patch("ingestion.generation.get_wiki_root")
    def test_node_generator_full_orchestration(self, mock_get_wiki_root, mock_load_prompt, mock_get_schema, mock_get_model, mock_get_persona_slug):
        """Test node_generator coordinates all sub-generators correctly."""
        mock_get_wiki_root.return_value = Path("/mock/wiki")
        mock_get_persona_slug.return_value = "alice-developer-person"
        mock_load_prompt.return_value = "Mock Prompt"
        mock_get_schema.return_value = Path("/mock/wiki/schema.md")
        mock_get_model.return_value = self.mock_llm

        state = IngestionState(
            extracted_roles=[{"raw_org_name": "Google", "title": "SWE"}],
            extracted_education=[{"raw_inst_name": "Stanford", "title": "BS"}],
            extracted_languages=[{"language": "Spanish"}],
            extracted_projects=[{"raw_org_name": "Google", "title": "Project X"}],
            extracted_patents=[{"raw_org_name": "Google", "title": "Patent Y"}],
            extracted_notes=[{"title": "Note Z"}],
            extracted_cover_letters=[{"target_organization_raw": "Google", "title": "CL"}],
            extracted_profile={"name": "Alice Developer"},
            resolved_entities={"Google": "google-inc", "Stanford": "stanford-university"},
            source_file="resume.pdf"
        )

        with patch("pathlib.Path.exists", return_value=False):
            result = node_generator(state)
            outputs = result["wiki_outputs"]
            # 8 outputs (roles, edu, languages, projects, patents, notes, CL, profile)
            self.assertEqual(len(outputs), 8)

    @patch("ingestion.generation.load_prompt")
    @patch("ingestion.generation.get_wiki_root")
    def test_edge_case_slugs_and_profile_exception(self, mock_get_wiki_root, mock_load_prompt):
        """Test fallback default slugs when input fields slugify to empty strings, and profile exception handling."""
        mock_load_prompt.return_value = "System prompt template"
        mock_get_wiki_root.return_value = Path("/mock/wiki")

        # Test experience empty title slug
        roles = [{"raw_org_name": "Intel Corp", "title": "$$$"}]
        resolved = {"Intel Corp": "intel-corp"}
        wiki_outputs = []
        _generate_experiences(self.mock_llm, roles, resolved, "2026-06-30", "Schema text", wiki_outputs)
        self.assertEqual(wiki_outputs[-1]["path"], "/mock/wiki/experiences/intel-corp-role.md")

        # Test education empty title slug
        education = [{"raw_inst_name": "Stanford", "title": "$$$"}]
        _generate_education(self.mock_llm, education, {"Stanford": "stanford"}, "2026-06-30", wiki_outputs)
        self.assertEqual(wiki_outputs[-1]["path"], "/mock/wiki/education/stanford-degree.md")

        # Test language empty slug
        languages = [{"language": "$$$"}]
        _generate_languages(self.mock_llm, languages, "2026-06-30", wiki_outputs)
        self.assertEqual(wiki_outputs[-1]["path"], "/mock/wiki/skills/lang-unknown.md")

        # Test project empty title slug
        projects = [{"raw_org_name": "Google", "title": "$$$"}]
        _generate_projects(self.mock_llm, projects, {"Google": "google"}, "2026-06-30", wiki_outputs)
        self.assertEqual(wiki_outputs[-1]["path"], "/mock/wiki/projects/project-project.md")

        # Test profile read existing created date exception (435-436)
        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.read_text", side_effect=Exception("Read failure")), \
             patch("ingestion.generation.get_persona_slug", return_value="alice-developer"):
            _generate_profile({"name": "Alice Developer"}, "source.pdf", "2026-06-30", wiki_outputs)
            self.assertIn("created: 2026-06-30", wiki_outputs[-1]["content"])


if __name__ == "__main__":
    unittest.main()
