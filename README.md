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
    subgraph BOOTSTRAP ["Bootstrapping"]
        B_Helper["_bootstrap_wiki_structure<br>(Schema, Mappings, CSS Templates)"]
    end

    subgraph INGESTION ["Foundation: Wiki Ingestion (kb-ingest)"]
        direction TB
        Raw["Raw Sources<br>(PDF / DOCX / MD)"] --> Parser["Parser<br>(pypdf / docling)"]
        Parser --> Classifier["Classifier<br>(Ollama: Classify)"]
        
        subgraph POLYMORPHIC ["Polymorphic Extraction Branching"]
            direction LR
            Ext_Exp["Experience<br>(Roles, Edu, Projects, Patents)"]
            Ext_CL["Cover Letter<br>(Target Org, Highlights, Body)"]
            Ext_Supp["Supplemental<br>(Performance Review Note)"]
        end
        
        Classifier -->|experience| Ext_Exp
        Classifier -->|cover_letter| Ext_CL
        Classifier -->|supplemental| Ext_Supp
        
        Resolver["Resolver<br>(Python: Map Aliases)"]
        Ext_Exp --> Resolver
        Ext_CL --> Resolver
        Ext_Supp --> Resolver
        
        Resolver --> Generator["Generator<br>(LLM: Schema Entry)"]
        Generator --> Merger["Merger<br>(LLM: Enrich/Create)"]
        Merger --> Validator["Validator<br>(Python: Schema/YAML Check)"]
        Validator --> Writer["Writer<br>(Python)"]
    end

    BOOTSTRAP -->|Init Directories| WIKI

    subgraph WIKI ["Semantic Database: Knowledge Graph (LLM-Wiki)"]
        direction LR
        Experiences["wiki/experiences/"]
        Skills["wiki/skills/"]
        Education["wiki/education/"]
        Projects["wiki/projects/"]
        Patents["wiki/patents/"]
        Notes["wiki/notes/<br>(Performance Reviews)"]
        CoverLetters["wiki/cover-letters/"]
        Strategies["wiki/strategies/"]
        Synthesis["wiki/synthesis/<br>(CRM Applied CV Archive)"]
    end

    Writer --> WIKI

    subgraph GENERATION ["Core: CV Generation (cv-gen)"]
        direction TB
        JD["Job Description"] --> Analyzer["ANALYSIS<br>(Extract persona, org, role, region)"]
        Analyzer --> Retriever["RETRIEVAL<br>(Rank experiences, projects, patents, notes,<br>retrieve few-shots, and build skill-bridge map)"]
        
        Retriever --> Drafter["DRAFTING<br>(Tailor CV, resolve skill-bridge, inject My Voice, mirror few-shots)"]
        Drafter --> Refiner["REFINER<br>(Validate density & page count limit)"]
        Refiner --> Auditor["AUDIT<br>(Brutally honest recruiter check)"]
        
        Auditor -->|Feedback / Density Error| Drafter
        
        FinalCV["Final Tailored CV<br>(Markdown + context.json)"]
        Auditor -->|PASS| FinalCV
        
        PDF["PDF Compilation<br>(WeasyPrint via final CSS template)"]
        FinalCV -->|--generate-pdf| PDF
    end

    WIKI -->|Read Profile Data| Retriever
    FinalCV -->|Automatic CRM Archiving| Synthesis
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

### 3. Initialize & Bootstrap Your Knowledge Graph
The Knowledge Graph (LLM-Wiki) is fully externalized. You can host it in any directory on your machine by setting the `LLM_WIKI_DIR` env variable or passing the `--wiki-dir` parameter. 

When you run ingestion against an empty or missing directory, CareerOS automatically **bootstraps** the whole structure for you:
- Creates all 14 standard wiki folders (`experiences`, `education`, `projects`, `skills`, `patents`, `notes`, etc.).
- Seeds a clean, candidate-anonymous `schema.md` blueprint.
- Seeds a clean `mappings.md` template for entity resolving and organization aliases.
- Pre-seeds a customization folder at `<LLM_WIKI_DIR>/templates/` with your default CSS stylesheets.

```bash
# Ingest career history from raw files to your external wiki
uv run kb-ingest --dir /path/to/raw/sources/ --wiki-dir /path/to/my-external-wiki
```

### 4. Generate a Tailored CV
Point the generator at a Job Description text file, specify your external wiki, and output the customized markdown CV (with optional PDF generation).

```bash
uv run cv-gen --jd job-descriptions/target_jd.txt --out outputs/My_Tailored_CV.md --wiki-dir /path/to/my-external-wiki --strategy ireland --generate-pdf
```

### 5. Advanced CLI Strategy & PDF Compilation
The generation pipeline supports direct override of region strategy selection and automatic production-ready PDF compilation:
*   `--strategy <slug>`: Force-bypasses the analyzer LLM's target region inference and enforces the specified regional strategy (e.g. `ireland`, `emea`, `nl_modern`).
*   `--generate-pdf`: Compiles a beautifully styled PDF directly from the final tailored markdown using the regional strategy's designated CSS stylesheet via WeasyPrint.


---

## 🧪 Testing & Continuous Integration (CI)

CareerOS includes a comprehensive test suite to ensure the stability and correctness of the ingestion, retrieval, scoring, and drafting nodes.

### Running Tests Locally

You can run the unit test suite locally using `uv`:

```bash
uv run python tests/test_pipeline.py
```

### GitHub Actions CI Pipeline

A GitHub Actions CI workflow is configured in `.github/workflows/test.yml`. It runs automatically on every `push` and `pull_request` to the `main` or `master` branches, performing the following steps:
1. Checks out the repository.
2. Installs `uv` using the official `astral-sh/setup-uv` action with dependency caching enabled.
3. Sets up a Python 3.12 environment.
4. Syncs project dependencies.
5. Runs the unit test suite to verify pipeline nodes, regex word boundary matching, few-shot retrieval, and skill-bridging logic.

### 🚫 Preventing PR Merges on Test Failure

To enforce high quality standards and prevent merging buggy code or unverified changes, configure branch protection rules in GitHub:
1. Go to your repository on GitHub.
2. Navigate to **Settings** -> **Branches**.
3. Under **Branch protection rules**, click **Add branch protection rule** (or edit your existing rule for `main`/`master`).
4. Set the **Branch name pattern** to `main` (or your default branch name).
5. Check **Require status checks to pass before merging**.
6. In the search box, search for **Run Unit Tests** and check it as a required status check.
7. Click **Create** or **Save changes** at the bottom of the page.

Now, GitHub will block any Pull Request from merging unless all unit tests pass successfully.

---

## 🧠 The Semantic Database (LLM-Wiki Graph)

CareerOS treats your professional history as a queryable graph. By defining the `LLM_WIKI_DIR` environment variable, your database is decoupled from this engine, allowing you to run it against multiple independent career graphs safely.

### Structured Graph Layout (under `<LLM_WIKI_DIR>/wiki/`)
1. **Experiences (`wiki/experiences/`)**: Canonical, structured records of professional roles (The Source of Truth).
2. **Projects & Patents (`wiki/projects/`, `wiki/patents/`)**: Standalone, reusable technical accomplishments, cross-linked back to experiences via frontmatter (e.g., `organization: [[intel-corporation]]`).
3. **Skills & Languages (`wiki/skills/`)**: Deep capabilities and languages, referencing specific experience nodes where they were demonstrated.
4. **Strategies (`wiki/strategies/`)**: Regional tailoring profiles containing localized bio copy, relocation rules, and style guidelines (e.g., Dutch directness vs. US brevity).
5. **Notes (`wiki/notes/`)**: Peer praise, performance reviews (`tags: ["performance-review"]`), and subjective reflections which are dynamically injected to enrich descriptions and enforce the **"My Voice" Standard**.
6. **Cover Letters (`wiki/cover-letters/`)**: Historical applications archived for style and tone consistency.

---

## 🎨 PDF & Stylesheet Customization

Decoupling the styles from the engine allows you to fully customize CV formatting for different industries or aesthetics.

### How Stylesheets are Bootstrapped
During directory initialization, standard CSS styles (`base.css`, `emea_tech.css`, `nl_modern.css`) are automatically copied into `<LLM_WIKI_DIR>/templates/`. 

- Because `<LLM_WIKI_DIR>/templates/` resides one level up from `wiki/`, it is completely ignored by the `kb-ingest` pipeline.
- You can freely edit, rename, or add new `.css` files directly in `<LLM_WIKI_DIR>/templates/`.

### Linking Styles to Regional Strategies
To apply a stylesheet to a regional profile, add the `pdf_template` attribute in the YAML frontmatter of your **Strategy Page** (e.g., `wiki/strategies/strategy-emea.md`):

```yaml
---
type: strategy
title: "EMEA Strategy"
region: [Ireland, Netherlands, Germany, USA]
pdf_template: "emea_tech.css"  # resolved directly to <LLM_WIKI_DIR>/templates/emea_tech.css
---
```

When you compile a CV with PDF generation enabled (`--generate-pdf`), the engine will automatically resolve the style name, searching:
1. Directly under `<LLM_WIKI_DIR>/`
2. Under your external `<LLM_WIKI_DIR>/templates/` (ideal for user customizations)
3. Under the engine repository's fallback `templates/` folder (standard templates)

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
