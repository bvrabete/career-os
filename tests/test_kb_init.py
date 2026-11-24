"""Unit tests for kb-init bootstrapping and fail-fast validation."""
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from ingestion.bootstrapping import bootstrap_wiki_structure, is_wiki_initialized
from kb_init import main as kb_init_main


class TestKBInitAndBootstrapping:
    """Test suite for wiki bootstrapping and initialization checks."""

    def setup_method(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_is_wiki_initialized_false_on_empty(self):
        assert not is_wiki_initialized(self.test_dir)
        assert not is_wiki_initialized(self.test_dir / "nonexistent")

    def test_bootstrap_wiki_structure(self):
        assert not is_wiki_initialized(self.test_dir)
        bootstrap_wiki_structure(self.test_dir)
        assert is_wiki_initialized(self.test_dir)

        wiki_root = self.test_dir / "wiki"
        assert wiki_root.is_dir()
        assert (self.test_dir / "schema.md").exists()
        assert (self.test_dir / "mappings.md").exists()
        assert (self.test_dir / "log.md").exists()
        assert (self.test_dir / "applications" / "applications.yaml").exists()

        # Verify essential subdirectories and .gitkeep exist
        for subdir in ["experiences", "education", "projects", "skills", "case-studies", "strategies", "voice"]:
            folder = wiki_root / subdir
            assert folder.is_dir(), f"Missing directory: {subdir}"
            assert any(folder.iterdir()), f"Folder is empty: {subdir}"

    def test_kb_init_cli_flow(self):
        target_wiki = self.test_dir / "my_new_wiki"
        with patch("sys.argv", ["kb-init", "--wiki-dir", str(target_wiki)]), patch("builtins.print"):
            kb_init_main()
            assert is_wiki_initialized(target_wiki)
