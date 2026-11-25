"""Nodes for the CV generation pipeline graph."""

import json
import logging
import re
from typing import Any, Literal

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from generation.cv_renderer import (
    parse_and_render_structured_cv,
    render_ats_markdown,
)
from generation.formatting import (
    check_typesetting_budget as check_typesetting_budget,
    handle_interactive_audit as _handle_interactive_audit,
    strip_wikilinks,
)
from generation.helpers import (
    _resolve_compressed_cv_doc,
    _resolve_compressor_input,
    _resolve_target_employer_slug,
    assemble_role_evidence_bundles,
    discover_available_strategies,
    generate_skill_bridging_map,
    get_subject_info,
    invoke_drafter_llm_with_fallback,
    llm_text,
    load_prompt,
    parse_and_sort_chronological_entries,
    resolve_regional_strategy,
    resolve_track_strategy,
    retrieve_and_deduplicate_education,
    retrieve_and_score_case_studies,
    retrieve_and_score_experiences,
    retrieve_and_score_notes,
    retrieve_and_score_patents,
    retrieve_and_score_projects,
    retrieve_few_shots,
    retrieve_languages,
    retrieve_voice_guide,
    robust_json_loads,
)
import generation.skills_helper as skills_helper
from generation.state import (
    AnalyzerOutput,
    AuditOutput,
    CVPipelineState,
    RegionalStrategy,
    TrackStrategy,
)
from kb_config import (
    get_model_for_step,
    get_strategy_default,
    get_wiki_dir,
)

logger = logging.getLogger(__name__)


def node_analyzer(state: CVPipelineState) -> dict[str, Any]:
    """Analyze the job description, extract keywords, expected format, location, employer vs. agency, and strategy."""
    logger.info("--- NODE A: ANALYZER ---")
    llm = get_model_for_step("ANALYSIS", format="json")
    jd = str(state.get("job_description") or state.get("job_description_raw") or "")

    wiki_dir = get_wiki_dir()
    available_locations, available_tracks = discover_available_strategies(wiki_dir)
    default_strategy = get_strategy_default()
    if not available_tracks:
        available_tracks = [
            "engineering-management",
            "staff-principal",
            "executive",
            "startup-founding-engineer",
            "general-engineering",
        ]

    analyzer_template = load_prompt("analyzer.txt")
    prompt = (
        analyzer_template
        .replace("{AVAILABLE_STRATEGIES}", ", ".join(available_locations))
        .replace("{AVAILABLE_TRACKS}", ", ".join(available_tracks))
        .replace("{DEFAULT_STRATEGY}", default_strategy)
        .replace("{JOB_DESCRIPTION}", jd)
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    content = llm_text(response.content)

    try:
        raw_data = robust_json_loads(content)
        parsed = AnalyzerOutput.model_validate(raw_data)
        persona = raw_data.get("persona", content)
        keywords = parsed.keywords
        locations = parsed.locations
        expectations = parsed.expectations
        region = str(raw_data.get("suggested_region", default_strategy)).lower()
        track = str(raw_data.get("suggested_track", "engineering-management")).lower()
        org_type, agency_name, employer_name, target_org = _resolve_target_employer_slug(raw_data)
        target_role = parsed.target_role
        employer_archetype = parsed.employer_archetype
        parallel_venture_policy = parsed.parallel_venture_policy
    except Exception as e:
        logger.warning("Failed to parse JSON from Analyzer, falling back to heuristics: %s", e)
        persona = content
        keywords = []
        locations = []
        expectations = "Standard professional CV"
        region = default_strategy
        track = "engineering-management"
        org_type = "direct_employer"
        agency_name = ""
        employer_name = ""
        target_org = "unknown-company"
        target_role = "unknown-role"
        employer_archetype = "enterprise_corporate"
        parallel_venture_policy = "strict_single_timeline"

    strategy_override = state.get("strategy_override", "")
    if strategy_override:
        logger.info("Bypassing analyzer strategy inference. Using override: %s", strategy_override)
        region = strategy_override.lower()

    track_override = state.get("track_override", "")
    if track_override:
        logger.info("Bypassing analyzer track inference. Using override: %s", track_override)
        track = track_override.lower()

    return {
        "job_description": jd,
        "target_persona": persona,
        "primary_keywords": keywords,
        "target_region": region,
        "target_track": track,
        "target_locations": locations,
        "cv_expectations": expectations,
        "posting_organization_type": org_type,
        "recruitment_agency_name": agency_name,
        "target_employer_name": employer_name,
        "target_organization_slug": target_org,
        "target_role": target_role,
        "employer_archetype": employer_archetype,
        "parallel_venture_policy": parallel_venture_policy,
    }


def node_retriever(state: CVPipelineState) -> dict[str, Any]:
    """Retrieve education, skills, projects, patents, notes, voice guide, role bundles, and match experiences."""
    logger.info("--- NODE B: RETRIEVER ---")
    llm = get_model_for_step("RETRIEVAL", format="json")

    jd = state.get("job_description", "")
    persona = state.get("target_persona", "")
    keywords = state.get("primary_keywords", [])
    region = state.get("target_region", get_strategy_default())
    track = state.get("target_track", "engineering-management")
    locations = state.get("target_locations", [])
    expectations = state.get("cv_expectations", "")

    wiki_dir = get_wiki_dir()

    strategy_text, pdf_template = resolve_regional_strategy(wiki_dir, region)
    track_strategy_text = resolve_track_strategy(wiki_dir, track)
    strategy_obj = RegionalStrategy.from_markdown(strategy_text)
    track_obj = TrackStrategy.from_markdown(track_strategy_text)

    selected_content, retrieved_exp_slugs = retrieve_and_score_experiences(
        llm,
        keywords,
        persona,
        jd,
        max_pages=strategy_obj.max_pages,
        target_track=track,
        org_culture=track_obj.org_culture,
    )
    education_content = retrieve_and_deduplicate_education(wiki_dir)

    skills_dir = wiki_dir / "wiki" / "skills"
    skills_content = skills_helper.get_compact_skills_list(skills_dir, retrieved_exp_slugs)
    all_candidate_skills = skills_helper.get_all_candidate_skills(wiki_dir)

    projects_entries = retrieve_and_score_projects(wiki_dir, keywords, retrieved_exp_slugs)
    patents_entries = retrieve_and_score_patents(wiki_dir, keywords, retrieved_exp_slugs)
    notes_entries = retrieve_and_score_notes(wiki_dir, keywords, retrieved_exp_slugs)
    case_studies_entries = retrieve_and_score_case_studies(wiki_dir, keywords, retrieved_exp_slugs)
    few_shot_examples = retrieve_few_shots(wiki_dir, keywords)
    languages_content = retrieve_languages(wiki_dir)
    voice_guide = retrieve_voice_guide(wiki_dir)
    role_bundles = assemble_role_evidence_bundles(wiki_dir, selected_content)

    skill_bridging_map = generate_skill_bridging_map(llm, skills_content, keywords)
    subject_info = get_subject_info(wiki_dir)

    voice_block = f"\n--- CANDIDATE VOICE & STYLE GUIDE ---\n{voice_guide}\n" if voice_guide else ""
    context_info = f"""
--- SUBJECT PROFILE (The Truth Source for Contact/Bio) ---
{subject_info}
{voice_block}
--- ROLE CONTEXT ---
Target Locations: {', '.join(locations)}
CV Format Expectations: {expectations}
Target Page Budget: {strategy_obj.max_pages} Page(s)

--- REGIONAL TAILORING STRATEGY ({region.upper()}) ---
{strategy_text}

--- CAREER TRACK STRATEGY ({track.upper()}) ---
{track_strategy_text}
"""

    return {
        "selected_entries": selected_content,
        "role_bundles": role_bundles,
        "education_entries": education_content,
        "skills_entries": skills_content,
        "all_candidate_skills": all_candidate_skills,
        "languages_entries": languages_content,
        "projects_entries": projects_entries,
        "patents_entries": patents_entries,
        "notes_entries": notes_entries,
        "case_studies_entries": case_studies_entries,
        "few_shot_examples": few_shot_examples,
        "skill_bridging_map": skill_bridging_map,
        "voice_guide": voice_guide,
        "strategy_info": context_info,
        "strategy_metadata": strategy_obj,
        "track_strategy_info": track_strategy_text,
        "track_strategy_metadata": track_obj,
        "target_track": track,
        "pdf_template": pdf_template,
    }


def _resolve_max_pages(state: CVPipelineState) -> int:
    """Resolve the target maximum page count from state metadata or strategy description."""
    strategy_meta = state.get("strategy_metadata")
    if strategy_meta and hasattr(strategy_meta, "max_pages"):
        return int(strategy_meta.max_pages)

    strategy_text = state.get("strategy_info", "").lower()
    if "3 pages" in strategy_text or "3-page" in strategy_text:
        return 3
    if "1 page" in strategy_text or "1-page" in strategy_text:
        return 1
    return 2


def node_drafter(state: CVPipelineState) -> dict[str, Any]:
    """Draft the resume/CV using SystemMessage constraints and externalized drafter prompts."""
    logger.info("--- NODE C: DRAFTER ---")
    llm = get_model_for_step("DRAFTING")

    jd = state.get("job_description", "")
    entries = state.get("selected_entries", [])
    education = state.get("education_entries", [])
    skills = state.get("skills_entries", [])
    strategy = state.get("strategy_info", "")
    feedback = state.get("audit_feedback", "")
    refiner_feedback = state.get("refiner_feedback", "")

    projects = state.get("projects_entries", [])
    patents = state.get("patents_entries", [])
    notes = state.get("notes_entries", [])
    case_studies = state.get("case_studies_entries", [])
    few_shots = state.get("few_shot_examples", [])
    skill_bridge = state.get("skill_bridging_map", {})
    languages = state.get("languages_entries", [])

    skills_text = "\n".join(skills)
    if languages:
        skills_text += "\n\nSPOKEN LANGUAGES:\n" + "\n".join(languages)

    feedback_instruction = ""
    if feedback:
        feedback_instruction += f"\nCRITICAL AUDIT FEEDBACK TO INCORPORATE: {feedback}"
    if refiner_feedback:
        feedback_instruction += f"\nCRITICAL DENSITY/LENGTH FEEDBACK: {refiner_feedback}"

    chronological_entries_text = parse_and_sort_chronological_entries(entries)

    manifest = state.get("selection_manifest")
    selection_manifest_text = "None"
    if manifest and isinstance(manifest, dict):
        selected_ev = manifest.get("selected_evidence", [])
        if selected_ev:
            lines = [
                f"- [{item.get('role_or_project', 'Evidence')}] {item.get('text', '')}"
                for item in selected_ev
                if isinstance(item, dict)
            ]
            selection_manifest_text = "\n".join(lines)

    system_prompt = load_prompt("drafter_system.txt")
    user_template = load_prompt("drafter_user.txt")

    prompt = user_template.format(
        job_description=jd,
        feedback_instruction=feedback_instruction,
        strategy_info=strategy,
        selection_manifest_text=selection_manifest_text,
        skill_bridge_text=json.dumps(skill_bridge, indent=2) if skill_bridge else "None",
        few_shots_text="\n\n".join(few_shots),
        chronological_entries_text=chronological_entries_text,
        projects_text="\n\n".join(projects),
        patents_text="\n\n".join(patents),
        notes_text="\n\n".join(notes),
        case_studies_text="\n\n".join(case_studies),
        education_text="\n\n".join(education),
        skills_text=skills_text,
    )

    response = invoke_drafter_llm_with_fallback(llm, system_prompt, prompt)
    raw_content = strip_wikilinks(llm_text(response.content))
    region = str(state.get("target_region") or "emea")
    structured_dict, clean_draft = parse_and_render_structured_cv(raw_content, region=region)
    if structured_dict is not None:
        return {"structured_cv": structured_dict, "draft_cv": clean_draft}
    return {"draft_cv": clean_draft}


def node_refiner(state: CVPipelineState) -> Command[Literal["compressor", "auditor"]]:
    """Verify that the drafted CV does not violate calibrated typesetting limits."""
    logger.info("--- NODE D: REFINER GUARD ---")
    draft = state.get("draft_cv", "")
    max_pages = _resolve_max_pages(state)
    is_over, feedback, words, bullets = check_typesetting_budget(draft, max_pages)

    compression_count = state.get("compression_count", 0)

    if is_over:
        goto_node: Literal["compressor", "auditor"] = "compressor" if compression_count < 2 else "auditor"
        if goto_node == "compressor":
            logger.warning(
                "Refiner guard triggered fast compressor (pass %d/2) due to page budget overflow.",
                compression_count + 1,
            )
        logger.warning("Refiner guard: over budget (%d words, %d bullets, max %d pages).", words, bullets, max_pages)
        return Command(
            update={
                "refiner_feedback": feedback,
                "total_words": words,
                "total_bullet_lines": bullets,
            },
            goto=goto_node,
        )

    logger.info("Refiner guard: within budget (%d words, %d bullets, max %d pages).", words, bullets, max_pages)
    return Command(
        update={
            "refiner_feedback": "",
            "total_words": words,
            "total_bullet_lines": bullets,
        },
        goto="auditor",
    )


def node_compressor(state: CVPipelineState) -> dict[str, Any]:
    """Compress the drafted CV to strictly fit the typesetting page budget returning typed data."""
    logger.info("--- NODE E: FAST COMPRESSOR ---")
    try:
        llm = get_model_for_step("COMPRESSION")
    except Exception:
        llm = get_model_for_step("REFINEMENT")

    draft = state.get("draft_cv", "")
    jd = state.get("job_description", "")
    max_pages = _resolve_max_pages(state)
    word_limit = 500 if max_pages == 1 else (1550 if max_pages == 3 else (max_pages * 500 if max_pages >= 4 else 1050))
    bullet_limit = 20 if max_pages == 1 else (62 if max_pages == 3 else (max_pages * 20 if max_pages >= 4 else 42))

    current_words = state.get("total_words", len(draft.split()))
    current_bullets = state.get("total_bullet_lines", 0)
    current_metrics = f"{current_words} words, {current_bullets} bullet lines"
    refiner_feedback = state.get("refiner_feedback", "")
    cv_input = _resolve_compressor_input(state, draft)

    compressor_template = load_prompt("compressor.txt")
    prompt = (
        compressor_template
        .replace("{max_pages}", str(max_pages))
        .replace("{target_words}", str(word_limit))
        .replace("{target_bullet_lines}", str(bullet_limit))
        .replace("{current_metrics}", current_metrics)
        .replace("{refiner_feedback}", refiner_feedback)
        .replace("{structured_cv_json}", cv_input)
        .replace("{draft_cv}", draft)
        .replace("{job_description}", jd)
    )

    region = str(state.get("target_region") or "emea")
    compression_count = state.get("compression_count", 0) + 1
    cv_doc = _resolve_compressed_cv_doc(llm, prompt, state, max_pages)

    rendered_md = render_ats_markdown(cv_doc, strategy_region=region)
    return {
        "structured_cv": cv_doc.model_dump(),
        "draft_cv": rendered_md,
        "compression_count": compression_count,
    }


def node_auditor(state: CVPipelineState) -> Command[Literal["drafter", "__end__"]]:
    """Perform a human-like ATS compliance audit, returning a PASS or a checklist of rewrite actions."""
    logger.info("--- NODE D: AUDITOR ---")
    llm = get_model_for_step("AUDIT")

    jd = state.get("job_description", "")
    draft = state.get("draft_cv", "")
    current_iterations = state.get("iteration_count", 0)
    strategy = state.get("strategy_info", "")

    auditor_template = load_prompt("auditor.txt")
    skills = list(state.get("skills_entries", []))
    all_skills = state.get("all_candidate_skills", [])
    if all_skills:
        skills.append("All Verified Wiki Skills: " + ", ".join(all_skills))
    skills_text = "\n".join(skills)
    skill_bridge = state.get("skill_bridging_map", {})
    skill_bridge_str = json.dumps(skill_bridge, indent=2) if skill_bridge else "None"

    prompt = (
        auditor_template
        .replace("{job_description}", jd)
        .replace("{draft_cv}", draft)
        .replace("{candidate_skills}", skills_text)
        .replace("{skill_bridging_map}", skill_bridge_str)
        .replace("{strategy_info}", strategy)
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    feedback = llm_text(response.content).strip()

    json_str = feedback
    if "```" in json_str:
        blocks = re.findall(r"```(?:json)?\s*(.*?)\s*```", json_str, re.DOTALL)
        if blocks:
            json_str = blocks[0].strip()

    ats_score: dict[str, Any] = {}
    try:
        raw_audit = robust_json_loads(json_str)
        audit_obj = AuditOutput.model_validate(raw_audit)
        is_pass = audit_obj.is_pass
        ats_score = audit_obj.ats_score.model_dump()
        checklist = audit_obj.rewrite_checklist

        if is_pass:
            stored_feedback = "PASS"
        else:
            stored_feedback = "REWRITE REQUIRED:\n" + "\n".join([f"- [ ] {item}" for item in checklist])
            if state.get("interactive", False):
                handled, custom_feedback = _handle_interactive_audit(checklist, ats_score)
                if handled:
                    stored_feedback = custom_feedback
    except Exception as e:
        logger.warning("Failed to parse structured auditor JSON: %s. Falling back to raw text.", e)
        stored_feedback = feedback

    is_pass = "PASS" in stored_feedback or (current_iterations + 1) >= 3
    goto_target: Literal["drafter", "__end__"] = "__end__" if is_pass else "drafter"
    update_payload: dict[str, Any] = {
        "audit_feedback": stored_feedback,
        "ats_scorecard": ats_score,
        "iteration_count": current_iterations + 1,
    }
    if goto_target == "drafter":
        update_payload["compression_count"] = 0

    return Command(update=update_payload, goto=goto_target)
