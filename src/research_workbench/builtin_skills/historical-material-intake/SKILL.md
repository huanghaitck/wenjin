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
