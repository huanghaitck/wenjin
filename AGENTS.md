# Historical Research Workbench Codex Rules

## Project identity

This repository is the independent implementation of the local-first historical research workbench.
It does not own or modify Bookflow Scholar, HistRA-Bench, the historical-research Codex plugin, or
private research projects.

## Current gate

Current milestone: `D2_EVIDENCE_PRESERVING_READING_AND_SECTION_WRITING_COMPLETE`.

The user authorized and completed M5 on 2026-08-10. M5 adds a pre-desktop, usable research-library vertical slice:
SKILL.md discovery, explicitly scoped read-only folder inventory, human-approved index-in-place, durable
work/edition/file/version identity, ten-page triage, tags, search and complete version display. See
`docs/M5_TASK_SPEC.md` and ADR 0005.

The user approved D1 on 2026-08-10. Follow `docs/D1_END_TO_END_DEMO_TASK_SPEC.md` and ADR 0006. D1 may
implement bounded slices of later milestones only to complete the documented vertical workflow. It does not
authorize credential capture, arbitrary skill-script execution, unattended authenticated browsing, broad
Bookflow code copying, full-paper generation or desktop packaging.

D1 completed on 2026-08-10 with 42 passing tests, a bounded live Crossref retrieval, loopback API/UI
checks and a visible conversation-first demo. Do not treat D1 as completion of production M6-M11. The
next scope must be chosen from real use feedback before expanding browser automation, connectors,
scholarly dialogue, citation styles, memory adapters or desktop packaging.

The user selected the next increment on 2026-08-10: article polishing and section writing first, with
bounded reading, historiography entries and journal templates as supporting objects. Follow
`docs/D2_AUTHORING_READING_TASK_SPEC.md` and ADR 0007. Do not implement license bypass or unattended
full-manuscript generation.

D2 completed on 2026-08-10. The next increment must come from use of the article workbench. Likely
candidates are real-model writing evaluation, DOCX/journal-template fidelity, historiography synthesis,
larger reading-job scheduling, or additional lawful database connectors. Do not expand all at once.

## Startup order

1. Read this file.
2. Read `docs/CURRENT_PROJECT_STATE.yaml`.
3. Read `docs/D2_AUTHORING_READING_TASK_SPEC.md`, ADR 0007 and `docs/ROADMAP.md`.
4. Inspect only files directly relevant to the task.

## Engineering principles

- Prefer the smallest direct implementation that passes the active milestone acceptance tests.
- Protect original sources, page/text relationships, human repairs and audit history.
- Quarantine local errors locally; block a full source only for systemic page or text-layer failure.
- Validate at input and state-transition boundaries; do not repeat the same check in every layer.
- Do not create an abstraction until a second real implementation or caller exists.
- Do not add microservices, distributed queues, vector stores, graph stores or speculative plugin layers.
- Never hide a failed state behind a successful-looking artifact.
- PyMuPDF remains the single PDF dependency. Keep the local web interface build-free during M5.
- A SHA-256 identifies an exact byte version or duplicate only. It must never define the enduring identity
  of a work, edition or library record.

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

Run M1-M5 target tests. Real provider checks are bounded integration tests and must never
print or persist credentials.
