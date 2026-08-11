# Dogfood Report: Field-Anchored Event Reading

| Field | Value |
|---|---|
| Date | 2026-08-11 |
| App URL | `http://127.0.0.1:8766/` |
| Session | `hrw` |
| Scope | Richthofen physical pages 250–251, cross-page relation and block verification |

## Summary

| Severity | Count |
|---|---:|
| Critical | 0 |
| High | 0 |
| Medium | 8 |
| Low | 0 |
| **Total** | **8** |

All eight findings were fixed in the same bounded branch and verified by the full 98-test suite.
The real GUI flow then produced and human-approved the 13-block `24-/25. Jan.` event
`EVT_c05991d5c1714c728c54f0ae607fc95c`. Approval remains explicitly below evidence freeze.

## Issues

### ISSUE-001: Marginal date is interleaved into a hyphenated body word

| Field | Value |
|---|---|
| Severity | medium |
| Category | content |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — static source-page issue |

**Description**

On Richthofen physical page 250 / printed page 231, the page image prints the marginal date
`23. Januar,` beside a body line split as `Wild-` / `heit`. The extracted block serializes the
layout as `Wild- 23. Januar,\nheit`, inserting the date into the word. The original PDF remains
unchanged and the local block-repair workflow is available, but the block is unsafe for event-date
and verbatim-text use until a human restores reading order and records the repair.

**Repro Steps**

1. Open the approved event on physical page 250 and enter the original-page review view.
2. Compare the center page image with block B004 in the extracted-text panel.
3. Observe that the image has a marginal date while the text panel places it between `Wild-` and
   `heit`.

Evidence screenshot:
`C:\Users\huanghai\.codex\visualizations\2026\08\06\019fd677-de66-7962-85a0-fbab9381cb1a\dogfood-event-table\screenshots\richthofen-page-250-source.png`

### ISSUE-002: Body-text extraction drops a word boundary

| Field | Value |
|---|---|
| Severity | medium |
| Category | content |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — static source-page issue |

**Description**

On physical page 251 / printed page 232, block B003 extracts the printed phrase `Stadt und`
as `Stadtund`. Because the block supplies an approved event's route and investigation-object
fields, it cannot be treated as verbatim source text until corrected. The GUI's manual correction
preserves the machine text and records the reviewer and reason; the final human text retains all
original line breaks and soft hyphens and changes only `Stadtund` to `Stadt und`.

**Repro Steps**

1. Open physical page 251 in the original-page review view.
2. Compare the last two lines of B003 in the page image with the extracted-text panel.
3. Observe `Stadt und` in the image and `Stadtund` in the extracted text.

### ISSUE-003: Arbitrary 12-block cap rejects one valid dated observation unit

| Field | Value |
|---|---|
| Severity | medium |
| Category | functional / ux |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — failure state is durably visible in the run timeline |

**Description**

The source itself labels the continuous segment `24-/25. Jan.`. Its verified boundary runs from
P0251_B004 through P0253_B004 and therefore contains 13 ordered blocks. The model selected that
boundary correctly and stopped before P0253_B005 (`26. Januar.`), but the workbench rejected the
draft because an undocumented validation rule allowed at most 12 blocks per event. Splitting the
row merely to satisfy that cap would corrupt the approved comparison unit. The cap was removed;
the meaningful gates remain same-source identity, existing ordered blocks, field-level anchors,
page verification and human approval.

**Repro Steps**

1. In the Richthofen batch thread, ask for one event covering the source-defined `24-/25. Jan.`
   segment on physical pages 251–253.
2. Let the model read all three pages and submit its event ending at P0253_B004.
3. Observe the failed run reason `an event row may reference at most 12 blocks` even though the
   proposal has one ordered 13-block segment and excludes the next date.

Evidence screenshot:
`C:\Users\huanghai\.codex\visualizations\2026\08\06\019fd677-de66-7962-85a0-fbab9381cb1a\dogfood-event-table\screenshots\failed-run-reason-visible.png`

### ISSUE-004: One malformed model action discards a completed reading turn

| Field | Value |
|---|---|
| Severity | medium |
| Category | functional / ux |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — failure state is durably visible in the run timeline |

**Description**

The model successfully read physical pages 251, 252 and 253, then returned a long action whose JSON
was missing a delimiter. The harness marked the entire run failed, forcing the researcher to resend
the task even though all source reads were still valid. A model action format error is recoverable:
the run now records `model_action_invalid`, supplies a concise parse error to the same model context,
and asks it to retry the same action as one shorter valid JSON object. Network failures and internal
program errors still fail the run.

**Repro Steps**

1. Retry the 13-block `24-/25. Jan.` event after removing the arbitrary block cap.
2. Observe three successful `source.page` calls in the run timeline.
3. Observe the run fail with `Expecting ',' delimiter` before any event proposal is recorded.

Evidence screenshot:
`C:\Users\huanghai\.codex\visualizations\2026\08\06\019fd677-de66-7962-85a0-fbab9381cb1a\dogfood-event-table\screenshots\malformed-model-action-visible.png`

### ISSUE-005: Source-relative block IDs are rejected despite an explicit source

| Field | Value |
|---|---|
| Severity | medium |
| Category | functional / ux |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — failure state is durably visible in the run timeline |

**Description**

After two malformed-action retries, the model submitted a valid event action using the short block
labels shown throughout the research discussion (`P0251_B004`, etc.) together with the exact
`source_id`. The event tool required composite database IDs and rejected the action as referencing
unknown blocks. Because the source scope is explicit and every resolved block is still checked for
existence, ordering and source ownership, the input boundary now qualifies source-relative block IDs
as `{source_id}:{block_id}`. Already-qualified IDs remain unchanged.

The run header also no longer claims that every completed run with a failed tool “self-corrected”; it
uses the neutral wording “本轮记录 N 次工具错误”.

**Repro Steps**

1. Let the model retry the `24-/25. Jan.` event after a JSON-format correction.
2. Observe a valid `research_event.propose_batch` action containing the explicit source ID and
   source-relative block IDs.
3. Observe the tool fail with `event candidate references an unknown block`, followed by a final
   message asking for the same IDs with the source prefix.

Evidence screenshot:
`C:\Users\huanghai\.codex\visualizations\2026\08\06\019fd677-de66-7962-85a0-fbab9381cb1a\dogfood-event-table\screenshots\short-block-id-tool-failure.png`

### ISSUE-006: XML-wrapped tool action is displayed as a completed assistant answer

| Field | Value |
|---|---|
| Severity | medium |
| Category | functional / ux |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — the incorrect completed state is durably visible |

**Description**

DeepSeek returned a valid `source.page` action wrapped as
`<json_logic><tool_call>{...}</tool_call></json_logic>`. The parser treated every response not
starting with `{` as prose, stored the wrapper as an assistant message and marked the run completed
without reading a page. The parser now unwraps only the two observed tags when they enclose the
entire response. It does not extract JSON examples embedded in ordinary prose, which avoids turning
discussion text into an unintended tool call.

**Repro Steps**

1. Ask the same thread to retry the page-scoped event after the short-ID fix.
2. Observe the run complete without any tool entries.
3. Observe the assistant message display literal `<json_logic>` and `<tool_call>` markup containing
   the unexecuted `source.page` action.

Evidence screenshot:
`C:\Users\huanghai\.codex\visualizations\2026\08\06\019fd677-de66-7962-85a0-fbab9381cb1a\dogfood-event-table\screenshots\xml-wrapped-tool-shown-as-final.png`

### ISSUE-007: Short preface before a tool action also produces a false completed run

| Field | Value |
|---|---|
| Severity | medium |
| Category | functional / ux |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — the incorrect completed state is durably visible |

**Description**

After the XML-wrapper fix, the model executed two `source.page` calls and then returned a short
sentence followed by the third valid page-read JSON object. The parser again stored the combined
text as a final answer and marked the run completed. It now accepts one complete trailing JSON
object only when it declares `type: tool_call`, consumes the end of the response and is preceded by
plain text. A trailing `type: final` example remains prose, and all executed tools still pass through
the normal allowlist and domain validation.

**Repro Steps**

1. Retry the same event with XML-wrapper compatibility enabled.
2. Observe successful page reads for physical pages 251 and 252.
3. Observe the assistant display “继续读取物理页253……” followed by literal tool JSON while the run
   is marked completed and page 253 was never called.

Evidence screenshot:
`C:\Users\huanghai\.codex\visualizations\2026\08\06\019fd677-de66-7962-85a0-fbab9381cb1a\dogfood-event-table\screenshots\prefaced-tool-shown-as-final.png`

### ISSUE-008: Draft original text becomes stale after an anchored source repair

| Field | Value |
|---|---|
| Severity | medium |
| Category | functional / ux |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — the stale draft and repaired source are durable states |

**Description**

The event copied its 13-block original text when the draft was created. Subsequent page review fixed
several local extraction errors while keeping the same anchors and event boundary. The draft form
continued to show the old text, and approval would fail the verified-source check unless the
researcher manually recopied three pages. Silent synchronization would erase the distinction between
the model proposal and later human repair.

Draft events now offer “按当前已核锚块刷新原文”. It reads the effective text in anchor order and
fills only the local approval form; it neither updates the database nor approves the event. The final
decision persists the edited form and records the names of edited fields in the audit event.

**Repro Steps**

1. Create the 13-block draft event.
2. Open its pages and repair a local source-text error without changing the anchors.
3. Return to the event table and observe that the original-text form still contains the pre-repair
   spelling, with no direct way to refill it from the anchors.

Evidence screenshot:
`C:\Users\huanghai\.codex\visualizations\2026\08\06\019fd677-de66-7962-85a0-fbab9381cb1a\dogfood-event-table\screenshots\stale-draft-original-after-repair.png`
