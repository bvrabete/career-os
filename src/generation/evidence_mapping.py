"""Candidate evidence normalization and requirement support mapping for CV generation."""

import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage

from generation.helpers import llm_text, load_prompt, robust_json_loads
from generation.state import EvidenceItem, JobRequirement, RequirementSupport
from kb_config import get_model_for_step


def extract_requirements_from_jd(jd: str, target_persona: str = "") -> list[JobRequirement]:
    """Extract explicit, typed, weighted requirement records from a target job description."""
    if not jd or not jd.strip():
        return []

    try:
        llm = get_model_for_step("REQUIREMENT_MAPPING", format="json")
        prompt_tmpl = load_prompt("requirement_mapper.txt")
        prompt = prompt_tmpl.replace("{JOB_DESCRIPTION}", jd).replace("{TARGET_PERSONA}", target_persona)
        response = llm.invoke([HumanMessage(content=prompt)])
        content = llm_text(response.content)
        data = robust_json_loads(content)
        reqs_raw = data.get("requirements", []) if isinstance(data, dict) else []

        requirements: list[JobRequirement] = []
        for idx, r in enumerate(reqs_raw, start=1):
            if not isinstance(r, dict):
                continue
            req_id = str(r.get("id") or f"req-{idx}")
            text = str(r.get("text") or "").strip()
            if not text:
                continue
            category = str(r.get("category", "core_technical"))
            if category not in [
                "core_technical", "system_architecture", "leadership_management",
                "domain_specialization", "delivery_methodology", "business_impact", "cultural_soft_skill"
            ]:
                category = "core_technical"

            priority = str(r.get("priority", "important")).lower()
            if priority not in ["essential", "important", "supporting"]:
                priority = "important"

            try:
                weight = float(r.get("weight", 1.0))
            except (ValueError, TypeError):
                weight = 1.0

            keywords = [str(k) for k in r.get("keywords", []) if k]
            source_text = str(r.get("source_text", ""))

            requirements.append(JobRequirement(
                id=req_id,
                text=text,
                category=category,  # type: ignore[arg-type]
                priority=priority,  # type: ignore[arg-type]
                weight=max(0.1, min(2.0, weight)),
                keywords=keywords,
                source_text=source_text,
            ))
        if requirements:
            return requirements
    except Exception as e:
        logging.warning(f"Failed to extract requirements via LLM, falling back to heuristic parsing: {e}")

    return _fallback_extract_requirements(jd)


def _fallback_extract_requirements(jd: str) -> list[JobRequirement]:
    """Deterministic fallback heuristic to extract requirements from JD text."""
    lines = [line.strip("- *• \t") for line in jd.splitlines() if len(line.strip()) > 15]
    requirements: list[JobRequirement] = []

    for idx, line in enumerate(lines[:12], start=1):
        words = re.findall(r"\b[A-Za-z0-9+#.-]{3,}\b", line)
        priority = "essential" if idx <= 4 else ("important" if idx <= 8 else "supporting")
        weight = 1.5 if priority == "essential" else (1.0 if priority == "important" else 0.7)
        requirements.append(JobRequirement(
            id=f"req-{idx}",
            text=line[:150],
            category="core_technical",
            priority=priority,  # type: ignore[arg-type]
            weight=weight,
            keywords=words[:6],
            source_text=line[:100],
        ))
    return requirements


def extract_candidate_evidence_items(
    experiences_raw: list[dict[str, Any]] | None = None,
    projects_raw: list[dict[str, Any]] | None = None,
    patents_raw: list[dict[str, Any]] | None = None,
    case_studies_raw: list[dict[str, Any]] | None = None,
    notes_raw: list[dict[str, Any]] | None = None,
) -> list[EvidenceItem]:
    """Normalize retrieved candidate assets into atomic EvidenceItem records."""
    evidence_items: list[EvidenceItem] = []

    if experiences_raw:
        for exp_idx, exp in enumerate(experiences_raw):
            role_title = str(exp.get("title") or exp.get("role") or exp.get("organization") or "Experience")
            role_score = float(exp.get("score") or exp.get("final_score") or 0.5)
            achievements = exp.get("achievements") or exp.get("bullets") or []
            if isinstance(achievements, str):
                achievements = [a.strip() for a in achievements.split("\n") if a.strip()]

            for b_idx, bullet in enumerate(achievements):
                bullet_str = str(bullet).strip("- *• \t")
                if len(bullet_str) < 10:
                    continue
                item_id = f"exp_{exp_idx}_b_{b_idx}"
                impact = _assess_impact_metrics(bullet_str)
                words = len(bullet_str.split())
                evidence_items.append(EvidenceItem(
                    id=item_id,
                    source_ref=f"experiences[{exp_idx}]:bullet[{b_idx}]",
                    source_type="experience",
                    role_or_project=role_title,
                    text=bullet_str,
                    existing_role_score=role_score,
                    impact_assessment=impact,
                    estimated_words=words,
                ))

    if projects_raw:
        for p_idx, proj in enumerate(projects_raw):
            title = str(proj.get("title") or proj.get("name") or "Project")
            desc = str(proj.get("description") or proj.get("summary") or "").strip()
            score = float(proj.get("score") or 0.5)
            if len(desc) >= 10:
                evidence_items.append(EvidenceItem(
                    id=f"proj_{p_idx}",
                    source_ref=f"projects[{p_idx}]",
                    source_type="project",
                    role_or_project=title,
                    text=desc,
                    existing_role_score=score,
                    impact_assessment=_assess_impact_metrics(desc),
                    estimated_words=len(desc.split()),
                ))

    if patents_raw:
        for pat_idx, pat in enumerate(patents_raw):
            title = str(pat.get("title") or "Patent")
            abstract = str(pat.get("abstract") or pat.get("summary") or "").strip()
            score = float(pat.get("score") or 0.5)
            if len(abstract) >= 10:
                evidence_items.append(EvidenceItem(
                    id=f"pat_{pat_idx}",
                    source_ref=f"patents[{pat_idx}]",
                    source_type="patent",
                    role_or_project=title,
                    text=abstract,
                    existing_role_score=score,
                    impact_assessment=0.8,  # Patents have inherent technical scope impact
                    estimated_words=len(abstract.split()),
                ))

    return evidence_items


def _assess_impact_metrics(text: str) -> float:
    """Assess quantitative impact in evidence text based on metrics, numbers, and scope signals."""
    score = 0.4
    if re.search(r"\b\d+%\b", text):  # percentage improvements
        score += 0.25
    if re.search(r"\$[\d,.]+[kMB]?", text, re.IGNORECASE):  # dollar savings/revenue
        score += 0.25
    if re.search(r"\b\d+(?:\.\d+)?\b", text):  # generic numbers
        score += 0.10
    return min(1.0, score)


def compute_requirement_supports(
    requirements: list[JobRequirement],
    evidence_items: list[EvidenceItem],
) -> None:
    """Compute semantic/keyword overlap between evidence items and requirements in-place."""
    for item in evidence_items:
        item_text_lower = item.text.lower()
        supports: list[RequirementSupport] = []

        for req in requirements:
            req_text_lower = req.text.lower()
            keyword_matches = sum(1 for kw in req.keywords if kw.lower() in item_text_lower)
            total_kws = max(1, len(req.keywords))
            kw_ratio = keyword_matches / total_kws

            # Token overlap fallback
            req_tokens = set(re.findall(r"\b\w{4,}\b", req_text_lower))
            item_tokens = set(re.findall(r"\b\w{4,}\b", item_text_lower))
            overlap = len(req_tokens & item_tokens) / max(1, len(req_tokens))

            score = max(kw_ratio * 0.7 + overlap * 0.3, overlap)
            if score >= 0.25:
                strength: Any = "primary" if score >= 0.60 else ("secondary" if score >= 0.40 else "supporting")
                supports.append(RequirementSupport(
                    requirement_id=req.id,
                    relevance_score=round(score, 3),
                    support_strength=strength,
                    rationale=f"Matched {keyword_matches} keywords and {len(req_tokens & item_tokens)} tokens",
                ))

        item.supports = supports
        if supports:
            item.keyword_relevance = max(s.relevance_score for s in supports)


def assign_redundancy_groups(evidence_items: list[EvidenceItem]) -> None:
    """Group evidence items by semantic similarity / skill cluster keys to penalize repetitive evidence."""
    cluster_keywords = {
        "cloud_aws": ["aws", "cloud", "s3", "ec2", "lambda"],
        "cloud_azure": ["azure", "devops", "blob"],
        "k8s_container": ["kubernetes", "k8s", "docker", "container", "helm"],
        "database_sql": ["postgresql", "postgres", "sql", "mysql", "database", "orm"],
        "leadership_team": ["led", "managed", "coached", "mentored", "hired", "team", "agile"],
        "architecture_microservices": ["microservices", "architecture", "distributed", "event-driven", "kafka"],
        "ci_cd_pipeline": ["ci/cd", "pipeline", "github actions", "jenkins", "deployment"],
    }

    for item in evidence_items:
        item_lower = item.text.lower()
        assigned_group = ""
        for group_name, keywords in cluster_keywords.items():
            if sum(1 for kw in keywords if kw in item_lower) >= 2:
                assigned_group = group_name
                break
        if not assigned_group:
            # Fallback group based on source or first major noun
            tokens = re.findall(r"\b[a-zA-Z]{5,}\b", item_lower)
            assigned_group = tokens[0] if tokens else "general"

        item.redundancy_group = assigned_group
