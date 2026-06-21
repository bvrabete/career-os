# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0] - 2026-06-21

### Added

- **Multi-Source Ingestion Bootstrapping**: Automated directory seeding. If a target wiki folder is missing or empty, `kb-ingest` initializes all 14 standard directories (`experiences`, `education`, `projects`, `skills`, `patents`, `notes`, etc.), copy-seeds a clean anonymized `schema.md` blueprint, and creates a candidate-agnostic `mappings.md` template.
- **Polymorphic Ingestion & Extraction**: Expanded `node_extractor` with standardized branching extraction prompts based on `doc_type`:
  - `experience`: Extracts roles, education, languages, and nested projects/patents.
  - `cover_letter`: Extracts standardized cover letter fields (`target_organization_raw`, `role_fit`, `highlights`, etc.).
  - `supplemental`: Extracts performance reviews and peer praise feedback into note structures.
- **Modular Project & Patent Modularity**: Standalone Markdown page generation under `wiki/projects/` and `wiki/patents/` utilizing cross-linking frontmatter (`organization: [[entity-slug]]`) to bind accomplishments to experiences.
- **Expanded Semantic Retrieval**: Updated `node_retriever` to retrieve and rank projects and patents using a fast, word-boundary-aware case-insensitive keyword matcher, with semantic score boosts applied to entries bound to currently retrieved experience slugs.
- **"My Voice" Standard Note Integration**: Automatic retrieval of performance reviews and reflection notes under `wiki/notes/` bound to currently retrieved experience slugs. Passed as `notes_entries` to help the drafter infuse authentic peer praise.
- **Success-Based Recursive Few-Shot Selection**: Automatically scans `wiki/synthesis/` for past successful applications (`status: Offer` or `status: Technical-Interview`) and injects the top 2 most relevant past CV templates to guide style, tone, and layout density.
- **Deterministic Skill Bridging**: Generates an explicit JSON `skill_bridging_map` (e.g. `{"AWS": "Azure (equivalent)"}`) during retrieval to translate required JD skills into the candidate's closest equivalents.
- **Dynamic PDF Compile Chaining**: Implemented the `--generate-pdf` CLI argument in `generate_cv.py` which automatically converts generated Markdown to a styled PDF using WeasyPrint and the regional strategy's designated CSS template.
- **Synthesis CRM Archiving**: Automatically duplicates generated CVs into `<LLM_WIKI_DIR>/wiki/synthesis/synthesis-cv-[company]-[role]-[date].md` with pre-populated application tracking frontmatter (`status: Applied`, `applied_date`, etc.).
- **Manual Strategy Overrides**: Implemented the `--strategy <slug>` CLI argument to force-bypass automated analyzer region strategy inference.
- **Native Gemini API Integration**: Added native support for Google Gemini models (e.g., `gemini-1.5-pro` for large context CV drafting) via `langchain-google-genai`.
- **Validation Test Suite**: Introduced a comprehensive standard Python `unittest` suite in `tests/test_pipeline.py` verifying keyword scoring, skill bridging, and strategy overrides.
- **GitHub Actions CI Pipeline**: Added a continuous integration workflow (`.github/workflows/test.yml`) that automatically runs the unit test suite on all pushes and pull requests to `main` and `master`, enabling pull request blocking on failure.
- **Project-Specific Dependabot Support**: Relocated and configured the Dependabot settings to the correct location at `.github/dependabot.yml` using the `pip` ecosystem for Python and `github-actions` for workflows.
- **Dependabot UV Lock Auto-Updater**: Created a custom workflow `.github/workflows/dependabot-uv-lock.yml` that runs on Dependabot PRs, automatically running `uv lock` and pushing updates to keep the virtual environment lockfile fully in-sync.

### Changed

- **Graph State Expansion**: Extended `CVPipelineState` inside `src/cv_generator_graph.py` with modular state keys for projects, patents, notes, few-shots, and skill-bridging maps.
- **Drafter Prompt Enrichment**: Updated the `node_drafter` system prompt to utilize retrieved projects, patents, and review notes, align phrasing with successful few-shots, and apply deterministic skill translations.
- **System Documentation**: Expanded `README.md` with complete details on PDF customization, bootstrapping, and an updated multi-pipeline system architecture Mermaid diagram.
