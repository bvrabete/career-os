"""Strategy resolution for regional location conventions and career track archetypes."""

import logging
from pathlib import Path
import re
from typing import Any
import yaml
from kb_config import get_strategy_default

logger = logging.getLogger(__name__)


def _parse_yaml_frontmatter(content: str) -> dict[str, Any]:
    """Extract and parse YAML frontmatter from markdown content."""
    if not isinstance(content, str):
        return {}
    fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not fm_match:
        return {}
    try:
        return yaml.safe_load(fm_match.group(1)) or {}
    except Exception:
        return {}


def discover_available_strategies(wiki_dir: Path) -> tuple[list[str], list[str]]:
    """Discover available location and track strategies from the wiki."""
    strategies_dir = wiki_dir / "wiki" / "strategies"
    available_locations: list[str] = []
    available_tracks: list[str] = []

    try:
        dir_exists = strategies_dir.exists()
        if isinstance(dir_exists, bool) and not dir_exists:
            return available_locations, available_tracks
    except Exception:
        return available_locations, available_tracks

    loc_dir = strategies_dir / "locations"
    try:
        if isinstance(loc_dir.is_dir(), bool) and loc_dir.is_dir():
            available_locations = [
                f.stem.replace("strategy-", "")
                for f in loc_dir.glob("*.md")
                if not getattr(f, "name", "").startswith(".")
            ]
    except Exception:
        pass

    if not available_locations:
        try:
            available_locations = [
                f.stem.replace("strategy-", "")
                for f in strategies_dir.glob("strategy-*.md")
                if not getattr(f, "name", "").startswith(".")
            ]
        except Exception:
            pass

    track_dir = strategies_dir / "tracks"
    try:
        if isinstance(track_dir.is_dir(), bool) and track_dir.is_dir():
            available_tracks = [
                f.stem.replace("track-", "")
                for f in track_dir.glob("*.md")
                if not getattr(f, "name", "").startswith(".")
            ]
    except Exception:
        pass

    clean_locations = sorted(list(set(str(x) for x in available_locations if x)))
    clean_tracks = sorted(list(set(str(x) for x in available_tracks if x)))
    return clean_locations, clean_tracks


def _find_location_strategy_file(wiki_dir: Path, name: str) -> Path | None:
    """Helper to locate a regional strategy file across locations/ and root strategies/."""
    candidates = [
        wiki_dir / "wiki" / "strategies" / f"strategy-{name}.md",
        wiki_dir / "wiki" / "strategies" / f"{name}.md",
        wiki_dir / "wiki" / "strategies" / "locations" / f"{name}.md",
        wiki_dir / "wiki" / "strategies" / "locations" / f"strategy-{name}.md",
    ]
    for c in candidates:
        try:
            res = c.exists()
            if isinstance(res, bool) and res:
                return c
        except Exception:
            continue
    return None


def _match_location_alias(wiki_dir: Path, region_lower: str) -> Path | None:
    """Matches regional keywords to available location strategies."""
    if any(kw in region_lower for kw in ["uk", "london", "united kingdom", "ireland"]):
        return _find_location_strategy_file(wiki_dir, "ireland")
    if any(kw in region_lower for kw in ["germany", "dach", "berlin", "munich"]):
        return _find_location_strategy_file(wiki_dir, "germany")
    if any(kw in region_lower for kw in ["netherlands", "amsterdam"]):
        return _find_location_strategy_file(wiki_dir, "netherlands")
    if any(kw in region_lower for kw in ["us", "usa", "america", "united states", "tech"]):
        return _find_location_strategy_file(wiki_dir, "us-tech")
    if any(kw in region_lower for kw in ["remote", "global"]):
        return _find_location_strategy_file(wiki_dir, "global-remote") or _find_location_strategy_file(wiki_dir, "remote")
    if any(kw in region_lower for kw in ["emea", "europe"]):
        return _find_location_strategy_file(wiki_dir, "emea")
    return None


def resolve_regional_strategy(wiki_dir: Path, region: str) -> tuple[str, str]:
    """Resolve the regional strategy file and template css."""
    region_lower = region.lower().strip()
    strategy_file = _find_location_strategy_file(wiki_dir, region_lower)
    if not strategy_file:
        strategy_file = _match_location_alias(wiki_dir, region_lower)

    if not strategy_file:
        default_strategy = get_strategy_default()
        strategy_file = _find_location_strategy_file(wiki_dir, default_strategy) or _find_location_strategy_file(
            wiki_dir, "emea"
        )

    strategy_text = ""
    pdf_template = "templates/base.css"
    if strategy_file:
        try:
            file_exists = strategy_file.exists()
            if isinstance(file_exists, bool) and file_exists:
                raw_text = strategy_file.read_text(encoding="utf-8")
                if isinstance(raw_text, str):
                    strategy_text = raw_text
                    if strategy_text.startswith("---"):
                        fm = _parse_yaml_frontmatter(strategy_text)
                        if fm and "pdf_template" in fm:
                            pdf_template = str(fm["pdf_template"]).strip()
        except Exception as e:
            logger.warning("Error reading regional strategy file %s: %s", strategy_file, e)

    return strategy_text, pdf_template


def _find_track_strategy_file(wiki_dir: Path, name: str) -> Path | None:
    """Helper to locate a career track strategy file."""
    candidates = [
        wiki_dir / "wiki" / "strategies" / "tracks" / f"{name}.md",
        wiki_dir / "wiki" / "strategies" / "tracks" / f"track-{name}.md",
        wiki_dir / "wiki" / "strategies" / f"track-{name}.md",
        wiki_dir / "wiki" / "strategies" / f"{name}.md",
    ]
    for c in candidates:
        try:
            res = c.exists()
            if isinstance(res, bool) and res:
                return c
        except Exception:
            continue
    return None


def _match_track_alias(wiki_dir: Path, track_lower: str) -> Path | None:
    """Matches track keywords to available track strategies."""
    if any(kw in track_lower for kw in ["manager", "management", "lead", "em", "director"]):
        return _find_track_strategy_file(wiki_dir, "engineering-management")
    if any(kw in track_lower for kw in ["staff", "principal", "architect"]):
        return _find_track_strategy_file(wiki_dir, "staff-principal")
    if any(kw in track_lower for kw in ["executive", "vp", "cto", "head of", "c-level", "chief"]):
        return _find_track_strategy_file(wiki_dir, "executive")
    if any(kw in track_lower for kw in ["startup", "founding", "founder"]):
        return _find_track_strategy_file(wiki_dir, "startup-founding-engineer")
    if any(kw in track_lower for kw in ["engineer", "developer", "software", "backend", "frontend", "full-stack"]):
        return _find_track_strategy_file(wiki_dir, "general-engineering")
    return None


def resolve_track_strategy(wiki_dir: Path, track: str) -> str:
    """Resolve the career track strategy file content."""
    track_lower = track.lower().strip()
    strategy_file = _find_track_strategy_file(wiki_dir, track_lower)
    if not strategy_file:
        strategy_file = _match_track_alias(wiki_dir, track_lower)

    if not strategy_file:
        strategy_file = (
            _find_track_strategy_file(wiki_dir, "engineering-management")
            or _find_track_strategy_file(wiki_dir, "general-engineering")
        )

    if strategy_file:
        try:
            file_exists = strategy_file.exists()
            if isinstance(file_exists, bool) and file_exists:
                raw_text = strategy_file.read_text(encoding="utf-8")
                if isinstance(raw_text, str):
                    return raw_text
        except Exception as e:
            logger.warning("Error reading track strategy file %s: %s", strategy_file, e)

    return ""
