# Historical Research Workbench

Local-first, model-selectable Research Codex for auditable historical research projects.

The product direction is a persistent Agent workspace in which conversations can use page-aware PDF,
retrieval, evidence, scholarly dialogue, writing and memory tools without bypassing historical-source
verification. See [the product baseline](docs/RESEARCH_CODEX_PRODUCT.md),
[V1 architecture](docs/ARCHITECTURE_V1.md), [中文使用手册](docs/USER_MANUAL_ZH.md) and
[roadmap](docs/ROADMAP.md).

## Environment

The project uses its own Conda environment at
`D:\AI_Workflows\conda-envs\historical-research-workbench`. Recreate it with:

```powershell
conda env create --prefix D:\AI_Workflows\conda-envs\historical-research-workbench --file environment.yml
conda env config vars set --prefix D:\AI_Workflows\conda-envs\historical-research-workbench PYTHONNOUSERSITE=1
```

## Current status

`D5_IMPLEMENTATION_COMPLETE_TEMPLATE_RECHECK_PENDING`

M1 provides the project state kernel. M2 adds:

- real PDF page rendering;
- coordinate-preserving text-layer extraction;
- page-aware Markdown artifacts;
- conservative page and cross-page quality gates;
- a local page/anomaly repair workbench.

M3 adds an explicit visual-model lane for pages already blocked by M2. A model result is stored as a
pending proposal with source/page hashes and model provenance. It changes effective source text only
after a human edits and accepts it through the existing page-repair record. Rejection leaves the page
blocked.

Supported M3 providers are an OpenAI-compatible visual endpoint, local Ollama and a test-only mock.
The runtime reads the selected provider from `HRW_OCR_*` environment variables. Missing configuration
is shown as unavailable; providers never fall back silently and credentials are not returned to the
browser or stored in a project.

M3 deliberately stopped before translation, evidence extraction, manuscript writing and desktop packaging.

M4 now adds the minimum Research Codex runtime: persistent conversation threads, Goals/Runs, ordered
tool and approval events, role-based text-model selection, and a human-gated research-note write path.
M5 adds the pre-desktop research library: SKILL.md discovery, explicitly scoped folder inventory,
human-approved index-in-place, durable work/edition/file/version identity, ten-page triage, tags and search.
Hashes identify exact file versions only; they do not define a work's identity.

D1 makes the conversation the home screen and joins the earlier components into one vertical demo:
projects can be created and switched; an exact library file version can be copied into a project and
processed; Crossref/OpenAlex/Zotero retrievals are recorded as non-citable leads; verified page blocks can
be linked to claims and human-approved evidence freezes; only approved freezes can generate traceable
Markdown drafts. The research-browser panel records a domain-limited, user-controlled session without
capturing login state. Translation and visual OCR are separate optional model roles, so a text-only main
model can use a visual or translation helper.

D2 adds an article workbench. Markdown manuscripts are split into versioned sections; polishing and
frozen-evidence section drafting create reviewable proposals rather than overwriting the approved text.
Direct quotations, numbers, footnote markers and source identifiers are protected during polishing.
Bounded reading jobs, page-linked reading notes, historiography candidates and Markdown-first journal
templates support the writing loop without silently becoming evidence.

D3 reorganizes the client into four permanent workspaces: research dialogue, research library,
manuscript workbench and project settings. PDF import and page repair now live under the library. The
manuscript workspace uses a structured document tree with immutable revisions, controlled DOCX/Markdown
adapters and explicit fidelity reports. Its research sidebar can bind a message to the current manuscript,
revision, section, node and selected text without silently promoting conversation into approved prose.
The research browser now occupies the central workspace and keeps domain/session receipts in its sidebar.

D4 makes the manuscript workspace usable for a first citation-writing loop. It provides two versioned built-in
journal presets, structured note proposals with page/evidence status and human approval, immutable note versions,
anchor invalidation after relevant prose changes, Markdown footnotes and true Word footnotes. The
`《中国社会科学》` preset is tied to official checked sources; the `《历史研究》` preset is deliberately marked as a
public reference that must be rechecked before submission. The article layout, template selector, note sidebar,
revision status and dynamic package/schema display are available at `http://127.0.0.1:8765/?mode=article`.

D5 packages that harness as a Windows desktop Demo. A Tauri local shell starts and stops the bundled Python
sidecar, exposes only allowlisted file/Word commands, and keeps the research UI on loopback. The settings page
configures independent main-reasoning, visual/OCR and translation roles for Ollama or OpenAI-compatible APIs;
remote secrets go to Windows Credential Manager. Word remains an external editor: export a DOCX, open it in
Microsoft Word, then reimport the saved file as a new immutable revision with a fidelity report. The supplied
`《历史研究》` rules DOCX is still locked by another process, so that preset remains pending exact recheck.

The built-in deterministic model makes the complete M4 approval path testable offline. To expose one
real main-reasoning profile, set the uncommitted `HRW_AGENT_PROVIDER`, `HRW_AGENT_BASE_URL`,
`HRW_AGENT_MODEL` and, for an OpenAI-compatible endpoint, `HRW_AGENT_API_KEY`. Supported providers are
`openai_compatible` and `ollama`. The selected profile is frozen per Run; missing configuration remains
visible as unavailable and never silently falls back.

## Run tests

```powershell
conda run --prefix D:\AI_Workflows\conda-envs\historical-research-workbench python scripts\assert_environment.py
conda run --prefix D:\AI_Workflows\conda-envs\historical-research-workbench python -m unittest discover -s tests -v
```

## CLI

```powershell
conda run --prefix D:\AI_Workflows\conda-envs\historical-research-workbench hrw --help
```

Register and process a PDF:

```powershell
conda run --prefix D:\AI_Workflows\conda-envs\historical-research-workbench hrw add-source D:\research\my-project D:\books\source.pdf
conda run --prefix D:\AI_Workflows\conda-envs\historical-research-workbench hrw ingest-pdf D:\research\my-project SOURCE_ID
```

Open the local repair workbench:

```powershell
conda run --prefix D:\AI_Workflows\conda-envs\historical-research-workbench hrw serve D:\research\my-project
```

Use one reusable library location across projects in browser development mode:

```powershell
conda run --prefix D:\AI_Workflows\conda-envs\historical-research-workbench hrw serve D:\research\my-project --library-root D:\research\historian-library
```

Add `--workspace-root D:\research\historian-workspace` to persist the project list and last selected
project. The default home is **研究对话**; its right-hand context panel contains project sources, library,
open retrieval, evidence, frozen writing, browser receipts and memory candidates.

In **研究图书馆**, paste only the folder you want to inventory. The first action is read-only preview;
selected candidates enter the library only after a second approval. Files remain in place. Exact hashes,
all observed file versions, the intake Skill hash and whether each recorded byte version is still available
at the current path are shown in the work detail panel. Single-PDF compatibility import and the project's
original-page repair view also live here rather than in the global navigation.

Then open `http://127.0.0.1:8765`. The interface can also import a PDF directly. The server binds
to loopback only. CLI commands continue to emit JSON so a later Tauri bridge can call the same
application service.

## Windows desktop Demo

Build the packaged sidecar and current-user NSIS installer with:

```powershell
& .\scripts\build_desktop.ps1
```

The installer is written under `src-tauri\target\release\bundle\nsis`. It creates the workspace, library,
projects, configuration and logs beneath the current user's application-data directory. The Demo is unsigned;
there is no automatic updater yet.

If the Demo service is not running, start or restart it with:

```powershell
& "C:\Program Files\PowerShell\7\pwsh.exe" -NoProfile -File .\scripts\start_demo.ps1 -Restart
```

Open the article workbench directly at `http://127.0.0.1:8765/?mode=article`. DOCX support intentionally
covers headings, paragraphs and quotations only; comments, tracked changes, fields, complex footnotes and
embedded objects are reported as fidelity risks for manual review in Word.

Check the configured OCR role without exposing its key:

```powershell
conda run --prefix D:\AI_Workflows\conda-envs\historical-research-workbench hrw ocr-capability
```
