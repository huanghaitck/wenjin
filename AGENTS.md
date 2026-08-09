# Historical Research Workbench Codex Rules

## Project identity

This repository is the independent implementation of the local-first historical research workbench.
It does not own or modify Bookflow Scholar, HistRA-Bench, the historical-research Codex plugin, or
private research projects.

## Current gate

Current milestone: `M4_AGENT_WORKSPACE_FOUNDATION`.

The user authorized M4 on 2026-08-09 after the Research Codex product, architecture and roadmap were
frozen. M4 is limited to persistent threads/messages/goals/runs/events, role-based text-model profiles,
one main Agent tool loop, project/source/page read tools, a human-gated research-note write tool, and
the corresponding CLI/API/GUI. See `docs/M4_TASK_SPEC.md`.

M4 must not implement network research, authenticated browser control, evidence freezing, long-term
memory writes, translation, formal manuscript drafting, journal export, a generic multi-agent framework,
packaged desktop distribution or broad Bookflow code copying. It must preserve all M1-M3 source and
repair gates.

## Startup order

1. Read this file.
2. Read `docs/CURRENT_PROJECT_STATE.yaml`.
3. Read the active milestone specification (`docs/M4_TASK_SPEC.md`).
4. Inspect only files directly relevant to the task.

## Engineering principles

- Prefer the smallest direct implementation that passes the active milestone acceptance tests.
- Protect original sources, page/text relationships, human repairs and audit history.
- Quarantine local errors locally; block a full source only for systemic page or text-layer failure.
- Validate at input and state-transition boundaries; do not repeat the same check in every layer.
- Do not create an abstraction until a second real implementation or caller exists.
- Do not add microservices, distributed queues, vector stores, graph stores or speculative plugin layers.
- Never hide a failed state behind a successful-looking artifact.
- PyMuPDF remains the single PDF dependency. Keep provider HTTP calls dependency-free and the local
  web interface build-free during M4.

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

Run M1-M4 target tests. Real provider checks are bounded integration tests and must never
print or persist credentials.
