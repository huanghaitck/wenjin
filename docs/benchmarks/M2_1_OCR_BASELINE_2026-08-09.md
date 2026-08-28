# M2.1 OCR baseline - 2026-08-09

## Purpose

Measure whether GPT-5.6-sol can visually transcribe page images well enough to justify an M3 model
OCR lane. This is a bounded engineering baseline, not a claim of general historical OCR accuracy.

## Runtime

- Conda prefix: `D:\AI_Workflows\conda-envs\historical-research-workbench`
- Python: 3.13.14
- user site packages: disabled
- PyMuPDF: installed inside the dedicated environment
- GPT-5.6-sol OCR API calls: 0 (host visual inspection)
- GLM-4.6V-Flash API calls: 2 (the first successful response was repeated because the Windows
  console could not encode one returned symbol)

## Blind procedure

The model first inspected the rendered page image and wrote a transcription. Only afterward was the
PDF text layer read as the reference. Scoring uses Unicode NFKC normalization, normalizes curly
quotes, and removes whitespace for character error rate (CER). WER is omitted for CJK-dominant text.

## Exact-reference results

| Fixture | Content | CER | WER | Note |
|---|---|---:|---:|---|
| `en_synthetic_test_page.pdf` | uncommon synthetic English | 0.0000 | 0.0000 | 147 normalized characters |
| `zh-Hans_synthetic_test_page.pdf` | uncommon synthetic Chinese | 0.0000 | n/a | 67 normalized characters |
| `en_udhr_page_image_only.pdf` | clean English UN page | 0.0000 | 0.0000 | memorization may contaminate result |
| `zh-Hans_udhr_page_image_only.pdf` | clean Chinese UN page | 0.0000 | n/a | memorization may contaminate result |

Synthetic fixture hashes:

- English: `10b1b700cff1b843f37b0f1efa740ccb29db64973970a26b72d6809765dd8ad6`
- Chinese: `eca5a5a7c8ad6f71a9e5653e48cbe2b6abcd84935ec73a283d9f09cd7acbff4e`

## Historical-page comparison

`sample_page_12.pdf` (`2aec2051f0eaa905d3125ca4afb97b7ed183576d16b7f5f2108795d913d1b7f9`)
has a visibly readable page image but a fragmented PDF text layer. GPT-5.6-sol produced a complete
visual transcription. Compared with the existing non-authoritative GLM-4.6V normalized result, the
pairwise disagreement was CER 0.002190 and WER 0.038168. Visual review located the main differences
in three printed line-break words: `unsub-stantial`, `can-noned`, and `gentle-man`; GPT-5.6-sol
reconstructed the lexical words without preserving the layout hyphens.

This is a disagreement measurement, not an accuracy score, because no independent human diplomatic
transcription was available for that page.

## Live GLM-4.6V-Flash provider check

The existing development credential in the disaster-history project was read in memory for a
bounded call to `glm-4.6v-flash`. The credential was not printed, copied into this project or stored
in the benchmark artifact. The model returned a complete transcription of the historical page.

Compared with the GPT-5.6-sol transcription, the live result had pairwise CER `0.008029` and WER
`0.015267`. Direct page-image review confirmed three material differences:

- printed `they swung by in succession` became `they swung in fours, in succession`;
- printed line-break form `can-` / `noned` became the nonexistent word `cannoneled`, rather than
  `cannoned`;
- footer symbol `®` became `©`.

The live output remains a comparator artifact only. It was not applied to the source block table or
marked research-usable.

## M2 fail-closed check

- Both image-only UN PDFs were rendered but remained `blocked` with page and systemic no-text-layer
  anomalies.
- The historical sample remained `blocked` with a fragmented-layout anomaly.
- No model transcription was automatically applied to project text.

## Conclusion and limits

GPT-5.6-sol is strong enough to serve as an OCR proposal generator or difficult-page adjudicator in
M3. GLM-4.6V-Flash is usable as a first remote proposal generator, but this live check produced
text-altering errors on a visually clean page, so it is not qualified as automatic source-text
authority.
The sample lacks handwriting, tables, marginalia, mixed scripts, severe blur, bleed-through and
multi-column historical layouts. A larger benchmark must include exact human references and
page-region localization before provider selection is frozen.
