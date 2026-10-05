"""Unit tests for the Applications CRM registry."""
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.crm import load_applications, record_application


class TestApplicationsCRM(unittest.TestCase):
    """Test suite for wiki/applications.yaml lifecycle."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.wiki_dir = self.test_dir / "wiki"
        self.wiki_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_load_empty_crm(self):
        apps = load_applications(self.test_dir)
        self.assertEqual(apps, [])

    def test_record_application_appends_new(self):
        record = {
            "company": "Acme Corp",
            "job_title": "Staff Engineer",
            "date": "2026-10-03",
            "strategy": "emea",
            "ats_score": 92,
            "output_markdown": "synthesis/cv.md",
        }
        res = record_application(self.test_dir, record)
        self.assertEqual(res["company"], "Acme Corp")

        apps = load_applications(self.test_dir)
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]["company"], "Acme Corp")
        self.assertEqual(apps[0]["ats_score"], 92)

    def test_record_application_overwrites_same_day(self):
        record_v1 = {
            "company": "Acme Corp",
            "job_title": "Staff Engineer",
            "date": "2026-10-03",
            "ats_score": 85,
            "output_markdown": "draft_v1.md",
        }
        record_application(self.test_dir, record_v1)

        # Overwrite on the same day for same company & role
        record_v2 = {
            "company": "Acme Corp",
            "job_title": "Staff Engineer",
            "date": "2026-10-03",
            "ats_score": 95,
            "output_markdown": "draft_v2.md",
            "output_pdf": "draft_v2.pdf",
        }
        record_application(self.test_dir, record_v2)

        apps = load_applications(self.test_dir)
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]["ats_score"], 95)
        self.assertEqual(apps[0]["output_markdown"], "draft_v2.md")
        self.assertEqual(apps[0]["output_pdf"], "draft_v2.pdf")

    def test_record_application_multiple_different_companies(self):
        record1 = {"company": "Acme Corp", "job_title": "Engineer", "date": "2026-10-03"}
        record2 = {"company": "Beta LLC", "job_title": "Director", "date": "2026-10-03"}
        record_application(self.test_dir, record1)
        record_application(self.test_dir, record2)

        apps = load_applications(self.test_dir)
        self.assertEqual(len(apps), 2)


if __name__ == "__main__":
    unittest.main()
