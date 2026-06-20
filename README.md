# CareerOS: Agentic CV Generator

CareerOS is an AI-powered engine designed to generate high-fidelity, ATS-optimized, and professionally tailored CVs. It uses an **Agentic LangGraph Pipeline** fueled by a **Structured Knowledge Graph** (Semantic Database) to synthesize career history into high-impact documents in seconds.

## The Core Value Proposition

1.  **Agentic Synthesis**: A multi-node pipeline that simulates a master executive writer and a brutally honest recruiter to tailor your experience to any job description.
2.  **Semantic Truth**: Every generated line is grounded in a canonical Knowledge Graph, ensuring 100% factual accuracy with zero hallucination.
3.  **Regional Intelligence**: Dynamic strategies that automatically adjust tone, section order, and formatting for target markets (e.g., EU, USA, UK).

## System Architecture

CareerOS is built on the principle that your career is a dataset, not a static document.

```mermaid
graph TD
    subgraph GENERATION ["Core: CV Generation (cv-gen)"]
        direction TB
        JD[Job Description]
        Analyzer[ANALYSIS\nAnalyzer\nExtract persona & region]
        Retriever[RETRIEVAL\nRetriever\nRank relevant roles]
        Drafter[DRAFTING\nDrafter\nTailor CV & Expand Acronyms]
        Refiner[REFINER\nRefiner\nCheck density & page count]
        Auditor[AUDIT\nAuditor\nBrutally honest recruiter]
        FinalCV[Final Tailored CV\nMarkdown + context.json]

        JD --> Analyzer --> Retriever --> Drafter --> Refiner --> Auditor
        Auditor -->|Feedback / Density Error| Drafter
        Auditor -->|PASS| FinalCV
    end

    subgraph WIKI ["Semantic Database: Knowledge Graph"]
        direction LR
        Experiences["wiki/experiences/\nCanonical roles"]
        Skills["wiki/skills/"]
        Education["wiki/education/"]
        Strategies["wiki/strategies/\nRegional rules"]
    end

    subgraph INGESTION ["Foundation: Wiki Ingestion (kb-ingest)"]
        direction TB
        Raw["Raw Sources\nPDF / DOCX / MD"]
        Parser[Parser\npypdf / docling]
        Classifier[Classifier\nOllama: Classify]
        Extractor[Extractor\nGPT-4o: Extract Verbatim]
        Resolver[Resolver\nPython: Map Aliases]
        Generator[Generator\nGPT-4o: Schema Entry]
        Merger[Merger\nGPT-4o: Enrich/Create]
        Validator[Validator\nPython: Schema Check]
        Writer[Writer\nPython]

        Raw --> Parser --> Classifier --> Extractor --> Resolver --> Generator --> Merger --> Validator --> Writer
    end

    Writer --> Experiences
    Experiences --> Retriever
    Skills --> Retriever
    Education --> Retriever
    Strategies --> Retriever
```

---

## Ingestion Pipeline Key Features

To maintain structural integrity and high ingestion speeds, `kb-ingest` employs:
*   **Dual PDF Parsing Strategy**: Digital PDFs are parsed using `pypdf`, preserving exact horizontal alignment of dates and text while reducing processing time by 100x. Scanned PDFs fallback dynamically to OCR via `docling`.
*   **Insensitive Entity Matching**: The mapping engine normalizes and slugifies both source organization names and aliases in `mappings.md` to avoid duplicate file creation due to formatting mismatches.
*   **Date-Bound Merging**: Unrelated roles at the same company (based on start date discrepancy) are correctly saved into separate time-bound files rather than being merged.
*   **Self-Healing YAML Validator**: Auto-cleans inline comments or annotations appended to YAML frontmatter fields by LLMs, ensuring strict parse compliance.

---

## 🚀 Quick Start

### 1. Installation
CareerOS uses `uv` for dependency management.

```bash
git clone https://github.com/bvrabete/career-os
cd career-os
uv sync
```

### 2. Configuration
Copy the example environment file and add your API keys.

```bash
cp .env.example .env
```
*Required: `OPENAI_API_KEY` for high-fidelity drafting. Local models (Ollama) can be used for supporting steps.*

### 3. Initialize Your Knowledge Graph
The `llm-wiki/` directory is your system's semantic database. Populate it by ingesting your existing CVs or certificates.

```bash
# Ingest career history from existing documents
uv run kb-ingest --dir llm-wiki/raw/sources/
```

### 4. Generate a Tailored CV
Point the generator at a Job Description text file and specify an output path.

```bash
uv run cv-gen --jd job-descriptions/target_jd.txt --out outputs/My_Tailored_CV.md
```

---

## 🧠 The Semantic Database (LLM-Wiki)

CareerOS treats your professional history as a queryable graph stored in `llm-wiki/`. This structure allows the LLM to understand the *relationships* between your skills, organizations, and specific achievements.

### Data Tiers
1.  **Experiences (`wiki/experiences/`)**: Structured records of professional roles (The Source of Truth).
2.  **Skills (`wiki/skills/`)**: Technical and soft skills mapped to specific career evidence.
3.  **Strategies (`wiki/strategies/`)**: Regional tailoring rules (e.g., Dutch directness vs. US brevity).

---

## 🛠️ Generator Node Roles

*   **Analyzer:** Deconstructs the JD to identify the target persona and region.
*   **Retriever:** Scans the Knowledge Graph, ranks relevant entries, and loads strategy rules.
*   *   **Drafter:** A high-fidelity executive writer that applies acronym expansion and aggressive quantification.
*   **Refiner:** Validates document density to ensure professional layout.
*   **Auditor:** Acts as a **Brutally Honest Senior Recruiter**, hunting for weak metrics or "fluff."

---

## 💡 Background & Motivation

CareerOS was created to solve the "Tailoring Paradox": the more experience you have (e.g., 20+ years), the harder it is to surgically compress that history into a high-impact, 2-page document for a specific role. By moving from static documents to a **Semantic Database**, we enable an AI agent to perform this synthesis with a level of precision and speed that is impossible for humans.
