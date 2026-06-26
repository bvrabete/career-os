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
import yaml
from typing import TypedDict, List, Union, Any, Dict
from pathlib import Path
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from kb_config import get_model_for_step, get_strategy_default, get_wiki_dir, get_fallback_model_for_step

JSON_PREAMBLE = "```json"


logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')


def _llm_text(content: Union[str, list]) -> str:  # type: ignore[type-arg]
    """Coerce a LangChain response.content value to a plain string."""
    if isinstance(content, str):
        return content
    return " ".join(str(part) for part in content)


def robust_json_loads(text: str) -> Any:
    """Robustly parse a JSON string from LLM output, handling preambles, trailing commas, comments, and control characters."""
    if not text:
        raise ValueError("Empty input string")
        
    text = text.strip()
    
    # 1. Strip markdown code blocks if present
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
        
    # 2. Locate the outermost JSON object/array
    start_brace = text.find("{")
    start_bracket = text.find("[")
    
    if start_brace == -1 and start_bracket == -1:
        raise ValueError("No JSON object or array found in text")
        
    if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
        # Starts with an object
        end_brace = text.rfind("}")
        if end_brace == -1:
            raise ValueError("Mismatched opening brace '{'")
        text = text[start_brace:end_brace+1]
    else:
        # Starts with an array
        end_bracket = text.rfind("]")
        if end_bracket == -1:
            raise ValueError("Mismatched opening bracket '['")
        text = text[start_bracket:end_bracket+1]
        
    # 3. Clean up comments (both // and /* */)
    # Strip single-line comments (ensure we don't strip http:// or https://)
    text = re.sub(r'(?<!:)\/\/.*$', '', text, flags=re.MULTILINE)
    # Strip multi-line comments
    text = re.sub(r'\/\*.*?\*\/', '', text, flags=re.DOTALL)
    
    # 4. Handle trailing commas before closing braces/brackets
    text = re.sub(r',\s*([\]}])', r'\1', text)
    
    # 5. Replace raw newlines and tabs inside string values
    def replace_control_chars(match: re.Match[str]) -> str:
        s = match.group(0)
        # Escape raw newlines, carriage returns, and tabs within the matched string
        s_escaped = s.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
        return s_escaped
    
    string_pattern = r'"(?:[^"\\]|\\.)*"'
    text = re.sub(string_pattern, replace_control_chars, text)

    # 6. Try parsing with standard json.loads
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logging.warning(f"Standard json.loads failed: {e}. Attempting last-resort recovery.")
        try:
            # Naive single quote to double quote fallback
            alt_text = text.replace("'", '"')
            return json.loads(alt_text)
        except Exception:
            raise e


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
    strategy_override: str
    projects_entries: List[str]
    patents_entries: List[str]
    notes_entries: List[str]
    few_shot_examples: List[str]
    skill_bridging_map: Dict[str, str]
    target_organization_slug: str
    target_role: str


def node_analyzer(state: CVPipelineState) -> dict:
    logging.info("--- NODE A: ANALYZER ---")
    llm = get_model_for_step("ANALYSIS", format="json")
    jd = state.get("job_description", "")

    # Discover available strategies
    strategies_dir = get_wiki_dir() / "wiki" / "strategies"
    available_strategies = []
    if strategies_dir.exists():
        available_strategies = [f.stem.replace(
            "strategy-", "") for f in strategies_dir.glob("strategy-*.md")]

    default_strategy = get_strategy_default()

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
       Default: {default_strategy}
    6. Extract 'Target Organization Slug': The lower-case, kebab-case name of the hiring organization/company (e.g. "google", "intel-corporation", "openai").
    7. Extract 'Target Role': The official title of the role being applied for (e.g. "Senior Software Engineer (Agentic AI)").
    
    Return your analysis in the following JSON format:
    {{
      "persona": "...",
      "keywords": [...],
      "locations": [...],
      "expectations": "...",
      "suggested_region": "...",
      "target_organization_slug": "...",
      "target_role": "..."
    }}
    
    Job Description:
    {jd}
    """

    response = llm.invoke([HumanMessage(content=prompt)])
    content = _llm_text(response.content)

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
            f"Failed to parse JSON from Analyzer, falling back to heuristics: {e}")
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


def _score_by_keywords(text: str, keywords: List[str]) -> int:
    """Calculate simple keyword overlap score (case-insensitive count of whole word matches)."""
    if not text or not keywords:
        return 0
    score = 0
    text_lower = text.lower()
    for kw in keywords:
        kw_lower = kw.lower().strip()
        if not kw_lower:
            continue
        # Find whole words/phrases using word boundaries
        pattern = r'\b' + re.escape(kw_lower) + r'\b'
        matches = len(re.findall(pattern, text_lower))
        score += matches
    return score


def _generate_skill_bridging_map(llm: Any, jd: str, skills: List[str], keywords: List[str]) -> Dict[str, str]:
    """Ask LLM to construct an explicit key-value mapping of required JD skills to sibling/equivalent candidate skills."""
    skills_summary = "\n".join(skills)
    prompt = f"""
    You are an expert technical resume strategist.
    Compare the 'Job Description Keywords' against the candidate's 'Existing Skills Profile'.
    Identify critical required technologies or skills from the Job Description that the candidate does NOT explicitly have in their profile,
    but where they have a close equivalent, direct sibling, or highly transferable skill.
    
    Construct a JSON mapping where:
    - Key: The missing required skill from the Job Description keywords.
    - Value: The closest equivalent or sibling skill from the candidate's profile, appended with " (equivalent)" or " (transferable)".
    
    Example output format:
    {{
      "AWS": "Azure (equivalent)",
      "React": "Angular (equivalent)"
    }}
    
    If there are no missing skills or no good equivalents, return an empty JSON object {{}}.
    
    Job Description Keywords: {', '.join(keywords)}
    
    Candidate's Existing Skills Profile:
    {skills_summary}
    """
    
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        content = _llm_text(response.content)
        data = robust_json_loads(content)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception as e:
        logging.warning(f"Failed to generate skill bridging map: {e}")
        
    return {}


def _compress_experience_llm(content: str) -> str:
    """
    Compresses an old, lower-relevance experience entry into a highly concise summary
    retaining metadata, company description/size, location, technologies, and 1 key achievement.
    """
    try:
        # Load a dedicated LLM without JSON formatting constraints
        llm = get_model_for_step("RETRIEVAL")
        prompt = f"""
        You are an expert resume compressor. Compress the following historical 'Career Entry' into a single highly condensed, ATS-optimized block.
        
        CRITICAL REQUIREMENTS:
        - Retain the exact YAML frontmatter (dates, title, organization, location, skills).
        - Provide a single short paragraph or 1-2 extremely concise bullet points summarizing:
          1. What the company does & its size (if mentioned).
          2. The primary responsibilities and key technologies used.
          3. The single most significant impact/accomplishment.
        - Keep the output extremely brief (under 100 words total).
        
        Career Entry to Compress:
        {content}
        """
        response = llm.invoke([HumanMessage(content=prompt)])
        return _llm_text(response.content)
    except Exception as e:
        logging.warning(f"Failed to compress experience via LLM: {e}")
        return content


def _prune_recent_experience(content: str, keywords: List[str] = []) -> str:
    """
    Prunes a recent experience file to reduce token bloat before sending it to the DRAFTER.
    - Strips comments (<!-- ... -->)
    - Removes unnecessary YAML fields (created, updated, sources, tags, tracks)
    - Strips the 'Narrative & Reflections' section to preserve token budget for Achievements.
    - Scores and retains only the top 4 achievements based on keyword overlap (complying with the "3-4 STAR achievements" rule).
    """
    # 1. Strip HTML comments
    content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
    
    # 2. Extract and prune frontmatter
    fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if fm_match:
        try:
            fm_raw = fm_match.group(1)
            fm = yaml.safe_load(fm_raw) or {}
            
            # Heal dates if start/end are at top-level (common indentation error)
            if "dates" not in fm or not isinstance(fm["dates"], dict):
                start = fm.get("start") or fm.get("dates")
                end = fm.get("end")
                if start or end:
                    fm["dates"] = {
                        "start": start,
                        "end": end or "Present"
                    }
            
            # Keep only essential fields
            pruned_fm = {}
            for key in ["type", "title", "organization", "location", "dates", "skills"]:
                if key in fm:
                    pruned_fm[key] = fm[key]
            
            # Reconstruct frontmatter
            pruned_fm_str = yaml.dump(pruned_fm, sort_keys=False)
            
            # Get body
            body = content[fm_match.end():].strip()
            
            # 3. Strip 'Narrative & Reflections' section if present
            body = re.sub(r'##\s*Narrative\s*&\s*Reflections.*?(?=##\s*|$)', '', body, flags=re.DOTALL)
            
            # 4. Extract and keep only the top 4 achievements
            ach_pattern = r'(^\s*-\s*\*\*Situation.*?(?=(^\s*-\s*\*\*Situation|^\s*##|^\s*###|\Z)))'
            achievements = [m.group(0) for m in re.finditer(ach_pattern, body, flags=re.MULTILINE | re.DOTALL)]
            if achievements:
                scored_ach = []
                for ach in achievements:
                    score = _score_by_keywords(ach, keywords)
                    scored_ach.append((score, ach))
                # Sort by score descending
                scored_ach.sort(key=lambda x: x[0], reverse=True)
                top_ach = [x[1] for x in scored_ach[:4]]
                
                # Strip original achievements and append top ones
                clean_body = re.sub(ach_pattern, '', body, flags=re.MULTILINE | re.DOTALL)
                clean_body = re.sub(r'\n{3,}', '\n\n', clean_body).strip()
                body = f"{clean_body}\n\n## Key STAR Achievements\n\n" + "\n".join(top_ach)
            
            # Reconstruct content
            content = f"---\n{pruned_fm_str}---\n\n{body.strip()}"
        except Exception as e:
            logging.warning(f"Failed to prune recent experience: {e}")
            
    return content



def node_retriever(state: CVPipelineState) -> dict:
    logging.info("--- NODE B: RETRIEVER ---")
    llm = get_model_for_step("RETRIEVAL", format="json")

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
                data = robust_json_loads(content)
                score = int(data.get("score", 0))
                justification = data.get("justification", "N/A")
            except Exception as e:
                logging.warning(
                    f"Failed to parse LLM score for {entry_path.name}, defaulting to 0: {e}")

            scored_entries.append(
                (score, entry_path.name, experience_content, justification))

    scored_entries.sort(key=lambda x: x[0], reverse=True)

    # Deduplicate experience entries to avoid overwhelming the LLM with duplicate files
    deduplicated_entries = []
    seen_roles = set()  # key is (org, start_year)
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

    selected_content = []
    retrieved_exp_slugs = []
    for score, name, content, justification in deduplicated_entries:
        logging.info(
            f"Retrieved experience {name} with semantic relevance score: {score} ({justification})")
        # Extract organizational slug by removing ".md"
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
            content = _compress_experience_llm(content)
        else:
            logging.info(f"Pruning recent experience {name} to optimize token budget...")
            content = _prune_recent_experience(content, keywords)

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
    edu_candidates = []
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
    def edu_sort_key(x):
        is_completed = 1 if "completed" in str(x["status"]).lower() else 0
        return (is_completed, x["size"])
        
    edu_candidates.sort(key=edu_sort_key, reverse=True)
    
    education_content = []
    seen_edu = set()
    for item in edu_candidates:
        key = (item["inst"], item["start_year"])
        if key not in seen_edu:
            seen_edu.add(key)
            education_content.append(item["content"])
            logging.info(f"Retrieved unique education: {item['path'].name} (Key: {key})")
        else:
            logging.info(f"Skipping duplicate education: {item['path'].name} (Key: {key})")

    skills_dir = wiki_dir / "wiki" / "skills"
    skills_content = [f.read_text(encoding="utf-8")
                      for f in skills_dir.glob("*.md")]

    # 1. Projects Retrieval & Keyword Scoring
    projects_dir = wiki_dir / "wiki" / "projects"
    scored_projects = []
    if projects_dir.exists():
        for f in projects_dir.glob("*.md"):
            p_content = f.read_text(encoding="utf-8")
            score = _score_by_keywords(p_content, keywords)
            for slug in retrieved_exp_slugs:
                if f"[[{slug}]]" in p_content:
                    score += 5
            scored_projects.append((score, f.name, p_content))
    scored_projects.sort(key=lambda x: x[0], reverse=True)
    projects_entries = []
    for p_score, p_name, p_content in scored_projects[:3]:
        projects_entries.append(
            f"--- PROJECT ENTRY: {p_name} (KEYWORD RELEVANCE SCORE: {p_score}) ---\n"
            f"{p_content}\n"
            f"--- END PROJECT ENTRY ---\n"
        )

    # 2. Patents Retrieval & Keyword Scoring
    patents_dir = wiki_dir / "wiki" / "patents"
    scored_patents = []
    if patents_dir.exists():
        for f in patents_dir.glob("*.md"):
            pat_content = f.read_text(encoding="utf-8")
            score = _score_by_keywords(pat_content, keywords)
            for slug in retrieved_exp_slugs:
                if f"[[{slug}]]" in pat_content:
                    score += 5
            scored_patents.append((score, f.name, pat_content))
    scored_patents.sort(key=lambda x: x[0], reverse=True)
    patents_entries = []
    for pat_score, pat_name, pat_content in scored_patents[:3]:
        patents_entries.append(
            f"--- PATENT ENTRY: {pat_name} (KEYWORD RELEVANCE SCORE: {pat_score}) ---\n"
            f"{pat_content}\n"
            f"--- END PATENT ENTRY ---\n"
        )

    # 3. Notes (Performance Reviews) Retrieval
    notes_dir = wiki_dir / "wiki" / "notes"
    scored_notes = []
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
                score = _score_by_keywords(note_content, keywords)
                if has_review_tag:
                    score += 5  # boost performance reviews
                scored_notes.append((score, f.name, note_content))
    scored_notes.sort(key=lambda x: x[0], reverse=True)
    notes_entries = []
    for n_score, n_name, n_content in scored_notes[:5]:
        notes_entries.append(
            f"--- NOTE ENTRY: {n_name} (RELEVANCE SCORE: {n_score}) ---\n"
            f"{n_content}\n"
            f"--- END NOTE ENTRY ---\n"
        )

    # 4. Success Feedback Retrieval (Few-Shot Selection)
    synthesis_dir = wiki_dir / "wiki" / "synthesis"
    scored_examples = []
    if synthesis_dir.exists():
        for f in synthesis_dir.glob("*.md"):
            cv_content = f.read_text(encoding="utf-8")
            status_match = re.search(r'status:\s*["\']?(Offer|Technical-Interview)["\']?', cv_content, re.IGNORECASE)
            if status_match:
                score = _score_by_keywords(cv_content, keywords)
                scored_examples.append((score, f.name, cv_content))
    scored_examples.sort(key=lambda x: x[0], reverse=True)
    few_shot_examples = []
    for fs_score, fs_name, fs_content in scored_examples[:1]:
        fs_content_pruned = fs_content
        if len(fs_content) > 12000:
            fs_content_pruned = fs_content[:12000] + "\n\n... [TRUNCATED SUCCESSFUL PAST CV FOR BREVITY] ...\n"
            logging.info(f"Few-shot example {fs_name} truncated to 12k characters to fit within TPM limits.")
        few_shot_examples.append(
            f"--- SUCCESSFUL PAST CV: {fs_name} (RELEVANCE SCORE: {fs_score}) ---\n"
            f"{fs_content_pruned}\n"
            f"--- END SUCCESSFUL PAST CV ---\n"
        )

    # 5. Skill Bridging Map Generation
    skill_bridging_map = _generate_skill_bridging_map(llm, jd, skills_content, keywords)

    strategy_file = wiki_dir / "wiki" / "strategies" / f"strategy-{region}.md"
    if not strategy_file.exists():
        # Fallback logic for regions
        if any(kw in region for kw in ["uk", "london", "united kingdom", "ireland"]):
            strategy_file = wiki_dir / "wiki" / "strategies" / "strategy-ireland.md"
        elif any(kw in region for kw in ["emea", "europe", "global", "remote"]):
            strategy_file = wiki_dir / "wiki" / "strategies" / "strategy-emea.md"
        else:
            default_strategy = get_strategy_default()
            strategy_file = wiki_dir / "wiki" / \
                "strategies" / f"strategy-{default_strategy}.md"
            if not strategy_file.exists():
                strategy_file = wiki_dir / "wiki" / "strategies" / "strategy-emea.md"

    strategy_text = ""
    pdf_template = "templates/base.css"
    if strategy_file.exists():
        strategy_text = strategy_file.read_text(encoding="utf-8")
        if strategy_text.startswith("---"):
            fm_match = re.search(
                r'pdf_template:\s*["\']?(.*?)["\']?\s*$', strategy_text, re.MULTILINE)
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

    # Retrieve expanded state values
    projects = state.get("projects_entries", [])
    patents = state.get("patents_entries", [])
    notes = state.get("notes_entries", [])
    few_shots = state.get("few_shot_examples", [])
    skill_bridge = state.get("skill_bridging_map", {})

    education_text = "\n\n".join(education)
    skills_text = "\n\n".join(skills)
    keywords_text = ", ".join(keywords)

    projects_text = "\n\n".join(projects)
    patents_text = "\n\n".join(patents)
    notes_text = "\n\n".join(notes)
    few_shots_text = "\n\n".join(few_shots)
    skill_bridge_text = json.dumps(skill_bridge, indent=2) if skill_bridge else "None"

    feedback_instruction = ""
    if feedback:
        feedback_instruction += f"\nCRITICAL AUDIT FEEDBACK TO INCORPORATE: {feedback}"
    if refiner_feedback:
        feedback_instruction += f"\nCRITICAL DENSITY/LENGTH FEEDBACK: {refiner_feedback}"

    parsed_entries: List[dict[str, Any]] = []
    for entry_str in entries:
        name_match = re.search(r'CAREER ENTRY: (.*?\.md)', entry_str)
        date_start_match = re.search(
            r'start:\s*[\'"]?(\d{4}-\d{2}-\d{2})[\'"]?', entry_str)

        if name_match:
            score_match = re.search(
                r'SEMANTIC RELEVANCE SCORE: (\d+)', entry_str)
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
        [str(entry["content"]) for entry in parsed_entries])

    system_prompt = """You are a highly rigorous, factual, and detail-oriented Executive Resume Writer. Your goal is to draft a professional, ATS-optimized Markdown CV that is 100% grounded in verifiable data and free of any embellishments, fluff, or fabricated claims.

CORE RULES:
1. TRUTH, NO EMBELLISHMENT & NO HALLUCINATIONS:
   - Use ONLY the provided 'CAREER ENTRIES', 'EDUCATION', 'SKILLS', and 'SUBJECT PROFILE' facts.
   - Absolutely NO embellishment, exaggeration, or generic buzzword-heavy marketing speak.
   - Every single claim, metric, role, and title MUST be directly backed by the provided facts.
   - Do NOT invent or assume any roles, achievements, years of experience, or leadership responsibilities not explicitly present in the data.
2. SURGICAL FILTERING: 
   - Act as a filter, not a copier. Even in high-scoring roles, select ONLY the top 3-4 STAR bullets that directly map to the Job Description.
   - Delete or condense supporting bullets that don't add specific value to the target Persona.
   - Prioritize evidence of 'Agentic AI', 'Forward Deployment', and 'Scale'.
3. CHRONOLOGY & DENSITY CONTROL (CRITICAL - PREVENT GAPS):
   - All experience MUST be in strict REVERSE CHRONOLOGICAL order.
   - NO CAREER GAPS: Every provided career entry (including career breaks like "Childcare Leave") must be represented in the final CV. There must be absolutely no timeline gaps in the work experience section.
   - INTEGRATE CAREER BREAKS: Do NOT list career breaks (like "Childcare Leave") at the end of the Work Experience section or in a separate section. They MUST be integrated directly into the 'Work Experience' timeline in their exact reverse-chronological order based on their dates (e.g., if a career break is 2012-2016, it must appear between a 2017-2026 role and a 2009-2011 role). The Work Experience section must form a single, unbroken chronological timeline from present to past.
   - RECENT ROLES (Last 10 Years, i.e., 2016 – present): Regardless of how well they match the job description or their semantic relevance score, all recent roles must be fully detailed with 3-4 STAR achievements. Never summarize, condense, or omit roles from the last 10 years.
   - OLDER ROLES (Older than 10 Years, i.e., pre-2016): Roles older than 10 years should be compressed/summarized to a single-line summary or 1-2 concise bullet points to respect the page budget, but they must remain in the timeline to preserve history.
4. DEDUPLICATION:
   - If there are duplicate or overlapping entries in the provided 'CAREER ENTRIES' (e.g. referencing the same company and overlapping dates), merge them cleanly into a single entry in the timeline instead of listing them separately.
5. ATS OPTIMIZATION & DATA INTEGRITY:
   - USE STANDARD HEADINGS: Only use "Professional Summary", "Key Skills", "Work Experience", "Education", and "Additional Information".
   - EXPAND ACRONYMS: For any technical or professional certification/skill, include both the full name and acronym (e.g., "Natural Language Processing (NLP)", "Project Management Professional (PMP)").
   - NO METRIC FABRICATION: Under no circumstances should you invent, estimate, or hallucinate metrics, numbers, percentages, budgets, or team sizes. Only include metrics if they are explicitly provided in the source facts. If no metric is given, describe the achievement's impact using clear, objective, and factual language.
   - REGIONAL PROFESSIONAL SUMMARY: Adapt the style and length of the "Professional Summary" to the target region and format expectations (e.g., US/technical style favors a concise, high-density 1-2 sentence branding statement or profile; UK/EMEA style favors a 3-line dense factual overview; other regions may omit it if requested). Under no circumstances should you use flowery marketing adjectives (e.g., do NOT use words like "Dynamic", "Visionary", "Proven track record", or "Adept at..."). If a summary is used, pack it entirely with dense, concrete facts: exact years of experience, primary technical skills, specific domains, and key verified achievements. Do not pad or add fluff to hit any arbitrary length.
6. FORMATTING:
   - Respond with pure markdown only (NO code blocks).
   - For EVERY role, include a **Technologies:** line immediately after the header.
7. SKILL BRIDGING: Use the 'SKILL BRIDGING MAP' to translate or bridge candidate skills to the JD's requested keywords where direct sibling/equivalent technologies exist.
8. INCORPORATE PROJECTS & PATENTS: Integrate the retrieved standalone projects and patents into the respective Work Experience roles or an "Additional Information" / "Key Accomplishments" section to showcase modular, high-impact achievements.
9. MY VOICE & PEER PRAISE: Infuse authentic reflections, peer praises, and proof points from 'PERFORMANCE REVIEW NOTES' into the Professional Summary and Work Experience descriptions to deliver a highly personal, high-agency tone. Do not extrapolate beyond the literal facts provided in the notes.
10. FEW-SHOT ALIGNMENT: Study the successful 'FEW-SHOT EXAMPLES' to mirror their style, density, and formatting structures, while maintaining absolute factual accuracy.
"""

    prompt = f"""Please draft the final CV.

Job Description:
{jd}

{feedback_instruction}

---
SUBJECT & STRATEGY:
{strategy}

---
SKILL BRIDGING MAP (Use to align skill names):
{skill_bridge_text}

---
FEW-SHOT EXAMPLES (Mirror the style, structure, and tone of these successful CVs):
{few_shots_text}

---
CAREER ENTRIES (Work Experience):
{chronological_entries_text}

---
RETRIEVED PROJECTS (Integrate with relevant company/roles):
{projects_text}

---
RETRIEVED PATENTS (Integrate with relevant company/roles):
{patents_text}

---
PERFORMANCE REVIEW NOTES ("My Voice" peer praise and evidence):
{notes_text}

---
EDUCATION ENTRIES:
{education_text}

---
SKILLS & LANGUAGES:
{skills_text}

Draft the final tailored Markdown CV now:
"""

    try:
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt)
        ])
    except Exception as e:
        err_msg = str(e).lower()
        if any(keyword in err_msg for keyword in ["rate_limit", "rate limit", "limit_exceeded", "429"]):
            fallback_llm = get_fallback_model_for_step("DRAFTING")
            if fallback_llm is not None:
                logging.warning(f"DRAFTING LLM invocation failed due to rate limit: {e}. Attempting configured fallback model...")
                try:
                    response = fallback_llm.invoke([
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=prompt)
                    ])
                except Exception as fallback_err:
                    logging.error(f"Configured fallback model failed: {fallback_err}. Re-raising original rate limit error.")
                    raise e
            else:
                logging.warning(f"DRAFTING LLM invocation failed due to rate limit: {e}. No valid fallback model configured or credentials missing. Re-raising error.")
                raise e
        else:
            raise e

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
1. EMBELLISHMENT & FABRICATION (CRITICAL): Ensure there are absolutely NO fabricated metrics, numbers, percentages, or achievements. Highlight any claim, metric, role, or title that is not directly supported by the candidate's career history and facts.
2. NO FLUFF/MARKETING HYPE: Identify and reject any generic marketing buzzwords or empty filler adjectives (such as "Dynamic", "Visionary", "Proven track record", "Adept at") in the summary or experience descriptions. Ensure the tone is objective, sober, factual, and direct.
3. ATS RED FLAGS: Check for non-standard headings or unexpanded acronyms.
4. RELEVANCE: Did we spend too much space on roles that aren't the core 'Target Persona'?
5. SUMMARY HOOK: Is the professional summary appropriate in length and style for the target region and format expectations (e.g. concise 1-2 sentence statement for US, or a 3-line overview for UK/EMEA), dense, strictly factual, and completely free of fluff or marketing hype?
6. TIMELINE CONTINUITY & CHRONOLOGY (CRITICAL):
   - Check if all experiences (including career breaks like "Childcare Leave") are in strict REVERSE CHRONOLOGICAL order.
   - Verify that there are absolutely NO timeline/career gaps in the Work Experience section.
   - Ensure that career breaks are integrated directly into the Work Experience timeline in their correct reverse-chronological position, NOT pushed to the end of the section or into a separate section.

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
