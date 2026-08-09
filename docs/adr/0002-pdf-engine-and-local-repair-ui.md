# ADR 0002: PDF engine and local repair UI

Status: accepted for M2

## Decision

Use PyMuPDF as the single M2 PDF dependency for both text blocks with bounding boxes and deterministic
page rendering. Store normalized coordinates in the M1 structure packet and PNG paths in each page's
machine payload.

Serve a build-free HTML/CSS/JavaScript interface from Python's loopback HTTP server. The browser is
only a view over a project root fixed when the server starts. A future Tauri/React shell may replace
this view without changing the application service or repair commands.

## Why

- Page images and text coordinates come from the same page geometry.
- The implementation remains small enough to inspect and test.
- A local browser interface validates the actual repair workflow before desktop packaging work.
- It adapts the useful split-reader interaction from `bilingual_book` without coupling the projects.

## Consequences

- M2 handles PDFs with an existing text layer. OCR and visual-model transcription are later provider
  roles, not hidden fallbacks.
- Possible cross-page joins remain blocked until a human decision.
- The local server is a development/MVP surface, not the final desktop distribution.
