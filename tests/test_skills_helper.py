import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile
import shutil

from generation.skills_helper import (
    get_skill_slug,
    extract_skills_from_file,
    gather_skills_from_directory,
    get_all_candidate_skills,
    run_skills_sync,
    get_compact_skills_list,
)

class TestSkillsHelper(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.wiki_dir = Path(self.temp_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir)

    def test_get_skill_slug_basic(self) -> None:
        """Test simple slug generation and cleanups."""
        self.assertEqual(get_skill_slug("Python"), "python")
        self.assertEqual(get_skill_slug("Python.md"), "python")
        self.assertEqual(get_skill_slug("  Docker  "), "docker")

    def test_get_skill_slug_common_overrides(self) -> None:
        """Test COMMON_SLUGS mapping overrides."""
        self.assertEqual(get_skill_slug("C#"), "c-sharp")
        self.assertEqual(get_skill_slug("C++"), "c-plus-plus")
        self.assertEqual(get_skill_slug(".NET"), "dotnet")
        self.assertEqual(get_skill_slug(".NET Core"), "dotnet-core")
        self.assertEqual(get_skill_slug("F#"), "f-sharp")

    def test_get_skill_slug_complex(self) -> None:
        """Test special character removal and normalization."""
        self.assertEqual(get_skill_slug("React Native!"), "react-native")
        self.assertEqual(get_skill_slug("CI/CD Pipeline"), "cicd-pipeline")

    def test_extract_skills_from_file_missing_and_invalid(self) -> None:
        """Test parsing with missing, malformed, or empty frontmatter files."""
        # Missing file
        self.assertEqual(extract_skills_from_file(self.wiki_dir / "does_not_exist.md"), [])

        # No frontmatter
        file_no_fm = self.wiki_dir / "no_fm.md"
        file_no_fm.write_text("Just some text", encoding="utf-8")
        self.assertEqual(extract_skills_from_file(file_no_fm), [])

        # Invalid frontmatter YAML
        file_bad_fm = self.wiki_dir / "bad_fm.md"
        file_bad_fm.write_text("---\nskills:\n  - [unclosed bracket\n---", encoding="utf-8")
        self.assertEqual(extract_skills_from_file(file_bad_fm), [])

        # Non-list skills
        file_not_list = self.wiki_dir / "not_list.md"
        file_not_list.write_text("---\nskills: python\n---", encoding="utf-8")
        self.assertEqual(extract_skills_from_file(file_not_list), [])

    def test_extract_skills_from_file_success(self) -> None:
        """Test successfully parsing valid skill entries."""
        file_ok = self.wiki_dir / "ok.md"
        file_ok.write_text("---\ntitle: Role\nskills:\n  - Python\n  - Kubernetes\n  - \n---", encoding="utf-8")
        self.assertEqual(extract_skills_from_file(file_ok), ["Python", "Kubernetes"])

    def test_gather_skills_from_directory(self) -> None:
        """Test scanning files in a directory to gather unique skills."""
        # Missing directory
        self.assertEqual(gather_skills_from_directory(self.wiki_dir / "missing_folder"), set())

        # Setup directory with valid and invalid files
        target_dir = self.wiki_dir / "exp"
        target_dir.mkdir()
        
        file1 = target_dir / "role1.md"
        file1.write_text("---\nskills:\n  - Python\n  - Git\n---", encoding="utf-8")
        
        file2 = target_dir / "role2.md"
        file2.write_text("---\nskills:\n  - Git\n  - Docker\n---", encoding="utf-8")

        file_txt = target_dir / "other.txt"
        file_txt.write_text("---\nskills:\n  - Python\n---", encoding="utf-8") # should be skipped because not .md

        skills = gather_skills_from_directory(target_dir)
        self.assertEqual(skills, {"Python", "Git", "Docker"})

    def test_get_all_candidate_skills(self) -> None:
        """Test aggregating skills from experiences and projects directories."""
        exp_dir = self.wiki_dir / "wiki" / "experiences"
        exp_dir.mkdir(parents=True)
        proj_dir = self.wiki_dir / "wiki" / "projects"
        proj_dir.mkdir(parents=True)

        f1 = exp_dir / "exp1.md"
        f1.write_text("---\nskills:\n  - React\n---", encoding="utf-8")

        f2 = proj_dir / "proj1.md"
        f2.write_text("---\nskills:\n  - Python\n---", encoding="utf-8")

        skills = get_all_candidate_skills(self.wiki_dir)
        self.assertEqual(skills, ["Python", "React"]) # returns sorted list

    def test_run_skills_sync_dry_run_and_active(self) -> None:
        """Test the sync execution under dry-run and write operations."""
        exp_dir = self.wiki_dir / "wiki" / "experiences"
        exp_dir.mkdir(parents=True)
        skills_dir = self.wiki_dir / "wiki" / "skills"

        # Create experiences that use python and kubernetes
        f1 = exp_dir / "intel.md"
        f1.write_text("---\nskills:\n  - Python.md\n  - Kubernetes\n  - \n---", encoding="utf-8")

        # 1. Dry run sync (should not write files or create skills folder)
        run_skills_sync(self.wiki_dir, dry_run=True)
        self.assertFalse(skills_dir.exists())

        # 2. Active run sync (should write the files)
        run_skills_sync(self.wiki_dir, dry_run=False)
        self.assertTrue(skills_dir.exists())
        
        python_skill_file = skills_dir / "python.md"
        self.assertTrue(python_skill_file.exists())
        
        content = python_skill_file.read_text(encoding="utf-8")
        self.assertIn("title: Python", content)
        self.assertIn("related_experiences:", content)
        self.assertIn("- [[intel]]", content)

    def test_get_compact_skills_list_various(self) -> None:
        """Test generating token-efficient list with and without experience filtering."""
        skills_dir = self.wiki_dir / "wiki" / "skills"
        
        # Missing skills directory
        self.assertEqual(get_compact_skills_list(skills_dir), [])

        skills_dir.mkdir(parents=True)

        # Write Python skill with intel and google relations
        f_py = skills_dir / "python.md"
        f_py.write_text("---\ntitle: Python\nrelated_experiences:\n  - '[[intel]]'\n  - google\n---", encoding="utf-8")

        # Write Docker skill with google relation
        f_dk = skills_dir / "docker.md"
        f_dk.write_text("---\ntitle: Docker\nrelated_experiences:\n  - '[[google]]'\n---", encoding="utf-8")

        # Write unrelated skill (no related experiences)
        f_un = skills_dir / "unrelated.md"
        f_un.write_text("---\ntitle: General\n---", encoding="utf-8")

        # Get all compact skills
        all_skills = get_compact_skills_list(skills_dir)
        self.assertIn("- **Python** (Applied in: intel, google)", all_skills)
        self.assertIn("- **Docker** (Applied in: google)", all_skills)
        self.assertIn("- **General**", all_skills)

        # Filter by allowed experience: only intel
        filtered = get_compact_skills_list(skills_dir, allowed_experience_slugs=["intel"])
        self.assertEqual(len(filtered), 1)
        self.assertIn("- **Python** (Applied in: intel)", filtered[0])

        # Test reading error exception path
        with patch("pathlib.Path.read_text", side_effect=Exception("Read failure")):
            self.assertEqual(get_compact_skills_list(skills_dir), [])


if __name__ == "__main__":
    unittest.main()
