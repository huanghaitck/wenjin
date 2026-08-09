# M2 Task Specification

## Objective

Turn a registered local PDF into a page-aware, inspectable document representation and let a
researcher correct only the unsafe part while always seeing the rendered source page.

## Intake contract

For every physical PDF page M2 must preserve:

- the one-based physical page number;
- a rendered PNG derived from the registered immutable PDF;
- page width and height;
- ordered text blocks with normalized source regions;
- a conservative printed-page candidate, when one is visible in a header or footer;
- an individual Markdown page with an explicit source-page marker.

M2 also writes a complete `structure.json` packet and a navigation-only `document.md`. The M1
single-writer import remains the only operation that applies the packet to project state.

## Quality gate

- A page with no usable text layer is blocked but its original page image remains available.
- If fewer than 20 percent of pages have usable text, a systemic source anomaly blocks the source.
- Replacement characters and obviously corrupted text blocks are blocked locally.
- A possible cross-page continuation is never silently joined. It creates a relation anomaly and
  blocks the two boundary blocks until a person confirms or rejects the relation.
- A clean sentence boundary is stored as a non-continuation relation without blocking text.

These heuristics identify review work; they are not claims that the page was read correctly.

## Repair workbench

The local interface must show:

- page rail and physical page number;
- rendered source page;
- effective extracted text and block regions;
- open anomalies for the selected source;
- local block repair, full-page repair and relation confirmation/rejection.

It runs on loopback only and does not read arbitrary paths supplied by the browser.

## Resource reuse boundary

The split reader, page rail, zoom controls and model-role ideas are adapted from the local
`bilingual_book` project. This repository owns its implementation and data contracts. It does not
import sibling source paths, translation state, caches, mascots or Bookflow-specific job state.

## Acceptance

1. A real two-page text PDF produces two PNGs, two page Markdown files and one structure packet.
2. Block coordinates are normalized and physical page order is preserved.
3. A scanned/image-only PDF remains visually inspectable but is blocked for research text use.
4. A possible cross-page continuation requires a human relation decision.
5. The local interface reads project state and submits repairs through the same application service.
6. M1 tests remain green and M2 tests cover intake, isolation and repair.
