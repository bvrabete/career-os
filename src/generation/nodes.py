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
    _parse_yaml_frontmatter_from_text,
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


def _get_org_slug_from_experience(exp_str: str) -> str:
    """Helper to extract organization slug from experience frontmatter."""
    fm = _parse_yaml_frontmatter_from_text(exp_str)
    org = str(fm.get("organization", "")).strip().lower()
    if org.startswith("[[") and org.endswith("]]"):
        org = org[2:-2].strip().lower()
    return org


def _find_associated_entries(org_slug: str, entries_list: list[str]) -> list[str]:
    """Find all items in entries_list associated with the given org_slug."""
    matched: list[str] = []
    if not org_slug:
        return matched
    for entry in entries_list:
        if org_slug in entry.lower():
            matched.append(entry)
    return matched


def _clean_subject_info(subject_info: str) -> str:
    """Filter out the Assessments & Cognitive Profile section from subject info."""
    lines: list[str] = []
    skipping = False
    for line in subject_info.splitlines():
        if line.strip().startswith("## Assessments"):
            skipping = True
            continue
        if skipping and line.strip().startswith("## ") and not line.strip().startswith("## Assessments"):
            skipping = False
        if not skipping:
            lines.append(line)
    return "\n".join(lines).strip()


def _draft_single_experience(
    llm: Any,
    system_prompt: str,
    entry: str,
    keywords_str: str,
    projects: list[str],
    patents: list[str],
    notes: list[str],
    skill_bridge_str: str,
    feedback_instruction: str = ""
) -> str:
    """Invoke LLM to tailor a single isolated experience role with its associated assets."""
    template = load_prompt("map_draft_role.txt")
    prompt = template.format(
        keywords=keywords_str,
        experience_content=entry,
        associated_projects="\n\n".join(projects) if projects else "None",
        associated_patents="\n\n".join(patents) if patents else "None",
        associated_notes="\n\n".join(notes) if notes else "None",
        skill_bridge_text=skill_bridge_str
    )
    if feedback_instruction:
        prompt += f"\n\n--- CRITICAL RE-DRAFT/DENSITY CORRECTION FEEDBACK:\n{feedback_instruction}\nPlease modify the bullet points to satisfy these guidelines (e.g. compress or edit structure as requested)."
    response = invoke_drafter_llm_with_fallback(llm, system_prompt, prompt)
    return llm_text(response.content)


def node_drafter(state: CVPipelineState) -> dict[str, Any]:
    """Draft the resume/CV using an isolated Map-Reduce tailoring approach or fallback to monolithic."""
    logging.info("--- NODE C: DRAFTER (MAP-REDUCE) ---")
    llm = get_model_for_step("DRAFTING")

    jd = state.get("job_description", "")
    entries = state.get("selected_entries", [])
    education = state.get("education_entries", [])
    skills = state.get("skills_entries", [])
    projects = state.get("projects_entries", [])
    patents = state.get("patents_entries", [])
    notes = state.get("notes_entries", [])
    skill_bridge = state.get("skill_bridging_map", {})
    keywords = state.get("primary_keywords", [])
    keywords_str = ", ".join(keywords) if keywords else "None"
    skill_bridge_str = json.dumps(skill_bridge, indent=2) if skill_bridge else "None"

    languages = state.get("languages_entries", [])
    skills_text = "\n".join(skills)
    if languages:
        skills_text += "\n\nSPOKEN LANGUAGES:\n" + "\n".join(languages)

    system_prompt = load_prompt("drafter_system.txt")
    
    # Check if we should use legacy/monolithic drafting (to perfectly satisfy unit tests or legacy configurations)
    try:
        user_template = load_prompt("drafter_user.txt")
    except Exception:
        user_template = ""

    if "{job_description}" in user_template:
        logging.info("Monolithic/Legacy template detected. Falling back to Monolithic formatting.")
        feedback = state.get("audit_feedback", "")
        refiner_feedback = state.get("refiner_feedback", "")
        feedback_instruction = ""
        if feedback:
            feedback_instruction += f"\nCRITICAL AUDIT FEEDBACK TO INCORPORATE: {feedback}"
        if refiner_feedback:
            feedback_instruction += f"\nCRITICAL DENSITY/LENGTH FEEDBACK: {refiner_feedback}"

        chronological_entries_text = parse_and_sort_chronological_entries(entries)
        few_shots = state.get("few_shot_examples", [])
        
        prompt = user_template.format(
            job_description=jd,
            feedback_instruction=feedback_instruction,
            strategy_info=state.get("strategy_info", ""),
            skill_bridge_text=skill_bridge_str,
            few_shots_text="\n\n".join(few_shots),
            chronological_entries_text=chronological_entries_text,
            projects_text="\n\n".join(projects),
            patents_text="\n\n".join(patents),
            notes_text="\n\n".join(notes),
            education_text="\n\n".join(education),
            skills_text=skills_text
        )
        response = invoke_drafter_llm_with_fallback(llm, system_prompt, prompt)
        return {"draft_cv": llm_text(response.content)}

    # Construct feedback instructions if we are in a re-draft loop
    feedback = state.get("audit_feedback", "")
    refiner_feedback = state.get("refiner_feedback", "")
    feedback_instruction = ""
    if feedback and feedback != "PASS":
        feedback_instruction += f"\nCRITICAL AUDIT FEEDBACK TO INCORPORATE: {feedback}"
    if refiner_feedback:
        feedback_instruction += f"\nCRITICAL DENSITY/LENGTH FEEDBACK: {refiner_feedback}"

    # Map Phase: tailor each experience in isolation
    tailored_experiences: list[str] = []
    for entry in entries:
        org_slug = _get_org_slug_from_experience(entry)
        assoc_projects = _find_associated_entries(org_slug, projects)
        assoc_patents = _find_associated_entries(org_slug, patents)
        assoc_notes = _find_associated_entries(org_slug, notes)
        
        tailored = _draft_single_experience(
            llm, system_prompt, entry, keywords_str,
            assoc_projects, assoc_patents, assoc_notes, skill_bridge_str,
            feedback_instruction=feedback_instruction
        )
        tailored_experiences.append(tailored)

    # Reduce Phase: Assemble the final resume structure
    education_text = "\n\n".join(education)
    drafted_work_experience = "\n\n".join(tailored_experiences)
    subject_info = get_subject_info(get_wiki_dir())
    cleaned_subject_info = _clean_subject_info(subject_info)

    final_cv = f"""{cleaned_subject_info}

## Work Experience

{drafted_work_experience}

## Education

{education_text}

## Skills & Technologies

{skills_text}
"""
    return {"draft_cv": final_cv.strip()}


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
