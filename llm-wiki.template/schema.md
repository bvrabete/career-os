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
| synthesis | `applications/` | Generated CV variants, parsed JDs, and application dossiers |
| concept | `wiki/concepts/` | Methodologies (Agile, Scrum) or domain-specific frameworks |
| note | `wiki/notes/` | Unfiltered personal reflections, "My Voice" snippets, and unsorted details |
| patent | `wiki/patents/` | Detailed records of patents and inventions |
| publication | `wiki/publications/` | Peer-reviewed articles, conference papers, whitepapers, and book chapters |
| strategy | `wiki/strategies/locations/` | Relocation profiles, contact strategy variants, and regional tailoring |
| strategy-track | `wiki/strategies/tracks/` | Career domain archetypes, seniority scopes, and org culture alignment |
| query | `wiki/queries/` | Reconciliation of conflicting data points from old CVs |
| case_study | `wiki/case-studies/` | In-depth technical architecture whitepapers, system designs, and platform migration reports |
| profile | `wiki/profile.md` | Canonical candidate profile, contact links, baseline summary & domains |
| overview | `wiki/` | High-level project summary (one per project) |

## Naming Conventions

- Experiences: `company-role-slug.md` (e.g., `example-corp-senior-software-engineer.md`)
- Education: `institution-degree-slug.md` (e.g., `university-of-science-master-computer-science.md`)
- Entities (Organizations/Tools): `entity-name.md` (e.g., `example-corporation.md`, `aws.md`)
- Skills: `skill-name.md` (e.g., `python.md`)
- Languages: `lang-language-name.md` (e.g., `lang-english.md`)
- Notes: `note-slug.md` (e.g., `note-leadership-reflections.md`)
- Case Studies: `company-topic-slug.md` (e.g., `example-corp-gitops-architecture-overview.md`)
- Patents: `patent-id-slug.md` (e.g., `patent-us12345678-distributed-caching.md`)
- Publications: `pub-slug.md` (e.g., `pub-distributed-edge-telemetry.md`)
- Strategies: `region-slug.md` (e.g., `ireland.md`)
- Strategy Tracks: `track-slug.md` (e.g., `engineering-management.md`, `startup-founding-engineer.md`)
- Projects: `project-name.md` (e.g., `project-cloud-migration.md`)
- Sources: `source-name.md` (e.g., `jane-doe-resume-2026.md`)
- Applications: `applications/{YYYY-MM-DD}-{company}-{role}/`
- Queries: `query-topic-slug.md` (e.g., `query-dates-example-corp-2012.md`)

---

## Frontmatter

All files in the Wiki MUST contain valid YAML frontmatter at the very top. All wikilinks in YAML frontmatter MUST be wrapped in double quotes (e.g., `"[[entity-slug]]"`) for strict YAML 1.2 and Obsidian Properties compatibility.

### Experience Page

```yaml
---
type: experience
title: "Role Title at Company"
organization: "[[entity-slug]]"
location: "City, Country"
dates:
  start: "2021-01-01"
  end: "Present"
employment_type: Permanent
tracks: ["Management", "Architecture"]
skills: ["python", "kubernetes"]
tags: ["senior", "cloud"]
case_studies: ["[[example-corp-gitops-architecture-overview]]"]
projects: ["[[project-cloud-migration]]"]
patents: []
notes: []
scope:
  team_size: "24 engineers across 3 squads"
  budget: "$4.5M OpEx"
  reports_to: "VP of Engineering"
  company_context: "Enterprise cloud platform provider"
sources: ["jane-doe-resume-2026.pdf"]
created: "2026-01-01"
updated: "2026-01-01"
---
```

### Education Page

```yaml
---
type: education
title: "Degree Name at Institution"
institution: "[[entity-slug]]"
dates:
  start: "2010-09-01"
  end: "2014-06-01"
status: "Completed"
major: "Field of Study"
minor: "Secondary Field"
sources: ["jane-doe-resume-2026.pdf"]
created: "2026-01-01"
updated: "2026-01-01"
---
```

### Note Page

```yaml
---
type: note
title: "Descriptive Title"
related: ["[[experience-slug]]", "[[skill-slug]]"]
perspective: "Third-Party"
tags: ["reflection", "leadership", "engineering", "performance-review"]
sources: ["performance-review-2025.pdf"]
created: "2026-01-01"
updated: "2026-01-01"
---
```

### Case Study Page

```yaml
---
type: case_study
title: "Technical Whitepaper, System Design, or Architecture Title"
organization: "[[entity-slug]]"
related_experience: "[[experience-slug]]"
dates:
  start: "2022-01-01"
  end: "2023-06-01"
skills: ["kubernetes", "kafka"]
tags: ["architecture", "distributed-systems", "microservices", "performance", "migration"]
sources: ["architecture-whitepaper.md"]
created: "2026-01-01"
updated: "2026-01-01"
---
```

### Patent Page

```yaml
---
type: patent
title: "Patent Title"
id: "US-12345678-B2"
inventors: ["Jane Doe", "Co-Inventor"]
organization: "[[entity-slug]]"
related_experience: "[[experience-slug]]"
grant_date: "2021-02-01"
link: "https://patents.google.com/patent/US12345678B2"
skills: ["distributed-systems", "iot"]
sources: ["patent-filing.pdf"]
created: "2026-01-01"
updated: "2026-01-01"
---
```

### Publication Page

```yaml
---
type: publication
title: "Publication Title"
doi: "10.1109/EXAMPLE.2024.001"
publication_type: "conference_paper"
venue: "IEEE International Conference"
date: "2024-05-15"
authors: ["Jane Doe", "Co-Author"]
is_first_author: true
peer_reviewed: true
organization: "[[entity-slug]]"
related_experience: "[[experience-slug]]"
link: "https://doi.org/10.1109/EXAMPLE.2024.001"
skills: ["distributed-systems"]
sources: ["ieee-paper.pdf"]
created: "2026-01-01"
updated: "2026-01-01"
---
```

### Project Page

```yaml
---
type: project
title: "Project Name"
project_nature: "open_source"
status: "active"
repo_url: "https://github.com/example/project"
demo_url: "https://example.com"
organization: "[[entity-slug]]"
related_experience: "[[experience-slug]]"
dates:
  start: "2023-01-01"
  end: "Present"
skills: ["python", "langgraph"]
domains: ["Developer Tools", "AI"]
sources: ["jane-doe-resume-2026.pdf"]
created: "2026-01-01"
updated: "2026-01-01"
---
```

### Strategy Page

```yaml
---
type: strategy
title: "Region Strategy"
region: ["Ireland", "Netherlands", "Germany", "USA"]
focus: ["Contact", "Relocation", "Tone"]
pdf_template: "templates/base.css"
max_pages: 2
created: "2026-01-01"
updated: "2026-01-01"
---
```

### Strategy Track Page

```yaml
---
type: strategy-track
title: "Track Title"
seniority_levels: ["Senior", "Lead", "Principal", "Manager"]
archetype: "Domain Archetype Description"
focus: ["Focus-Area-1", "Focus-Area-2"]
org_culture: "corporate"
created: "2026-01-01"
updated: "2026-01-01"
---
```

### Cover Letter Page

```yaml
---
type: cover-letter
title: "Cover Letter for [Role] at [Company]"
target_organization: "[[entity-slug]]"
related_synthesis: "[[synthesis-slug]]"
sources: ["cover-letter.docx"]
created: "2026-01-01"
updated: "2026-01-01"
---
```

### Skill Page

```yaml
---
type: skill
title: "Skill Name"
category: ["Framework"]
related_experiences: ["[[experience-slug]]"]
proficiency: ["Expert"]
sources: ["skills-sync"]
---
```

### Language Page

```yaml
---
type: language
title: "English"
category: ["Spoken-Language"]
proficiency: "Fluent"
cefr: "C2"
sources: ["jane-doe-resume-2026.pdf"]
created: "2026-01-01"
updated: "2026-01-01"
---
```

### Entity Page

```yaml
---
type: entity
title: "Entity Name"
category: "organization"
industry: "Telecommunications & Cloud"
company_size: "10,000+ employees"
headquarters: "London, UK"
tags: ["telecommunications", "cloud"]
related: ["[[experience-slug]]"]
experiences: ["[[experience-slug]]"]
case_studies: ["[[example-corp-gitops-architecture-overview]]"]
projects: []
patents: []
sources: ["jane-doe-resume-2026.pdf"]
created: "2026-01-01"
updated: "2026-01-01"
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
```

### Case Study Template (`wiki/case-studies/`)

```markdown
# Technical Case Study Title

## Context & Problem
[Problem description and architectural constraints]

## Architecture & Technical Implementation
[Detailed technical architecture, patterns, components, and code/design decisions]

## Quantified Impact & Results
[Measurable metrics, benchmarks, SLA improvements, cost savings]
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

### Entity Template (`wiki/entities/`)

```markdown
# [Entity Name]

## Overview
[Summary of what the company, tool, or technology represents, its core domain, and market presence.]

## Key Contributions / Core Value
[For companies, summarize the candidate's key impact. For tools, outline the candidate's proficiency and typical use cases.]
```

---

## Cross-referencing Rules

- Always wrap `[[page-slug]]` links in double quotes inside YAML frontmatter (`"[[page-slug]]"`).
- Every experience must link to an `"[[entity-slug]]"` representing the organization, and list its child `case_studies`, `projects`, `patents`, and `notes`.
- Every case study, corporate project, and patent links back to its parent experience via `related_experience: "[[experience-slug]]"`.
