# Wiki Schema

This document defines the strict frontmatter schemas, naming conventions, and markdown body templates for the Career Operating System's Wiki. Downstream generative models and analysis scripts rely on these standards for deterministic parsing.

## Page Types

| Type | Directory | Purpose |
| ------ | ----------- | --------- |
| experience | `wiki/experiences/` | Structured records of professional roles (canonical outputs) |
| education | `wiki/education/` | Academic degrees, certifications, and formal training |
| entity | `wiki/entities/` | Organizations (companies, schools), people, or specific tools |
| project | `wiki/projects/` | Major initiatives or cross-role technical projects |
| skill | `wiki/skills/` | Technical and soft skills |
| language | `wiki/languages/` | Spoken language proficiencies and certifications |
| source | `wiki/sources/` | Metadata about raw input files (historical CVs, certificates) |
| synthesis | `wiki/synthesis/` | Generated CV variants, career summaries, and theme-based reports |
| concept | `wiki/concepts/` | Methodologies (Agile, Scrum) or domain-specific frameworks |
| note | `wiki/notes/` | Unfiltered personal reflections, "My Voice" snippets, and unsorted details |
| patent | `wiki/patents/` | Detailed records of patents and inventions |
| strategy | `wiki/strategies/` | Relocation profiles, contact strategy variants, and regional tailoring |
| query | `wiki/queries/` | Reconciliation of conflicting data points from old CVs |
| overview | `wiki/` | High-level project summary (one per project) |

## Naming Conventions

- Experiences: `company-role-slug.md` (e.g., `example-corp-senior-software-engineer.md`)
- Education: `institution-degree-slug.md` (e.g., `university-of-science-master-computer-science.md`)
- Entities (Organizations/Tools): `entity-name.md` (e.g., `example-corporation.md`, `aws.md`)
- Skills: `skill-name.md` (e.g., `python.md`)
- Languages: `lang-language-name.md` (e.g., `lang-english.md`)
- Notes: `note-slug.md` (e.g., `note-leadership-reflections.md`)
- Patents: `patent-id-slug.md` (e.g., `patent-us12345678-distributed-caching.md`)
- Strategies: `strategy-region-slug.md` (e.g., `strategy-ireland.md`)
- Projects: `project-name.md` (e.g., `project-cloud-migration.md`)
- Sources: `source-name.md` (e.g., `jane-doe-resume-2026.md`)
- Synthesis: `synthesis-variant-name.md` (e.g., `synthesis-cto-startup.md`)
- Queries: `query-topic-slug.md` (e.g., `query-dates-example-corp-2012.md`)

---

## Frontmatter

All files in the Wiki MUST contain valid YAML frontmatter at the very top.

### Experience Page

```yaml
---
type: experience
title: "Role Title at Company"
organization: [[entity-slug]]
location: "City, Country"
dates: 
  start: YYYY-MM-DD
  end: YYYY-MM-DD | Present
employment_type: Permanent | Contract  # Optional, defaults to Permanent
tracks: [Track-A, Track-B] # Functional specializations tailored to your industry (e.g. Management, Engineering, Sales, Medical, etc.)
skills: [skill-slug-1, skill-slug-2]
tags: [role-level, industry]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

### Education Page

```yaml
---
type: education
title: "Degree Name at Institution"
institution: [[entity-slug]]
dates: 
  start: YYYY-MM-DD
  end: YYYY-MM-DD
status: [Completed, In-Progress, Abandoned]
major: "Field of Study"
minor: "Secondary Field"
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

### Note Page

```yaml
---
type: note
title: "Descriptive Title"
related: [[[experience-slug]], [[skill-slug]]]
perspective: [Self, Third-Party]
tags: [reflection, leadership, engineering, recruiter-commentary, performance-review, thought-leadership, technical-strategy]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

### Patent Page

```yaml
---
type: patent
title: "Patent Title"
id: "Patent ID (e.g., US-12345678-B2)"
inventors: ["Jane Doe", "Co-Inventor"]
organization: [[entity-slug]]
link: "URL to patent"
skills: [skill-slug]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

### Strategy Page

```yaml
---
type: strategy
title: "Region Strategy"
region: [Ireland, Netherlands, Germany, USA]
focus: [Contact, Relocation, Tone]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

### Cover Letter Page

```yaml
---
type: cover-letter
title: "Cover Letter for [Role] at [Company]"
target_organization: [[entity-slug]]
related_synthesis: [[synthesis-slug]]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

### Skill Page

```yaml
---
type: skill
title: Skill Name
category: [Language-Code, Framework, Infrastructure, Leadership, Spoken-Language]
related_experiences: [[[experience-slug]]]
proficiency: [Expert, Proficient, Familiar, Native, Professional-Working]
---
```

### Entity Page

```yaml
---
type: entity
title: "Entity Name"
category: [organization, tool, university, technology]
tags: [telecommunications, cloud, compiler]
related: [[[experience-slug]]]
sources: [source-slug-1]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

### Project Page

```yaml
---
type: project
title: "Project Name"
organization: [[entity-slug]]
dates:
  start: YYYY-MM-DD
  end: YYYY-MM-DD
skills: [skill-slug]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

### Source Page

```yaml
---
type: source
title: "Canonical Source Filename"
file_type: [pdf, docx, md, email]
original_date: YYYY-MM-DD
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

### Synthesis Page

```yaml
---
type: synthesis
title: "CV Track Variant Name"
track: [Management, Architecture, Engineering, Entrepreneurial]
target_role: "Target Title"
related: [experience-slug-1, skill-slug-1]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

### Concept Page

```yaml
---
type: concept
title: "Concept Name"
category: [methodology, framework, architecture-pattern]
related: [experience-slug-1]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

### Query Page

```yaml
---
type: query
title: "Data Reconciliation Title"
status: [open, resolved]
related_experiences: [experience-slug-1]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

### Overview Page

```yaml
---
type: overview
title: "Wiki Overview"
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

---

## Page Content Structure

### Experience Template (`wiki/experiences/`)

Every experience file must follow this structural layout. Note that STAR achievements must be categorized under **Thematic Topics** using H3 sub-headers.

```markdown
# [Role Title] at [Organization]

## Context
[Company Name] ([Location]) is a [Industry/Domain] company focusing on [Scale/Business].
[1-2 paragraphs detailing the company's business domain, scale, direct reports, budget managed, and overall engineering challenge.]

## Narrative & Reflections
[Your subjective view of the role: personal reflections, authentic thoughts, the real human challenges, leadership philosophy in action, critical strategic pivots, and context that STAR bullet points alone cannot capture.]

## Achievements

### [Theme 1: e.g., Engineering Leadership & Team Management]
- **Situation**: [The context or problem being solved]
  - **Task**: [What you were responsible for achieving]
  - **Action**: [The exact engineering/leadership steps you took verbatim]
  - **Result**: [Metric-backed business or technical outcome]

### [Theme 2: e.g., Technical Strategy & System Architecture]
- **Situation**: ...

### [Theme 3: e.g., Cloud, DevOps & DevSecOps]
- **Situation**: ...

### [Theme 4: e.g., Software Engineering & Development]
- **Situation**: ...
```

### Education Template (`wiki/education/`)

```markdown
# [Degree Name] at [Institution]

## Description
[Summary of the degree/program structure.]

## Key Courses & Projects
- **[Topic]**: [Core learnings, thesis work, or academic achievements]

## My Voice
[Personal reflection on academic growth and key lessons.]
```

### Skill Template (`wiki/skills/`)

```markdown
# [Skill Name]

## Description
[1 paragraph defining the technical or leadership skill and its core sub-domains.]

## Evidence & Accomplishments
[Links to specific STAR achievements where this skill was utilized and proven in action, e.g., "Demonstrated in [[example-corp-senior-software-engineer]] through the automation of multi-cloud deployment."]
```

### Patent Template (`wiki/patents/`)

```markdown
# [Patent Title]

## Abstract
[Summary of the technical invention.]

## Technical Mechanism
[Deep-dive details of how the hardware/software architecture operates.]

## Related Work & Value
[Business impact of the patent, links to [[experiences]] where it was conceived.]
```

### Project Template (`wiki/projects/`)

```markdown
# [Project Name]

## Overview
[Executive summary of the project scope and deliverables.]

## Tech Stack & Architecture
- **[Layer]**: [[entity-slug]] (e.g. AWS, React, etc.)

## Contribution & Outcomes
[Metric-backed achievements or STAR bullets representing your contributions.]
```

### Strategy Template (`wiki/strategies/`)

```markdown
# [Region] Strategy

## Contact Information
- **Phone**: [Localized phone number]
- **Address**: [Localized address]
- **Target Areas**: [Specific cities/hubs]

## Relocation Message
"[Standardised, professional copy to inject into CV regarding relocation/availability.]"

## Tone Preferences
- **Tone**: [e.g., Direct and results-oriented (NL) vs. Formal and detailed (DE)]
- **Directives**: [How the LLM should adapt its writing style.]
```

### Entity Template (`wiki/entities/`)

```markdown
# [Entity Name]

## Overview
[Summary of what the company, tool, or technology represents, its core domain, and market presence.]

## Key Contributions / Core Value
[For companies, summarize the candidate's key impact. For tools, outline the candidate's proficiency and typical use cases.]
```

### Source Template (`wiki/sources/`)

```markdown
# Source: [Source Title]

## Metadata
- **File Name:** `filename`
- **Origin Date:** `YYYY-MM-DD`
- **Relevance:** [e.g., Extended CV, LinkedIn profile, Performance Review]

## Extracted Text / Content
[Verbatim or structured summary of the raw text contents.]
```

### Synthesis Template (`wiki/synthesis/`)

```markdown
# Synthesis: [CV Variant Name]

## Profile Statement
[Targeted summary of qualifications for this track.]

## Core Career Tracks Mapped
- [[experience-slug-1]] (Targeting the Leadership element)
- [[experience-slug-2]] (Targeting the Architecture element)

## Skill Focus Map
- [[skill-slug-1]]: Highly prominent
```

### Concept Template (`wiki/concepts/`)

```markdown
# [Concept Name]

## Overview
[Defining description of the architectural pattern, development methodology, or conceptual domain.]

## Core Importance
[How this concept shapes the candidate's technical philosophy and links to experience nodes.]
```

### Note Template (`wiki/notes/`)

```markdown
# Note: [Title]

## Context & Thoughts
[Unstructured, raw thoughts, technical discoveries, meeting summaries, or personal goals.]
```

### Cover Letter Template (`wiki/cover-letters/`)

```markdown
# Cover Letter: [Role] at [Company]

## Salutation
Dear [Hiring Manager / Recruiter],

## Role & Organization Fit
[Highly personalized paragraph articulating excitement for this specific company and domain.]

## Career Highlights Map
- **Core Narrative:** [Narrative paragraph showing alignment with target JD.]

## Professional Closing
Sincerely,
Jane Doe
```

### Query Template (`wiki/queries/`)

```markdown
# Query: [Contradiction Topic]

## Description of Contradiction
[Explain the discrepancy, e.g., 'Resume-A lists Example-Corp start date as March 2012, whereas Resume-B lists it as July 2012.']

## Investigative Action
- [ ] Check raw contract / email offer
- [ ] Resolve in canonical experiences

## Resolution
[Once resolved, document the final confirmed facts here.]
```

### Overview Template (`wiki/`)

```markdown
# Wiki Overview

## Introduction
[High-level summary of the Career Single Source of Truth project.]

## Core Tracks Covered
- **[Track-A]:** [Dynamic Summary of specialization A]
- **[Track-B]:** [Dynamic Summary of specialization B]
```

---

## Index Format

`wiki/index.md` lists all pages grouped by type. Each entry:

```
- [[page-slug]] — one-line description
```

## Log Format

`wiki/log.md` records activity in reverse chronological order:

```
## YYYY-MM-DD

- Action taken / finding noted
```

## Cross-referencing Rules

- Use `[[page-slug]]` syntax to link between wiki pages.
- Every achievement should ideally link to the `[[skill-slug]]` it demonstrates.
- Every experience must link to an `[[entity-slug]]` representing the organization.
- Synthesis pages cite all contributing sources via `related:`.

## Contradiction Handling

- When sources contradict each other:
  1. Note the contradiction in the relevant `experience` or `entity` page.
  2. Create or update a `query` page to track the open question.
  3. Resolve in the canonical `experience` page once reconciled.
