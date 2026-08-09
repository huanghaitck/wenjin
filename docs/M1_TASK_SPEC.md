# M1 Task Specification

## Objective

Create the smallest local state kernel that proves page/block anomalies can be imported, locally
quarantined, human-repaired at block or full-page scope, and audited without calling a model.

## In scope

- Project directory and SQLite initialization.
- Source copying with SHA-256 and immutable original storage.
- Page, block, page relation and anomaly records.
- Idempotent structure staging receipts and application-service single writer.
- Block repair and page repair records.
- Recalculation that blocks only affected regions unless an anomaly is systemic.
- JSON CLI.
- Standard-library `unittest` fixtures.

## Out of scope

- PDF rendering or OCR.
- Network access, API keys and model calls.
- Desktop UI or Tauri Bridge.
- Evidence, claims, drafting, review and citation export.
- Direct imports from Bookflow or other sibling projects.

## Acceptance

1. A project initializes with the expected directories, metadata and schema.
2. A source is copied without changing the original and is identified by its content hash.
3. A deterministic structure packet imports exactly once.
4. A local block anomaly blocks only that block.
5. A page anomaly blocks only that page and its blocks.
6. A block repair resolves the target anomaly and preserves other blocks.
7. A page repair updates page-scoped block/relation corrections and preserves other pages.
8. A systemic anomaly blocks the entire source.
9. Every state-changing action creates an audit event.

