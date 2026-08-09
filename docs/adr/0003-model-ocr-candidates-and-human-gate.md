# ADR 0003: Model OCR candidates and human gate

Status: accepted as the M3 direction; provider implementation is not yet authorized  
Date: 2026-08-09

## Decision

Scanned and unsafe-text pages require a visual transcription model, but model output is a repair
proposal rather than research-usable source text. Every proposal must retain:

- source PDF hash, physical page and rendered-image hash;
- provider, exact model code and prompt version;
- proposed blocks, reading order, regions and uncertain characters;
- raw response and normalized response hashes;
- comparison with any existing text layer;
- human acceptance, correction or rejection through the M1 repair record.

The first remote OCR candidate is `glm-4.6v-flash`. The `v` is significant: official documentation
lists image, video, text and file input and explicitly recommends the model for image OCR. The plain
`glm-4.6` family is not the visual model. The local comparator remains the installed Ollama Qwen3-VL
model.

Official references:

- https://docs.bigmodel.cn/cn/guide/models/free/glm-4.6v-flash
- https://docs.z.ai/guides/overview/overview

## Role pairing

A text-only main model may dispatch a bounded page or region to the OCR/vision role. It receives a
structured proposal with page anchors and uncertainty, not an unqualified Markdown string. A second
model may review difficult characters, but agreement between models does not replace source-page
review when the text supports a historical claim or quotation.

## Evaluation order

1. `glm-4.6v-flash`: free remote visual baseline.
2. local Ollama Qwen3-VL: offline/privacy comparator.
3. GPT-5.6-sol: bounded evaluation or adjudication when available in the host environment.

No provider may silently replace another. Missing credentials leave the role unavailable.
