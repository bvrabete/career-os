# AGENTS.md — Career Operating System (CareerOS)

This document serves as the primary operational directive, architecture blueprint, and coding standard for all AI agents, pairing assistants, and autonomous tools working in the **CareerOS** workspace.

---

## 1. Project Overview & Core Mission

**CareerOS** is an AI-powered operating system for career knowledge management and tailored document generation. It integrates:
1. **A Semantic Knowledge Graph (LLM-Wiki)**: A canonical, versioned, file-based database storing the candidate's career history, skills, education, projects, patents, notes, and past applications.
2. **Wiki Ingestion Pipeline (`kb-ingest`)**: An automated extraction and normalization engine that parses raw resumes, cover letters, and performance notes into structured YAML/Markdown files conforming strictly to schema.
3. **Tailored Generation Pipeline (`cv-gen`)**: A LangGraph-based multi-agent synthesizer that tailors executive CVs to specific job descriptions with ATS scoring, regional styling, and recruiter audits.
4. **Standalone Document Compiler (`doc-gen`)**: Direct renderer from Markdown to production-ready styled PDF (WeasyPrint) and Word (.docx).

---

## 2. Core Mandates & Hierarchy of Truth

### The Canonical Wiki Principle
- **The Wiki is Master**: The `<LLM_WIKI_DIR>/wiki/` directory is the single source of truth.
- **Zero Hallucination**: Never invent, extrapolate, or embellish roles, dates, or achievements. All generated professional claims must trace directly back to wiki entries.

### The Total Recall Master Archive Principle
- **Exhaustive History**: The Knowledge Base must record 100% of the candidate's career history, milestones, minor accomplishments, metrics, and technical contributions over their entire lifetime, regardless of size or quantity.
- **Zero Pre-Filtering or Length Budgets in the Wiki**: Ingestion and maintenance pipelines must NEVER drop, summarize away, or truncate achievements to "save space". A single role may contain 30, 40, or more achievements.
- **Separation of Concerns**:
  - The **Wiki** maximizes recall, evidence retention, and historical completeness.
  - The **CV Generation Pipeline (`cv-gen`)** performs the surgical knapsack selection, choosing the top 5% of relevant evidence to fit a strict 1-to-2 page executive document.

### Semantic Integrity Tiers
- **Tier 1: Factual Records (`wiki/experiences/`, `wiki/education/`, `wiki/projects/`, `wiki/patents/`)**
  - Canonical employment and credential history. If an experience or credential does not exist here, the candidate never held it.
- **Tier 2: Reflective & Qualitative Artifacts (`wiki/cover-letters/`, `wiki/notes/`, `wiki/synthesis/`)**
  - Performance reviews, personal reflections ("My Voice"), and historical applied CVs. Used strictly for tone, narrative voice, and alignment—never as factual employment history.
- **Tier 3: Raw Archive (`raw/` or incoming documents)**
  - Unstructured input files used solely for parsing, extraction, and verification.

### Schema & Source Traceability
- Every entry in `<LLM_WIKI_DIR>/wiki/` must adhere strictly to `<LLM_WIKI_DIR>/schema.md`.
- All extracted entities must record their raw file origin in the `sources` YAML frontmatter field.

---

## 3. System Architecture & Workflows

### Ingestion Architecture (`kb-ingest`)

```
Raw Sources (PDF, DOCX, MD)
       │
       ▼
 Parser (pypdf for digital PDFs, docling for scanned/OCR)
       │
       ▼
 Classifier (Identifies document type: experience, cover_letter, supplemental)
       │
       ▼
 Polymorphic Extractor (Structured entity extraction)
       │
       ▼
 Resolver (Entity & organization alias mapping via mappings.md)
       │
       ▼
 Generator (Schema-compliant Markdown/YAML drafting)
       │
       ▼
 Merger (Enrich existing file or create date-bound entry)
       │
       ▼
 Validator (Self-healing YAML parser & schema check)
       │
       ▼
 Writer (Persist to <LLM_WIKI_DIR>/wiki/)
```

### Generation Architecture (`cv-gen`)

```
Job Description (JD) + LLM-Wiki
       │
       ▼
 [ANALYSIS Node]
   Extracts target persona, role, organization, key skills, and regional strategy.
       │
       ▼
 [RETRIEVAL Node]
   - Applies 4-Tier Multi-Factor Experience Weighting:
     * ATS keyword relevance (50%)
     * Recency decay over 15 years (30%)
     * Tenure duration up to 3 years (20%)
   - Dynamic 10-year boundary calculation (current_year - 10).
   - Programmatic pre-grouping of multi-tenure company histories.
   - Skill-bridging & few-shot retrieval.
       │
       ▼
 [DRAFTING Node]
   - Generates tailored CV sections matching regional strategy and tone.
   - Uses high-context LLMs (e.g. GPT-4o, Gemini 2.5/Pro) to prevent context truncation.
       │
       ▼
 [REFINER Node]
   - Evaluates line density, section flow, and strict page budget limits (e.g. 1-page vs 2-page).
       │
       ▼
 [AUDITOR Node]
   - Recruiter & ATS simulation check.
   - Loops back to Drafter with actionable feedback if density/keyword criteria fail.
       │
       ▼
 [EXPORTER Node]
   - Saves final tailored CV (Markdown + context.json).
   - Automatically archives CRM record to wiki/synthesis/.
   - Optionally invokes WeasyPrint (--generate-pdf) and python-docx (--generate-docx).
```

---

## 4. Setup, Environment & CLI Commands

Package and runtime management uses **`uv`** with Python 3.12+.

### Installation

```bash
# Core installation (cv-gen, doc-gen, ats-audit, kb-cleanup)
uv sync

# Extended installation including ingestion dependencies (docling, pypdf)
uv sync --group ingest

# Development and testing tools
uv sync --group dev
```

### Environment Variables
Configure `.env` based on `.env.example`:
- `OPENAI_API_KEY`: Required for high-fidelity drafting and synthesis.
- `GEMINI_API_KEY`: Required when using Gemini model configurations.
- `LLM_WIKI_DIR`: Path to the external knowledge base (default: `llm-wiki`).
- Ollama endpoint (default `http://localhost:11434`) when using local models.

### Key Commands

```bash
# Bootstrap a new external knowledge base
uv run kb-init --wiki-dir /path/to/llm-wiki

# Ingest career sources into the wiki
uv run kb-ingest --dir /path/to/raw/sources/ --wiki-dir /path/to/llm-wiki
uv run kb-ingest --dir /path/to/cover-letters/ --wiki-dir /path/to/llm-wiki

# Generate tailored CV (Zero-config saves directly to wiki/synthesis/)
uv run cv-gen --jd job-descriptions/target_jd.txt --wiki-dir /path/to/llm-wiki

# Generate tailored CV with custom output, theming, and document compilation
uv run cv-gen --jd job-descriptions/target_jd.txt --out ai-generated-cvs/Tailored_CV.md --wiki-dir /path/to/llm-wiki --generate-pdf --generate-docx --template executive

# Standalone document rendering with theme selection
uv run doc-gen --input ai-generated-cvs/Tailored_CV.md --format pdf --template compact
uv run doc-gen --input ai-generated-cvs/Tailored_CV.md --format docx --template executive

# Audit wiki data or external profiles
uv run ats-audit --wiki-dir /path/to/llm-wiki
uv run kb-cleanup --wiki-dir /path/to/llm-wiki
```

---

## 5. Directory Structure

```
career-os/
├── .agents/                      # Agent instruction rules and tooling hooks
│   └── AGENTS.md                 # Agent guidelines
├── docs/                         # Technical guides and ATS scoring documentation
├── job-descriptions/             # Sample and active target job descriptions
├── ai-generated-cvs/             # Exported CV drafts and tailored outputs
├── llm-wiki.template/            # Seed templates, schemas, and default styles for bootstrapping
├── src/                          # Main application source code
│   ├── generation/               # CV Generation LangGraph pipeline
│   │   ├── graph.py              # LangGraph compilation & workflow definition
│   │   ├── nodes.py              # Generation pipeline nodes (analyzer, retriever, drafter, etc.)
│   │   ├── state.py              # Pydantic schemas and pipeline state
│   │   ├── retrieval.py          # Fast-filter scoring & transferable skill equivalence
│   │   ├── pruning.py            # Frontmatter pruning & achievement selection
│   │   ├── formatting.py         # Chronological sorting & markdown builders
│   │   ├── helpers.py            # Core generation facade & text helpers
│   │   └── skills_helper.py      # Skill bridging and categorization logic
│   │   └── skills_helper.py      # Skill bridging and categorization logic
│   ├── ingestion/                # Wiki Ingestion pipeline
│   │   ├── graph.py              # Ingestion graph orchestration
│   │   ├── nodes.py              # Classifier, extractor, generator, merger nodes
│   │   ├── extraction.py         # Parsing and structured data extraction
│   │   ├── generation.py         # Schema-conforming generation logic
│   │   ├── helpers.py            # Normalization, alias resolution, YAML validation
│   │   └── state.py              # Ingestion state definitions
│   ├── prompts/                  # Externalized system prompts and Jinja templates
│   │   ├── cv_gen/               # Prompts for analyzer, drafter, auditor, compressors
│   │   └── ingestion/            # Prompts for classifier, extractors, mergers
│   ├── tools/                    # External auditing and diagnostic scripts
│   ├── cv_generator_graph.py     # Graph entrypoint compatibility wrapper
│   ├── docx_generator.py         # python-docx document builder
│   ├── pdf_generator.py          # WeasyPrint PDF compiler
│   ├── generate_cv.py            # CLI entrypoint: cv-gen
│   ├── generate_document_cli.py  # CLI entrypoint: doc-gen
│   ├── kb_cleanup.py             # CLI entrypoint: kb-cleanup
│   ├── kb_config.py              # Model and pipeline configuration loaders
│   ├── kb_ingest.py              # CLI entrypoint: kb-ingest
│   ├── kb_ingest_graph.py        # Ingestion graph entrypoint
│   ├── kb_skills_sync.py         # Skill synchronization utility
│   └── utils.py                  # Core utility functions, path security sanitizers
├── tests/                        # Comprehensive unit and integration test suite
├── pyproject.toml                # Project metadata, dependencies, and CLI script mappings
└── README.md                     # Human-facing documentation and project overview
```

---

## 6. Code Standards & Architecture Guidelines

All contributions in `src/` must strictly observe these engineering rules:

### Code Style & Formatting
- **PEP 8 Compliance**: Strictly enforced. Maximum line length is **120 characters**.
- **Imports**: All imports must reside exclusively at the top of the file. Inline or inside-function imports are strictly prohibited.
  - Import order: Standard library → Third-party libraries → Local project modules.
- **Ruff & Formatter**: Code must pass `ruff check` and formatting before submission.

### Type Annotations & Static Checking
- **Strict Typing**: All function parameters, return values, and module-level variables must include complete type annotations.
- Generic type syntax is required (e.g. `list[str]`, `dict[str, Any]`, `str | None`).
- No untyped calls or unbound variables permitted (Pyright / Pylance strict mode).

### File Size & Modular Decomposition
- **500-Line Maximum**: No single Python source file may exceed 500 lines.
- Complex sub-systems must be decomposed into dedicated subpackages containing:
  - `state.py`: TypedDict / Pydantic schemas.
  - `nodes.py`: Atomic graph node implementations.
  - `helpers.py`: Pure helper and utility routines.
  - `graph.py`: Graph wiring and state-machine compilation.

### Externalized Prompts
- Long prompt templates, system instructions, and few-shot examples must be externalized into plain text (`.txt`), Markdown (`.md`), or YAML files inside `src/prompts/`. Never hardcode multi-paragraph prompts in Python source.

### Error Handling & LLM Interfacing
- Wrap external LLM calls and network operations in explicit try/except blocks with descriptive custom exceptions.
- Always coerce LLM response content to `str` before downstream consumption (e.g. `str(response.content)`).
- Implement explicit, user-configured fallback models where defined in `config.yaml`.

### Configuration & Fail-Fast Mandate
- **Strictly Config-Driven**: All model selections, step bindings, and operational paths must be resolved from `config.yaml` or explicit CLI flags. Never embed hardcoded fallback model names (e.g. `qwen2.5:7b`, `gpt-4o`, `gemma`) in Python source code.
- **Fail-Fast Principles**:
  - **Missing Configuration File**: If `config.yaml` does not exist, immediately raise `FileNotFoundError` with clear setup instructions. Never return a phantom internal dummy configuration.
  - **Missing Step Binding**: If a pipeline step is invoked but absent in `config.yaml` under `STEPS`, immediately raise `KeyError`. Never silently fall back to an arbitrary default provider (e.g. Ollama).
  - **Missing Model Name**: If a step or provider does not specify `MODEL_NAME`, immediately raise `ValueError`.
  - **Secret Isolation**: Never place filesystem paths in `.env`. The `.env` file is strictly reserved for API credentials and secrets. Operational directories belong in `config.yaml` under `PATHS`.

### Security & Path Validation (pythonsecurity:S8707)
- **Path Traversal Prevention**: To eliminate directory traversal vulnerabilities, all filesystem reads and writes must pass through `validate_path()` in [src/utils.py](file:///C:/Users/bvrabete/source/personal/career-os/src/utils.py). Never read or write paths provided by CLI parameters or LLM outputs without canonicalization and sanitization.

### Cognitive Complexity (SonarQube python:S3776)
Keep cognitive complexity **strictly below 15** per function/method:
- **Maximum 2 Levels of Nesting**: Extract deeply nested loops or conditionals into helper functions.
- **Return-Early / Guard Clauses**: Handle preconditions, empty collections, and errors at the top of functions.
- **Focused Functions (<= 30 lines)**: Functions should perform one single logical step. Orchestrators call atomic helpers.
- **Linear Logic**: Avoid complex chained boolean operations (`and`, `or`, `not`) and complex regex backtracking.

### Logging vs. Console UI
- **Internal Modules (`src/generation/`, `src/ingestion/`, `src/utils.py`)**:
  - Always use standard Python logging:
    ```python
    import logging
    logger = logging.getLogger(__name__)
    ```
  - Never call `print()` or `logging.basicConfig()` inside library modules.
- **CLI Scripts (`generate_cv.py`, `kb_ingest.py`, etc.)**:
  - May configure root logging in `main()`.
  - May use descriptive, emoji-enhanced `print()` calls (🚀, ✅, ❌, 📦, 🧹, ✨) for human-facing CLI progress.

---

## 7. Definition of Done (Pre-Finalization Checklist)

Before concluding any feature, refactor, or bug fix, the agent **MUST** execute and verify:

1. **Unit Test Suite**:
   ```bash
   uv run pytest
   ```
   All tests must pass with 100% success.
2. **Static Type Verification**:
   ```bash
   uv run mypy
   ```
   Must produce zero type errors and zero untyped definitions.
3. **Linting & Code Cleanliness**:
   ```bash
   uv run ruff check src tests
   ```
   Must pass with zero lint errors or warnings.
4. **Complexity & Security Validation**:
   - Verify cognitive complexity remains < 15 per function.
   - Confirm all file I/O operations utilize `validate_path()`.
