"""Unit tests for the ingestion pipeline helpers and validation logic."""

import unittest
import tempfile
import shutil
import re
import uuid
import os
import yaml
from pathlib import Path
from unittest.mock import patch, MagicMock
from ingestion.helpers import (
    slugify,
    resolve_org,
    get_persona_slug,
    clean_frontmatter,
    validate_path,
    get_wiki_root,
    get_schema_path,
    get_mappings_path,
    load_prompt,
    _bootstrap_subdirs,
    _bootstrap_templates_and_schema,
    get_persona_slug_from_mappings,
    add_persona_mapping_if_missing,
    llm_text,
    strip_fences,
    _extract_frontmatter_from_fence,
    _clean_frontmatter_lines,
    _clean_body_lines,
    _extract_start_date_from_file,
    _filter_by_matching_year,
    _find_existing_wiki_file,
    find_existing_experience,
    find_existing_education,
)
from ingestion.nodes import (
    node_validator,
    _validate_experience,
    _validate_education,
    _validate_skill,
)
from ingestion.state import IngestionState

MAPPINGS_FILE_NAME = "mappings.md"


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

    def test_validate_path_valid(self):
        """Test validate_path with valid user directory path."""
        home_path = Path("~").expanduser().resolve()
        valid_file = home_path / "some_file_test.txt"
        validated = validate_path(valid_file)
        self.assertEqual(validated, valid_file.resolve())

    def test_validate_path_invalid_traversal(self):
        """Test validate_path raises ValueError on path traversal escape."""
        with self.assertRaises(ValueError):
            validate_path("/etc/passwd")

    @patch("kb_config.get_wiki_dir")
    def test_get_wiki_paths(self, mock_get_wiki_dir):
        """Test the path getters return correct absolute paths."""
        mock_get_wiki_dir.return_value = Path("/tmp/mock-wiki")
        self.assertEqual(get_wiki_root(), Path("/tmp/mock-wiki/wiki"))
        self.assertEqual(get_schema_path(), Path("/tmp/mock-wiki/schema.md"))
        self.assertEqual(get_mappings_path(), Path("/tmp/mock-wiki/mappings.md"))

    def test_load_prompt_exists(self):
        """Test load_prompt reads existing file correctly."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "pathlib.Path.read_text", return_value="System Prompt Template"
            ) as mock_read,
        ):
            text = load_prompt("test_prompt.txt")
            self.assertEqual(text, "System Prompt Template")

    def test_load_prompt_not_found(self):
        """Test load_prompt raises FileNotFoundError if file missing."""
        with patch("pathlib.Path.exists", return_value=False):
            with self.assertRaises(FileNotFoundError):
                load_prompt("nonexistent.txt")

    def test_bootstrap_subdirs(self):
        """Test bootstrapping subdirectories creates all folders."""
        # Use a temporary directory inside user home to avoid path traversal errors
        temp_dir = Path.home() / f".tmp_test_ingestion_{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            _bootstrap_subdirs(temp_dir)
            for subdir in [
                "experiences",
                "education",
                "entities",
                "projects",
                "skills",
            ]:
                self.assertTrue((temp_dir / subdir).exists())
                self.assertTrue((temp_dir / subdir).is_dir())
        finally:
            shutil.rmtree(temp_dir)

    def test_bootstrap_templates_and_schema_creates_defaults(self):
        """Test bootstrapping writes default files if templates not found."""
        temp_dir = Path.home() / f".tmp_test_ingestion_{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        wiki_root = temp_dir / "wiki"
        wiki_root.mkdir()
        try:
            with patch("pathlib.Path.exists", return_value=False):
                _bootstrap_templates_and_schema(temp_dir, wiki_root)
            self.assertTrue((temp_dir / "schema.md").exists())
            self.assertTrue((temp_dir / MAPPINGS_FILE_NAME).exists())
            self.assertTrue((wiki_root / "log.md").exists())
        finally:
            shutil.rmtree(temp_dir)

    def test_llm_text_str_and_list(self):
        """Test llm_text conversion for standard str and LangChain list contents."""
        self.assertEqual(llm_text("Direct string"), "Direct string")
        self.assertEqual(llm_text(["part1", 2, "part3"]), "part1 2 part3")

    def test_strip_fences(self):
        """Test strip_fences removes markdown syntax wrapping."""
        self.assertEqual(strip_fences('```json\n{"key": "val"}\n```'), '{"key": "val"}')
        self.assertEqual(strip_fences("```\nplain text\n```"), "plain text")

    def test_clean_frontmatter_lines_fences(self):
        """Test internal _clean_frontmatter_lines helper."""
        lines = ["```yaml", "key: value", "  nested: <!-- comment --> secret", "```"]
        cleaned = _clean_frontmatter_lines(lines)
        self.assertIn("key: value", cleaned)
        self.assertIn("nested:  secret", cleaned)
        self.assertNotIn("```yaml", cleaned)

    def test_clean_body_lines_strips(self):
        """Test internal _clean_body_lines helper removes starting/ending empty lines and fences."""
        lines = ["```", "", "Actual content line", "```", ""]
        cleaned = _clean_body_lines(lines)
        self.assertEqual(cleaned, "Actual content line")


class TestWikiFileResolution(unittest.TestCase):
    """Tests file matching and resolution logic inside helpers."""

    def setUp(self):
        # Create temp dir under user home to satisfy validate_path bounds
        self.temp_dir = Path.home() / f".tmp_test_ingestion_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.wiki_dir = self.temp_dir / "wiki"
        self.wiki_dir.mkdir()
        (self.wiki_dir / "experiences").mkdir()
        (self.wiki_dir / "education").mkdir()

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    @patch("ingestion.helpers.get_wiki_root")
    def test_extract_start_date_from_file_success(self, mock_get_wiki_root):
        mock_get_wiki_root.return_value = self.wiki_dir
        f_path = self.wiki_dir / "experiences" / "role.md"
        content = """---
type: experience
organization: "[[org-slug]]"
dates:
  start: "2019-01-01"
---
Some body text.
"""
        f_path.write_text(content, encoding="utf-8")
        start = _extract_start_date_from_file(f_path, "org-slug")
        self.assertEqual(start, "2019-01-01")

    @patch("ingestion.helpers.get_wiki_root")
    def test_find_existing_experience_by_year(self, mock_get_wiki_root):
        mock_get_wiki_root.return_value = self.wiki_dir

        # Write candidate file with org slug inside frontmatter
        f_path1 = self.wiki_dir / "experiences" / "company_old.md"
        f_path1.write_text(
            '---\ntype: experience\norganization: "[[company-slug]]"\ndates:\n  start: "2015-05-15"\n---\n',
            encoding="utf-8",
        )

        f_path2 = self.wiki_dir / "experiences" / "company_new.md"
        f_path2.write_text(
            '---\ntype: experience\norganization: "[[company-slug]]"\ndates:\n  start: "2020-03-20"\n---\n',
            encoding="utf-8",
        )

        gen_path = self.wiki_dir / "experiences" / "generated.md"

        # Match close to 2020 (start date 2020-01-01)
        found = find_existing_experience("company-slug", gen_path, "2020-01-01")
        self.assertEqual(found, f_path2)

        # Match close to 2015 (start date 2014-12-31)
        found_old = find_existing_experience("company-slug", gen_path, "2014-12-31")
        self.assertEqual(found_old, f_path1)

    @patch("ingestion.helpers.get_wiki_root")
    def test_find_existing_education_one_candidate(self, mock_get_wiki_root):
        mock_get_wiki_root.return_value = self.wiki_dir
        f_path = self.wiki_dir / "education" / "uni.md"
        f_path.write_text(
            '---\ntype: education\ninstitution: "[[uni-slug]]"\ndates:\n  start: "2012-09-01"\n---\n',
            encoding="utf-8",
        )

        gen_path = self.wiki_dir / "education" / "generated.md"
        found = find_existing_education("uni-slug", gen_path, "")
        self.assertEqual(found, f_path)


class TestIngestionPersonaMappings(unittest.TestCase):
    """Tests mappings.md parsing and mapping additions."""

    def setUp(self):
        self.temp_dir = Path.home() / f".tmp_test_ingestion_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.mappings_path = self.temp_dir / MAPPINGS_FILE_NAME
        content = """# Entity Aliases & Mappings

## Organization Mappings

- **Canonical:** [[intel-corporation]]
  - Aliases: `Intel Corp`, `Intel`

## Persona Mappings

- **Canonical:** [[brad-vrabete]]
  - Aliases: `Brad`, `Vrabete`
"""
        self.mappings_path.write_text(content, encoding="utf-8")

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    @patch("ingestion.helpers.get_mappings_path")
    def test_get_persona_slug_from_mappings_success(self, mock_get_mappings_path):
        mock_get_mappings_path.return_value = self.mappings_path
        slug = get_persona_slug_from_mappings()
        self.assertEqual(slug, "brad-vrabete")

    @patch("ingestion.helpers.get_mappings_path")
    def test_add_persona_mapping_if_missing(self, mock_get_mappings_path):
        mock_get_mappings_path.return_value = self.mappings_path
        add_persona_mapping_if_missing("Staff Person", "staff-person")

        # Verify it was added
        updated_content = self.mappings_path.read_text(encoding="utf-8")
        self.assertIn("[[staff-person]]", updated_content)
        self.assertIn("Staff Person", updated_content)

    @patch("ingestion.helpers.get_mappings_path")
    def test_get_persona_slug_already_exists(self, mock_get_mappings_path):
        mock_get_mappings_path.return_value = self.mappings_path
        slug = get_persona_slug("Brad")
        self.assertEqual(slug, "brad-vrabete")


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
            "skills": ["Python"],
        }
        errors = []
        _validate_experience(fm, errors)
        self.assertEqual(errors, [])

    def test_validate_experience_missing_fields(self):
        """Test _validate_experience fails when required fields are missing."""
        fm = {"type": "experience", "title": "Staff Manager"}
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
            "skills": ["Python"],
        }
        errors = []
        _validate_experience(fm, errors)
        self.assertTrue(
            any("organization field missing [[slug]]" in err for err in errors)
        )

    def test_validate_experience_invalid_date(self):
        """Test _validate_experience fails on invalid date format."""
        fm = {
            "type": "experience",
            "title": "Staff Manager",
            "organization": "[[intel-corp]]",
            "dates": {"start": "2020/01/01", "end": "Present"},
            "tracks": ["Engineering"],
            "skills": ["Python"],
        }
        errors = []
        _validate_experience(fm, errors)
        self.assertTrue(any("dates.start invalid format" in err for err in errors))

    def test_validate_education_success(self):
        """Test _validate_education succeeds on correct schema."""
        fm = {
            "type": "education",
            "title": "BSc Computer Science",
            "institution": "[[university-of-test]]",
            "dates": {"start": "2015-09-01", "end": "2018-06-30"},
            "status": "Completed",
            "major": "Computer Science",
            "minor": "Mathematics",
        }
        errors = []
        _validate_education(fm, errors)
        self.assertEqual(errors, [])

    def test_validate_skill_success(self):
        """Test _validate_skill succeeds on correct schema."""
        fm = {
            "type": "skill",
            "title": "Python Programming",
            "category": "Language-Code",
            "proficiency": "Expert",
        }
        errors = []
        _validate_skill(fm, errors)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
