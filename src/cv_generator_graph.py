"""
LangGraph CV generation pipeline for the Career Operating System.

Reads a job description and the llm-wiki knowledge graph, then produces a
tailored, ATS-optimised Markdown CV via a four-node pipeline:
  analyzer → retriever → drafter → auditor (loops up to 2× on feedback)

Inputs:  job_description str + wiki files under llm-wiki/wiki/
Outputs: draft_cv str (Markdown)
"""

import os
import json
import logging
import re
from typing import TypedDict, List, Union, Any
from pathlib import Path
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from kb_config import get_model_for_step, get_strategy_default, get_wiki_dir

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def _llm_text(content: Union[str, list]) -> str:  # type: ignore[type-arg]
    """Coerce a LangChain response.content value to a plain string."""
    if isinstance(content, str):
        return content
    return " ".join(str(part) for part in content)

class CVPipelineState(TypedDict):
    job_description: str
    target_persona: str
    target_region: str
    target_locations: List[str]
    cv_expectations: str
    primary_keywords: List[str]
    selected_entries: List[str]
    education_entries: List[str]
    skills_entries: List[str]
    strategy_info: str
    pdf_template: str
    draft_cv: str
    audit_feedback: str
    refiner_feedback: str
    iteration_count: int

def node_analyzer(state: CVPipelineState) -> dict:
    logging.info("--- NODE A: ANALYZER ---")
    llm = get_model_for_step("ANALYSIS")
    jd = state.get("job_description", "")
    
    # Discover available strategies
    strategies_dir = get_wiki_dir() / "wiki" / "strategies"
    available_strategies = []
    if strategies_dir.exists():
        available_strategies = [f.stem.replace("strategy-", "") for f in strategies_dir.glob("strategy-*.md")]
    
    default_strat = get_strategy_default()
    
    prompt = f"""
    You are an expert technical recruiter and career coach analyzing a job description.
    
    TASKS:
    1. Extract the core 'persona' (seniority, specialty, core value prop).
    2. Extract 10-15 'Primary Keywords' critical for ATS and human review.
    3. Identify 'Target Locations': What are the specific locations (cities, countries, or regions) accepted for this role?
    4. Infer 'CV/Resume Expectations': Based on the company type and location, what kind of cv/resume is expected by the company?
       (e.g., "Standard UK 2-pager", "US-style technical resume", "Detailed DACH-region CV", "High-agency startup profile").
    5. Suggest a 'Strategy Key': Based on the locations and company profile, choose the best fit from the available strategies:
       Available: [{', '.join(available_strategies)}]
       Default: {default_strat}
    
    Return your analysis in the following JSON format:
    {{
      "persona": "...",
      "keywords": [...],
      "locations": [...],
      "expectations": "...",
      "suggested_region": "..."
    }}
    
    Job Description:
    {jd}
    """
    
    response = llm.invoke([HumanMessage(content=prompt)])
    content = _llm_text(response.content)
    
    try:
        # Robust JSON extraction
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "{" in content:
            content = content[content.find("{"):content.rfind("}")+1]
        
        data = json.loads(content)
        persona = data.get("persona", content)
        keywords = data.get("keywords", [])
        locations = data.get("locations", [])
        expectations = data.get("expectations", "Standard professional CV")
        region = data.get("suggested_region", default_strat).lower()
    except Exception:
        logging.warning("Failed to parse JSON from Analyzer, falling back to heuristics.")
        persona = content
        keywords = []
        locations = []
        expectations = "Standard professional CV"
        region = default_strat

    logging.info(f"Locations detected: {', '.join(locations)}")
    logging.info(f"CV Expectations: {expectations}")
    logging.info(f"Target Region suggested: {region.upper()}")
    
    return {
        "target_persona": persona, 
        "primary_keywords": keywords,
        "target_region": region,
        "target_locations": locations,
        "cv_expectations": expectations
    }

def node_retriever(state: CVPipelineState) -> dict:
    logging.info("--- NODE B: RETRIEVER ---")
    llm = get_model_for_step("RETRIEVAL")
    
    jd = state.get("job_description", "")
    persona = state.get("target_persona", "")
    keywords = state.get("primary_keywords", [])
    region = state.get("target_region", get_strategy_default())
    locations = state.get("target_locations", [])
    expectations = state.get("cv_expectations", "")
    
    experiences_dir = get_wiki_dir() / "wiki" / "experiences"
    scored_entries = []
    
    for entry_path in experiences_dir.glob("*.md"):
        with open(entry_path, "r", encoding="utf-8") as f:
            experience_content = f.read()

            logging.info(f"Analysing relevance of career entry {entry_path}")

            if len(experience_content) < 50:
                logging.info(f"Career entry {entry_path} too short. Skipping")
                continue
            
            score_prompt = f"""
            You are an expert CV analyst. Score the semantic relevance of the 'Career Entry' below to the 'Job Description', 'Target Persona', and 'Primary Keywords'.
            Return a score from 0-100, where 100 is a perfect match. Also provide a 1-sentence justification.
            
            Return in JSON format:
            {{
              "score": <integer_score>,
              "justification": "short explanation"
            }}
            
            Job Description:
            {jd}
            
            Target Persona:
            {persona}
            
            Primary Keywords: {', '.join(keywords)}
            
            ---
            Career Entry to Score:
            {experience_content}
            """
            
            response = llm.invoke([HumanMessage(content=score_prompt)])
            content = _llm_text(response.content)
            
            logging.info(f"Career entry {entry_path} analysed")

            score = 0
            justification = "N/A"
            try:
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "{" in content:
                    content = content[content.find("{"):content.rfind("}")+1]
                
                data = json.loads(content)
                score = int(data.get("score", 0))
                justification = data.get("justification", "N/A")
            except Exception:
                logging.warning(f"Failed to parse LLM score for {entry_path.name}, defaulting to 0.")

            scored_entries.append((score, entry_path.name, experience_content, justification))
            
    scored_entries.sort(key=lambda x: x[0], reverse=True)
    
    selected_content = []
    # Reduced to top 7 most relevant roles to keep length under control
    for score, name, content, justification in scored_entries[:7]:
        logging.info(f"Retrieved experience {name} with semantic relevance score: {score} ({justification})")
        entry_wrapper = (
            f"--- CAREER ENTRY: {name} (SEMANTIC RELEVANCE SCORE: {score}) ---\n"
            f"JUSTIFICATION: {justification}\n"
            f"{content}\n"
            f"--- END CAREER ENTRY ---\n"
        )
        selected_content.append(entry_wrapper)
    
    wiki_dir = get_wiki_dir()
    education_dir = wiki_dir / "wiki" / "education"
    education_content = [f.read_text(encoding="utf-8") for f in education_dir.glob("*.md")]
            
    skills_dir = wiki_dir / "wiki" / "skills"
    skills_content = [f.read_text(encoding="utf-8") for f in skills_dir.glob("*.md")]
            
    strategy_file = wiki_dir / "wiki" / "strategies" / f"strategy-{region}.md"
    if not strategy_file.exists():
        # Fallback logic for regions
        if any(kw in region for kw in ["uk", "london", "united kingdom", "ireland"]):
            strategy_file = wiki_dir / "wiki" / "strategies" / "strategy-ireland.md"
        elif any(kw in region for kw in ["emea", "europe", "global", "remote"]):
            strategy_file = wiki_dir / "wiki" / "strategies" / "strategy-emea.md"
        else:
            default_strat = get_strategy_default()
            strategy_file = wiki_dir / "wiki" / "strategies" / f"strategy-{default_strat}.md"
            if not strategy_file.exists():
                 strategy_file = wiki_dir / "wiki" / "strategies" / "strategy-emea.md"
        
    strategy_text = ""
    pdf_template = "templates/base.css"
    if strategy_file.exists():
        strategy_text = strategy_file.read_text(encoding="utf-8")
        if strategy_text.startswith("---"):
            fm_match = re.search(r'pdf_template:\s*["\']?(.*?)["\']?\s*$', strategy_text, re.MULTILINE)
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
        "strategy_info": context_info,
        "pdf_template": pdf_template
    }

def node_drafter(state: CVPipelineState) -> dict:
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
    
    education_text = "\n\n".join(education)
    skills_text = "\n\n".join(skills)
    keywords_text = ", ".join(keywords)
    
    feedback_instruction = ""
    if feedback:
        feedback_instruction += f"\nCRITICAL AUDIT FEEDBACK TO INCORPORATE: {feedback}"
    if refiner_feedback:
        feedback_instruction += f"\nCRITICAL DENSITY/LENGTH FEEDBACK: {refiner_feedback}"
        
    parsed_entries: List[dict[str, Any]] = []
    for entry_str in entries:
        name_match = re.search(r'CAREER ENTRY: (.*?\.md)', entry_str)
        date_start_match = re.search(r'start:\s*(\d{4}-\d{2}-\d{2})', entry_str)
        
        if name_match and date_start_match:
            score_match = re.search(r'SEMANTIC RELEVANCE SCORE: (\d+)', entry_str)
            score = int(score_match.group(1)) if score_match else 0
            
            entry_name = name_match.group(1)
            start_date_str = date_start_match.group(1)
            year, month, _ = map(int, start_date_str.split('-'))
            
            parsed_entries.append({
                "name": entry_name,
                "start_date": (year, month),
                "score": score,
                "content": entry_str
            })
    
    parsed_entries.sort(key=lambda x: x["start_date"], reverse=True)
    chronological_entries_text = "\n\n".join([str(entry["content"]) for entry in parsed_entries])
        
    system_prompt = """You are a Master Executive Resume Writer. Your goal is to draft a professional, ATS-optimized Markdown CV that passes both sophisticated and simple tracking systems.

CORE RULES:
1. TRUTH & NO HALLUCINATIONS: Use ONLY the provided 'CAREER ENTRIES', 'EDUCATION', 'SKILLS', and 'SUBJECT PROFILE' facts.
2. SURGICAL FILTERING: 
   - Act as a filter, not a copier. Even in high-scoring roles, select ONLY the top 3-4 STAR bullets that directly map to the Job Description.
   - Delete or condense supporting bullets that don't add specific value to the target Persona.
   - Prioritize evidence of 'Agentic AI', 'Forward Deployment', and 'Scale'.
3. CHRONOLOGY & DENSITY CONTROL:
   - All experience MUST be in strict REVERSE CHRONOLOGICAL order.
   - Compress roles older than 10 years (pre-2015) into a single line summary or 1 concise bullet.
   - Target length: STRICTLY 2-3 pages.
4. ATS OPTIMIZATION (EXPERT TIPS):
   - USE STANDARD HEADINGS: Only use "Professional Summary", "Key Skills", "Work Experience", "Education", and "Additional Information".
   - EXPAND ACRONYMS: For any technical or professional certification/skill, include both the full name and acronym (e.g., "Natural Language Processing (NLP)", "Project Management Professional (PMP)").
   - QUANTIFY EVERYTHING: If a bullet doesn't have a number, find a way to quantify it (team size, budget, % increase, number of users, countries reached, or time saved).
   - 3-LINE HOOK: The "Professional Summary" must be exactly 3 lines long and high-impact.
5. FORMATTING:
   - Respond with pure markdown only (NO code blocks).
   - For EVERY role, include a **Technologies:** line immediately after the header.
"""
    
    prompt = f"""Please draft the final CV.

Job Description:
{jd}

{feedback_instruction}

---
SUBJECT & STRATEGY:
{strategy}

---
CAREER ENTRIES:
{chronological_entries_text}

---
EDUCATION ENTRIES:
{education_text}

---
SKILLS & LANGUAGES:
{skills_text}

Draft the final tailored Markdown CV now:
"""
    
    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=prompt)
    ])
    
    return {"draft_cv": _llm_text(response.content)}

def node_refiner(state: CVPipelineState) -> dict:
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

def node_auditor(state: CVPipelineState) -> dict:
    logging.info("--- NODE D: AUDITOR ---")
    llm = get_model_for_step("AUDIT")
    
    jd = state.get("job_description", "")
    draft = state.get("draft_cv", "")
    current_iterations = state.get("iteration_count", 0)
    
    prompt = f"""Act as a brutally honest Executive Recruiter and ATS Specialist. Review the Draft CV against the Job Description.

CRITIQUE CRITERIA:
1. WEAK METRICS: Highlight any bullet points that lack quantifiable impact (numbers, %, $, time).
2. ATS RED FLAGS: Check for non-standard headings or unexpanded acronyms.
3. FLUFF: Identify overused buzzwords that don't have supporting evidence.
4. RELEVANCE: Did we spend too much space on roles that aren't the core 'Target Persona'?
5. SUMMARY HOOK: Is the professional summary exactly 3 lines and compelling?

If the CV is world-class and perfectly optimized, output "PASS". 
Otherwise, provide a BRUTALLY HONEST list of gaps and specific rewrite suggestions.

Job Description:
{jd}

Draft CV:
{draft}
"""
    
    response = llm.invoke([HumanMessage(content=prompt)])
    feedback = _llm_text(response.content).strip()
    
    return {"audit_feedback": feedback, "iteration_count": current_iterations + 1}

def routing_logic(state: CVPipelineState) -> str:
    feedback = state.get("audit_feedback", "")
    refiner_feedback = state.get("refiner_feedback", "")
    iterations = state.get("iteration_count", 0)
    
    if refiner_feedback and iterations < 3:
        logging.warning("Refiner triggered a re-draft due to length/density.")
        return "drafter"
        
    if "PASS" in feedback or iterations >= 3:
        return END
    else:
        return "drafter"

def build_graph():
    workflow = StateGraph(CVPipelineState)
    workflow.add_node("analyzer", node_analyzer)
    workflow.add_node("retriever", node_retriever)
    workflow.add_node("drafter", node_drafter)
    workflow.add_node("refiner", node_refiner)
    workflow.add_node("auditor", node_auditor)
    
    workflow.set_entry_point("analyzer")
    workflow.add_edge("analyzer", "retriever")
    workflow.add_edge("retriever", "drafter")
    workflow.add_edge("drafter", "refiner")
    workflow.add_edge("refiner", "auditor")
    
    workflow.add_conditional_edges(
        "auditor",
        routing_logic,
        {END: END, "drafter": "drafter"}
    )
    
    return workflow.compile()
