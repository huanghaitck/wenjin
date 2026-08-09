# Historical Research Workbench Codex Rules

## Project identity

This repository is the independent implementation of the local-first historical research workbench.
It does not own or modify Bookflow Scholar, HistRA-Bench, the historical-research Codex plugin, or
private research projects.

## Current gate

Current milestone: `M2_PDF_INTAKE_AND_REPAIR_WORKBENCH_COMPLETE`.

M2 is complete. Until the user explicitly approves M3, changes may only fix an M2 acceptance
failure or improve its documentation and targeted tests.

M2 may implement only:

- deterministic PDF page rendering and text-layer extraction;
- physical-page, printed-page candidate, text block and region preservation;
- conservative cross-page continuation candidates;
- local and systemic quality gates before research use;
- a local page/anomaly repair interface over the M1 application service;
- targeted fixtures, CLI commands and tests for this intake loop.

M2 must not implement OCR model calls, networking, paid APIs, translation, evidence extraction,
research drafting, journal export, a packaged Tauri application or broad Bookflow code copying.

## Startup order

1. Read this file.
2. Read `docs/CURRENT_PROJECT_STATE.yaml`.
3. Read the active milestone specification.
4. Inspect only files directly relevant to the task.

## Engineering principles

- Prefer the smallest direct implementation that passes the active milestone acceptance tests.
- Protect original sources, page/text relationships, human repairs and audit history.
- Quarantine local errors locally; block a full source only for systemic page or text-layer failure.
- Validate at input and state-transition boundaries; do not repeat the same check in every layer.
- Do not create an abstraction until a second real implementation or caller exists.
- Do not add microservices, distributed queues, vector stores, graph stores or speculative plugin layers.
- Never hide a failed state behind a successful-looking artifact.
- M2 may use PyMuPDF as its single PDF dependency. Keep the local web interface build-free.

## File safety

- Original user files are read-only inputs and must never be overwritten.
- Project artifacts are written beneath the selected project root.
- No secrets belong in source, fixtures, logs or SQLite.
- `.env` is ignored; `.env.example` contains names only.
- Do not modify sibling projects under `D:\AI_Workflows`.

## Validation

Use the dedicated Conda environment and verify isolation before project commands:

```powershell
conda run --prefix D:\AI_Workflows\conda-envs\historical-research-workbench python scripts\assert_environment.py
conda run --prefix D:\AI_Workflows\conda-envs\historical-research-workbench python -m unittest discover -s tests -v
```

Run M1 and M2 target tests. Stop after they pass; do not enter M3 without explicit user approval.
