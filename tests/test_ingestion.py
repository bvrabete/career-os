"""Unit tests for the ingestion pipeline helpers and validation logic."""
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from ingestion.helpers import (
    slugify, resolve_org, get_persona_slug, clean_frontmatter
)
from ingestion.nodes import (
    node_validator, _validate_experience, _validate_education, _validate_skill
)
from ingestion.state import IngestionState


class TestIngestionHelpers(unittest.TestCase):
    """Deterministic offline tests for ingestion pure helper functions."""

    def test_slugify(self):
        """Test slugify function handles special characters and casing."""
        self.assertEqual(slugify("Intel Corp"), "intel-corp")
        self.assertEqual(slugify("Google (DeepMind)"), "google-deepmind")
        self.assertEqual(slugify("   Leading -- trailing  "), "leading-trailing")
        self.assertEqual(slugify("simple-slug"), "simple-slug")

    def test_resolve_org_exact_match(self):
        """Test resolve_org finds exact mappings."""
        mappings = {"intel corp": "intel-corporation", "google": "google-inc"}
        self.assertEqual(resolve_org("Intel Corp", mappings), "intel-corporation")
        self.assertEqual(resolve_org("Unknown Org", mappings), "unknown-org")

    def test_resolve_org_alias_match(self):
        """Test resolve_org resolves aliases or slugified overlaps."""
        mappings = {"example corporation": "example-corp"}
        self.assertEqual(resolve_org("example-corporation", mappings), "example-corp")

    def test_clean_frontmatter_fences(self):
        """Test clean_frontmatter removes code fences, blocks and normalizes formatting."""
        wrapped = "```yaml\n---\ntype: experience\n---\n```\nBody content."
        cleaned = clean_frontmatter(wrapped)
        self.assertIn("type: experience", cleaned)
        self.assertNotIn("```", cleaned)
        self.assertTrue(cleaned.endswith("Body content."))

    def test_clean_frontmatter_html_comments(self):
        """Test clean_frontmatter strips HTML comments from YAML block."""
        wrapped = "---\ntype: experience <!-- comment -->\n---\nBody"
        cleaned = clean_frontmatter(wrapped)
        self.assertIn("type: experience", cleaned)
        self.assertNotIn("comment", cleaned)


class TestIngestionValidation(unittest.TestCase):
    """Deterministic offline tests for ingestion frontmatter validation schemas."""

    def test_validate_experience_success(self):
        """Test _validate_experience succeeds on correct schema."""
        fm = {
            "type": "experience",
            "title": "Staff Manager",
            "organization": "[[intel-corporation]]",
            "dates": {"start": "2020-01-01", "end": "Present"},
            "tracks": ["Engineering"],
            "skills": ["Python"]
        }
        errors = []
        _validate_experience(fm, errors)
        self.assertEqual(errors, [])

    def test_validate_experience_missing_fields(self):
        """Test _validate_experience fails when required fields are missing."""
        fm = {
            "type": "experience",
            "title": "Staff Manager"
        }
        errors = []
        _validate_experience(fm, errors)
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("Missing frontmatter fields" in err for err in errors))


    def test_validate_experience_invalid_org_link(self):
        """Test _validate_experience fails on raw string organization names without [[slug]]."""
        fm = {
            "type": "experience",
            "title": "Staff Manager",
            "organization": "Intel Corp",
            "dates": {"start": "2020-01-01", "end": "Present"},
            "tracks": ["Engineering"],
            "skills": ["Python"]
        }
        errors = []
        _validate_experience(fm, errors)
        self.assertTrue(any("organization field missing [[slug]]" in err for err in errors))

    def test_validate_experience_invalid_date(self):
        """Test _validate_experience fails on invalid date format."""
        fm = {
            "type": "experience",
            "title": "Staff Manager",
            "organization": "[[intel-corp]]",
            "dates": {"start": "2020/01/01", "end": "Present"},
            "tracks": ["Engineering"],
            "skills": ["Python"]
        }
        errors = []
        _validate_experience(fm, errors)
        self.assertTrue(any("dates.start invalid format" in err for err in errors))


if __name__ == "__main__":
    unittest.main()
