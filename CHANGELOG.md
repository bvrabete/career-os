# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.6.0] - 2026-07-27

### Added
- **Experience-by-Experience Map-Reduce Tailoring**: Engineered a modular Map-Reduce pipeline (`node_drafter` in `src/generation/nodes.py`) that isolates each professional experience entry. The **Map Phase** extracts organization slugs, matches associated projects, patents, and performance notes, and processes each experience in complete isolation to dramatically reduce LLM context overhead and prevent attention dilution. The **Reduce Phase** assembles the final tailored experience blocks and compiles them into a unified resume format, appending education, skills, and spoken languages.
- **Dedicated Mapping Prompt Templates**: Introduced `src/prompts/cv_gen/map_draft_role.txt` for single-experience tailoring, separating granular prompt instructions from the python logic.

## [1.5.0] - 2026-07-26

### Added
- **Multi-Factor Experience Weighting (4-Tier Routing)**: Engineered a dynamic, multi-factor weighting algorithm (`calculate_experience_weight`) based on *ATS Score Relevance* (50%), *Recency Decay* (30%), and *Service Duration* (20%).
- **Tier 4 Historical One-Liner Compressor**: Introduced a pre-drafting compression step (`compress_experience_to_one_liner_llm`) that automatically compiles extremely historical roles (15+ years old) or ultra-low weight roles into a single high-impact, keyword-rich, ATS-aligned sentence, preventing page-budget exhaustion while fully avoiding chronological role omissions.
- **Dynamic JD-Aligned Side-Project Selection**: Re-engineered the drafting guidelines to dynamically evaluate side projects and startup ventures against the target Job Description's keywords, automatically expanding them with STAR bullets to capture the ATS match, or compressing them to single-line entries to maximize page budget.
- **Standalone Document Conversion CLI**: Fully documented and registered the `doc-gen` CLI script shortcut to compile existing Markdown resumes into production-ready PDF and high-compatibility Microsoft Word (`.docx`) formats.
- **Standalone ATS Parser Auditor CLI**: Registered and documented the `ats-audit` CLI script shortcut to upload and stress-test compiled resumes against target Job Descriptions using real-world parsing engines.

### Changed
- **Pristine Prompt & Engine Decoupling**: Fully refactored and generalized all generation and extraction system prompts to remove any candidate-specific or company-specific names, replacing them with generic, high-fidelity algorithmic guidelines.
- **Generic Organization Slugification**: Decoupled the custom organization-prefix check in `helpers.py` to ensure prefix-agnostic string slugification and entity resolving.

## [1.4.1] - 2026-07-02

### Added

- **PDF Frontmatter Parsing and Header Generation**: Added robust sequential YAML frontmatter extraction in `src/pdf_generator.py` along with automatic extraction of contact details (name, position, email, phone, location, and social links) to build a styled, professional HTML header at the top of generated PDFs, completely separating metadata from body content.
- **Markdown Code Block Wrapper Stripping**: Implemented automatic markdown wrapper cleaning (`_clean_markdown_wrapper`) in both `src/pdf_generator.py` and `src/docx_generator.py` to strip outer ` ```markdown ... ``` ` blocks, preventing raw markdown formatting wrapper lines from leaking into compilations.
- **PDF and DOCX Test Coverage**: Created a comprehensive unit test suite in `tests/test_pdf_generator.py` to validate markdown code block stripping, single/multiple YAML frontmatter block parsing, styled contact header construction, and mock-based PDF and DOCX generation.

### Changed

- **Dependabot Infrastructure & Core Upgrades**:
  - Upgraded dependencies in the `uv` group, including `langchain` to `1.3.11`, `pytest` to `9.0.3`, `h2` to `4.3.0`, and `torch` to `2.12.1`.
  - Bumped core CI Workflow actions, including `actions/checkout` to `v7` and `astral-sh/setup-uv` to `v7`.

## [1.4.0] - 2026-06-26

### Added

- **Factual Honesty and Non-Embellishment Mandate**: Re-engineered the core CV generation pipeline prompts in `src/cv_generator_graph.py` to enforce strict data integrity and prohibit metric fabrication or empty resume-writing adjectives (e.g. "Dynamic", "Visionary", "Proven track record").
- **Dynamic Regional Professional Summaries**: Refactored the summary guidelines to adapt style and length dynamically according to target regions (such as 1-2 sentence concise technical hooks for US-style resumes, or 3-line dense factual overviews for UK/EMEA targets) rather than a rigid, hardcoded 3-line constraint.
- **Fact-Based Skill Bridging Guidelines**: Guided the `node_drafter` to explicitly represent transferable skills using honest qualifiers (e.g. "Azure (AWS equivalent)" or "Kotlin (transferable to Java)") to pass semantic ATS screeners without fabricating direct experience.

### Changed

- **Rigorous Auditing Criteria**: Updated the `node_auditor` critique prompt to penalize embellishments, fake metrics, and empty marketing buzzwords while allowing flexible, factual, region-appropriate summaries.

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
- **Dynamic Wiki-Synthesis Default Output**: Refactored `cv-gen` to make `--out` completely optional. If omitted, the generated CV (enriched with tracking frontmatter properties) is saved by default directly inside the predefined LLM-Wiki Synthesis directory (`wiki/synthesis/synthesis-cv-{company}-{role}-{date}.md`), keeping the root clean and automating your professional application tracking.

### Changed

- **Graph State Expansion**: Extended `CVPipelineState` inside `src/cv_generator_graph.py` with modular state keys for projects, patents, notes, few-shots, and skill-bridging maps.
- **Drafter Prompt Enrichment**: Updated the `node_drafter` system prompt to utilize retrieved projects, patents, and review notes, align phrasing with successful few-shots, and apply deterministic skill translations.
- **System Documentation**: Expanded `README.md` with complete details on PDF customization, bootstrapping, and an updated multi-pipeline system architecture Mermaid diagram.
- **PDF Compilation Filtering**: Upgraded PDF generation to always compile using the clean draft CV layout, preventing raw YAML frontmatter tracking properties from showing up at the top of compiled PDFs.
