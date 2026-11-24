"""Layer 4: Static prompt, template, CSS, pytest-standard, and 500-line modularity gate tests."""

from pathlib import Path
import re


FORBIDDEN_PERSONAL_STRINGS = [
    "Intel Corporation",
    "intel-corporation",
    "Virgin Media",
    "virgin-media",
    "Smart-RS",
    "smart-rs",
    "Allwayswithyou",
    "allwayswithyou",
    "Dell Corp",
    "BlackBox",
    "US 10,912,283",
    "Red Foundation",
    "llm-wiki-brad",
]


class TestPromptAndTemplateHygiene:
    """Static verification of zero personal data leakage, prompt placeholders, CSS rules, and file sizes."""

    repo_root: Path = Path(__file__).parent.parent

    def test_zero_personal_profile_leakage_in_prompts_templates_and_configs(self) -> None:
        """Verify zero personal employer/patent/path strings exist in prompts, templates, or config files."""
        scan_paths: list[Path] = []
        scan_paths.extend((self.repo_root / "src" / "prompts").rglob("*.txt"))
        scan_paths.extend((self.repo_root / "llm-wiki.template").rglob("*.md"))
        scan_paths.extend((self.repo_root / "llm-wiki.template").rglob("*.json"))
        scan_paths.extend(self.repo_root.glob("config*.yaml"))
        scan_paths.append(self.repo_root / "src" / "tools" / "external_auditor.py")

        violations: list[str] = []
        for path in scan_paths:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for forbidden in FORBIDDEN_PERSONAL_STRINGS:
                if forbidden.lower() in text.lower():
                    rel = path.relative_to(self.repo_root)
                    violations.append(f"{rel} contains forbidden string '{forbidden}'")

        assert violations == [], "\n".join(violations)

    def test_prompt_placeholder_parity(self) -> None:
        """Verify critical prompt placeholders exist in externalized prompt templates."""
        cv_prompts = self.repo_root / "src" / "prompts" / "cv_gen"
        for comp_name in ["compress_experience.txt", "compress_to_one_liner.txt", "compress_grouped_experience.txt"]:
            text = (cv_prompts / comp_name).read_text(encoding="utf-8")
            assert "{CONTENT}" in text
            assert "{KEYWORDS}" in text

        auditor_text = (cv_prompts / "auditor.txt").read_text(encoding="utf-8")
        for placeholder in ["{job_description}", "{draft_cv}", "{candidate_skills}", "{skill_bridging_map}", "{strategy_info}"]:
            assert placeholder in auditor_text

        analyzer_text = (cv_prompts / "analyzer.txt").read_text(encoding="utf-8")
        assert "posting_organization_type" in analyzer_text
        assert "recruitment_agency_name" in analyzer_text

    def test_css_templates_enforce_outside_bullets_and_pagination_guards(self) -> None:
        """All 5 CSS templates must use list-style-position: outside and avoid orphan headings."""
        templates_dir = self.repo_root / "llm-wiki.template" / "templates"
        css_files = sorted(templates_dir.glob("*.css"))
        assert len(css_files) == 5

        for css_file in css_files:
            content = css_file.read_text(encoding="utf-8")
            assert "list-style-position: inside" not in content, f"{css_file.name} uses inside bullets"
            assert "list-style-position: outside" in content, f"{css_file.name} missing outside bullets"
            assert "page-break-after: avoid" in content, f"{css_file.name} missing page-break-after: avoid"
            assert "orphans:" in content, f"{css_file.name} missing orphans rule"
            assert "widows:" in content, f"{css_file.name} missing widows rule"

    def test_all_src_python_files_under_500_lines(self) -> None:
        """Enforce AGENTS.md mandate: no Python source file under src/ may exceed 500 lines."""
        src_dir = self.repo_root / "src"
        oversized: list[str] = []
        for py_file in sorted(src_dir.rglob("*.py")):
            line_count = len(py_file.read_text(encoding="utf-8").splitlines())
            if line_count > 500:
                oversized.append(f"{py_file.relative_to(self.repo_root)}: {line_count} lines (max 500)")

        assert oversized == [], "\n".join(oversized)

    def test_pure_pytest_and_monkeypatch_compliance_in_tests(self) -> None:
        """Enforce AGENTS.md mandate: zero unittest.TestCase subclasses or direct os.environ mutations in tests/."""
        tests_dir = self.repo_root / "tests"
        violations: list[str] = []
        for test_file in sorted(tests_dir.glob("*.py")):
            if test_file.name == "test_prompt_and_template_hygiene.py":
                continue
            content = test_file.read_text(encoding="utf-8")
            if "unittest.TestCase" in content:
                violations.append(f"{test_file.name}: inherits from unittest.TestCase")
            if re.search(r"os\.environ\s*\[.*?\]\s*=", content) or re.search(r"del\s+os\.environ", content):
                violations.append(f"{test_file.name}: mutates os.environ directly instead of using monkeypatch")

        assert violations == [], "\n".join(violations)
