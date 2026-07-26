"""
Independent command-line utility to run an external resume-parsing audit via Affinda.
Allows users to upload a generated resume and compare parsing results against a target Job Description.
"""

import sys
import re
import argparse
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Set

from dotenv import load_dotenv
load_dotenv()

from tools.external_auditor import AffindaParserClient

# Set up module-level logging
logger = logging.getLogger(__name__)


def extract_keywords_from_jd(jd_text: str) -> Set[str]:
    """Helper to extract a set of lowercase keywords and core technical skills from a Job Description."""
    # Use standard list of common engineering/architectural/management keywords to look for
    common_skills = {
        "python", "kubernetes", "gitops", "ci/cd", "observability", "docker", "aws", "gcp", "azure",
        "microservices", "redis", "elasticsearch", "sql", "management", "architecture", "agile",
        "devsecops", "terraform", "platform engineering", "api management", "distributed systems"
    }
    
    found: Set[str] = set()
    normalized_jd = jd_text.lower()
    for skill in common_skills:
        if re.search(r'\b' + re.escape(skill) + r'\b', normalized_jd):
            found.add(skill)
            
    return found


def calculate_overlap_score(parsed_skills: List[str], jd_keywords: Set[str]) -> Dict[str, Any]:
    """Calculates keyword matching stats between parsed resume skills and job description requirements."""
    parsed_normalized = {s.lower() for s in parsed_skills}
    
    matched = set()
    missed = set()
    
    for keyword in jd_keywords:
        keyword_lower = keyword.lower()
        is_matched = False
        for skill in parsed_normalized:
            if keyword_lower in skill or skill in keyword_lower:
                is_matched = True
                break
        if is_matched:
            matched.add(keyword)
        else:
            missed.add(keyword)
            
    score = int((len(matched) / len(jd_keywords) * 100)) if jd_keywords else 100
    
    return {
        "score": score,
        "matched": sorted(matched),
        "missed": sorted(missed)
    }


def _extract_contact_info(parsed_data: Dict[str, Any]) -> tuple[str, str, str]:
    """Extract contact information (name, emails, phone numbers) from parsed resume data."""
    contact = (
        parsed_data.get("name", {}).get("raw")
        or parsed_data.get("candidateName", {}).get("raw")
        or "Unknown"
    )
    
    emails_list = parsed_data.get("emails") or parsed_data.get("email") or []
    emails = ", ".join([e.get("raw", "") if isinstance(e, dict) else str(e) for e in emails_list]) or "None detected"
    
    phones_list = parsed_data.get("phones") or parsed_data.get("phoneNumber") or []
    phones = ", ".join([p.get("raw", "") if isinstance(p, dict) else str(p) for p in phones_list]) or "None detected"
    
    return contact, emails, phones


def _resolve_job_title(parsed_fields: Dict[str, Any]) -> str:
    """Resolve job title from parsed fields."""
    title_obj = parsed_fields.get("workExperienceJobTitle") or {}
    if not isinstance(title_obj, dict):
        title_obj = {}
    return (
        parsed_fields.get("jobTitle")
        or title_obj.get("parsed")
        or title_obj.get("raw")
        or "Unknown Title"
    )


def _resolve_organization(parsed_fields: Dict[str, Any]) -> str:
    """Resolve organization from parsed fields."""
    org_obj = parsed_fields.get("workExperienceOrganization") or {}
    if not isinstance(org_obj, dict):
        org_obj = {}
    return (
        parsed_fields.get("organization")
        or org_obj.get("parsed")
        or org_obj.get("raw")
        or "Unknown Organization"
    )


def _resolve_dates(parsed_fields: Dict[str, Any]) -> tuple[str, str]:
    """Resolve start and end dates from parsed fields."""
    dates_obj = parsed_fields.get("workExperienceDates") or {}
    if not isinstance(dates_obj, dict):
        dates_obj = {}
    parsed_dates = dates_obj.get("parsed") or {} if isinstance(dates_obj, dict) else {}
    
    if not parsed_dates or not isinstance(parsed_dates, dict):
        start_date = parsed_fields.get("startDate") or "N/A"
        end_date = parsed_fields.get("endDate") or "Present"
        return start_date, end_date
        
    start_date = parsed_dates.get("start", {}).get("date") if isinstance(parsed_dates.get("start"), dict) else "N/A"
    if not start_date:
        start_date = "N/A"
        
    is_current = parsed_dates.get("end", {}).get("isCurrent", False) if isinstance(parsed_dates.get("end"), dict) else False
    if is_current:
        end_date = "Present"
    elif isinstance(parsed_dates.get("end"), dict):
        end_date = parsed_dates.get("end", {}).get("date") or "Present"
    else:
        end_date = "Present"
        
    return start_date, end_date


def _resolve_description(parsed_fields: Dict[str, Any]) -> str:
    """Resolve job description from parsed fields."""
    desc_obj = parsed_fields.get("workExperienceDescription") or {}
    if not isinstance(desc_obj, dict):
        desc_obj = {}
    return (
        parsed_fields.get("jobDescription")
        or desc_obj.get("parsed")
        or desc_obj.get("raw")
        or ""
    )


def _extract_work_history(parsed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract a list of parsed experience items containing clean title, org, date, and description fields."""
    work_history = []
    for exp in parsed_data.get("workExperience", []):
        if not isinstance(exp, dict):
            continue
        
        parsed_fields = exp.get("parsed") or exp
        title = _resolve_job_title(parsed_fields)
        org = _resolve_organization(parsed_fields)
        start_date, end_date = _resolve_dates(parsed_fields)
        desc = _resolve_description(parsed_fields)
        
        work_history.append({
            "jobTitle": title,
            "organization": org,
            "startDate": start_date,
            "endDate": end_date,
            "jobDescription": desc
        })
    return work_history


def _format_native_section(native_match_data: Dict[str, Any] | None) -> str:
    """Format the Affinda native scoring breakdown into a rich markdown section."""
    if not native_match_data:
        return ""
    
    overall_score = native_match_data.get("score")
    overall_pct = f"{int(overall_score * 100)}%" if isinstance(overall_score, (int, float)) else "N/A"
    details = native_match_data.get("details", {})
    
    native_section = f"""
---

## 🤖 Affinda Native Match Analysis: {overall_pct}

This section represents **Affinda's native machine-learning match predictions** and category weights.

| Criterion | Score | Extracted Context / Value |
| :--- | :--- | :--- |
"""
    for key, criterion in details.items():
        if not isinstance(criterion, dict):
            continue
        lbl = criterion.get("label", key.title())
        val = criterion.get("value") or "*Not specified / No Match*"
        c_score = criterion.get("score")
        c_score_str = f"**{int(c_score * 100)}%**" if isinstance(c_score, (int, float)) else "*N/A / Low weight*"
        native_section += f"| **{lbl}** | {c_score_str} | {val} |\n"
        
    native_section += "\n"
    return native_section


def generate_markdown_report(
    parsed_data: Dict[str, Any],
    overlap_results: Dict[str, Any],
    native_match_data: Dict[str, Any] | None = None
) -> str:
    """Generates a detailed, beautiful markdown report comparing parsed results with JD expectations."""
    contact, emails, phones = _extract_contact_info(parsed_data)
    work_history = _extract_work_history(parsed_data)
    native_section = _format_native_section(native_match_data)
    
    score = overlap_results["score"]
    matched = overlap_results["matched"]
    missed = overlap_results["missed"]
    
    # Construct the report with beautiful, rich layout
    markdown = f"""# Affinda ATS Parser Audit Report

This on-demand report presents a professional, commercial-grade ATS parse analysis of your generated resume using **Affinda's Ingestion Engine**.

---

## 📊 ATS Parse scorecard: {score}/100

| Metric | Status | Details |
| :--- | :--- | :--- |
| **Parsing Parsability** | ✅ PASS | File parsed successfully without layout-induced corruption. |
| **Contact Extraction** | {"✅ OK" if emails != "None detected" else "⚠️ WARNING"} | Name: `{contact}` | Email: `{emails}` | Phone: `{phones}` |
| **Technical Skill Alignment** | { "✅ EXCELLENT" if score >= 80 else "⚠️ IMPROVEMENT ADVISED" } | Overlap score of `{score}%` against core job description keywords. |
{native_section}
---

## 🛠️ Keyword Overlap Map

### ✅ Matched Keywords ({len(matched)})
These skills were correctly identified and extracted by Affinda's machine-learning parser:
{chr(10).join([f"- **{m.title()}**" for m in matched]) if matched else "- *None detected*"}

### ❌ Missed Keywords ({len(missed)})
These core Job Description requirements were **not** parsed from the resume file. Consider adding explicit mentions of these terms:
{chr(10).join([f"- `{m}`" for m in missed]) if missed else "- *None (Perfect match!)*"}

---

## 📦 Parsed Work Experience Timeline

Affinda extracted the following chronological history from your PDF/DOCX structure:

"""
    for idx, exp in enumerate(work_history, 1):
        title = exp.get("jobTitle", "Unknown Title")
        org = exp.get("organization", "Unknown Organization")
        start = exp.get("startDate", "N/A")
        end = exp.get("endDate", "Present")
        desc = exp.get("jobDescription", "")
        
        markdown += f"""### {idx}. {title} at {org}
- **Tenure:** `{start}` to `{end}`
- **Parsed Summary:** {desc or "*No description extracted*"}

"""
        
    markdown += """---

## 💡 Recommended Layout & ATS Adjustments
1. **Font & Bullet Compliance**: If any missed keywords were actually present in your resume, the parser likely failed to extract them due to a multi-column layout or customized bullet points. Always use linear, clean structures.
2. **Explicit Skill Taxonomy**: commercial parsers look for exact keyword matches. Ensure your skills frontmatter compiles cleanly and matches industry-standard spellings.
"""
    return markdown


def main() -> None:
    parser = argparse.ArgumentParser(description="Affinda ATS Parse Comparator Tool")
    parser.add_argument("--resume", required=True, help="Path to the compiled PDF/DOCX/TXT resume file")
    parser.add_argument("--jd", required=True, help="Path to the target Job Description txt file")
    parser.add_argument("--out", help="Path to output markdown report file")
    
    args = parser.parse_args()
    
    resume_path = Path(args.resume)
    jd_path = Path(args.jd)
    out_path = Path(args.out) if args.out else Path("ai-generated-cvs/affinda_ats_report.md")
    
    print("🚀 Starting Standalone External ATS Audit Tool...")
    
    if not resume_path.exists():
        print(f"❌ Error: Resume file not found at {resume_path}")
        sys.exit(1)
        
    if not jd_path.exists():
        print(f"❌ Error: JD file not found at {jd_path}")
        sys.exit(1)
        
    try:
        # Load inputs
        jd_text = jd_path.read_text(encoding="utf-8")
        
        # Initialize client and trigger uploads
        client = AffindaParserClient()
        
        print("📁 Uploading and parsing Job Description...")
        jd_response = client.parse_job_description(jd_path)
        
        print("📄 Uploading and parsing Resume...")
        response_data = client.parse_resume(resume_path)
        
        # Extract Identifiers for Native Match API
        resume_id = response_data.get("identifier") or response_data.get("meta", {}).get("identifier")
        jd_id = jd_response.get("identifier") or jd_response.get("meta", {}).get("identifier")
        
        native_match_data = {}
        if resume_id and jd_id:
            try:
                print("⚡ Programmatically indexing resume into Search & Match index 'Resume-Search-Demo'...")
                client.add_to_index(resume_id, "Resume-Search-Demo")
                print("⏳ Waiting 15 seconds for Search & Match index to asynchronously process skills, title, and education metadata...")
                time.sleep(15)
            except Exception as idx_err:
                print(f"⚠️ Warning: Could not index resume: {idx_err}")
                
            print("🤖 Requesting native machine-learning match score from Affinda...")
            try:
                native_match_data = client.get_native_match(resume_id, jd_id)
            except Exception as match_err:
                print(f"⚠️ Warning: Could not retrieve native match score: {match_err}")
        
        # Analyze overlap
        data_obj = response_data.get("data", {})
        skills_raw = data_obj.get("skills") or data_obj.get("skill") or []
        parsed_skills = [
            (s.get("parsed", {}).get("name") if isinstance(s.get("parsed"), dict) else s.get("name", ""))
            for s in skills_raw
            if isinstance(s, dict)
        ]
        jd_keywords = extract_keywords_from_jd(jd_text)
        overlap_results = calculate_overlap_score(parsed_skills, jd_keywords)
        
        # Build Report
        report_md = generate_markdown_report(
            response_data.get("data", {}),
            overlap_results,
            native_match_data
        )
        
        # Write Output
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report_md, encoding="utf-8")
        
        print("✅ Success! Comparative ATS audit complete. Report written to:")
        print(f"   [Report Link](file://{out_path.resolve()})")
        print(f"📊 [Score: {overlap_results['score']}/100]")
        
    except Exception as e:
        print(f"❌ Ingestion/Comparison Failed: {e}")
        logger.exception("Audit tool failure")
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    main()
