# M3 task specification: model-assisted page repair

Status: complete
Date: 2026-08-09

## Objective

Add one auditable loop for pages that M2 has already blocked:

1. a human selects a physical page;
2. one explicitly configured visual provider creates a structured OCR proposal;
3. the proposal remains separate from effective source text;
4. a human compares it with the rendered original page and edits it;
5. accepting it creates the existing M1 page-repair record, while rejecting it leaves the anomaly open.

## Required proposal record

Each proposal stores:

- source, physical page and open page-anomaly identifiers;
- source-file and rendered-page SHA-256 hashes;
- provider, exact model and prompt version;
- sanitized raw response, normalized blocks and their hashes;
- pending, accepted, rejected or superseded state;
- reviewer, reason, decision time and resulting repair identifier.

Credentials must not enter SQLite, source files, logs, HTTP responses or Git.

## Providers

- `openai_compatible`: the first remote test target is `glm-4.6v-flash`;
- `ollama`: local visual models use Ollama's local chat endpoint;
- `mock`: deterministic tests only.

The selected provider never falls back silently. Missing configuration produces a visible unavailable
state. A text-only main model may later call this bounded vision role, but M3 does not create a generic
multi-agent framework.

## Human gate

- Creating a proposal never changes `pages`, `blocks`, anomalies or source usability.
- Only explicit human acceptance may call the existing full-page repair operation.
- The reviewer may edit every proposed block before acceptance.
- Rejection preserves the proposal and keeps the source anomaly unresolved.
- A proposal cannot be accepted twice or after its anomaly has already been resolved.
- Accepting one proposal marks other pending proposals for the same page as superseded.

## HistRA engineering sample

Use derived single-page copies from read-only HistRA-Bench books for local integration testing:

- a vertical-layout image-only scan from `shenke-yuandianzhang-vol4.pdf`;
- a layered OCR page from `校勘学大纲`;
- a searchable page from `十七史商榷`.

The full books remain untouched and outside this repository. Derived pages and runtime projects stay
under ignored `tmp/` paths.

## Acceptance checks

- Existing schema-v1 projects migrate without losing M1/M2 state.
- A mock proposal remains pending and does not change effective source text.
- Accepting an edited proposal creates a repair record and resolves only the target page workflow.
- Rejecting a proposal does not resolve the anomaly.
- Provider configuration returned to the browser never includes a key.
- OpenAI-compatible and Ollama request construction are covered without network calls.
- M1/M2 regression tests remain green.

## Non-goals

Translation, evidence extraction, research planning, drafting, journal formatting, automatic source
approval, Windows Credential Manager integration and packaged desktop distribution remain outside M3.
