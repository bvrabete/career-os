# Active Implementation Plan: Career OS & Agentic CV Generator

This document serves as the persistent record of the current implementation phases and design decisions for the CV Generator project.

## Current Goal

Finalize the "Master Source of Truth" and transition to an agentic generation pipeline using LangGraph.

---

## Phase 1: Knowledge Base Consolidation (The "Master" Source)

**Status**: COMPLETED

### Objectives

- Create one **Comprehensive Master Experience** document (`CVKnowledgeBase/Brad Vrabete Career Knowledge Base.md`) acting as the ultimate ground truth.
- Identify and merge scattered, unique details from over 20 years of history across multiple existing CV formats (`GeneratedCVs/`).
- Safely resolve semantic overlaps and duplications while aggressively preserving distinct metrics, technical stacks, and qualitative achievements.
- Capture personal narratives and framing from historical Cover Letters found in the source subfolders.
- Standardize all parsed achievements into the **STAR** (Situation, Task, Action, Result) format for programmatic consumption by downstream nodes.

### Granular Technical Implementation

#### Step 1.1: Raw Data Collection & Preprocessing

- **Bulk Source Material**: Recursively scan `GeneratedCVs/` (including all subfolders) to capture all historical CVs and Cover Letters.
- **Document Classification & Routing**:
  - **CVs**: Process via `docling` and route to `CVKnowledgeBase/extracted_raw/`.
  - **Cover Letters**: Identified by file/folder names (e.g., "Cover Letter", "Narrative"); processed and routed to `CVKnowledgeBase/my_voice/` to enrich the personal narrative database.
- **Pre-processing to Markdown**: Use `docling` to convert PDFs and DOCX files directly into Markdown structure, preserving headers and bullet points as structural hints for the LLM.
- **Ingestion Tracking System (The Audit Log)**: Maintain `CVKnowledgeBase/ingestion_status.json` to log every file, its classification (CV/Cover Letter), and processing state (`SUCCESS`/`FAILED`).
- **"My Voice" Inbox**: Maintain `CVKnowledgeBase/my_voice/` for both manual brain-dumps and automated cover letter extractions.

#### Step 1.2: Agentic Refinement & Normalization (RAG & STAR Conversion)

**Status**: COMPLETED

- **Continuous Refinery Loop**: Execute `kb_refinery.py` iteratively against both document extractions and "My Voice" inputs. The LLM acts as the core processor: digesting messy, unstructured brain-dumps and converting them strictly into actionable, metric-driven STAR bullets aligned with the correct canonical role in `CVKnowledgeBase/entries/`.
- **Repeatable Enhancement**: The knowledge base generation is not a one-time script. It is an ongoing cycle—whenever the user drops a new "My Voice" note about a past project, the agent re-runs, enhances the existing structured entry, and gracefully merges the new insights.
- **Track Assignment Initialization**: During refinement, append initial YAML tags indicating the hypothesized career track (e.g., Corporate vs. Entrepreneurial).

#### Step 1.3: Compiling the Master Extended CV

- **The Compiler**: Rather than treating the Extended CV as a static document we edit directly, `master_merger.py` acts as a build script. It reads the thousands of discrete, STAR-formatted fragments from the canonical KB and dynamically compiles them into a single continuous, readable sequence (`Brad Vrabete Extended CV.md`).
- **Discrepancy Tagging (`[RECONCILE]`)**: If two inputs (e.g., an old PDF vs. a recent "My Voice" note) provide conflicting metrics, the compiler flags it with the `[RECONCILE]` tag so the human user can manually audit the output.
- **Deduplication**: Remove exact duplicates sourced from concurrent extractions without losing context.

#### Step 1.4: Validation & Gap Analysis

- **Gap Finder**: Utilize `kb_gap_finder.py` on the resulting Master Document to pinpoint chronological gaps (e.g., missing months between roles) or roles lacking quantified results. Flag these inside `CVKnowledgeBase/Gaps.md` for human remediation.

- **Target Target**: [Brad Vrabete Extended CV.md](CVKnowledgeBase/Brad Vrabete Career Knowledge Base.md)

---

## Phase 2: Parallel Tracks & Overlapping Roles

**Status**: Pending

### Objectives

- Handle simultaneous career streams (e.g., Corporate role + Startup/Side project).
- Categorize experience into tracks: `Main Track`, `Entrepreneurial`, `Project/Contract`.

### Implementation

- **Metadata**: Add YAML or Markdown header tags to `entries/` files.
- **Filtering**: Allow the generator to "pivot" the CV based on the target persona (e.g., highlighting "Builder" accomplishments for startups).

---

## Phase 3: Agentic Generation Pipeline (LangGraph)

**Status**: Planning

### Node Architecture

1. **Node A (Analyzer)**: Deconstructs the Job Description and Company Persona.
2. **Node B (Retriever)**: Selects fragments from Parallel Tracks matching the target persona.
3. **Node C (Adapter)**: Adjusts tone and localized formatting styles (EU/IE/DE/NL).
4. **Node D (Drafter)**: Produces the final Markdown/DOCX draft.
5. **Node E (Auditor)**: Self-correcting loop for ATS compliance.

---

## Technical Decisions

- **LLMs**: OpenAI (GPT-4o), Ollama (Local Qwen 2.5, Llama 3)
- **Vector Stores**: ChromaDB, FAISS
- **Document Processing**: `docling`, `pypdf`, `python-docx`
- **Environment**: Python 3.12+, managed by `uv`
- **Credentials**: Managed via `.env` (OpenAI API Key, etc.)
- **Career Strategy**: Multi-threaded career management with explicit support for **Parallel Tracks** (Corporate, Entrepreneurial, Project-based).
