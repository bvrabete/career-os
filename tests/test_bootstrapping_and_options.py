"""
Unit tests for validating the llm_wiki bootstrapping structure and CLI option configurations with dummy responses.
"""

import sys
from pathlib import Path
import tempfile
import shutil
from unittest.mock import patch, MagicMock

from ingestion.helpers import bootstrap_wiki_structure
import kb_ingest


class TestBootstrappingAndOptions:
    def setup_method(self):
        # Create a clean isolated temporary directory for wiki bootstrapping
        self.temp_dir = Path(tempfile.mkdtemp())
        self.wiki_dir = self.temp_dir / "llm-wiki"

    def teardown_method(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_complete_bootstrap_flow(self):
        """Test that bootstrap_wiki_structure creates all 14 folders and template files."""
        bootstrap_wiki_structure(self.wiki_dir)

        # Verify subdirectories are created under wiki/
        wiki_root = self.wiki_dir / "wiki"
        assert wiki_root.is_dir()

        expected_subdirs = [
            "experiences", "education", "entities", "projects", "skills",
            "sources", "concepts", "notes", "patents",
            "strategies", "queries", "media", "cover-letters"
        ]
        for subdir in expected_subdirs:
            assert (wiki_root / subdir).is_dir(), f"Subfolder {subdir} was not bootstrapped."

        assert (self.wiki_dir / "applications").is_dir()
        assert (self.wiki_dir / "applications" / "applications.yaml").is_file()
        assert (self.wiki_dir / "log.md").is_file()

        # Verify core blueprint templates
        assert (self.wiki_dir / "schema.md").is_file()
        assert (self.wiki_dir / "mappings.md").is_file()

    @patch("kb_ingest_graph.build_ingest_graph")
    @patch("kb_ingest.collect_files")
    @patch("kb_ingest.load_status")
    @patch("kb_ingest.save_status")
    @patch("kb_ingest._process_file")
    @patch("kb_ingest.validate_path")
    def test_kb_ingest_cli_options(self, mock_validate_path, mock_process_file, mock_save_status, mock_load_status, mock_collect_files, mock_build_graph):
        """Test the kb-ingest CLI entrypoint option flows with mock payloads."""
        dummy_file = self.temp_dir / "test_resume.pdf"
        dummy_file.write_text("dummy resume content", encoding="utf-8")
        bootstrap_wiki_structure(self.wiki_dir)

        mock_validate_path.return_value = dummy_file
        mock_collect_files.return_value = [dummy_file]
        mock_load_status.return_value = {"processed": {}}
        mock_process_file.return_value = (1, 0, 0)

        # Mock Graph compilation
        mock_graph = MagicMock()
        mock_build_graph.return_value = mock_graph

        test_args = [
            "kb-ingest",
            "--file", str(dummy_file),
            "--wiki-dir", str(self.wiki_dir),
            "--dry-run",
            "--force",
            "--skip-skills-sync"
        ]

        with patch.object(sys, 'argv', test_args):
            kb_ingest.main()

        # Assertions
        mock_build_graph.assert_called_with(dry_run=True)
        assert mock_process_file.call_args[1]["force"]
        assert mock_process_file.call_args[1]["dry_run"]
