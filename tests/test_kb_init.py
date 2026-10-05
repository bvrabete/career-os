"""Unit tests for kb-init bootstrapping and fail-fast validation."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ingestion.bootstrapping import bootstrap_wiki_structure, is_wiki_initialized
from kb_init import main as kb_init_main


class TestKBInitAndBootstrapping(unittest.TestCase):
    """Test suite for wiki bootstrapping and initialization checks."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_is_wiki_initialized_false_on_empty(self):
        self.assertFalse(is_wiki_initialized(self.test_dir))
        self.assertFalse(is_wiki_initialized(self.test_dir / "nonexistent"))

    def test_bootstrap_wiki_structure(self):
        self.assertFalse(is_wiki_initialized(self.test_dir))
        bootstrap_wiki_structure(self.test_dir)
        self.assertTrue(is_wiki_initialized(self.test_dir))

        wiki_root = self.test_dir / "wiki"
        self.assertTrue(wiki_root.is_dir())
        self.assertTrue((self.test_dir / "schema.md").exists())
        self.assertTrue((self.test_dir / "mappings.md").exists())
        self.assertTrue((wiki_root / "applications.yaml").exists())

        # Verify essential subdirectories and .gitkeep exist
        for subdir in ["experiences", "education", "projects", "skills", "case-studies", "strategies", "voice"]:
            folder = wiki_root / subdir
            self.assertTrue(folder.is_dir(), f"Missing directory: {subdir}")
            self.assertTrue(any(folder.iterdir()), f"Folder is empty: {subdir}")

    def test_kb_init_cli_flow(self):
        target_wiki = self.test_dir / "my_new_wiki"
        with patch("sys.argv", ["kb-init", "--wiki-dir", str(target_wiki)]), patch("builtins.print"):
            kb_init_main()
            self.assertTrue(is_wiki_initialized(target_wiki))


if __name__ == "__main__":
    unittest.main()
