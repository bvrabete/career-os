import pytest
import logging
from pathlib import Path
import shutil
import tempfile
from unittest.mock import MagicMock, patch

from generation.helpers import (
    _build_combined_body,
    _consolidate_company_roles,
    _detect_employment_type,
    _extract_and_clean_achievements,
    _extract_start_year,
    _group_old_experiences_by_company,
    _parse_education_candidate,
    _prune_recent_frontmatter,
    _score_experiences_list,
    _score_single_experience,
    _select_top_achievements,
    compress_experience_llm,
    compress_grouped_experience_llm,
    generate_skill_bridging_map,
    invoke_drafter_llm_with_fallback,
    prune_recent_experience,
    retrieve_and_deduplicate_education,
    retrieve_and_score_notes,
    retrieve_and_score_patents,
    retrieve_and_score_projects,
    retrieve_few_shots,
    robust_json_loads,
    score_by_keywords,
)
from generation.pruning import _compress_and_wrap_experiences
from langchain_core.messages import AIMessage

# Suppress debug/info logging during tests
logging.basicConfig(level=logging.ERROR)


class TestGenerationHelpersAdditional:
    """Deterministic offline unit tests for remaining generation helpers paths."""

    def setup_method(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=".")
        self.temp_path = Path(self.temp_dir.name)
        self.wiki_dir = self.temp_path / "wiki_dir"
        self.wiki_root = self.wiki_dir / "wiki"
        self.wiki_root.mkdir(parents=True, exist_ok=True)

    def teardown_method(self):
        self.temp_dir.cleanup()

    # 1. robust_json_loads & score_by_keywords Edge Cases
    def test_robust_json_loads_failures(self):
        """Test robust_json_loads throwing exceptions on invalid json format."""
        with pytest.raises(ValueError):
            robust_json_loads("{invalid json string}")

    def test_score_by_keywords_edge_cases(self):
        """Test score_by_keywords with null text, empty keywords, and empty elements."""
        assert score_by_keywords("", ["python"]) == 0
        assert score_by_keywords("python", []) == 0
        assert score_by_keywords("python java", ["", "  ", "python"]) == 1

    # 2. Skill Bridging Map & LLM Experience Compression
    @patch("generation.helpers.load_prompt", return_value="KEYWORDS: {KEYWORDS}\nSUMMARY: {SKILLS_SUMMARY}")
    def test_generate_skill_bridging_map_success_and_exception(self, mock_load):
        """Test generate_skill_bridging_map success and exception paths."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '```json\n{"java": "kotlin", "pytest": "unittest"}\n```'
        mock_llm.invoke.return_value = mock_response

        # Success
        res = generate_skill_bridging_map(mock_llm, ["java", "pytest"], ["kotlin", "unittest"])
        assert res.get("java") == "kotlin"

        # Exception
        mock_llm.invoke.side_effect = Exception("LLM call failed")
        res = generate_skill_bridging_map(mock_llm, ["java"], ["kotlin"])
        assert res == {}

    def test_compress_experience_llm(self):
        """Test compress_experience_llm success and exception handling."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Compressed content"
        mock_llm.invoke.return_value = mock_response

        # Success
        with patch("generation.helpers.get_model_for_step", return_value=mock_llm), \
             patch("generation.helpers.load_prompt", return_value="Compress template"):
            res = compress_experience_llm("Detailed experience text")
            assert res == "Compressed content"

        # Exception path should return original content
        mock_llm.invoke.side_effect = Exception("LLM failed")
        with patch("generation.helpers.get_model_for_step", return_value=mock_llm), \
             patch("generation.helpers.load_prompt", return_value="Compress template"):
            res = compress_experience_llm("Detailed experience text")
            assert res == "Detailed experience text"

    # 3. Recent Experience Pruning and Achievement Extraction
    def test_prune_recent_frontmatter(self):
        """Test _prune_recent_frontmatter formats various dict keys."""
        fm = {
            "title": "Staff Software Engineer",
            "organization": "[[google-cloud]]",
            "dates": {"start": "2020-01-01", "end": "Present"},
            "tracks": ["Engineering", "Leadership"]
        }
        res = _prune_recent_frontmatter(fm, "Permanent")
        assert "Staff Software Engineer" in res
        assert "google-cloud" in res
        assert "Permanent" in res

    def test_extract_and_clean_achievements(self):
        """Test _extract_and_clean_achievements splits bullet points and paragraphs."""
        body = """Some introductory description.
- **Situation**: Achieved 50% performance improvement on backend query engine.
- **Situation**: Designed and built scalable ML feature store in AWS.
Other trailing details here."""
        achievements, desc = _extract_and_clean_achievements(body)
        assert len(achievements) == 2
        assert "- **Situation**: Achieved 50% performance improvement" in achievements[0]
        assert "Some introductory description" in desc

    def test_select_top_achievements(self):
        """Test selecting achievements matching keywords."""
        body = """Intro
- **Situation**: Achieved 50% improvement on backend query engine using Python.
- **Situation**: Managed a large team of frontend engineers.
- **Situation**: Designed and built scalable ML feature store in AWS.
Outro"""
        # Python keyword should rank Python achievement first
        res = _select_top_achievements(body, ["python", "ML"])
        assert "Achieved 50% improvement" in res
        assert "Designed and built scalable ML" in res

    def test_prune_recent_experience_no_frontmatter(self):
        """Test prune_recent_experience returns cleaned body when no frontmatter is found."""
        content = "Just simple text without frontmatter blocks."
        res = prune_recent_experience(content)
        assert res == "Just simple text without frontmatter blocks."

    # 4. Experiences Scoring, Extraction and Deduplication
    @patch("generation.helpers.get_wiki_dir")
    def test_score_experiences_list_missing_dir_and_invalid_yaml(self, mock_get_wiki_dir):
        """Test scoring when the directory is missing, and file sizes are too small."""
        mock_get_wiki_dir.return_value = self.wiki_dir / "does_not_exist"
        scored = _score_experiences_list(MagicMock(), ["kw"], "persona", "jd", "template")
        assert scored == []

        # File size < 50 chars
        exp_dir = self.wiki_dir / "wiki" / "experiences"
        exp_dir.mkdir(parents=True, exist_ok=True)
        mock_get_wiki_dir.return_value = self.wiki_dir

        small_file = exp_dir / "short.md"
        small_file.write_text("Short")

        mock_llm = MagicMock()
        res = _score_single_experience(mock_llm, small_file, ["kw"], "persona", "jd", "template")
        assert res is None

    def test_extract_start_year(self):
        """Test _extract_start_year variations."""
        assert _extract_start_year({"start": "2020"}) == "2020"
        assert _extract_start_year({"dates": "2015-05-15"}) == "2015"
        assert _extract_start_year({}) == ""

    def test_detect_employment_type(self):
        """Test _detect_employment_type configurations."""
        assert _detect_employment_type({"employment_type": "Contract"}, "Body") == "Contract"
        assert _detect_employment_type({}, "This is a contractor role") == "Contract"
        assert _detect_employment_type({}, "consulting (contract) work") == "Contract"
        assert _detect_employment_type({}, "Regular permanent job") == "Permanent"
        assert _detect_employment_type({"title": "Co-Founder and CTO"}, "") == "Startup / Co-Founder"
        assert _detect_employment_type({"employment_type": "co_founder"}, "") == "Startup / Co-Founder"
        assert _detect_employment_type({"title": "Technical Advisor"}, "") == "Advisory"
        assert _detect_employment_type({"employment_type": "advisory"}, "") == "Advisory"

    def test_build_combined_body(self):
        """Test combining multiple experiences chronologically or otherwise."""
        roles = [
            ((10, "intel.md", "Intel Body", "Justification"), {"dates": {"start": "2020-01-01"}}),
            ((20, "google.md", "Google Body", "Justification"), {"dates": {"start": "2022-01-01"}})
        ]
        res = _build_combined_body(roles)
        assert "Intel Body" in res
        assert "Google Body" in res

    def test_consolidate_company_roles(self):
        """Test consolidating multiple roles at the same company."""
        # Setup mock directory structure for experiences (using dates > 10 years ago to be "old")
        exp_dir = self.wiki_root / "experiences"
        exp_dir.mkdir(parents=True, exist_ok=True)

        exp_1 = exp_dir / "role_1.md"
        exp_1.write_text("---\norganization: [[intel]]\ntitle: Engineer 1\ndates:\n  start: 2010-01-01\n---\nIntel Body 1")
        exp_2 = exp_dir / "role_2.md"
        exp_2.write_text("---\norganization: [[intel]]\ntitle: Engineer 2\ndates:\n  start: 2012-01-01\n---\nIntel Body 2")

        with patch("generation.helpers.get_wiki_dir", return_value=self.wiki_dir):
            old_experiences = [
                (10, "role_1.md", exp_1.read_text(), "justification 1"),
                (20, "role_2.md", exp_2.read_text(), "justification 2")
            ]
            grouped = _group_old_experiences_by_company(old_experiences)
            assert len(grouped) == 1
            assert grouped[0][1] == "grouped-intel.md"

            # Consolidate with LLM mock
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = AIMessage(content="Consolidated Intel experiences")
            with patch("generation.helpers.get_model_for_step", return_value=mock_llm), \
                 patch("generation.helpers.load_prompt", return_value="template"):
                res = _consolidate_company_roles("intel", [
                    ((10, "role_1.md", exp_1.read_text(), "justification 1"), {"dates": {"start": "2010-01-01"}}),
                    ((20, "role_2.md", exp_2.read_text(), "justification 2"), {"dates": {"start": "2012-01-01"}})
                ])
                assert res[0] == 20
                assert res[1] == "grouped-intel.md"
                assert "Intel Body 1" in res[2]
                assert "Intel Body 2" in res[2]
                assert "[role_1.md]: justification 1" in res[3]
                assert "[role_2.md]: justification 2" in res[3]

    def test_compress_grouped_experience_llm_exception(self):
        """Test compress_grouped_experience_llm fallback on LLM failure."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("LLM failure")
        with patch("generation.helpers.get_model_for_step", return_value=mock_llm), \
             patch("generation.helpers.load_prompt", return_value="template"):
            res = compress_grouped_experience_llm("Grouped text here")
            assert res == "Grouped text here"

    # 5. Project, Patent, and Note Retrieval
    def test_retrieve_and_score_projects(self):
        """Test projects retrieval, scoring, age decay, and sorting."""
        from generation.retrieval import _calculate_project_recency_factor

        # Test _calculate_project_recency_factor directly
        assert _calculate_project_recency_factor({"dates": {"end": "present"}}) == pytest.approx(1.0, abs=10**(-2))
        assert _calculate_project_recency_factor({}) == pytest.approx(0.5, abs=10**(-2))
        old_factor = _calculate_project_recency_factor({"dates": {"end": "2010-01-01"}})
        recent_factor = _calculate_project_recency_factor({"dates": {"end": "2024-01-01"}})
        assert recent_factor > old_factor

        proj_dir = self.wiki_root / "projects"
        proj_dir.mkdir(parents=True, exist_ok=True)

        p1 = proj_dir / "p1.md"
        p1.write_text("---\ntitle: Project One\ndates:\n  start: 2021-01-01\nskills:\n  - Python\n---\nBuilding super AI backend with Python.")
        p2 = proj_dir / "p2.md"
        p2.write_text("---\ntitle: Project Two\ndates:\n  start: 2022-01-01\nskills:\n  - Go\n---\nFrontend web client in react.")

        with patch("generation.helpers.get_wiki_dir", return_value=self.wiki_dir):
            res = retrieve_and_score_projects(self.wiki_dir, ["Python", "AI"], ["intel"])
            assert len(res) == 2
            # Python project should be ranked first because of relevance score
            assert "p1.md" in res[0]

    def test_retrieve_and_score_patents(self):
        """Test patents retrieval, scoring, and sorting."""
        pat_dir = self.wiki_root / "patents"
        pat_dir.mkdir(parents=True, exist_ok=True)

        p1 = pat_dir / "pat1.md"
        p1.write_text("---\ntitle: Patent One\nid: US123456\norganization: '[[intel-corporation]]'\n---\nNovel neural networks.")
        p2 = pat_dir / "pat2.md"
        p2.write_text("---\ntitle: Patent Two\nid: US789101\ntenure: intel-platform-architect-and-tech-lead\n---\nCrypto security protocol.")

        with patch("generation.helpers.get_wiki_dir", return_value=self.wiki_dir):
            res = retrieve_and_score_patents(self.wiki_dir, ["Neural", "networks"], ["intel-corporation", "intel-platform-architect-and-tech-lead"])
            assert len(res) == 2
            assert "pat1.md" in res[0]

    def test_compress_and_wrap_experiences_constituent_slugs(self):
        """Test that _compress_and_wrap_experiences populates constituent and org slugs."""
        exp_1 = (10, "intel-role-1.md", "---\norganization: [[intel-corp]]\ntitle: Eng 1\n---\nBody 1", "Just 1")
        exp_2 = (20, "smartrs-cto.md", "---\norganization: [[smartrs]]\ntitle: CTO\nemployment_type: co_founder\n---\nBody 2", "Just 2")
        dedup = [exp_1, exp_2]
        _, slugs = _compress_and_wrap_experiences(dedup, ["Python"], max_pages=1)
        assert "intel-role-1" in slugs
        assert "intel-corp" in slugs
        assert "smartrs-cto" in slugs
        assert "smartrs" in slugs

    def test_retrieve_and_score_notes(self):
        """Test notes retrieval, scoring, and sorting."""
        note_dir = self.wiki_root / "notes"
        note_dir.mkdir(parents=True, exist_ok=True)

        n1 = note_dir / "n1.md"
        n1.write_text("---\ntags: [tech, study]\n---\nHow to scale kubernetes nodes efficiently with performance-review.")
        n2 = note_dir / "n2.md"
        n2.write_text("---\ntags: [personal]\n---\nMy travel diary.")

        with patch("generation.helpers.get_wiki_dir", return_value=self.wiki_dir):
            res = retrieve_and_score_notes(self.wiki_dir, ["kubernetes", "scale"], ["intel"])
            assert len(res) == 1  # travel diary does not have performance-review or relation, so it is skipped
            assert "n1.md" in res[0]

    # 6. Education Retrieval and Duplication
    def test_retrieve_and_deduplicate_education_variations(self):
        """Test _parse_education_candidate exceptions and deduplication sorting."""
        edu_dir = self.wiki_root / "education"
        edu_dir.mkdir(parents=True, exist_ok=True)

        e1 = edu_dir / "stanford.md"
        e1.write_text("---\ninstitution: [[stanford-university]]\ndates:\n  start: 2016-09-01\nstatus: Completed\n---\nMajor in Computer Science")
        e2 = edu_dir / "stanford-dup.md"
        e2.write_text("---\ninstitution: [[stanford-university]]\ndates:\n  start: 2016-09-01\nstatus: In-Progress\n---\nMajor in CS")

        res = retrieve_and_deduplicate_education(self.wiki_dir)
        # Should deduplicate stanford based on completed status first, and start year
        assert len(res) == 1
        assert "Major in Computer Science" in res[0]

        # Test exception path inside _parse_education_candidate
        mock_path = MagicMock(spec=Path)
        mock_path.read_text.side_effect = Exception("Read failed")
        assert _parse_education_candidate(mock_path) is None

    # 7. Few Shots Retrieval and Truncation
    def test_retrieve_few_shots_scenarios(self):
        """Test retrieve_few_shots gets offers and handles truncation."""
        synth_dir = self.wiki_root / "synthesis"
        synth_dir.mkdir(parents=True, exist_ok=True)

        cv1 = synth_dir / "success_offer.md"
        cv1.write_text("---\nstatus: Offer\n---\nAwesome successful CV content with Python and LangChain. " + "A" * 13000)
        cv2 = synth_dir / "rejected.md"
        cv2.write_text("---\nstatus: Rejected\n---\nFailed interview details.")

        res = retrieve_few_shots(self.wiki_dir, ["Python"])
        # Should only retrieve success_offer.md (Offers/Technical-Interviews)
        assert len(res) == 1
        assert "success_offer.md" in res[0]
        # Should be truncated to 12000 chars
        assert "[TRUNCATED SUCCESSFUL PAST CV FOR BREVITY]" in res[0]

        # Test empty synthesis directory path
        shutil.rmtree(synth_dir)
        assert retrieve_few_shots(self.wiki_dir, ["Python"]) == []

    # 8. Drafter LLM with Fallback Integration (Rate Limits)
    def test_invoke_drafter_llm_with_fallback_success(self):
        """Test invoke_drafter_llm_with_fallback normal invocation success."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content="Perfect CV Draft")
        res = invoke_drafter_llm_with_fallback(mock_llm, "system instructions", "user prompt")
        assert res.content == "Perfect CV Draft"

    def test_invoke_drafter_llm_with_fallback_not_rate_limit(self):
        """Test invoke_drafter_llm_with_fallback re-raising non-rate-limit exceptions."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = ValueError("Some standard value error")
        with pytest.raises(ValueError):
            invoke_drafter_llm_with_fallback(mock_llm, "system", "prompt")

    @patch("generation.helpers.get_fallback_model_for_step")
    def test_invoke_drafter_llm_with_fallback_rate_limit_no_fallback_model(self, mock_fallback_model):
        """Test invoke_drafter_llm_with_fallback rate limit where no fallback model is configured."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("rate_limit_exceeded: TPM limit reached.")
        mock_fallback_model.return_value = None

        with pytest.raises(Exception) as ctx:
            invoke_drafter_llm_with_fallback(mock_llm, "system", "prompt")
        assert "rate_limit_exceeded" in str(ctx.value)

    @patch("generation.helpers.get_fallback_model_for_step")
    def test_invoke_drafter_llm_with_fallback_rate_limit_with_successful_fallback(self, mock_fallback_model):
        """Test invoke_drafter_llm_with_fallback rate limit successfully recovering via fallback model."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("limit_exceeded: Rate limit reached.")

        mock_fallback = MagicMock()
        mock_fallback.invoke.return_value = AIMessage(content="Draft from fallback model")
        mock_fallback_model.return_value = mock_fallback

        res = invoke_drafter_llm_with_fallback(mock_llm, "system", "prompt")
        assert res.content == "Draft from fallback model"

    @patch("generation.helpers.get_fallback_model_for_step")
    def test_invoke_drafter_llm_with_fallback_rate_limit_with_failing_fallback(self, mock_fallback_model):
        """Test invoke_drafter_llm_with_fallback rate limit where configured fallback model also fails."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("rate_limit: TPM reached")

        mock_fallback = MagicMock()
        mock_fallback.invoke.side_effect = Exception("Fallback model connection timeout")
        mock_fallback_model.return_value = mock_fallback

        with pytest.raises(Exception) as ctx:
            invoke_drafter_llm_with_fallback(mock_llm, "system", "prompt")
        # Should raise the ORIGINAL rate limit error
        assert "rate_limit" in str(ctx.value)

    def test_heading_double_hash_sanitization(self):
        """Verify regex cleans duplicate heading hash markers cleanly."""
        import re
        sample = "### ### Job Title at Org [Full-Time]\n## ## Section\n# # Header"
        cleaned = re.sub(r'^(#{1,6})\s*#{1,6}\s+', r'\1 ', sample, flags=re.MULTILINE)
        assert cleaned == "### Job Title at Org [Full-Time]\n## Section\n# Header"

    def test_resolve_timeline_conflicts_and_anchor_tenure(self):
        """Verify generic interval-graph timeline de-confliction and anchor tenure protection."""
        from generation.grouping import _is_anchor_tenure, resolve_timeline_conflicts

        anchor_fm = {"dates": {"start": "2007-09-01", "end": "2017-07-01"}, "employment_type": "Permanent"}
        assert _is_anchor_tenure(anchor_fm, score=90) is True
        assert _is_anchor_tenure(anchor_fm, score=40) is False

        deduplicated = [
            (92, "corp-recent.md", "---\ntitle: Director\ndates:\n  start: 2024-04-01\n  end: Present\nemployment_type: Permanent\n---\nBody", "just"),
            (60, "side-venture-active.md", "---\ntitle: Co-Founder & CTO\ndates:\n  start: 2021-01-01\n  end: Present\nemployment_type: Startup / Co-Founder\n---\nBody", "just"),
            (55, "corp-mid.md", "---\ntitle: Advisor\ndates:\n  start: 2019-02-01\n  end: 2020-05-01\nemployment_type: Contract\n---\nBody", "just"),
            (90, "spinout-winner.md", "---\ntitle: Co-Founder & CTO\ndates:\n  start: 2017-08-01\n  end: 2020-02-29\nemployment_type: Startup / Co-Founder\n---\nBody", "just"),
            (70, "venture-loser.md", "---\ntitle: Co-Founder & CTO\ndates:\n  start: 2016-10-01\n  end: 2019-01-30\nemployment_type: Startup / Co-Founder\n---\nBody", "just"),
            (5, "short-contract.md", "---\ntitle: Engineer\ndates:\n  start: 2017-12-01\n  end: 2018-05-01\nemployment_type: Contract\n---\nBody", "just"),
            (90, "corp-anchor.md", "---\ntitle: Architect\ndates:\n  start: 2007-09-01\n  end: 2017-07-01\nemployment_type: Permanent\n---\nBody", "just"),
        ]

        resolved = resolve_timeline_conflicts(deduplicated, parallel_venture_policy="strict_single_timeline", min_contract_score=25)
        retained_names = [r[1] for r in resolved]
        assert "corp-recent.md" in retained_names
        assert "corp-mid.md" in retained_names
        assert "spinout-winner.md" in retained_names
        assert "corp-anchor.md" in retained_names
        assert "side-venture-active.md" not in retained_names
        assert "venture-loser.md" not in retained_names
        assert "short-contract.md" not in retained_names

        spinout_entry = next(r for r in resolved if r[1] == "spinout-winner.md")
        assert "end: 2019-02-01" in spinout_entry[2]
