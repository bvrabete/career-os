"""Catalog generator and indexer for the LLM-Wiki knowledge base."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from utils import validate_path

logger = logging.getLogger(__name__)


def _parse_frontmatter(file_path: Path) -> dict[str, Any]:
    """Parse YAML frontmatter from a markdown file."""
    try:
        content = file_path.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return {}
        parts = content.split("---", 2)
        if len(parts) >= 3:
            parsed = yaml.safe_load(parts[1])
            return parsed if isinstance(parsed, dict) else {}
    except Exception as e:
        logger.debug(f"Failed to parse frontmatter from {file_path.name}: {e}")
    return {}


def _index_experiences(wiki_root: Path) -> list[dict[str, Any]]:
    """Index all experience markdown files."""
    exp_dir = wiki_root / "experiences"
    if not exp_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for file in sorted(exp_dir.glob("*.md")):
        if file.name.startswith("."):
            continue
        fm = _parse_frontmatter(file)
        content = file.read_text(encoding="utf-8")
        bullets = [line for line in content.splitlines() if line.strip().startswith("- ")]
        case_study_links = content.count("[[case-studies/")
        records.append({
            "slug": file.stem,
            "organization": fm.get("organization", ""),
            "role": fm.get("role", ""),
            "start_date": str(fm.get("start_date", "")),
            "end_date": str(fm.get("end_date", "")),
            "achievements_count": len(bullets),
            "case_studies_count": case_study_links,
            "file": file.name,
        })
    return records


def _index_education(wiki_root: Path) -> list[dict[str, Any]]:
    """Index education records."""
    edu_dir = wiki_root / "education"
    if not edu_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for file in sorted(edu_dir.glob("*.md")):
        if file.name.startswith("."):
            continue
        fm = _parse_frontmatter(file)
        records.append({
            "slug": file.stem,
            "institution": fm.get("institution", ""),
            "degree": fm.get("degree", ""),
            "year": str(fm.get("year", fm.get("end_date", ""))),
            "file": file.name,
        })
    return records


def _index_projects(wiki_root: Path) -> list[dict[str, Any]]:
    """Index personal, side, and open source projects."""
    proj_dir = wiki_root / "projects"
    if not proj_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for file in sorted(proj_dir.glob("*.md")):
        if file.name.startswith(".") or file.name.endswith(".example.md"):
            continue
        fm = _parse_frontmatter(file)
        records.append({
            "slug": file.stem,
            "name": fm.get("name", file.stem),
            "project_nature": fm.get("project_nature", "project"),
            "technologies": fm.get("technologies", []),
            "file": file.name,
        })
    return records


def _index_case_studies(wiki_root: Path) -> list[dict[str, Any]]:
    """Index in-depth STAR case studies."""
    cs_dir = wiki_root / "case-studies"
    if not cs_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for file in sorted(cs_dir.glob("*.md")):
        if file.name.startswith("."):
            continue
        fm = _parse_frontmatter(file)
        records.append({
            "slug": file.stem,
            "title": fm.get("title", file.stem),
            "related_experience": fm.get("related_experience", ""),
            "file": file.name,
        })
    return records


def _index_skills(wiki_root: Path) -> list[str]:
    """Index skills taxonomy slugs."""
    skills_dir = wiki_root / "skills"
    if not skills_dir.is_dir():
        return []
    return [f.stem for f in sorted(skills_dir.glob("*.md")) if not f.name.startswith(".")]


def _index_strategies(wiki_root: Path) -> dict[str, list[str]]:
    """Index available regional and track strategies."""
    strat_dir = wiki_root / "strategies"
    if not strat_dir.is_dir():
        return {"locations": [], "tracks": [], "all": []}

    locations: list[str] = []
    loc_dir = strat_dir / "locations"
    if loc_dir.is_dir():
        locations = [
            f.stem.replace("strategy-", "")
            for f in sorted(loc_dir.glob("*.md"))
            if not f.name.startswith(".")
        ]
    if not locations:
        locations = [
            f.stem.replace("strategy-", "")
            for f in sorted(strat_dir.glob("strategy-*.md"))
            if not f.name.startswith(".")
        ]

    tracks: list[str] = []
    track_dir = strat_dir / "tracks"
    if track_dir.is_dir():
        tracks = [
            f.stem.replace("track-", "")
            for f in sorted(track_dir.glob("*.md"))
            if not f.name.startswith(".")
        ]

    all_strats = sorted(list(set(locations + tracks)))
    return {"locations": locations, "tracks": tracks, "all": all_strats}


def generate_catalog(wiki_dir: Path) -> dict[str, Any]:
    """Build a comprehensive index catalog of all entities in the wiki."""
    validated_dir = validate_path(wiki_dir)
    wiki_root = validated_dir / "wiki" if (validated_dir / "wiki").is_dir() else validated_dir

    experiences = _index_experiences(wiki_root)
    education = _index_education(wiki_root)
    projects = _index_projects(wiki_root)
    case_studies = _index_case_studies(wiki_root)
    skills = _index_skills(wiki_root)
    strategies_info = _index_strategies(wiki_root)
    strategies = strategies_info["all"]

    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_experiences": len(experiences),
            "total_education": len(education),
            "total_projects": len(projects),
            "total_case_studies": len(case_studies),
            "total_skills_categories": len(skills),
            "total_strategies": len(strategies),
            "total_location_strategies": len(strategies_info["locations"]),
            "total_track_strategies": len(strategies_info["tracks"]),
        },
        "experiences": experiences,
        "education": education,
        "projects": projects,
        "case_studies": case_studies,
        "skills_categories": skills,
        "strategies": strategies,
        "location_strategies": strategies_info["locations"],
        "track_strategies": strategies_info["tracks"],
    }


def save_catalog(wiki_dir: Path, catalog: dict[str, Any] | None = None) -> Path:
    """Save the catalog to catalog.json under wiki_dir/wiki or wiki_dir."""
    validated_dir = validate_path(wiki_dir)
    wiki_root = validated_dir / "wiki" if (validated_dir / "wiki").is_dir() else validated_dir

    if catalog is None:
        catalog = generate_catalog(wiki_dir)

    target_file = validate_path(wiki_root / "catalog.json")
    target_file.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Saved wiki catalog to: {target_file}")
    return target_file


def load_catalog(wiki_dir: Path) -> dict[str, Any] | None:
    """Load existing catalog.json if available."""
    validated_dir = validate_path(wiki_dir)
    wiki_root = validated_dir / "wiki" if (validated_dir / "wiki").is_dir() else validated_dir
    catalog_path = wiki_root / "catalog.json"
    if not catalog_path.exists():
        return None
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning(f"Failed to load catalog.json: {e}")
        return None
