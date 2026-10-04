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


def _resolve_max_pages(state: CVPipelineState) -> int:
    """Resolves the target maximum page count from state metadata or strategy description."""
    strategy_meta = state.get("strategy_metadata")
    if strategy_meta:
        return strategy_meta.max_pages

    strategy_text = state.get("strategy_info", "").lower()
    if "3 pages" in strategy_text or "3-page" in strategy_text:
        return 3
    if "1 page" in strategy_text or "1-page" in strategy_text:
        return 1
    return 2


def check_typesetting_budget(draft: str, max_pages: int) -> tuple[bool, str, int, int]:
    """
    Evaluates whether the drafted CV fits within the calibrated typesetting page budget.
    Returns (is_over_budget, feedback_message, word_count, bullet_count).
    """
    words = len(draft.split())
    bullet_lines = sum(
        1 for line in draft.splitlines()
        if line.strip().startswith(("- ", "* ", "• "))
    )
    char_count = len(draft)

    if max_pages == 1:
        word_limit, bullet_limit, char_limit = 500, 20, 4500
    elif max_pages == 3:
        word_limit, bullet_limit, char_limit = 1550, 62, 12500
    elif max_pages >= 4:
        word_limit = max_pages * 500
        bullet_limit = max_pages * 20
        char_limit = 12500 + (max_pages - 3) * 4000
    else:  # 2 pages default
        word_limit, bullet_limit, char_limit = 1050, 42, 8500

    over_words = words > word_limit
    over_bullets = bullet_lines > bullet_limit
    over_chars = char_count > char_limit

    if over_words or over_bullets or over_chars:
        excess_words = max(0, words - word_limit)
        excess_bullets = max(0, bullet_lines - bullet_limit)
        feedback = (
            f"DENSITY ERROR: The CV is too long. DENSITY OVERFLOW: CV exceeds the {max_pages}-page budget. "
            f"Words: {words}/{word_limit} (+{excess_words}), "
            f"Bullet lines: {bullet_lines}/{bullet_limit} (+{excess_bullets}), "
            f"Characters: {char_count}/{char_limit}. "
            "Compress wordy STAR achievement bullets, eliminate fluff, and trim secondary accomplishments from older roles."
        )
        return True, feedback, words, bullet_lines

    return False, "", words, bullet_lines


def node_refiner(state: CVPipelineState) -> dict[str, Any]:
    """Verify that the drafted CV does not violate calibrated typesetting limits."""
    logging.info("--- NODE D: REFINER GUARD ---")
    draft = state.get("draft_cv", "")
    max_pages = _resolve_max_pages(state)
    is_over, feedback, words, bullets = check_typesetting_budget(draft, max_pages)

    if is_over:
        logging.warning(f"Refiner guard: over budget ({words} words, {bullets} bullets, max {max_pages} pages).")
        return {
            "refiner_feedback": feedback,
            "total_words": words,
            "total_bullet_lines": bullets,
        }

    logging.info(f"Refiner guard: within budget ({words} words, {bullets} bullets, max {max_pages} pages).")
    return {
        "refiner_feedback": "",
        "total_words": words,
        "total_bullet_lines": bullets,
    }


def node_compressor(state: CVPipelineState) -> dict[str, Any]:
    """Compress the drafted CV to strictly fit the typesetting page budget using a fast model."""
    logging.info("--- NODE E: FAST COMPRESSOR ---")
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

    compressor_template = load_prompt("compressor.txt")
    prompt = (
        compressor_template
        .replace("{max_pages}", str(max_pages))
        .replace("{target_words}", str(word_limit))
        .replace("{target_bullet_lines}", str(bullet_limit))
        .replace("{current_metrics}", current_metrics)
        .replace("{draft_cv}", draft)
        .replace("{job_description}", jd)
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    compressed_text = llm_text(response.content).strip()

    if compressed_text.startswith("```"):
        compressed_text = re.sub(r"^```(?:markdown)?\n", "", compressed_text)
        compressed_text = re.sub(r"\n```$", "", compressed_text).strip()

    compression_count = state.get("compression_count", 0) + 1
    return {
        "draft_cv": compressed_text,
        "compression_count": compression_count,
    }


def _handle_interactive_audit(checklist: list[str], ats_score: dict[str, Any]) -> tuple[bool, str]:
    """Interactive CLI prompt allowing the user to review the scorecard and guide the audit."""
    import sys
    if not sys.stdin.isatty():
        return False, ""

    print("\n" + "=" * 50)
    print("🤝 INTERACTIVE AUDITOR REVIEW")
    print("=" * 50)
    print("[1] Accept Draft (override audit and mark PASS)")
    print("[2] Provide Custom Revision Guidance")
    print("[3] Proceed with Automatic Rewrite Checklist")
    try:
        choice = input("Select an option [1-3] (default 3): ").strip()
    except (EOFError, KeyboardInterrupt):
        return False, ""

    if choice == "1":
        return True, "PASS"
    if choice == "2":
        try:
            custom_note = input("Enter your custom revision directive for the drafter: ").strip()
        except (EOFError, KeyboardInterrupt):
            custom_note = ""
        if custom_note:
            feedback = f"USER REVISION DIRECTIVE:\n- {custom_note}\n\nORIGINAL AUDIT CHECKLIST:\n" + "\n".join(
                [f"- [ ] {item}" for item in checklist]
            )
            return True, feedback
    return False, ""


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

    ats_score: dict[str, Any] = {}
    try:
        audit_data = json.loads(json_str)
        is_pass = audit_data.get("pass", False)
        ats_score = audit_data.get("ats_score", {})
        checklist = audit_data.get("rewrite_checklist", [])

        total_score = ats_score.get("total_score", 0)
        logging.info(f"--- ATS SCORECARD: {total_score}/100 ---")
        for dimension, details in ats_score.items():
            if isinstance(details, dict):
                score_val = details.get("score", 0)
                max_val = details.get("max", 100)
                justification = details.get("justification", "")
                logging.info(f"    * {dimension}: {score_val}/{max_val} - {justification}")

        if is_pass:
            stored_feedback = "PASS"
            logging.info("ATS AUDIT: PASS")
        else:
            stored_feedback = "REWRITE REQUIRED:\n" + "\n".join([f"- [ ] {item}" for item in checklist])
            logging.info(f"ATS AUDIT: REWRITE REQUIRED - {len(checklist)} items to address.")
            if state.get("interactive", False):
                handled, custom_feedback = _handle_interactive_audit(checklist, ats_score)
                if handled:
                    stored_feedback = custom_feedback
    except Exception as e:
        logging.warning(f"Failed to parse structured auditor JSON: {e}. Falling back to raw text.")
        stored_feedback = feedback

    return {
        "audit_feedback": stored_feedback,
        "ats_scorecard": ats_score,
        "iteration_count": current_iterations + 1,
    }
