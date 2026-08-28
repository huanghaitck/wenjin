# M3 HistRA provider check - 2026-08-09

## Purpose

Exercise the M3 proposal gate with real book pages while keeping HistRA-Bench read-only. This is an
engineering integration check, not a published OCR accuracy benchmark.

## Sample construction

Three single-page derivatives were created under ignored `tmp/m3-histra-samples/` and imported into
an ignored workbench project. Full books were neither copied into Git nor modified.

| Role | Original book | Physical PDF page | Original SHA-256 | Derived page SHA-256 | M2 result |
|---|---|---:|---|---|---|
| image-only vertical scan | `shenke-yuandianzhang-vol4.pdf` | 123 | `06735a29b3078c3f8cdada2efb4a1f8e14c6e71e9884a49632810da64cd92d5b` | `f5c23809386626a480dd19f4fbd8ecfdaabd6c514330f0ec2c6976a6d634a8e7` | blocked, two open content anomalies |
| layered OCR | `[OCR]校勘学大纲...layered.pdf` | 155 | `e38b766d0841c420856d088a213dcc34fe3a39fdd70d76b99af17003595e05df` | `e07717e4d73c7a8f9340ccb04f1428327680ed6bf98fc112231d456d36123f12` | research-usable |
| searchable book | `史学考据_十七史商榷_王鸣盛_可搜索.pdf` | 397 | `b4d1537666dbd51975d2f556a79c774d1ed8d9127c782468e8634871d8dee983` | `ed3165b958cb08009bb86464138ce4ea0cecb6c46599c1a5ee7af7b490c1d618` | research-usable |

The two text-bearing pages were used to verify that M3 does not invite or spend a model call on an
already accepted page. The image-only page was the sole proposal target.

## Local Ollama result

- provider: `ollama`
- model: `qwen3-vl:4b-instruct-q4_K_M`
- calls: 1
- outcome: one pending proposal, no repair and no source-text mutation

The model returned a complete right-to-left transcription as one paragraph. It supplied no regions
or column boundaries, so it did not reconstruct the page's position relationships. It also emitted a
boolean as `printed_page`; this live failure led to a normalization rule that quarantines boolean or
structured page-number values and adds `invalid_printed_page`.

The stored first-run proposal predates that normalization fix and is intentionally retained as raw
audit evidence. The GUI does not treat its page-number value as effective source metadata.

## GLM-4.6V-Flash result

The existing disaster-history development credential was loaded in memory only. Two spaced attempts
reached the configured OpenAI-compatible endpoint and both returned HTTP 429. No proposal record was
created and no automatic provider fallback occurred. The same credential and model had completed the
earlier M2.1 single-page provider check, so this result is classified as external rate limiting rather
than a request-format or credential failure.

## Gate result

- proposal creation did not alter pages, blocks, anomalies or source usability;
- the proposal retains source/image hashes, provider, exact model, prompt version and response hashes;
- the pending proposal is visible in the M3 GUI for human editing, acceptance or rejection;
- the original HistRA files remain unchanged;
- no credential was copied into the workbench project, SQLite database, documentation or Git.

## Limits

No independent diplomatic transcription was produced for the vertical page, so no CER is reported.
The local result must not be treated as citation-ready merely because it appears visually plausible.
Column-level regions, rare-character uncertainty and a human-approved reference set remain future
evaluation work.
