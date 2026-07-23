"""
Helper module to extract, compile, and link all candidate skills across the Wiki.
This is shared between the standalone sync CLI and the main ingestion pipeline.
"""

import logging
from pathlib import Path
import re
from typing import Any
import yaml

logger = logging.getLogger(__name__)

COMMON_SLUGS = {
    "c#": "c-sharp",
    "c++": "c-plus-plus",
    ".net": "dotnet",
    ".net core": "dotnet-core",
    "f#": "f-sharp",
}


def get_skill_slug(name: str) -> str:
    """Get a clean, safe filename slug for a skill."""
    cleaned = name.strip().lower()
    if cleaned in COMMON_SLUGS:
        return COMMON_SLUGS[cleaned]
    slug = re.sub(r"[^a-z0-9\s_\-\.#\+]+", "", cleaned)
    slug = re.sub(r"[\s_\-\.#\+]+", "-", slug)
    return slug.strip("-")


def extract_skills_from_file(file_path: Path) -> list[str]:
    """Parse a markdown file's YAML frontmatter and extract its skills list."""
    if not file_path.exists():
        return []
    try:
        content = file_path.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if not match:
            return []
        frontmatter: dict[str, Any] = yaml.safe_load(match.group(1)) or {}
        skills = frontmatter.get("skills", [])
        if isinstance(skills, list):
            return [str(s).strip() for s in skills if s]
    except Exception as e:
        logger.warning("Failed to parse skills from %s: %s", file_path.name, e)
    return []


def gather_skills_from_directory(directory: Path) -> set[str]:
    """Gather all unique skills from all markdown files in a directory."""
    skills_set: set[str] = set()
    if not directory.exists():
        return skills_set
    for file_path in directory.glob("*.md"):
        extracted = extract_skills_from_file(file_path)
        skills_set.update(extracted)
    return skills_set


def get_all_candidate_skills(wiki_dir: Path) -> list[str]:
    """Extract and compile a sorted list of all unique candidate skills from experiences and projects."""
    all_skills: set[str] = set()
    exp_dir = wiki_dir / "wiki" / "experiences"
    all_skills.update(gather_skills_from_directory(exp_dir))
    proj_dir = wiki_dir / "wiki" / "projects"
    all_skills.update(gather_skills_from_directory(proj_dir))
    return sorted(list(all_skills))


def run_skills_sync(wiki_dir: Path, dry_run: bool = False) -> None:
    """Scan experiences and projects, compiling and linking all skills in wiki/skills/."""
    experiences_dir = wiki_dir / "wiki" / "experiences"
    projects_dir = wiki_dir / "wiki" / "projects"
    skills_dir = wiki_dir / "wiki" / "skills"

    if not skills_dir.exists():
        if not dry_run:
            skills_dir.mkdir(parents=True, exist_ok=True)

    # 1. Gather all unique skills mapped by slug to prevent duplicates
    skill_sources: dict[str, dict[str, Any]] = {}

    def scan_directory(directory: Path) -> None:
        if not directory.exists():
            return
        for f in directory.glob("*.md"):
            slug = f.stem
            skills = extract_skills_from_file(f)
            for skill in skills:
                if not skill:
                    continue
                skill_slug = get_skill_slug(skill)
                if skill_slug not in skill_sources:
                    skill_sources[skill_slug] = {
                        "name": skill,
                        "sources": set()
                    }
                else:
                    # Format refinement heuristic: prefer capitalized / nicer formatted variants
                    current_name = skill_sources[skill_slug]["name"]
                    if sum(1 for c in skill if c.isupper()) > sum(1 for c in current_name if c.isupper()):
                        skill_sources[skill_slug]["name"] = skill
                skill_sources[skill_slug]["sources"].add(slug)

    scan_directory(experiences_dir)
    scan_directory(projects_dir)

    print(f"📊 Found {len(skill_sources)} unique skill slug(s) across experiences and projects.")

    created_count = 0
    updated_count = 0

    for slug, data in sorted(skill_sources.items()):
        skill_name = data["name"]
        skill_file = skills_dir / f"{slug}.md"
        new_related = sorted(list(data["sources"]))

        # Check if skill file already exists
        if skill_file.exists():
            try:
                content = skill_file.read_text(encoding="utf-8")
                match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
                if match:
                    fm = yaml.safe_load(match.group(1)) or {}
                    body = content[match.end():].strip()
                else:
                    fm = {}
                    body = content.strip()
            except Exception as e:
                logger.error("Error reading existing skill %s.md: %s", slug, e)
                continue

            # Merge related experiences
            existing_related_raw = fm.get("related_experiences", [])
            existing_related = []
            if isinstance(existing_related_raw, list):
                for item in existing_related_raw:
                    item_str = str(item).strip()
                    m = re.match(r"^\[\[(.*?)\]\]$", item_str)
                    existing_related.append(m.group(1) if m else item_str)

            merged_related = sorted(list(set(existing_related + new_related)))
            
            # Update frontmatter
            fm["type"] = "skill"
            fm["title"] = fm.get("title", skill_name)
            fm["category"] = fm.get("category", ["Framework"])
            fm["related_experiences"] = [f"[[{r}]]" for r in merged_related]

            # Reconstruct content
            fm_str = yaml.dump(fm, default_flow_style=False, sort_keys=False).strip()
            new_content = f"---\n{fm_str}\n---\n\n{body}"
            
            if content.strip() != new_content.strip():
                print(f"  🔄 [UPDATE] {slug}.md -> Added links to {len(merged_related) - len(existing_related)} new sources.")
                if not dry_run:
                    skill_file.write_text(new_content, encoding="utf-8")
                updated_count += 1
        else:
            # Create a brand new skill file
            fm = {
                "type": "skill",
                "title": skill_name,
                "category": ["Framework"],
                "related_experiences": [f"[[{r}]]" for r in new_related],
                "proficiency": ["Proficient"]
            }
            fm_str = yaml.dump(fm, default_flow_style=False, sort_keys=False).strip()
            body_str = f"# {skill_name}\n\n## Description\nDefinition and details of {skill_name}.\n\n## Evidence & Accomplishments\nProven in action across:\n" + "\n".join(f"- [[{r}]]" for r in new_related)
            new_content = f"---\n{fm_str}\n---\n\n{body_str}"

            print(f"  ✨ [NEW] Creating skill: {slug}.md (linked to {len(new_related)} sources)")
            if not dry_run:
                skill_file.write_text(new_content, encoding="utf-8")
            created_count += 1

    print(f"🧹 Skills compilation completed. Created: {created_count}  Updated: {updated_count}")


def get_compact_skills_list(skills_dir: Path, allowed_experience_slugs: list[str] | None = None) -> list[str]:
    """Generates a compact, token-efficient summary of candidate's skills and where they were applied."""
    if not skills_dir.exists():
        return []
    
    allowed_set = set(allowed_experience_slugs) if allowed_experience_slugs is not None else None
    compact_skills = []
    
    for f in sorted(skills_dir.glob("*.md")):
        try:
            content = f.read_text(encoding="utf-8")
            # Extract title and related experiences
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if match:
                fm = yaml.safe_load(match.group(1)) or {}
                title = fm.get("title", f.stem)
                related_raw = fm.get("related_experiences", [])
                related_slugs = []
                for item in related_raw:
                    item_str = str(item).strip()
                    m_link = re.match(r"^\[\[(.*?)\]\]$", item_str)
                    related_slugs.append(m_link.group(1) if m_link else item_str)
                
                # Filter by allowed experience slugs if specified
                if allowed_set is not None:
                    filtered_related = [r for r in related_slugs if r in allowed_set]
                    if not filtered_related:
                        continue # Skip this skill entirely as it's not linked to any selected experience
                    related_slugs = filtered_related
                
                if related_slugs:
                    compact_skills.append(f"- **{title}** (Applied in: {', '.join(related_slugs)})")
                else:
                    compact_skills.append(f"- **{title}**")
        except Exception as e:
            logger.error("Error reading skill %s: %s", f.name, e)
            continue
            
    return compact_skills
