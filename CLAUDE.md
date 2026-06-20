# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the **Career Operating System** — a Python/LangGraph pipeline that generates tailored, ATS-optimized CVs from a structured knowledge graph (the "LLM Wiki"). The wiki lives in `llm-wiki/wiki/` and serves as the canonical single source of truth for all professional history.

## Commands

All commands use `uv` as the package manager (Python 3.12+).

```bash
# Install dependencies
uv sync

# Generate a CV (primary workflow)
uv run cv-gen --jd job-descriptions/target_jd.txt --out ai-generated-cvs/Output_CV.md

# Alternatively, run the script directly from src/
cd src && uv run generate_cv.py --jd ../job-descriptions/target_jd.txt --out ../ai-generated-cvs/Output_CV.md
```

Running the pipeline also saves a `_context.json` sidecar file next to the CV output for debugging the graph state.

## Environment

Create a `.env` file in the project root with:
```
OPENAI_API_KEY=<your-key>
```

Ollama must be running locally at `http://localhost:11434` for local model steps. Default local model: `gemma4:26b`.

## Architecture

### Agentic Pipeline (`src/`)

The LangGraph pipeline runs four nodes in sequence, with the Auditor→Drafter loop repeating up to 2 times:

```
Job Description → Analyzer → Retriever → Drafter → Auditor → [re-draft or PASS] → CV Output
```

| File | Role |
|------|------|
| `src/generate_cv.py` | CLI entry point; reads JD file, invokes graph, writes output |
| `src/cv_generator_graph.py` | LangGraph state machine; all four node functions + routing logic |
| `src/kb_config.py` | Loads `config.yaml` and instantiates the correct LLM per pipeline step |

**Node responsibilities:**
- **Analyzer**: Extracts target persona/keywords from the JD; detects target region (ireland/netherlands/germany) via keyword matching
- **Retriever**: Scores and selects top-6 most relevant `wiki/experiences/` files by keyword overlap; also loads `wiki/education/`, `wiki/skills/`, and the region-specific `wiki/strategies/strategy-<region>.md`
- **Drafter**: Writes the final Markdown CV using the canonical facts from selected entries — must never hallucinate roles or dates
- **Auditor**: ATS compliance check; returns `"PASS"` or specific feedback to feed back into the Drafter

### Model Configuration (`config.yaml`)

Each pipeline step's LLM can be independently set to `ollama` or `openai`. Current defaults:
- `ANALYSIS`: `openai` / `gpt-4o`
- `RETRIEVAL`: `ollama` / `gemma4:26b`
- `DRAFTING`: `openai` / `gpt-4o` — **GPT-4o is critical here** due to its 128k context window; local models silently truncate large career histories
- `AUDIT`: `ollama` / `gemma4:26b`

### Knowledge Graph (`llm-wiki/wiki/`)

The wiki is the authoritative data source. All files must follow `llm-wiki/schema.md` — frontmatter type, naming conventions, and body structure are strictly enforced.

**Hierarchy of truth:**
1. `wiki/experiences/` — only canonical source for employment history; Tier 1
2. `wiki/cover-letters/` — use for tone/voice only, never as factual history
3. `llm-wiki/raw/` — raw input archive, for initial extraction only

**Key wiki directories the pipeline reads at runtime:**

| Directory | Content |
|-----------|---------|
| `wiki/experiences/` | One `.md` per role; STAR-formatted achievements under thematic H3 headers |
| `wiki/education/` | Academic degrees and certifications |
| `wiki/skills/` | Skills with proficiency and evidence links |
| `wiki/strategies/` | Regional contact info and tone directives (`strategy-ireland.md`, `strategy-netherlands.md`, `strategy-germany.md`) |
| `wiki/notes/` | "My Voice" reflections; Third-Party perspectives tagged `perspective: Third-Party` are auto-retrieved |
| `wiki/entities/` | Organizations and tools |
| `wiki/synthesis/` | Final generated CV variants (outputs) |

**Naming conventions** (from `schema.md`):
- Experiences: `company-role-slug.md`
- Strategies: `strategy-<region>.md`
- Skills: `skill-name.md`
- Notes: `note-slug.md`

### Outputs

- `ai-generated-cvs/` — tailored CV Markdown files
- `job-descriptions/` — input JD text files for the pipeline

## Code Standards

All Python code in `src/` must comply with the following:

### Style — PEP 8
- All imports at the top of the module, never inside functions or methods. Exception: unavoidable circular imports only.
- Import order: stdlib → third-party → local, each group separated by a blank line.
- Maximum line length: 120 characters.
- Two blank lines between top-level definitions; one blank line between methods.
- No trailing whitespace; files end with a single newline.

### Type checking — Pylance strict mode
- Every function must have full type annotations on parameters and return type.
- `response.content` from LangChain LLM calls returns `str | list[str | dict]` — always coerce to `str` before use:
  ```python
  raw = response.content
  content = raw if isinstance(raw, str) else " ".join(str(c) for c in raw)
  ```
- Avoid `Any` except where unavoidable; prefer `dict[str, ...]` over bare `dict`.
- Do not use mutable default arguments; use `None` with an explicit guard.

### Docstrings
- Every module must have a module-level docstring at the top (after imports) describing its purpose, inputs, and outputs.
- Every function must have a docstring. One-line docstrings are fine for simple helpers; multi-line for anything with non-obvious behaviour, side effects, or LLM calls.
- Format: plain text, no Sphinx/Google/NumPy style decorators required.

## Key Design Constraints

- The Retriever currently uses **keyword scoring** (not vector search) to pick the top 6 experiences — relevance depends on meaningful content in wiki experience files.
- The pipeline runs relative to `src/` for file path resolution of `llm-wiki/` — run `generate_cv.py` from the `src/` directory, or use the `cv-gen` script entry point from the project root.
- `wiki/log.md` should be updated after significant wiki changes.
- `wiki/index.md` lists all pages grouped by type.
- Contradictions between sources are tracked as `wiki/queries/query-*.md` files until resolved.
