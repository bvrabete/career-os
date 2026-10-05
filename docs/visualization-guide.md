# Visualizing and Browsing Your Career LLM-Wiki

This guide explains how to visualize, explore, and navigate your CareerOS Knowledge Base using modern Personal Knowledge Management (PKM) and open-source graph visualizers.

---

## 1. Andrej Karpathy's LLM-Wiki Philosophy

CareerOS strictly implements **Andrej Karpathy's LLM-Wiki concept**:
* **100% Plain-Text Markdown (`.md`)**: No proprietary binaries, no database locks, and zero vendor entrapment.
* **Standard YAML Frontmatter**: Structured metadata parseable by standard Python, Node.js, and LLM reasoning pipelines.
* **Universal Bidirectional Wikilinks (`[[slug]]`)**: Cross-references connect employers to roles, roles to skills, and skills to authored patents and case studies.
* **Universal Multi-Client Readiness**: Because the underlying data is standard Markdown, **you never have to choose a single app**. You can use VS Code with Foam while programming, open the folder in Logseq for offline outliner browsing, or view it in Obsidian for a full 3D interactive knowledge graph.

---

## 2. Supported Visualizers & Quick Setup

The `llm-wiki.template` comes pre-configured with seed dotfiles so every client works immediately out of the box.

### Option A: VS Code & Cursor (Foam Extension) — *In-Editor Visualizer*
Best for users who want zero-context-switch graph navigation while actively working in the IDE.

1. Install the **Foam** extension (`foam.foam-vscode`) in VS Code or Cursor.
2. Open your `llm-wiki/` directory in VS Code.
3. Open the Command Palette (`Ctrl+Shift+P` or `Cmd+Shift+P`) and run:
   ```
   Foam: Show Graph
   ```
4. **Features**:
   - Live interactive graph panel docked right next to your markdown files.
   - Autocomplete for `[[wikilinks]]` as you type.
   - Built-in Backlinks Explorer in the sidebar showing every file that cites the current role or skill.

---

### Option B: Logseq — *100% Free & Open Source Desktop App*
Best for users committed to 100% FOSS, offline privacy, and local outliner search.

1. Download and launch **[Logseq](https://logseq.com/)** (Available on Windows, macOS, Linux).
2. Click **Add new graph** $\rightarrow$ select your local `llm-wiki/` folder.
3. Logseq reads the pre-configured [logseq/config.edn](file:///C:/Users/bvrabete/source/personal/career-os/llm-wiki.template/logseq/config.edn), automatically setting Markdown mode and mapping pages directly to `wiki/`.
4. Click **Graph view** in the left sidebar (or press `Ctrl+G` / `Cmd+G`).
5. **Features**:
   - Interactive local graph for any page (e.g. click into `intel-platform-architect` to see only adjacent skills and patents).
   - Global force-directed graph.
   - Native unlinked references finder.

---

### Option C: Obsidian — *Polished 2D/3D Interactive Visualizer*
Best for rich visual presentations, deep exploration, and color-coded entity hubs.

1. Download and launch **[Obsidian](https://obsidian.md/)**.
2. Click **Open folder as vault** $\rightarrow$ select your local `llm-wiki/` folder.
3. Open the Graph View (`Ctrl+G` or `Cmd+G`).
4. The pre-configured [.obsidian/graph.json](file:///C:/Users/bvrabete/source/personal/career-os/llm-wiki.template/.obsidian/graph.json) will automatically load semantic color-coding:

| Entity Type | Folder Location | Node Color | Hex Code |
| :--- | :--- | :--- | :--- |
| **Experiences / Tenures** | `wiki/experiences/` | Blue | `#3b82f6` |
| **Skills & Competencies** | `wiki/skills/` | Emerald Green | `#10b981` |
| **Patents & IP** | `wiki/patents/` | Royal Purple | `#8b5cf6` |
| **Publications & Papers** | `wiki/publications/` | Violet | `#a855f7` |
| **Case Studies** | `wiki/case-studies/` | Amber Gold | `#f59e0b` |
| **Qualitative Notes** | `wiki/notes/` | Warm Orange | `#f97316` |
| **Candidate Voice** | `wiki/voice/` | Rose Pink | `#f43f5e` |
| **Synthesis Tailored CVs** | `wiki/synthesis/` | Teal | `#14b8a6` |
| **Company Hubs** | `wiki/entities/` | Deep Navy | `#1d4ed8` |

5. **Tips in Obsidian**:
   - Toggle **Local Graph** in the right sidebar to focus purely on the currently open company or role.
   - Use the **Search** modal (`Ctrl+Shift+F`) to find any bullet point or skill instantly.

---

### Option D: Quartz v4 — *Local Browser Web Portal*
Best for generating a lightweight, fast web interface in your browser.

1. Open your terminal in the workspace root.
2. Install and serve Quartz against your wiki:
   ```bash
   npx quartz build --serve --directory llm-wiki/wiki
   ```
3. Open `http://localhost:8080` in your web browser.
4. **Features**:
   - Interactive canvas-based force-directed graph in the browser.
   - Dark mode, lightning-fast full-text search, and breadcrumb navigation.

---

## 3. Link Syntax & Cross-Platform Integrity

To guarantee that links never break regardless of which client you or an LLM uses:
1. **Always use Basename Slugs**:
   Write `[[intel-platform-architect]]`, **never** full filesystem paths like `[[wiki/experiences/intel-platform-architect.md]]`.
2. **Unique Slugs Across Directories**:
   Because every entity, experience, skill, and patent has a unique filename stem (slug), all PKM visualizers resolve links globally without ambiguity.
3. **Bidirectional Frontmatter Links**:
   Keep relations declared in YAML frontmatter (e.g. `organization: [[intel-corporation]]`, `tenure: [[intel-platform-architect]]`, `skills: [[[python]], [[kubernetes]]]`). Both Obsidian, Logseq, and CareerOS Python graph parsers index these links automatically.
