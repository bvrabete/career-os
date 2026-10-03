"""Unit tests for the sync_case_studies tool."""

import pytest
from pathlib import Path
from tools.sync_case_studies import (
    _clean_slug,
    _extract_case_study_bullet,
    _extract_frontmatter_and_body,
    _extract_related_slugs,
    _find_parent_experience_file,
    sync_case_studies,
)


def test_clean_slug():
    assert _clean_slug(None) == ""
    assert _clean_slug("simple-slug") == "simple-slug"
    assert _clean_slug("[[case-studies/my-case-study]]") == "case-studies/my-case-study"
    assert _clean_slug("  [[company-role]]  ") == "company-role"


def test_extract_frontmatter_and_body():
    raw_content = "---\ntitle: Sample Case Study\ntenure: [[experiences/acme-corp]]\n---\n\n## Overview\nThis is a body."
    fm, body = _extract_frontmatter_and_body(raw_content)
    assert fm.get("title") == "Sample Case Study"
    assert "## Overview" in body

    # Content without frontmatter
    fm_empty, body_raw = _extract_frontmatter_and_body("Just body content")
    assert fm_empty == {}
    assert body_raw == "Just body content"


def test_extract_case_study_bullet():
    fm = {"title": "Distributed Cache Migration"}
    body = "## Quantified Impact & Results\n- Reduced latency by 45% and scaled to 10M requests."
    bullet = _extract_case_study_bullet(fm, body, "cache-migration")
    assert bullet == "- **Distributed Cache Migration**: Reduced latency by 45% and scaled to 10M requests. ([[case-studies/cache-migration]])"

    # Fallback to Architecture & System Design
    body_arch = "## Architecture & System Design\nDesigned multi-region Redis replica topology."
    bullet_arch = _extract_case_study_bullet(fm, body_arch, "cache-migration")
    assert bullet_arch == "- **Distributed Cache Migration**: Designed multi-region Redis replica topology. ([[case-studies/cache-migration]])"

    # Fallback to title only
    bullet_empty = _extract_case_study_bullet(fm, "", "cache-migration")
    assert bullet_empty == "- **Distributed Cache Migration**: Spearheaded technical architecture and implementation. ([[case-studies/cache-migration]])"


def test_extract_related_slugs():
    assert _extract_related_slugs("acme-corp") == ["acme-corp"]
    assert _extract_related_slugs(["[[acme-corp]]", "globex"]) == ["acme-corp", "globex"]
    assert _extract_related_slugs([["nested-corp"], "outer"]) == ["nested-corp", "outer"]


def test_find_parent_experience_file(tmp_path: Path):
    exp_dir = tmp_path / "wiki" / "experiences"
    exp_dir.mkdir(parents=True)
    (exp_dir / "acme-corp-lead-engineer.md").write_text("---\norganization: Acme Corp\n---\n# Acme", encoding="utf-8")

    # Match by tenure slug
    target = _find_parent_experience_file(exp_dir, {"tenure": "acme-corp-lead-engineer"})
    assert target is not None
    assert target.name == "acme-corp-lead-engineer.md"

    # Match by organization name
    target_org = _find_parent_experience_file(exp_dir, {"organization": "acme-corp"})
    assert target_org is not None
    assert target_org.name == "acme-corp-lead-engineer.md"

    # Match by related
    target_rel = _find_parent_experience_file(exp_dir, {"related": ["acme-corp"]})
    assert target_rel is not None
    assert target_rel.name == "acme-corp-lead-engineer.md"


def test_sync_case_studies_end_to_end(tmp_path: Path):
    wiki_dir = tmp_path
    cs_dir = wiki_dir / "wiki" / "case-studies"
    exp_dir = wiki_dir / "wiki" / "experiences"
    cs_dir.mkdir(parents=True)
    exp_dir.mkdir(parents=True)

    exp_file = exp_dir / "acme-corp-lead.md"
    exp_file.write_text(
        "---\ntype: experience\ntitle: Lead\norganization: Acme Corp\n---\n\n## Key Achievements\n- Existing achievement.\n",
        encoding="utf-8"
    )

    cs_file = cs_dir / "scale-system.md"
    cs_file.write_text(
        "---\ntitle: Scaling System\ntenure: [[acme-corp-lead]]\n---\n\n## Quantified Impact & Results\nBoosted throughput by 300%.\n",
        encoding="utf-8"
    )

    # First pass: should sync 1 case study
    stats = sync_case_studies(wiki_dir, dry_run=False)
    assert stats["total_case_studies"] == 1
    assert stats["synced"] == 1
    assert stats["already_synced"] == 0
    assert stats["unmatched"] == 0

    content_after = exp_file.read_text(encoding="utf-8")
    assert "([[case-studies/scale-system]])" in content_after

    # Second pass: idempotent, already synced
    stats_idempotent = sync_case_studies(wiki_dir, dry_run=False)
    assert stats_idempotent["total_case_studies"] == 1
    assert stats_idempotent["synced"] == 0
    assert stats_idempotent["already_synced"] == 1
