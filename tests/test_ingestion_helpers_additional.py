"""Unit tests for remaining uncovered sections of ingestion/helpers.py."""
import unittest
import shutil
import tempfile
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

# Set up quiet logger during tests
logging.basicConfig(level=logging.ERROR)

from ingestion.helpers import (
    _bootstrap_templates_and_schema, _bootstrap_css_templates,
    bootstrap_wiki_structure, resolve_org, get_persona_slug_from_mappings,
    add_persona_mapping_if_missing, clean_frontmatter,
    _extract_start_date_from_file, _find_existing_wiki_file,
    find_existing_experience, find_existing_education, SCHEMA_MD
)


class TestIngestionHelpersAdditional(unittest.TestCase):
    """Deterministic offline unit tests for uncovered ingestion helpers."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=".")
        self.wiki_dir = Path(self.temp_dir.name) / "wiki_dir"
        self.wiki_root = self.wiki_dir / "wiki"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_bootstrap_templates_and_schema_exception(self):
        """Test _bootstrap_templates_and_schema exception handling when shutil.copy fails."""
        self.wiki_dir.mkdir(parents=True, exist_ok=True)
        self.wiki_root.mkdir(parents=True, exist_ok=True)
        # Patch shutil.copy to raise an Exception
        with patch("shutil.copy", side_effect=Exception("Copy failed")):
            _bootstrap_templates_and_schema(self.wiki_dir, self.wiki_root)
            # Check that mappings.md and log.md were created because those are done afterwards
            self.assertTrue((self.wiki_dir / "mappings.md").exists())
            self.assertTrue((self.wiki_root / "log.md").exists())

    def test_bootstrap_css_templates(self):
        """Test _bootstrap_css_templates success and exception flows."""
        self.wiki_dir.mkdir(parents=True, exist_ok=True)
        # We can run it directly! Since repo_templates_dir exists in the repository,
        # it will copy any existing .css templates into target_templates_dir.
        _bootstrap_css_templates(self.wiki_dir)
        target_templates_dir = self.wiki_dir / "templates"
        self.assertTrue(target_templates_dir.exists())

        # Test the exception path by patching shutil.copy to fail
        # and making sure it handles it gracefully
        shutil.rmtree(self.wiki_dir)
        self.wiki_dir.mkdir(parents=True, exist_ok=True)
        with patch("shutil.copy", side_effect=Exception("Copy failed")):
            _bootstrap_css_templates(self.wiki_dir)
            # The directory templates should still exist (mkdir runs before copy)
            self.assertTrue((self.wiki_dir / "templates").exists())

    def test_bootstrap_wiki_structure(self):
        """Test bootstrap_wiki_structure skips when not needed and runs when needed."""
        # Run scenario (directory is empty/non-existent)
        bootstrap_wiki_structure(self.wiki_dir)
        self.assertTrue(self.wiki_root.exists())
        self.assertTrue((self.wiki_root / "experiences").exists())
        self.assertTrue((self.wiki_dir / SCHEMA_MD).exists())

        # Skip scenario (already bootstrapped)
        # We modify one of the bootstrapped files or check that it doesn't try to recreate/re-copy
        with patch("ingestion.helpers._bootstrap_subdirs") as mock_subdirs:
            bootstrap_wiki_structure(self.wiki_dir)
            mock_subdirs.assert_not_called()

    def test_resolve_org_substring_matches(self):
        """Test resolve_org finds sub-slug overlaps."""
        mappings = {"google-cloud-platform": "gcp"}
        # "google-cloud" is a substring of "google-cloud-platform"
        self.assertEqual(resolve_org("google-cloud", mappings), "gcp")

    @patch("ingestion.helpers.get_mappings_path")
    def test_get_persona_slug_from_mappings(self, mock_get_mappings_path):
        """Test get_persona_slug_from_mappings with real file scenarios."""
        mappings_file = self.wiki_dir / "mappings.md"
        self.wiki_dir.mkdir(parents=True, exist_ok=True)
        mock_get_mappings_path.return_value = mappings_file

        # Scenario 1: mappings.md does not exist
        if mappings_file.exists():
            mappings_file.unlink()
        self.assertIsNone(get_persona_slug_from_mappings())

        # Scenario 2: File exists but no persona header
        mappings_file.write_text("## Some Other Header\n")
        self.assertIsNone(get_persona_slug_from_mappings())

        # Scenario 3: File exists with persona header, then exits section
        file_data = "## Persona Mappings\n## Other Section\n- **Canonical:** [[brad-vrabete]]\n"
        mappings_file.write_text(file_data)
        self.assertIsNone(get_persona_slug_from_mappings())

        # Scenario 4: File exists with valid persona canonical slug
        file_data_valid = "## Persona Mappings\n- **Canonical:** [[brad-vrabete]]\n"
        mappings_file.write_text(file_data_valid)
        self.assertEqual(get_persona_slug_from_mappings(), "brad-vrabete")

    @patch("ingestion.helpers.get_mappings_path")
    def test_add_persona_mapping_if_missing_edge_cases(self, mock_get_mappings_path):
        """Test add_persona_mapping_if_missing with missing mappings, existing slug, and various insertions."""
        mappings_file = self.wiki_dir / "mappings.md"
        self.wiki_dir.mkdir(parents=True, exist_ok=True)
        mock_get_mappings_path.return_value = mappings_file

        # Scenario 1: mappings_path does not exist
        if mappings_file.exists():
            mappings_file.unlink()
        self.assertIsNone(add_persona_mapping_if_missing("Brad", "brad-vrabete"))

        # Scenario 2: Slug already in content
        mappings_file.write_text("Some text with [[brad-vrabete]] mapping.")
        self.assertIsNone(add_persona_mapping_if_missing("Brad", "brad-vrabete"))

        # Scenario 3: Next line starts with "##" in section
        mappings_file.write_text("## Persona Mappings\n## Next Section")
        add_persona_mapping_if_missing("Brad", "brad-vrabete")
        written = mappings_file.read_text()
        self.assertIn("- **Canonical:** [[brad-vrabete]]", written)

        # Scenario 4: Section ends without adding (in_section and not added)
        mappings_file.write_text("## Persona Mappings\n- Some entry")
        add_persona_mapping_if_missing("Brad", "brad-vrabete")
        written = mappings_file.read_text()
        self.assertIn("- **Canonical:** [[brad-vrabete]]", written)

        # Scenario 5: Header not added (appends header at end)
        mappings_file.write_text("Some file without persona header")
        add_persona_mapping_if_missing("Brad", "brad-vrabete")
        written = mappings_file.read_text()
        self.assertIn("## Persona Mappings", written)
        self.assertIn("- **Canonical:** [[brad-vrabete]]", written)

    def test_clean_frontmatter_edge_cases(self):
        """Test clean_frontmatter with unclosed fence and missing boundary indices."""
        # Unclosed fence
        unclosed = "```markdown\n---\ntitle: Unclosed\n"
        self.assertEqual(clean_frontmatter(unclosed), unclosed.strip())

        # Less than 2 boundaries
        no_boundaries = "No boundaries here."
        self.assertEqual(clean_frontmatter(no_boundaries), no_boundaries)

    def test_extract_start_date_from_file_edge_cases(self):
        """Test _extract_start_date_from_file error paths."""
        self.wiki_dir.mkdir(parents=True, exist_ok=True)
        f = self.wiki_dir / "test.md"

        # No frontmatter match
        f.write_text("No frontmatter here.")
        self.assertIsNone(_extract_start_date_from_file(f, "slug"))

        # Slug not in frontmatter
        f.write_text("---\ntitle: Role\n---\n")
        self.assertIsNone(_extract_start_date_from_file(f, "slug"))

        # safe_load exception
        f.write_text("---\ntitle: [[slug]]\n  invalid yaml:\n  - some:\n---\n")
        self.assertIsNone(_extract_start_date_from_file(f, "slug"))

    @patch("ingestion.helpers.get_wiki_root")
    def test_find_existing_wiki_file_edge_cases(self, mock_get_wiki_root):
        """Test _find_existing_wiki_file directory missing, empty candidates, and invalid target date."""
        self.wiki_dir.mkdir(parents=True, exist_ok=True)
        self.wiki_root.mkdir(parents=True, exist_ok=True)

        # Target dir missing
        mock_get_wiki_root.return_value = self.wiki_root / "does_not_exist"
        self.assertIsNone(_find_existing_wiki_file("subdir", "slug", Path("gen")))

        # No candidates found
        target_subdir = self.wiki_root / "experiences"
        target_subdir.mkdir(parents=True, exist_ok=True)
        mock_get_wiki_root.return_value = self.wiki_root
        
        gen_path = self.wiki_dir / "gen.md"
        self.assertIsNone(_find_existing_wiki_file("experiences", "slug", gen_path))
        gen_path.write_text("Hello")
        self.assertEqual(_find_existing_wiki_file("experiences", "slug", gen_path), gen_path)

        # Target year ValueError / start date extraction and multiple candidates
        candidate_file_1 = target_subdir / "role_1.md"
        candidate_file_1.write_text("---\ntitle: [[slug]]\ndates:\n  start: 2020-01-01\n---\n")
        
        res = _find_existing_wiki_file("experiences", "slug", gen_path, "invalid-year")
        self.assertEqual(res, candidate_file_1)

        # Multiple candidates found (select max modification time or matching year)
        candidate_file_2 = target_subdir / "role_2.md"
        candidate_file_2.write_text("---\ntitle: [[slug]]\ndates:\n  start: 2022-01-01\n---\n")
        
        import os, time
        os.utime(candidate_file_1, (time.time() - 100, time.time() - 100))
        os.utime(candidate_file_2, (time.time(), time.time()))

        # If we ask for start_date 2020-05-01, should return candidate_file_1 (matching year within 1)
        res = _find_existing_wiki_file("experiences", "slug", gen_path, "2020-05-01")
        self.assertEqual(res, candidate_file_1)

        # If we ask for start_date without year, should return newest modified (candidate_file_2)
        res = _find_existing_wiki_file("experiences", "slug", gen_path, "")
        self.assertEqual(res, candidate_file_2)

    def test_find_existing_experience_and_education(self):
        """Test wrapper functions for experiences and education."""
        with patch("ingestion.helpers._find_existing_wiki_file") as mock_find:
            find_existing_experience("org", Path("gen"), "2020")
            mock_find.assert_called_once_with("experiences", "org", Path("gen"), "2020")

        with patch("ingestion.helpers._find_existing_wiki_file") as mock_find:
            find_existing_education("inst", Path("gen"), "2020")
            mock_find.assert_called_once_with("education", "inst", Path("gen"), "2020")


if __name__ == "__main__":
    unittest.main()
