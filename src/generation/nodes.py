"""Nodes for the CV generation pipeline graph."""

import logging
import json
import re
from typing import Any

from langchain_core.messages import HumanMessage

from kb_config import (
    get_model_for_step,
    get_strategy_default,
    get_wiki_dir,
)
from generation.state import CVPipelineState, RegionalStrategy
from generation.helpers import (
    llm_text,
    robust_json_loads,
    load_prompt,
    generate_skill_bridging_map,
    retrieve_and_score_experiences,
    retrieve_and_deduplicate_education,
    retrieve_languages,
    retrieve_and_score_projects,
    retrieve_and_score_patents,
    retrieve_and_score_notes,
    retrieve_few_shots,
    resolve_regional_strategy,
    get_subject_info,
    parse_and_sort_chronological_entries,
    invoke_drafter_llm_with_fallback,
)


def node_analyzer(state: CVPipelineState) -> dict[str, Any]:
    """Analyze the job description, extract keywords, expected format, location, organization, and regional strategy."""
    logging.info("--- NODE A: ANALYZER ---")
    llm = get_model_for_step("ANALYSIS", format="json")
    jd = state.get("job_description", "")

    # Discover available strategies
    strategies_dir = get_wiki_dir() / "wiki" / "strategies"
    available_strategies: list[str] = []
    if strategies_dir.exists():
        available_strategies = [
            f.stem.replace("strategy-", "") for f in strategies_dir.glob("strategy-*.md")
        ]

    default_strategy = get_strategy_default()

    analyzer_template = load_prompt("analyzer.txt")
    prompt = (
        analyzer_template
        .replace("{AVAILABLE_STRATEGIES}", ", ".join(available_strategies))
        .replace("{DEFAULT_STRATEGY}", default_strategy)
        .replace("{JOB_DESCRIPTION}", jd)
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    content = llm_text(response.content)

    try:
        data = robust_json_loads(content)
        persona = data.get("persona", content)
        keywords = data.get("keywords", [])
        locations = data.get("locations", [])
        expectations = data.get("expectations", "Standard professional CV")
        region = data.get("suggested_region", default_strategy).lower()
        target_org = data.get("target_organization_slug", "unknown-company").lower()
        target_role = data.get("target_role", "unknown-role")
    except Exception as e:
        logging.warning(
            f"Failed to parse JSON from Analyzer, falling back to heuristics: {e}"
        )
        persona = content
        keywords = []
        locations = []
        expectations = "Standard professional CV"
        region = default_strategy
        target_org = "unknown-company"
        target_role = "unknown-role"

    strategy_override = state.get("strategy_override", "")
    if strategy_override:
        logging.info(f"Bypassing analyzer strategy inference. Using override: {strategy_override}")
        region = strategy_override.lower()

    logging.info(f"Locations detected: {', '.join(locations)}")
    logging.info(f"CV Expectations: {expectations}")
    logging.info(f"Target Region suggested: {region.upper()}")

    return {
        "target_persona": persona,
        "primary_keywords": keywords,
        "target_region": region,
        "target_locations": locations,
        "cv_expectations": expectations,
        "target_organization_slug": target_org,
        "target_role": target_role
    }


def node_retriever(state: CVPipelineState) -> dict[str, Any]:
    """Retrieve education, skills, projects, patents, notes, few-shots, and match semantic relevance of experiences."""
    logging.info("--- NODE B: RETRIEVER ---")
    llm = get_model_for_step("RETRIEVAL", format="json")

    jd = state.get("job_description", "")
    persona = state.get("target_persona", "")
    keywords = state.get("primary_keywords", [])
    region = state.get("target_region", get_strategy_default())
    locations = state.get("target_locations", [])
    expectations = state.get("cv_expectations", "")

    wiki_dir = get_wiki_dir()

    # Load strategy first to determine page budget
    strategy_text, pdf_template = resolve_regional_strategy(wiki_dir, region)
    strategy_obj = RegionalStrategy.from_markdown(strategy_text)

    # Sub-retrievals (with budget-aware pruning)
    selected_content, retrieved_exp_slugs = retrieve_and_score_experiences(
        llm, keywords, persona, jd, max_pages=strategy_obj.max_pages
    )
    education_content = retrieve_and_deduplicate_education(wiki_dir)
    
    skills_dir = wiki_dir / "wiki" / "skills"
    from generation.skills_helper import get_compact_skills_list
    skills_content = get_compact_skills_list(skills_dir, retrieved_exp_slugs)

    projects_entries = retrieve_and_score_projects(wiki_dir, keywords, retrieved_exp_slugs)
    patents_entries = retrieve_and_score_patents(wiki_dir, keywords, retrieved_exp_slugs)
    notes_entries = retrieve_and_score_notes(wiki_dir, keywords, retrieved_exp_slugs)
    few_shot_examples = retrieve_few_shots(wiki_dir, keywords)

    languages_content = retrieve_languages(wiki_dir)

    skill_bridging_map = generate_skill_bridging_map(llm, skills_content, keywords)
    subject_info = get_subject_info(wiki_dir)

    context_info = f"""
--- SUBJECT PROFILE (The Truth Source for Contact/Bio) ---
{subject_info}

--- ROLE CONTEXT ---
Target Locations: {', '.join(locations)}
CV Format Expectations: {expectations}

--- REGIONAL TAILORING STRATEGY ({region.upper()}) ---
{strategy_text}
"""

    return {
        "selected_entries": selected_content,
        "education_entries": education_content,
        "skills_entries": skills_content,
        "languages_entries": languages_content,
        "projects_entries": projects_entries,
        "patents_entries": patents_entries,
        "notes_entries": notes_entries,
        "few_shot_examples": few_shot_examples,
        "skill_bridging_map": skill_bridging_map,
        "strategy_info": context_info,
        "strategy_metadata": strategy_obj,
        "pdf_template": pdf_template
    }


def node_drafter(state: CVPipelineState) -> dict[str, Any]:
    """Draft the resume/CV using SystemMessage constraints and externalized drafter prompts."""
    logging.info("--- NODE C: DRAFTER ---")
    llm = get_model_for_step("DRAFTING")

    jd = state.get("job_description", "")
    entries = state.get("selected_entries", [])
    education = state.get("education_entries", [])
    skills = state.get("skills_entries", [])
    strategy = state.get("strategy_info", "")
    feedback = state.get("audit_feedback", "")
    refiner_feedback = state.get("refiner_feedback", "")

    # Retrieve expanded state values
    projects = state.get("projects_entries", [])
    patents = state.get("patents_entries", [])
    notes = state.get("notes_entries", [])
    few_shots = state.get("few_shot_examples", [])
    skill_bridge = state.get("skill_bridging_map", {})

    languages = state.get("languages_entries", [])
    languages_text = "\n".join(languages)

    education_text = "\n\n".join(education)
    skills_text = "\n".join(skills)
    if languages_text:
        skills_text += "\n\nSPOKEN LANGUAGES:\n" + languages_text

    projects_text = "\n\n".join(projects)
    patents_text = "\n\n".join(patents)
    notes_text = "\n\n".join(notes)
    few_shots_text = "\n\n".join(few_shots)
    skill_bridge_text = (
        json.dumps(skill_bridge, indent=2) if skill_bridge else "None"
    )

    feedback_instruction = ""
    if feedback:
        feedback_instruction += f"\nCRITICAL AUDIT FEEDBACK TO INCORPORATE: {feedback}"
    if refiner_feedback:
        feedback_instruction += f"\nCRITICAL DENSITY/LENGTH FEEDBACK: {refiner_feedback}"

    chronological_entries_text = parse_and_sort_chronological_entries(entries)

    system_prompt = load_prompt("drafter_system.txt")
    user_template = load_prompt("drafter_user.txt")

    prompt = user_template.format(
        job_description=jd,
        feedback_instruction=feedback_instruction,
        strategy_info=strategy,
        skill_bridge_text=skill_bridge_text,
        few_shots_text=few_shots_text,
        chronological_entries_text=chronological_entries_text,
        projects_text=projects_text,
        patents_text=patents_text,
        notes_text=notes_text,
        education_text=education_text,
        skills_text=skills_text
    )

    response = invoke_drafter_llm_with_fallback(llm, system_prompt, prompt)
    return {"draft_cv": llm_text(response.content)}


def node_refiner(state: CVPipelineState) -> dict[str, Any]:
    """Verify that the drafted CV/Resume does not violate regional length limitations, giving density feedback."""
    logging.info("--- NODE D: REFINER ---")
    draft = state.get("draft_cv", "")
    char_count = len(draft)
    logging.info(f"Current CV length: {char_count} characters.")

    # Try to find the strongly-typed strategy metadata in the state
    strategy_meta = state.get("strategy_metadata")
    if strategy_meta:
        max_pages = strategy_meta.max_pages
        logging.info(f"Using strongly-typed max pages limit from strategy metadata: {max_pages}")
    else:
        # Fallback to textual description matching for backwards compatibility (e.g., legacy test state)
        max_pages = 2
        strategy_text = state.get("strategy_info", "").lower()
        if "3 pages" in strategy_text or "3-page" in strategy_text:
            max_pages = 3
            logging.info("Regional strategy indicates a 3-page limit from text description (fallback).")
        elif "1 page" in strategy_text or "1-page" in strategy_text:
            max_pages = 1
            logging.info("Regional strategy indicates a 1-page limit from text description (fallback).")

    # Calculate dynamic character limit based on page count
    if max_pages == 1:
        char_limit = 4500
    elif max_pages == 3:
        char_limit = 12500
    elif max_pages >= 4:
        char_limit = 12500 + (max_pages - 3) * 4000
    else:
        char_limit = 8500  # Default to 2 pages (8500 characters)

    logging.info(f"Target page limit: {max_pages}. Dynamically computed character budget: {char_limit}.")

    if char_count > char_limit:
        feedback = (
            f"DENSITY ERROR: The CV is too long ({char_count} characters, limit is {char_limit}). "
            "Please compress older roles to single-line summaries. "
            "In current and recent roles, keep only the most impactful bullets that directly "
            "align with the target job description to maximize the ATS score and relevance."
        )
        return {"refiner_feedback": feedback}

    return {"refiner_feedback": ""}


def node_auditor(state: CVPipelineState) -> dict[str, Any]:
    """Perform a brutal human-like ATS compliance audit, returning a PASS or a checklist of rewrite actions."""
    logging.info("--- NODE D: AUDITOR ---")
    llm = get_model_for_step("AUDIT")

    jd = state.get("job_description", "")
    draft = state.get("draft_cv", "")
    current_iterations = state.get("iteration_count", 0)
    strategy = state.get("strategy_info", "")

    auditor_template = load_prompt("auditor.txt")
    skills = state.get("skills_entries", [])
    skills_text = "\n".join(skills)
    prompt = (
        auditor_template
        .replace("{job_description}", jd)
        .replace("{draft_cv}", draft)
        .replace("{candidate_skills}", skills_text)
        .replace("{strategy_info}", strategy)
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    feedback = llm_text(response.content).strip()

    # Clean markdown json code blocks if present and parse the scorecard
    json_str = feedback
    if "```" in json_str:
        blocks = re.findall(r'```(?:json)?\s*(.*?)\s*```', json_str, re.DOTALL)
        if blocks:
            json_str = blocks[0].strip()

    try:
        audit_data = json.loads(json_str)
        is_pass = audit_data.get("pass", False)
        ats_score = audit_data.get("ats_score", {})
        checklist = audit_data.get("rewrite_checklist", [])

        total_score = ats_score.get("total_score", 0)
        logging.info(f"--- ATS SCORECARD: {total_score}/100 ---")
        print(f"\n📊 [ATS SCORECARD: {total_score}/100]")
        for dimension, details in ats_score.items():
            if isinstance(details, dict):
                score_val = details.get("score", 0)
                max_val = details.get("max", 100)
                justification = details.get("justification", "")
                print(f"  - {dimension.replace('_', ' ').title()}: {score_val}/{max_val}")
                logging.info(f"    * {dimension}: {score_val}/{max_val} - {justification}")

        if is_pass:
            stored_feedback = "PASS"
            print("✅ [ATS AUDIT: PASS]")
        else:
            stored_feedback = "REWRITE REQUIRED:\n" + "\n".join([f"- [ ] {item}" for item in checklist])
            print(f"❌ [ATS AUDIT: REWRITE REQUIRED] - {len(checklist)} items to address.")
    except Exception as e:
        logging.warning(f"Failed to parse structured auditor JSON: {e}. Falling back to raw text.")
        stored_feedback = feedback

    return {"audit_feedback": stored_feedback, "iteration_count": current_iterations + 1}
