---
name: historical-material-intake
description: Read-only inventory and human-approved registration of historical research materials.
---

# Historical Material Intake Adapter

Use only a directory explicitly selected by the user. Inventory files without moving, renaming or rewriting
them. Separate exact file versions, duplicate locations, bibliographic identity and citation qualification.

For PDF, Markdown and TXT, create an intake candidate with path, format, byte size, SHA-256, available
bibliographic metadata and a bounded triage sample. A newly approved file may reach `FILE_VERIFIED`; it is
not `CITABLE`. Preserve unsupported files and read errors as visible candidate states. Human approval is
required before any candidate becomes a library record.

Read responsibility, title, journal or publisher, year, DOI and ISBN from the title page, first article page,
copyright page or explicit electronic citation before falling back to file names or embedded tags. Treat a
shared DOI or ISBN as stronger evidence of one work than file-name or language differences. Distinguish one
work with multiple files, editions, translations or generated copies from exact duplicate bytes. After
approval, candidate cards must show the resolved library work and its current bibliography rather than the
stale scan-time suggestion. Missing metadata remains visibly unresolved; never replace it with a guessed name.

During bulk folder inventory, admit Word files only when they are complete research materials, source
transcriptions or translations, scholarly drafts, or reading notes. Hide Office lock files, administrative
forms, templates, software exercises, creative scripts, and isolated abstract/introduction fragments behind
an explicit ignored-Word count. A file explicitly uploaded by the user overrides this bulk gate.

Before approving admitted Word files, compare full paragraph and table text rather than file names alone.
Cluster exact copies, near-identical revisions, partial drafts and renamed files. For one translation or draft
line, keep the most complete file; if completeness is comparable, keep the newest timestamp. Record its
relationship to the source PDF or edition, and do not count an OCR, translation or bilingual copy as an
independent witness. Ambiguous clusters require human confirmation.
