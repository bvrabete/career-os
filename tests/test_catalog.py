"""Unit tests for knowledge base catalog generation."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.catalog import generate_catalog, load_catalog, save_catalog


class TestCatalogIndexing(unittest.TestCase):
    """Test suite for catalog.json generation and parsing."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.wiki_dir = self.test_dir / "wiki"
        self.wiki_dir.mkdir(parents=True, exist_ok=True)

        # Seed dummy experience
        exp_dir = self.wiki_dir / "experiences"
        exp_dir.mkdir(parents=True, exist_ok=True)
        (exp_dir / "google.md").write_text(
            "---\norganization: Google\nrole: Staff SWE\nstart_date: 2020\nend_date: 2023\n---\n"
            "- Built distributed engine\n- Mentored 10 engineers\nSee [[case-studies/google-perf]]",
            encoding="utf-8"
        )

        # Seed dummy case study
        cs_dir = self.wiki_dir / "case-studies"
        cs_dir.mkdir(parents=True, exist_ok=True)
        (cs_dir / "google-perf.md").write_text(
            "---\ntitle: Google Performance Boost\nrelated_experience: google\n---\nDeep dive details.",
            encoding="utf-8"
        )

        # Seed dummy project
        proj_dir = self.wiki_dir / "projects"
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "career-os.md").write_text(
            "---\nname: CareerOS\nproject_nature: side_project\ntechnologies: [Python, LangGraph]\n---\n",
            encoding="utf-8"
        )

        # Seed dummy skills
        skills_dir = self.wiki_dir / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        (skills_dir / "python.md").write_text("# Python\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_generate_catalog(self):
        cat = generate_catalog(self.test_dir)
        self.assertEqual(cat["metadata"]["total_experiences"], 1)
        self.assertEqual(cat["metadata"]["total_case_studies"], 1)
        self.assertEqual(cat["metadata"]["total_projects"], 1)
        self.assertEqual(cat["metadata"]["total_skills_categories"], 1)

        exp = cat["experiences"][0]
        self.assertEqual(exp["organization"], "Google")
        self.assertEqual(exp["achievements_count"], 2)
        self.assertEqual(exp["case_studies_count"], 1)

    def test_save_and_load_catalog(self):
        target_path = save_catalog(self.test_dir)
        self.assertTrue(target_path.exists())

        loaded = load_catalog(self.test_dir)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["metadata"]["total_experiences"], 1)


if __name__ == "__main__":
    unittest.main()
