"""Layers 2 & 3: Zero-token positive and negative contract tests for CV generation and cleanup."""

import pytest
from pathlib import Path
import shutil
import tempfile
from typing import Any
from unittest.mock import patch
import yaml

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from generation.evidence_mapping import parse_experience_entry_to_dict
from generation.formatting import invoke_structured_llm
from generation.grouping import _is_old_role
from generation.nodes import node_analyzer, node_auditor, node_drafter
from generation.retrieval import assemble_role_evidence_bundles, retrieve_company_entity, retrieve_voice_guide
from generation.selection_nodes import node_evidence_selector, node_requirement_mapper
from generation.state import AnalyzerOutput, CVPipelineState, RegionalStrategy
from kb_cleanup import extract_voice_profile, normalize_wiki_frontmatter


class DeterministicStructuredChatModel(BaseChatModel):
    """Zero-token deterministic LangChain BaseChatModel supporting .with_structured_output()."""

    responses: list[str]
    call_idx: int = 0

    @property
    def _llm_type(self) -> str:
        return "deterministic-test-chat-model"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        _ = messages, stop, run_manager, kwargs
        idx = min(self.call_idx, len(self.responses) - 1)
        text = self.responses[idx]
        self.call_idx += 1
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


class TestZeroTokenPipelineContracts:
    """Zero-token positive and negative tests for every major pipeline improvement."""

    def setup_method(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.wiki_root = self.temp_dir / "wiki"
        for subdir in ["experiences", "entities", "case-studies", "projects", "patents", "notes", "voice", "cover-letters"]:
            (self.wiki_root / subdir).mkdir(parents=True, exist_ok=True)

    def teardown_method(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_invoke_structured_llm_positive_and_fallback(self) -> None:
        """invoke_structured_llm validates JSON output into Pydantic schema without tokens."""
        llm = DeterministicStructuredChatModel(
            responses=[
                '{"persona": "Principal Architect", "keywords": ["Kubernetes", "Go"], '
                '"posting_organization_type": "direct_employer", "target_employer_name": "Acme Cloud", '
                '"target_organization_slug": "acme-cloud", "target_role": "Principal Architect"}'
            ]
        )
        res = invoke_structured_llm(llm, AnalyzerOutput, [])
        assert isinstance(res, AnalyzerOutput)
        assert res.target_organization_slug == "acme-cloud"

    @patch("generation.nodes.get_wiki_dir")
    @patch("generation.nodes.get_model_for_step")
    def test_node_analyzer_recruitment_agency_never_used_as_employer(
        self, mock_get_model: Any, mock_get_wiki_dir: Any
    ) -> None:
        """When JD is posted by a recruitment agency, target_organization_slug uses the client employer, never the agency."""
        mock_get_wiki_dir.return_value = self.temp_dir
        # Case 1: LLM mistakenly puts agency slug in target_organization_slug, but provides target_employer_name
        llm_agency_with_client = DeterministicStructuredChatModel(
            responses=[
                '{"persona": "Cloud Director", "keywords": ["AWS"], "locations": ["Amsterdam"], '
                '"posting_organization_type": "recruitment_agency", '
                '"recruitment_agency_name": "Hays Recruitment", '
                '"target_employer_name": "Adyen FinTech", '
                '"target_organization_slug": "hays-recruitment", '
                '"target_role": "VP Engineering"}'
            ]
        )
        mock_get_model.return_value = llm_agency_with_client
        state: CVPipelineState = {"job_description": "Hays is recruiting on behalf of Adyen FinTech..."}
        out = node_analyzer(state)
        assert out["posting_organization_type"] == "recruitment_agency"
        assert out["recruitment_agency_name"] == "Hays Recruitment"
        assert out["target_organization_slug"] == "adyen-fintech"

        # Case 2: Confidential client with no employer name -> confidential-employer
        llm_confidential = DeterministicStructuredChatModel(
            responses=[
                '{"persona": "CTO", "keywords": ["Rust"], '
                '"posting_organization_type": "recruitment_agency", '
                '"recruitment_agency_name": "Michael Page", '
                '"target_employer_name": "", '
                '"target_organization_slug": "michael-page", '
                '"target_role": "CTO"}'
            ]
        )
        mock_get_model.return_value = llm_confidential
        out_conf = node_analyzer(state)
        assert out_conf["target_organization_slug"] == "confidential-employer"

    def test_is_old_role_checks_end_date_for_long_tenures(self) -> None:
        """A long tenure starting >10 years ago that ended recently or is Present is NOT an old role."""
        assert not _is_old_role({"dates": {"start": "2012-01-01", "end": "Present"}})
        assert not _is_old_role({"dates": {"start": "2014-01-01", "end": "2024-06-01"}})
        assert _is_old_role({"dates": {"start": "2008-01-01", "end": "2013-12-31"}})
        assert _is_old_role({"dates": {"start": "2012-01-01"}})

    def test_parse_experience_entry_to_dict_extracts_atomic_bullets(self) -> None:
        """parse_experience_entry_to_dict extracts individual bullets rather than treating the whole file as 1 bullet."""
        wrapped_entry = (
            "--- CAREER ENTRY: acme-architect.md | START_DATE: 2022-01-01 | "
            "EMPLOYMENT_TYPE: Permanent | IS_STARTUP_TRACK: False | "
            "(SEMANTIC RELEVANCE SCORE: 90) ---\n"
            "JUSTIFICATION: High match\n"
            "---\n"
            "type: experience\n"
            "title: Principal Cloud Architect\n"
            "organization: \"[[acme-corp]]\"\n"
            "---\n\n"
            "## Key Achievements\n"
            "- **Situation**: Legacy monolith. **Action**: Migrated to [[kubernetes]] microservices. **Result**: Cut latency 45%.\n"
            "- **Cloud FinOps**: Reduced AWS spend by $1.2M annually via spot autoscaling ([[case-studies/finops]]).\n"
            "--- END CAREER ENTRY ---\n"
        )
        parsed = parse_experience_entry_to_dict(wrapped_entry)
        assert parsed["title"] == "Principal Cloud Architect"
        assert parsed["score"] == pytest.approx(0.90)
        assert len(parsed["achievements"]) == 2
        assert "[[" not in parsed["achievements"][0]
        assert "[[" not in parsed["achievements"][1]

    @patch("generation.evidence_mapping.get_model_for_step")
    def test_requirement_mapper_and_evidence_selector_produce_long_draft(self, mock_get_model: Any) -> None:
        """node_requirement_mapper + node_evidence_selector extract atomic bullets and synthesize TailoredLongDraft."""
        mock_get_model.return_value = DeterministicStructuredChatModel(
            responses=[
                '{"requirements": [{"id": "req-1", "text": "Kubernetes and AWS FinOps", '
                '"category": "system_architecture", "priority": "essential", "weight": 1.5, '
                '"keywords": ["Kubernetes", "AWS", "FinOps"]}]}'
            ]
        )
        wrapped_entry = (
            "--- CAREER ENTRY: acme-architect.md | START_DATE: 2022-01-01 | "
            "(SEMANTIC RELEVANCE SCORE: 92) ---\n"
            "---\ntitle: Principal Architect\norganization: \"[[acme-corp]]\"\n---\n"
            "- Architected Kubernetes multi-cluster platform on AWS reducing FinOps costs by 40%.\n"
            "- Mentored 18 senior engineers across 4 distributed platform squads.\n"
            "--- END CAREER ENTRY ---\n"
        )
        state: CVPipelineState = {
            "job_description": "Seeking Principal Architect with Kubernetes and AWS FinOps expertise.",
            "target_persona": "Principal Cloud Architect",
            "primary_keywords": ["Kubernetes", "AWS", "FinOps"],
            "selected_entries": [wrapped_entry],
            "strategy_metadata": RegionalStrategy(max_pages=1),
        }
        mapped = node_requirement_mapper(state)
        assert len(mapped["candidate_evidence"]) == 2

        state["requirements"] = mapped["requirements"]
        state["candidate_evidence"] = mapped["candidate_evidence"]
        selected = node_evidence_selector(state)
        assert "selection_manifest" in selected
        assert "long_draft" in selected
        assert len(selected["long_draft"]["synthesized_roles"]) > 0

    def test_hub_and_spoke_role_bundle_assembly(self) -> None:
        """assemble_role_evidence_bundles links company entity context and child case studies/projects."""
        (self.wiki_root / "entities" / "acme-corp.md").write_text(
            "---\ntype: entity\nentity_type: company\ntitle: Acme Corp\nsummary: Global Cloud Leader ($2B ARR)\n---\n",
            encoding="utf-8",
        )
        (self.wiki_root / "case-studies" / "cs-mesh.md").write_text(
            "---\ntype: case_study\ntitle: Service Mesh\n---\nScaled Envoy mesh to 50k RPS with [[istio]].",
            encoding="utf-8",
        )
        (self.wiki_root / "voice" / "my-voice.md").write_text(
            "---\ntype: voice\ntitle: My Voice\n---\nUse direct engineering verbs.",
            encoding="utf-8",
        )

        entry = (
            "--- CAREER ENTRY: acme-corp-architect.md | START_DATE: 2022-01-01 | "
            "(SEMANTIC RELEVANCE SCORE: 88) ---\n"
            "---\ntype: experience\ntitle: Staff Architect\norganization: \"[[acme-corp]]\"\n"
            "case_studies:\n  - \"[[cs-mesh]]\"\n---\n"
            "- Built cloud mesh architecture.\n"
            "--- END CAREER ENTRY ---\n"
        )
        bundles = assemble_role_evidence_bundles(self.temp_dir, [entry])
        assert len(bundles) == 1
        assert bundles[0]["organization_overview"] == "Global Cloud Leader ($2B ARR)"
        assert len(bundles[0]["linked_case_studies"]) == 1
        assert "Scaled Envoy mesh to 50k RPS with istio." in bundles[0]["linked_case_studies"][0]
        assert "direct engineering verbs" in retrieve_voice_guide(self.temp_dir)
        assert retrieve_company_entity(self.temp_dir, "acme-corp") == "Global Cloud Leader ($2B ARR)"

        # Negative test: compressed one-liner entry where --- block contains plain prose string instead of YAML dict
        prose_entry = (
            "--- CAREER ENTRY: berg-computers-senior-software-engineer.md | START_DATE: 2006-01-01 | "
            "(SEMANTIC RELEVANCE SCORE: 10) ---\n"
            "JUSTIFICATION: Historical role\n"
            "---\n"
            "Senior Software Engineer at Berg Computers (2006-2008) delivering C++ and SQL systems.\n"
            "--- END CAREER ENTRY ---\n"
        )
        prose_bundles = assemble_role_evidence_bundles(self.temp_dir, [prose_entry])
        assert len(prose_bundles) == 1
        assert prose_bundles[0]["slug"] == "berg-computers-senior-software-engineer"

    @patch("generation.nodes.get_model_for_step")
    def test_auditor_resets_compression_count_and_drafter_strips_wikilinks(self, mock_get_model: Any) -> None:
        """node_auditor resets compression_count to 0 on rewrite loops, and node_drafter strips [[wikilinks]]."""
        drafter_llm = DeterministicStructuredChatModel(
            responses=["# Jane Doe\n### Staff Architect — [[acme-corp]]\n- Built [[kubernetes]] platform."]
        )
        auditor_llm = DeterministicStructuredChatModel(
            responses=['{"pass": false, "ats_score": {"total_score": 70}, "rewrite_checklist": ["Add metrics"]}']
        )
        mock_get_model.return_value = drafter_llm
        draft_res = node_drafter({"job_description": "JD", "selected_entries": []})
        assert "[[" not in draft_res["draft_cv"]

        mock_get_model.return_value = auditor_llm
        audit_cmd = node_auditor({
            "job_description": "JD",
            "draft_cv": draft_res["draft_cv"],
            "iteration_count": 0,
            "compression_count": 2,
            "skill_bridging_map": {"AWS": "GCP"},
            "all_candidate_skills": ["Python", "Kubernetes"],
        })
        assert audit_cmd.goto == "drafter"
        assert audit_cmd.update["compression_count"] == 0

    def test_kb_cleanup_normalize_frontmatter_and_extract_voice(self) -> None:
        """normalize_wiki_frontmatter quotes unquoted wikilinks and creates missing company entity files."""
        exp_file = self.wiki_root / "experiences" / "acme-corp-lead.md"
        exp_file.write_text(
            "---\ntype: experience\ntitle: Lead\norganization: [[acme-corp]]\n"
            "case_studies:\n  - [[[cs-1]]]\n---\n\n- Built platform.\n",
            encoding="utf-8",
        )
        (self.wiki_root / "cover-letters" / "cl-1.md").write_text(
            "---\ntype: cover-letter\ntitle: CL\n---\nI build reliable distributed systems with clear metrics.",
            encoding="utf-8",
        )

        stats = normalize_wiki_frontmatter(self.temp_dir, dry_run=False)
        assert stats["files_updated"] == 1
        assert stats["entities_created"] == 1
        assert (self.wiki_root / "entities" / "acme-corp.md").exists()

        updated_fm = yaml.safe_load(exp_file.read_text(encoding="utf-8").split("---", 2)[1])
        assert updated_fm["organization"] == "[[acme-corp]]"
        assert updated_fm["case_studies"] == ["[[cs-1]]"]

        voice_file = extract_voice_profile(self.temp_dir, dry_run=False)
        assert voice_file.exists()
        assert "reliable distributed systems" in voice_file.read_text(encoding="utf-8")
