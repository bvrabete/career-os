# Workspace Rules: Career Operating System (Wiki + Agent)

You are the curator and architect of the Career Operating System. This workspace combines a **Knowledge Graph (Wiki)**, managed via an **Ingestion Pipeline**, with an **Agentic Generation Pipeline (Python/LangGraph)** for creating tailored professional outputs.

## Core Mandates

1.  **The Wiki is Master**: The `<LLM_WIKI_DIR>/wiki/` directory is the canonical source of truth. Never generate a CV or answer a query based *only* on raw files if structured wiki data exists.
2.  **Hierarchy of Truth (Semantic Integrity)**:
    -   **Tier 1: Experiences (`wiki/experiences/`)**: Factual employment history. If it's not here, it's not a role you held.
    -   **Tier 2: Application Artifacts (`wiki/cover-letters/`)**: Archives of applications (cover letters). Use **strictly for tone and style**, never as factual history.
    -   **Tier 3: Raw Archive (`raw/` or external files)**: Used only for initial extraction and verification.
3.  **Schema Adherence**: Every file in `<LLM_WIKI_DIR>/wiki/` MUST strictly follow `<LLM_WIKI_DIR>/schema.md`.
4.  **Source Integrity**: Reference raw input sources in the `sources` field of wiki pages.
5.  **The "My Voice" Standard**: Prioritize capturing human reflections in `My Voice` sections and `wiki/notes/`.

## Setup & Commands

All commands use `uv` as the package manager (Python 3.12+).

```bash
# Install dependencies
uv sync

# Ingest new sources to external wiki (Experiences and cover letters must be in separate runs)
uv run kb-ingest --dir /path/to/raw/sources/ --wiki-dir /path/to/llm-wiki
uv run kb-ingest --dir /path/to/raw/cover-letters/ --wiki-dir /path/to/llm-wiki

# Generate a tailored CV pointing to external wiki
uv run cv-gen --jd job-descriptions/target_jd.txt --out ai-generated-cvs/Output_CV.md --wiki-dir /path/to/llm-wiki
```

### Environment
- `.env` file must contain `OPENAI_API_KEY`, `GEMINI_API_KEY` (if using Gemini), and optionally `LLM_WIKI_DIR` to specify a default external wiki path.
- Ollama must be running at `http://localhost:11434` for local model steps (default: `qwen2.5:7b` / `gemma2:27b`).

## System Architecture

```mermaid
graph TD
    subgraph INGESTION ["Pipeline 1: Wiki Ingestion (kb-ingest)"]
        Raw["Raw Files"] --> Parser[docling]
        Parser --> Classifier[Ollama: Classify]
        Classifier -->|experience| Extractor[Ollama: Extract Verbatim]
        Extractor --> Resolver[Python: Map Aliases]
        Resolver --> Generator[GPT-4o: Schema Entry]
        Generator --> Merger[Enrich/Create]
        Merger --> Validator[Python: Schema Check]
        Validator --> Writer[Writer]
    end

    subgraph WIKI ["LLM Wiki Knowledge Graph"]
        Writer --> Experiences["wiki/experiences/"]
        Writer --> Skills["wiki/skills/"]
        Writer --> Education["wiki/education/"]
    end

    subgraph GENERATION ["Pipeline 2: CV Generation (cv-gen)"]
        JD[Job Description] --> Analyzer[ANALYSIS: Persona/Region]
        Analyzer --> Retriever[RETRIEVAL: Keyword-Score Top 6]
        Retriever --> Drafter[DRAFTING: Tailored CV]
        Drafter --> Auditor[AUDIT: ATS Check]
        Auditor -->|Feedback| Drafter
        Auditor -->|PASS| FinalCV[Final CV + context.json]
    end

    Experiences --> Retriever
    Skills --> Retriever
    Education --> Retriever
```

## Model Configuration

Each pipeline step's LLM can be independently set in `config.yaml`.
- **ANALYSIS**: `openai` / `gpt-4o`
- **RETRIEVAL**: `ollama` / `gemma4:26b`
- **DRAFTING**: `openai` / `gpt-4o` — **GPT-4o is critical** here due to its 128k context window; local models truncate large career histories.
- **AUDIT**: `ollama` / `gemma4:26b`

## Directory Structure

- `<LLM_WIKI_DIR>/` (configured via `LLM_WIKI_DIR` env variable or `--wiki-dir` flag; default: `llm-wiki`): Central directory for Knowledge Graph.
    - `wiki/`: Structured graph (`experiences/`, `education/`, `skills/`, `strategies/`, `notes/`, `entities/`, `projects/`, `patents/`, `cover-letters/`).
    - `schema.md`: Strict blueprint for all entries.
    - `mappings.md`: Org alias → canonical slug registry.
    - `ingestion_status.json`: Ingestion state cache.
- `job-descriptions/`: Input JD text files.
- `ai-generated-cvs/`: Final tailored CV outputs.
- `src/`: Python source for pipelines.

## Code Standards (src/)

- **Style**: PEP 8, 120 char limit. Imports: stdlib → third-party → local.
- **Typing**: Pylance strict mode. Full annotations on all parameters and return types (comprehensive type checking). Use generic type aliases and standard collection types (e.g., `list[str]`, `dict[str, Any]`, `str | None`).
- **File Length & Structure Limits**:
  - No single Python source file should exceed **500 lines** to maintain readability and ease of maintenance.
  - Large modules or graphs (e.g., `kb_ingest_graph.py`) must be decomposed into dedicated package subdirectories (e.g., `src/ingestion/`) with separated files:
    - `state.py` (State definition & Pydantic schemas)
    - `prompts.py` (Prompt templates & externalized instructions)
    - `nodes.py` (Functional implementation of graph nodes)
    - `graph.py` (Orchestration & compiler)
- **LLM Prompt Externalization**: Keep long system prompts and user templates separated from Python logic. Load prompts from external `.txt`, `.md`, or `.yaml` files in `src/prompts/` at runtime where applicable.
- **Ruff Linting & Formatting**: Enforce strict linting and automatic code formatting with `Ruff`. Run Ruff before committing or testing to ensure maximum cleanliness.
- **Error Handling & Fallbacks**: Implement explicit, typed error catching for all external APIs and LLM calls. Always define reliable model fallbacks (e.g., failing over to local Ollama models on API timeouts) and raise custom descriptive exceptions.
- **LLM Handling**: Always coerce `response.content` to `str` before use.
- **Docstrings & Comments**: Required for every module, class, function, and method. Plain text format. Include descriptive inline comments for complex steps.
- **Design Principles**:
  - **DRY (Don't Repeat Yourself)**: Extract shared logic into modular helper functions or utility classes.
  - **Modularity**: Code must be well-structured, clean, and highly modular.
  - **Complexity**: Keep SonarQube cognitive/cyclomatic complexity STRICTLY below 15 per function/method. Large complex routines must be decomposed into smaller, single-responsibility functions.
  - **Deterministic Testing**: Write unit tests for core helpers and node functions. Mock external LLM and database operations using unit testing mocks or standard fixtures to guarantee fast, offline, and predictable tests.

## Legacy Note
The scripts `kb_ingest.py`, `kb_refinery.py`, and `master_merger.py` (in `src/`) are largely superseded by the new LLM-driven Wiki workflow. Use the `uv run kb-ingest` command for new ingestion.
