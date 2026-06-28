"""Nodes for the CV generation pipeline graph."""

import logging
import json
import re
from pathlib import Path
from typing import Any
import yaml
from langchain_core.messages import HumanMessage, SystemMessage

from kb_config import (
    get_model_for_step,
    get_strategy_default,
    get_wiki_dir,
    get_fallback_model_for_step
)
from generation.state import CVPipelineState
from generation.helpers import (
    llm_text,
    robust_json_loads,
    score_by_keywords,
    generate_skill_bridging_map,
    compress_experience_llm,
    prune_recent_experience,
    load_prompt
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
    llm = get_model_for_step("RETREIVAL", format="json")  # Fallback matches spelling in config

    jd = state.get("job_description", "")
    persona = state.get("target_persona", "")
    keywords = state.get("primary_keywords", [])
    region = state.get("target_region", get_strategy_default())
    locations = state.get("target_locations", [])
    expectations = state.get("cv_expectations", "")

    experiences_dir = get_wiki_dir() / "wiki" / "experiences"
    scored_entries: list[tuple[int, str, str, str]] = []

    score_template = load_prompt("retriever_score.txt")

    for entry_path in experiences_dir.glob("*.md"):
        with open(entry_path, "r", encoding="utf-8") as f:
            experience_content = f.read()

            logging.info(f"Analysing relevance of career entry {entry_path}")

            if len(experience_content) < 50:
                logging.info(f"Career entry {entry_path} too short. Skipping")
                continue

            score_prompt = (
                score_template
                .replace("{JOB_DESCRIPTION}", jd)
                .replace("{TARGET_PERSONA}", persona)
                .replace("{KEYWORDS}", ", ".join(keywords))
                .replace("{EXPERIENCE_CONTENT}", experience_content)
            )

            response = llm.invoke([HumanMessage(content=score_prompt)])
            content = llm_text(response.content)

            logging.info(f"Career entry {entry_path} analysed")

            score = 0
            justification = "N/A"
            try:
                data = robust_json_loads(content)
                score = int(data.get("score", 0))
                justification = data.get("justification", "N/A")
            except Exception as e:
                logging.warning(
                    f"Failed to parse LLM score for {entry_path.name}, defaulting to 0: {e}"
                )

            scored_entries.append(
                (score, entry_path.name, experience_content, justification)
            )

    scored_entries.sort(key=lambda x: x[0], reverse=True)

    # Deduplicate experience entries to avoid overwhelming the LLM with duplicate files
    deduplicated_entries: list[tuple[int, str, str, str]] = []
    seen_roles: set[tuple[str, str]] = set()  # key is (org, start_year)
    for score, name, content, justification in scored_entries:
        org = ""
        start_year = ""
        fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        if fm_match:
            try:
                fm = yaml.safe_load(fm_match.group(1)) or {}
                org_raw = str(fm.get("organization", ""))
                org_match = re.search(r'\[\[(.*?)\]\]', org_raw)
                org = org_match.group(1) if org_match else org_raw.strip().lower()
                
                dates = fm.get("dates")
                if not isinstance(dates, dict):
                    start = fm.get("start") or dates
                    end = fm.get("end")
                    dates = {"start": start, "end": end or "Present"} if (start or end) else {}
                
                if isinstance(dates, dict):
                    start_date_val = str(dates.get("start", ""))
                    if start_date_val:
                        start_year = start_date_val[:4]
            except Exception:
                pass
        
        if not org:
            org = name.replace(".md", "").split("-")[0]
            
        key = (org, start_year)
        if key not in seen_roles:
            seen_roles.add(key)
            deduplicated_entries.append((score, name, content, justification))
            logging.info(f"Retrieved unique experience: {name} (Key: {key})")
        else:
            logging.info(f"Skipping duplicate experience: {name} (Key: {key})")

    selected_content: list[str] = []
    retrieved_exp_slugs: list[str] = []
    for score, name, content, justification in deduplicated_entries:
        logging.info(
            f"Retrieved experience {name} with semantic relevance score: {score} ({justification})"
        )
        slug = name.replace(".md", "")
        retrieved_exp_slugs.append(slug)

        # Smart-compression: experiences older than 10 years (pre-2016)
        is_old_role = False
        fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        if fm_match:
            try:
                fm = yaml.safe_load(fm_match.group(1)) or {}
                dates = fm.get("dates")
                if not isinstance(dates, dict):
                    start = fm.get("start") or dates
                    end = fm.get("end")
                    dates = {"start": start, "end": end or "Present"} if (start or end) else {}
                
                if isinstance(dates, dict):
                    start_date_val = str(dates.get("start", ""))
                    if start_date_val and start_date_val[:4].isdigit():
                        if int(start_date_val[:4]) < 2016:
                            is_old_role = True
            except Exception:
                pass

        if is_old_role:
            logging.info(f"Smart-compressing old experience {name} to reduce token bloat...")
            content = compress_experience_llm(content)
        else:
            logging.info(f"Pruning recent experience {name} to optimize token budget...")
            content = prune_recent_experience(content, keywords)

        entry_wrapper = (
            f"--- CAREER ENTRY: {name} (SEMANTIC RELEVANCE SCORE: {score}) ---\n"
            f"JUSTIFICATION: {justification}\n"
            f"{content}\n"
            f"--- END CAREER ENTRY ---\n"
        )
        selected_content.append(entry_wrapper)

    wiki_dir = get_wiki_dir()
    education_dir = wiki_dir / "wiki" / "education"
    
    # Deduplicate education entries
    edu_candidates: list[dict[str, Any]] = []
    if education_dir.exists():
        for f in education_dir.glob("*.md"):
            try:
                edu_text = f.read_text(encoding="utf-8")
                inst = ""
                start_year = ""
                status = ""
                fm_match = re.match(r'^---\n(.*?)\n---', edu_text, re.DOTALL)
                if fm_match:
                    try:
                        fm = yaml.safe_load(fm_match.group(1)) or {}
                        inst_raw = str(fm.get("institution", ""))
                        inst_match = re.search(r'\[\[(.*?)\]\]', inst_raw)
                        inst = inst_match.group(1) if inst_match else inst_raw.strip().lower()
                        
                        dates = fm.get("dates", {})
                        if isinstance(dates, dict):
                            start_date_val = str(dates.get("start", ""))
                            if start_date_val:
                                start_year = start_date_val[:4]
                        status = str(fm.get("status", ""))
                    except Exception:
                        pass
                
                if not inst:
                    inst = f.name.replace(".md", "").split("-")[0]
                    
                edu_candidates.append({
                    "path": f,
                    "content": edu_text,
                    "inst": inst,
                    "start_year": start_year,
                    "status": status,
                    "size": len(edu_text)
                })
            except Exception:
                pass

    # Sort: completed status first, then larger file size
    def edu_sort_key(x: dict[str, Any]) -> tuple[int, int]:
        is_completed = 1 if "completed" in str(x["status"]).lower() else 0
        return (is_completed, x["size"])
        
    edu_candidates.sort(key=edu_sort_key, reverse=True)
    
    education_content: list[str] = []
    seen_edu: set[tuple[str, str]] = set()
    for item in edu_candidates:
        key = (item["inst"], item["start_year"])
        if key not in seen_edu:
            seen_edu.add(key)
            education_content.append(item["content"])
            logging.info(f"Retrieved unique education: {item['path'].name} (Key: {key})")
        else:
            logging.info(f"Skipping duplicate education: {item['path'].name} (Key: {key})")

    skills_dir = wiki_dir / "wiki" / "skills"
    skills_content = [
        f.read_text(encoding="utf-8") for f in skills_dir.glob("*.md")
    ]

    # 1. Projects Retrieval & Keyword Scoring
    projects_dir = wiki_dir / "wiki" / "projects"
    scored_projects: list[tuple[int, str, str]] = []
    if projects_dir.exists():
        for f in projects_dir.glob("*.md"):
            p_content = f.read_text(encoding="utf-8")
            score = score_by_keywords(p_content, keywords)
            for slug in retrieved_exp_slugs:
                if f"[[{slug}]]" in p_content:
                    score += 5
            scored_projects.append((score, f.name, p_content))
    scored_projects.sort(key=lambda x: x[0], reverse=True)
    projects_entries: list[str] = []
    for p_score, p_name, p_content in scored_projects[:3]:
        projects_entries.append(
            f"--- PROJECT ENTRY: {p_name} (KEYWORD RELEVANCE SCORE: {p_score}) ---\n"
            f"{p_content}\n"
            f"--- END PROJECT ENTRY ---\n"
        )

    # 2. Patents Retrieval & Keyword Scoring
    patents_dir = wiki_dir / "wiki" / "patents"
    scored_patents: list[tuple[int, str, str]] = []
    if patents_dir.exists():
        for f in patents_dir.glob("*.md"):
            pat_content = f.read_text(encoding="utf-8")
            score = score_by_keywords(pat_content, keywords)
            for slug in retrieved_exp_slugs:
                if f"[[{slug}]]" in pat_content:
                    score += 5
            scored_patents.append((score, f.name, pat_content))
    scored_patents.sort(key=lambda x: x[0], reverse=True)
    patents_entries: list[str] = []
    for pat_score, pat_name, pat_content in scored_patents[:3]:
        patents_entries.append(
            f"--- PATENT ENTRY: {pat_name} (KEYWORD RELEVANCE SCORE: {pat_score}) ---\n"
            f"{pat_content}\n"
            f"--- END PATENT ENTRY ---\n"
        )

    # 3. Notes (Performance Reviews) Retrieval
    notes_dir = wiki_dir / "wiki" / "notes"
    scored_notes: list[tuple[int, str, str]] = []
    if notes_dir.exists():
        for f in notes_dir.glob("*.md"):
            note_content = f.read_text(encoding="utf-8")
            has_review_tag = "performance-review" in note_content.lower()
            has_relation = False
            for slug in retrieved_exp_slugs:
                if f"[[{slug}]]" in note_content:
                    has_relation = True
                    break
            if has_review_tag or has_relation:
                score = score_by_keywords(note_content, keywords)
                if has_review_tag:
                    score += 5  # boost performance reviews
                scored_notes.append((score, f.name, note_content))
    scored_notes.sort(key=lambda x: x[0], reverse=True)
    notes_entries: list[str] = []
    for n_score, n_name, n_content in scored_notes[:5]:
        notes_entries.append(
            f"--- NOTE ENTRY: {n_name} (RELEVANCE SCORE: {n_score}) ---\n"
            f"{n_content}\n"
            f"--- END NOTE ENTRY ---\n"
        )

    # 4. Success Feedback Retrieval (Few-Shot Selection)
    synthesis_dir = wiki_dir / "wiki" / "synthesis"
    scored_examples: list[tuple[int, str, str]] = []
    if synthesis_dir.exists():
        for f in synthesis_dir.glob("*.md"):
            cv_content = f.read_text(encoding="utf-8")
            status_match = re.search(
                r'status:\s*["\']?(Offer|Technical-Interview)["\']?', cv_content, re.IGNORECASE
            )
            if status_match:
                score = score_by_keywords(cv_content, keywords)
                scored_examples.append((score, f.name, cv_content))
    scored_examples.sort(key=lambda x: x[0], reverse=True)
    few_shot_examples: list[str] = []
    for fs_score, fs_name, fs_content in scored_examples[:1]:
        fs_content_pruned = fs_content
        if len(fs_content) > 12000:
            fs_content_pruned = (
                fs_content[:12000]
                + "\n\n... [TRUNCATED SUCCESSFUL PAST CV FOR BREVITY] ...\n"
            )
            logging.info(
                f"Few-shot example {fs_name} truncated to 12k characters to fit within TPM limits."
            )
        few_shot_examples.append(
            f"--- SUCCESSFUL PAST CV: {fs_name} (RELEVANCE SCORE: {fs_score}) ---\n"
            f"{fs_content_pruned}\n"
            f"--- END SUCCESSFUL PAST CV ---\n"
        )

    # 5. Skill Bridging Map Generation
    skill_bridging_map = generate_skill_bridging_map(llm, jd, skills_content, keywords)

    strategy_file = wiki_dir / "wiki" / "strategies" / f"strategy-{region}.md"
    if not strategy_file.exists():
        # Fallback logic for regions
        if any(kw in region for kw in ["uk", "london", "united kingdom", "ireland"]):
            strategy_file = wiki_dir / "wiki" / "strategies" / "strategy-ireland.md"
        elif any(kw in region for kw in ["emea", "europe", "global", "remote"]):
            strategy_file = wiki_dir / "wiki" / "strategies" / "strategy-emea.md"
        else:
            default_strategy = get_strategy_default()
            strategy_file = (
                wiki_dir / "wiki" / "strategies" / f"strategy-{default_strategy}.md"
            )
            if not strategy_file.exists():
                strategy_file = wiki_dir / "wiki" / "strategies" / "strategy-emea.md"

    strategy_text = ""
    pdf_template = "templates/base.css"
    if strategy_file.exists():
        strategy_text = strategy_file.read_text(encoding="utf-8")
        if strategy_text.startswith("---"):
            fm_match = re.search(
                r'pdf_template:\s*["\']?(.*?)["\']?\s*$', strategy_text, re.MULTILINE
            )
            if fm_match:
                pdf_template = fm_match.group(1)

    subject_info = ""
    entities_dir = wiki_dir / "wiki" / "entities"
    for ent in entities_dir.glob("*.md"):
        c = ent.read_text(encoding="utf-8")
        if 'tags: ["person"' in c or 'tags: ["person",' in c:
            subject_info = c
            break

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
        "projects_entries": projects_entries,
        "patents_entries": patents_entries,
        "notes_entries": notes_entries,
        "few_shot_examples": few_shot_examples,
        "skill_bridging_map": skill_bridging_map,
        "strategy_info": context_info,
        "pdf_template": pdf_template
    }


def node_drafter(state: CVPipelineState) -> dict[str, Any]:
    """Draft the resume/CV using SystemMessage constraints and externalized drafter prompts."""
    logging.info("--- NODE C: DRAFTER ---")
    llm = get_model_for_step("DRAFTING")

    jd = state.get("job_description", "")
    persona = state.get("target_persona", "")
    keywords = state.get("primary_keywords", [])
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

    education_text = "\n\n".join(education)
    skills_text = "\n\n".join(skills)

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

    parsed_entries: list[dict[str, Any]] = []
    for entry_str in entries:
        name_match = re.search(r'CAREER ENTRY: (.*?\.md)', entry_str)
        date_start_match = re.search(
            r'start:\s*[\'"]?(\d{4}-\d{2}-\d{2})[\'"]?', entry_str
        )

        if name_match:
            score_match = re.search(
                r'SEMANTIC RELEVANCE SCORE: (\d+)', entry_str
            )
            score = int(score_match.group(1)) if score_match else 0
            entry_name = name_match.group(1)

            if date_start_match:
                start_date_str = date_start_match.group(1)
                try:
                    year, month, _ = map(int, start_date_str.split('-'))
                    start_date = (year, month)
                except Exception:
                    start_date = (1970, 1)
            else:
                start_date = (1970, 1)

            parsed_entries.append({
                "name": entry_name,
                "start_date": start_date,
                "score": score,
                "content": entry_str
            })

    parsed_entries.sort(key=lambda x: x["start_date"], reverse=True)
    chronological_entries_text = "\n\n".join(
        [str(entry["content"]) for entry in parsed_entries]
    )

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

    try:
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt)
        ])
    except Exception as e:
        err_msg = str(e).lower()
        if any(
            keyword in err_msg
            for keyword in ["rate_limit", "rate limit", "limit_exceeded", "429"]
        ):
            fallback_llm = get_fallback_model_for_step("DRAFTING")
            if fallback_llm is not None:
                logging.warning(
                    f"DRAFTING LLM invocation failed due to rate limit: {e}. "
                    "Attempting configured fallback model..."
                )
                try:
                    response = fallback_llm.invoke([
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=prompt)
                    ])
                except Exception as fallback_err:
                    logging.error(
                        f"Configured fallback model failed: {fallback_err}. "
                        "Re-raising original rate limit error."
                    )
                    raise e
            else:
                logging.warning(
                    f"DRAFTING LLM invocation failed due to rate limit: {e}. "
                    "No valid fallback model configured or credentials missing. Re-raising error."
                )
                raise e
        else:
            raise e

    return {"draft_cv": llm_text(response.content)}


def node_refiner(state: CVPipelineState) -> dict[str, Any]:
    """Verify that the drafted CV/Resume does not violate regional length limitations, giving density feedback."""
    logging.info("--- NODE D: REFINER ---")
    draft = state.get("draft_cv", "")
    char_count = len(draft)
    logging.info(f"Current CV length: {char_count} characters.")

    # 8500 chars is approx 2 full pages with standard formatting
    if char_count > 8500:
        feedback = (
            f"DENSITY ERROR: The CV is too long ({char_count} characters). "
            "Please compress older roles (pre-2015) to single-line summaries. "
            "In your current and recent roles, keep only the 2-3 most impactful bullets that "
            "demonstrate direct technical leadership and agentic AI experience."
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

    auditor_template = load_prompt("auditor.txt")
    prompt = auditor_template.format(
        job_description=jd,
        draft_cv=draft
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    feedback = llm_text(response.content).strip()

    return {"audit_feedback": feedback, "iteration_count": current_iterations + 1}
