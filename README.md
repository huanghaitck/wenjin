# Historical Research Workbench

Local-first, model-selectable Research Codex for auditable historical research projects.

The product direction is a persistent Agent workspace in which conversations can use page-aware PDF,
retrieval, evidence, scholarly dialogue, writing and memory tools without bypassing historical-source
verification. See [the product baseline](docs/RESEARCH_CODEX_PRODUCT.md),
[V1 architecture](docs/ARCHITECTURE_V1.md) and [roadmap](docs/ROADMAP.md).

## Environment

The project uses its own Conda environment at
`D:\AI_Workflows\conda-envs\historical-research-workbench`. Recreate it with:

```powershell
conda env create --prefix D:\AI_Workflows\conda-envs\historical-research-workbench --file environment.yml
conda env config vars set --prefix D:\AI_Workflows\conda-envs\historical-research-workbench PYTHONNOUSERSITE=1
```

## Current status

`M5_SKILLS_COMPATIBLE_RESEARCH_LIBRARY_IN_PROGRESS`

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
M5 is now adding the pre-desktop research library: SKILL.md discovery, explicitly scoped folder inventory,
human-approved index-in-place, durable work/edition/file/version identity, ten-page triage, tags and search.
Hashes identify exact file versions only; they do not define a work's identity.

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

Then open `http://127.0.0.1:8765`. The interface can also import a PDF directly. The server binds
to loopback only. CLI commands continue to emit JSON so a later Tauri bridge can call the same
application service.

Check the configured OCR role without exposing its key:

```powershell
conda run --prefix D:\AI_Workflows\conda-envs\historical-research-workbench hrw ocr-capability
```
