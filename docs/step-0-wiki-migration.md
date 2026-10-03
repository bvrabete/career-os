# Step 0: LLM-Wiki Reorganization & Migration Guide

This document defines the pre-requisite migration protocol ("Step 0") to audit, reorganize, and upgrade the existing candidate knowledge base located at:
`C:\Users\bvrabete\source\personal\cv-repo\llm-wiki-brad`
into the new CareerOS canonical Knowledge Base format.

---

## 1. Core Principles: Contiguous Tenures & Boomerang Stints

### The Contiguous Tenure Principle
> [!IMPORTANT]
> **A Company Tenure represents a contiguous, unbroken period of employment at an organization.**
> Progressive roles, promotions, and lateral moves within the **same unbroken timeline** belong in that single tenure container.

### The Boomerang Stint Rule (External Employment Gaps)
When a candidate leaves an organization to work elsewhere and later returns (a "boomerang" employee):
* **Each contiguous period MUST remain a separate tenure record.**
* **Never merge non-contiguous stints across external employment gaps.** Merging non-contiguous stints into a single file would create a false impression of continuous employment, distort recency calculations, and corrupt the chronological sequence of intermediate roles on generated CVs.

#### Applied Example: Brad's Career at Intel
In `wiki/experiences/`, Intel is represented by two separate files:
1. `intel-platform-architect-and-tech-lead.md` (Dates: **2007-09-01 to 2017-07-01** — 10-year contiguous tenure covering consecutive engineering, architecture, and leadership roles).
2. `intel-software-engineering-manager.md` (Dates: **2021-11-01 to 2023-09-01** — 2-year contiguous tenure after returning to Intel following external leadership roles).

**Decision**: **Leave these two Intel files separated.** They are distinct, contiguous tenures separated by a 4-year external employment gap. Both files should simply be formatted to adhere to the schema, with child roles clearly structured within each respective period.

### The Concurrent Roles & Side Ventures Rule
When a candidate holds a concurrent co-founder, advisory, or startup role (e.g. `allwayswithyou-cto.md`) parallel to primary corporate employment:
* **Tag Frontmatter Clearly**:
  ```yaml
  employment_nature: side_venture # or "primary", "advisory"
  employment_type: co_founder     # or "full_time", "part_time", "contract"
  ```
* **Preserve Full Technical Depth in Wiki**: Keep all hands-on technical architecture (LangGraph multi-agent systems, FastAPI, Kubernetes) and executive delivery in the wiki record.
* **Downstream Flexibility**: This metadata allows the CV generator to dynamically feature, reframe (as Technical Advisor), or place into a dedicated "Ventures & Advisory" section based on target JD culture and regional strategy.

---

## 2. How Git Handles File Renames & The "Dumb Detection" Trap

### How Git Actually Tracks Renames
Unlike legacy systems (Subversion, Perforce), **Git does NOT record "renames" in its commit database**.
- A commit in Git is purely a snapshot of a directory tree mapping paths to SHA-1/SHA-256 blob hashes.
- `git mv old_path new_path` does not store a special "rename" metadata entry; it simply performs `mv old_path new_path` and stages both the deletion of `old_path` and the addition of `new_path` in the index.
- Git detects renames **dynamically at inspection time** (`git log`, `git diff`, `git status`) using a content similarity heuristic:
  $$\text{Similarity Index} = \frac{\text{Unchanged Bytes}}{\text{Total Bytes}}$$
- The default similarity threshold is **50%**.

### The Danger: Rename + Heavy Rewrite in One Commit
If you move a file from `wiki/notes/CoverLetterING.md` to `wiki/cover-letters/ing.md` AND in the exact same commit you rewrite its frontmatter, reformat the markdown, and change more than 50% of the text:
> [!WARNING]
> Git's similarity detector will drop below 50%. Git will consider the operation as:
> `deleted file: wiki/notes/CoverLetterING.md`
> `new file: wiki/cover-letters/ing.md`
> As a result, standard `git log wiki/cover-letters/ing.md` will treat it as a brand-new file with zero previous history!

### The Safe Two-Commit Migration Protocol
To guarantee that Git preserves 100% of your revision history across renames:

```
[EXISTING REPO]
       │
       ▼  Step 1: PURE MOVE (git mv, NO content edits)
[STAGED: rename similarity index 100%]
       │
       ▼  Commit 1: "chore(wiki): reorganize file structure to canonical folders"
[COMMITTED RENAMES]
       │
       ▼  Step 2: TRANSFORMATION (Schema updates, frontmatter fixes)
[STAGED: content modifications on existing paths]
       │
       ▼  Commit 2: "feat(wiki): standardize frontmatter and schemas"
[CLEAN REVISION HISTORY PRESERVED]
```

---

## 3. Audit of Existing `llm-wiki-brad`

An inspection of `C:\Users\bvrabete\source\personal\cv-repo\llm-wiki-brad` reveals several organizational clean-up targets:

### A. Misplaced Files in `wiki/notes/`
The `wiki/notes/` folder currently contains a mix of three completely different document types:
1. **Historical Cover Letters** (belong in `wiki/cover-letters/`):
   - `CoverLetterDoIT.md` $\rightarrow$ `wiki/cover-letters/do-it.md`
   - `CoverLetterFirstData.md` $\rightarrow$ `wiki/cover-letters/first-data.md`
   - `CoverLetterING.md` $\rightarrow$ `wiki/cover-letters/ing.md`
   - `CoverLetterTrustonic.md` $\rightarrow$ `wiki/cover-letters/trustonic.md`
   - `CoverLetterTemplate.md` $\rightarrow$ `wiki/cover-letters/template.md`
2. **Full Raw Resumes** (belong in `raw/` or archived synthesis):
   - `CV.BradVrabete.doc.md`
   - `Resume-Brad-Vrabete-TOPIC-Embedded-Systems.md`
   - `resume-brad-vrabete.md`
3. **Deep-Dive Technical Case Studies & Architecture Notes** (belong in `wiki/case-studies/`):
   - ~40 detailed architectural problem/solution notes (e.g. `note-key-performance-benefits-of-decoupling...`, `note-kubernetes-migration...`, `note-virgin-media...`).
   - Move to `wiki/case-studies/` linked via `related: [[virgin-media]]`. Prune pure scraper noise (e.g. `note-virgin-media-ireland-platform-modernization-feedback.md` controller catalogs).
4. **Candidate Voice Manifesto** (belong in `wiki/voice/my-voice.md`):
   - Create a central `wiki/voice/my-voice.md` defining your genuine phrasing principles, banned AI buzzwords, and reference writing exemplars. Technical code snippets are permanently decoupled from this folder.

### B. Synthesis Bloat in `wiki/synthesis/`
- Contains 19 generated CVs from previous runs.
- `synthesis-cv-alibaba-cloud-senior_full_stack_engineer-2026-07-27.md` is **97 KB** (contains raw debug prompt logs).
- Needs pruning or indexing into the new structured `applications.yaml` registry.

---

## 4. Step-by-Step Reorganization Execution Plan

### Step 0.1: Prepare Git Branch in cv-repo
Navigate to the repository and create an isolated migration branch:
```bash
cd "C:\Users\bvrabete\source\personal\cv-repo\llm-wiki-brad"
git checkout -b chore/reorganize-llm-wiki
```

### Step 0.2: Pure File Renames & Relocations (Commit 1)
Execute pure `git mv` commands without touching file contents:

```powershell
# 1. Ensure target folders exist
mkdir -p wiki/cover-letters
mkdir -p raw/resumes-legacy
mkdir -p wiki/case-studies
mkdir -p wiki/voice

# 2. Relocate Misplaced Cover Letters
git mv "wiki/notes/CoverLetterDoIT.md" "wiki/cover-letters/do-it.md"
git mv "wiki/notes/CoverLetterFirstData.md" "wiki/cover-letters/first-data.md"
git mv "wiki/notes/CoverLetterING.md" "wiki/cover-letters/ing.md"
git mv "wiki/notes/CoverLetterTrustonic.md" "wiki/cover-letters/trustonic.md"
git mv "wiki/notes/CoverLetterTemplate.md" "wiki/cover-letters/template.md"

# 3. Move Full Resumes to raw/ archive
git mv "wiki/notes/CV.BradVrabete.doc.md" "raw/resumes-legacy/cv-brad-vrabete.md"
git mv "wiki/notes/Resume-Brad-Vrabete-TOPIC-Embedded-Systems.md" "raw/resumes-legacy/resume-embedded-systems.md"
git mv "wiki/notes/resume-brad-vrabete.md" "raw/resumes-legacy/resume-general.md"

# 4. Commit pure renames
git commit -m "chore(wiki): relocate cover letters and legacy resumes to proper folders"
```
*(At this stage, `git log -M --stat` will confirm 100% rename similarity for all files).*

---

### Step 0.3: Frontmatter Schema Standardization (Commit 2)
Standardize frontmatter across all experience files, ensuring both Intel tenures preserve their independent dates:
1. **`intel-platform-architect-and-tech-lead.md`**: Stint 1 (2007-09-01 to 2017-07-01).
2. **`intel-software-engineering-manager.md`**: Stint 2 (2021-11-01 to 2023-09-01).
3. Ensure all dates use strict ISO format (`YYYY-MM-DD` or `Present`).
4. Ensure organization links use `[[intel-corporation]]`.
5. Link Patents to Employer: In `wiki/patents/*.md`, ensure each patent explicitly links `organization: [[intel-corporation]]` and `tenure: [[intel-platform-architect-and-tech-lead]]`, and reference their IDs in the Intel experience file frontmatter (`patents: ["US-10912283-B2", ...]`).

```bash
git add wiki/experiences/ wiki/patents/
git commit -m "feat(wiki): standardize schema, preserve contiguous tenures, and link patents"
```

---

### Step 0.4: Bootstrap Applications Tracking Registry
Extract past application records from `wiki/synthesis/` into the new `wiki/applications.yaml` file:

```yaml
# wiki/applications.yaml
applications:
  - id: "2026-07-27-alibaba-cloud-senior-full-stack"
    company: "Alibaba Cloud"
    role: "Senior Full Stack Engineer"
    date: "2026-07-27"
    strategy: "emea"
    cv_file: "wiki/synthesis/synthesis-cv-alibaba-cloud-senior_full_stack_engineer-2026-07-27.md"
    status: "Applied"
  - id: "2026-07-25-jumbo-tech-lead-staff-engineer"
    company: "Jumbo"
    role: "Tech Lead / Staff Engineer"
    date: "2026-07-25"
    strategy: "nl_modern"
    cv_file: "wiki/synthesis/synthesis-cv-jumbo-tech_lead___staff_engineer-2026-07-25.md"
    status: "Applied"
```

Commit and merge `chore/reorganize-llm-wiki` back to your main branch. Your Knowledge Base is now 100% prepared!
