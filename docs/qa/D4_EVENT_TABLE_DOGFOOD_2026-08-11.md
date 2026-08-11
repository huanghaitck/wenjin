# Dogfood Report: Field-Anchored Event Reading

| Field | Value |
|---|---|
| Date | 2026-08-11 |
| App URL | `http://127.0.0.1:8766/` |
| Session | `hrw` |
| Scope | Richthofen physical pages 250–260, cross-page relation, block verification and model correction |

## Summary

| Severity | Count |
|---|---:|
| Critical | 0 |
| High | 0 |
| Medium | 16 |
| Low | 0 |
| **Total** | **16** |

The first nine findings were fixed in bounded Git branches and verified by the earlier 99-test suite.
The real GUI flow then produced and human-approved the 13-block `24-/25. Jan.` event
`EVT_c05991d5c1714c728c54f0ae607fc95c` plus corrected 26 and 27 January rows. Approval remains
explicitly below evidence freeze. The corrected 28 January row was then approved after all 19 blocks
were verified; it remains below evidence freeze. ISSUE-010 remains under investigation and created no
partial row. ISSUE-011 and ISSUE-012 have bounded fixes and regression coverage. The current
environment check and full 100-test suite passed before their commit. ISSUE-013 is handled by an
exact human repair plus a shorter verbatim span; ISSUE-014 has a bounded one-retry fix. The current
environment check and prior 101-test suite passed. ISSUE-015 records a provider wrapper that made a
page-read request look like a completed answer; the parser now accepts that exact whole-response
shape without extracting tool examples from prose. ISSUE-016 adds a one-successful-batch-per-run
mutation gate after a model submitted duplicate 1 February drafts. The current full 103-test suite
and frontend syntax check pass.

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

### ISSUE-009: Missing-data codes can masquerade as anchored source facts

| Field | Value |
|---|---|
| Severity | medium |
| Category | evidence integrity |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — proposals and human decisions are durably recorded |

**Description**

While proposing the 26 and 27 January rows, DeepSeek placed `NR` directly in
`chinese_participants` and `institutional_task`. After the anchor-required error, it made the call
pass by attaching ordinary narrative blocks to those `NR` values. An anchor proves where a positive
source statement occurs; it cannot prove that a field is absent. The workbench therefore accepted a
missing-data code as if it were a source-derived fact.

Creation and approval now reject `NR`, `UNC` and `PND` at the start of any source-derived field. The
error tells the model or reviewer to leave that field blank and put the code plus explanation in
`missing_reason`. The two faulty drafts were rejected in the GUI, the same model resubmitted corrected
rows, and a simulated historian checked physical pages 253–254, repaired three local extraction
errors, refreshed the anchored text and approved both rows.

**Repro Steps**

1. Ask the model to encode a dated segment whose page does not state an institutional task.
2. Submit `institutional_task: "NR"` with an arbitrary page-block anchor.
3. Before the fix the candidate is created; after the fix the tool rejects it and requires a blank
   source field plus `missing_reason`.

Evidence screenshot:
`C:\Users\huanghai\.codex\visualizations\2026\08\06\019fd677-de66-7962-85a0-fbab9381cb1a\dogfood-event-table\screenshots\missing-code-drafts-rejected-and-corrected.png`

### ISSUE-010: A multi-page reading run loses its proposed output at the provider deadline

| Field | Value |
|---|---|
| Severity | medium |
| Category | reliability / ux |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — the failed run and completed page calls are durably recorded |

**Description**

The guided execution asked DeepSeek to read only the 28 and 29 January segments and submit exactly
two event drafts. The model successfully called `source.page` for physical pages 254 through 258,
but its next provider step exceeded the fixed 180-second deadline. The run was marked `FAILED` and
created no draft. The page reads remain in the audit trail, but the interface offers no checkpointed
continuation from those completed tool results, so the researcher must reduce the task and ask the
model to read overlapping pages again.

This is not an evidence-integrity failure: no partial row was approved or frozen. It is a research
task granularity and recovery problem. The immediate safe workaround is one dated segment per run;
the product fix should preserve completed tool context and make timeout continuation explicit rather
than silently increasing the global deadline.

**Repro Steps**

1. In guided execution, ask for two consecutive dated events whose second boundary must be located
   by reading forward.
2. Observe five completed `source.page` calls for physical pages 254–258.
3. After 180 seconds, observe the thread state change to `FAILED` with no event drafts created.

Evidence screenshot:
`C:\Users\huanghai\.codex\visualizations\2026\08\06\019fd677-de66-7962-85a0-fbab9381cb1a\dogfood-event-table\screenshots\provider-timeout-after-five-page-reads.png`

### ISSUE-011: A whole-action `<{...}>` wrapper is displayed instead of executing the tool

| Field | Value |
|---|---|
| Severity | medium |
| Category | functional / ux |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — the literal assistant messages and completed runs are durable |

**Description**

During correction of the rejected 28 January row, DeepSeek returned the valid
`research_event.list` action as `<{"type":"tool_call",...}>`. The parser already handled named XML
wrappers and a short prose preface, but not this single unnamed angle wrapper. It stored the literal
text as the assistant answer and marked the run completed without calling the tool.

The parser now unwraps this form only when one angle-bracket pair encloses one complete JSON object
and consumes the entire provider response. An embedded example such as `示例：<{...}>` remains prose,
so ordinary discussion cannot become an unintended tool call.

**Repro Steps**

1. Ask DeepSeek to read `research_event.list` while correcting a rejected event.
2. Observe the assistant response `<{"type":"tool_call","tool":"research_event.list",...}>`.
3. Observe the run marked `COMPLETED` with no `research_event.list` tool entry.

Evidence screenshot:
`C:\Users\huanghai\.codex\visualizations\2026\08\06\019fd677-de66-7962-85a0-fbab9381cb1a\dogfood-event-table\screenshots\wrong-thread-reset-and-angle-wrapper.png`

The screenshot also records that the correction was sent while a different thread was visibly
selected. A separate automatic thread-reset defect was investigated but not reproduced: explicitly
selecting the batch thread remained stable across later checks. This is treated as a tester routing
mistake aided by a global event panel, not counted as another product issue.

### ISSUE-012: Opening an event source leaves the page-number control on a different page

| Field | Value |
|---|---|
| Severity | medium |
| Category | ux / evidence review |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — the conflicting page indicators are visible in one screen |

**Description**

Opening the four-page 28 January event correctly displayed its first anchor page, physical page 254
/ printed page 235. The physical-page input still showed `257`, the final page previously reviewed.
The page rail and text belonged to page 254, so a researcher could record a correction against the
wrong page number even though the underlying source block ID remained correct.

The source renderer now writes the current page's physical number into the jump control every time
the page changes. The approval error also names every still-unverified block ID; in this run it
identified `P0254_B009`, which was checked against the image before the 19-block event was approved.

**Repro Steps**

1. Review physical page 257, then return to the event table.
2. Open the 28 January event whose first anchored page is 254.
3. Observe printed page `235` and page-254 text while the physical-page input still shows `257`.

Evidence screenshot:
`C:\Users\huanghai\.codex\visualizations\2026\08\06\019fd677-de66-7962-85a0-fbab9381cb1a\dogfood-event-table\screenshots\issue-012-event-open-page-number-desync.png`

Fixed-state screenshot:
`C:\Users\huanghai\.codex\visualizations\2026\08\06\019fd677-de66-7962-85a0-fbab9381cb1a\dogfood-event-table\screenshots\issue-012-fixed-page-number-synced.png`

### ISSUE-013: One extracted block mixes the end of 29 January with the 30 January heading

| Field | Value |
|---|---|
| Severity | medium |
| Category | content / evidence boundary |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — static page image and extracted block |

**Description**

On physical page 258 / printed page 239, the first printed line completes the 29 January paragraph
with `700 li weit abwärts.`. The marginal `30. Januar,` marker belongs before the next paragraph, but
the extractor inserted it inside `ein hoher`, producing one block that contains the prior-day ending,
the next-day marker and next-day body text. The model correctly stopped before that block and marked
the sentence incomplete; approving the draft would therefore have frozen an artificial boundary.

The block was manually repaired to restore reading order without changing the original image. The
29 January row was rejected and must be resubmitted with the exact short span ending at
`700 li weit abwärts.`; the rest of the repaired block belongs to 30 January. This uses the existing
block-plus-verbatim-substring gate and avoids adding a speculative block-splitting subsystem.

**Repro Steps**

1. Create the 29 January row from P0257_B004 through P0258_B003.
2. Open physical page 258 and compare B004 with the original image.
3. Observe that B003 ends mid-sentence while B004 begins with its completion and then interleaves
   `30. Januar,` into the following sentence.

Evidence screenshot:
`C:\Users\huanghai\.codex\visualizations\2026\08\06\019fd677-de66-7962-85a0-fbab9381cb1a\dogfood-event-table\screenshots\issue-013-one-block-spans-two-dates-detail-2.png`

### ISSUE-014: One empty provider message fails the whole research run

| Field | Value |
|---|---|
| Severity | medium |
| Category | reliability / ux |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — failed run is durably visible in the thread |

**Description**

When asked to resubmit the corrected 29 January boundary, DeepSeek returned a normal response
envelope with empty message content. The workbench immediately marked the run failed before any tool
call, forcing the researcher to resend a long correction even though no unsafe data had been written.

The runtime now records `model_response_empty` and retries the same action once inside the same run,
including the original objective and thread history. A second empty response still fails the run; the
harness does not hide a persistent provider problem or retry indefinitely.

**Repro Steps**

1. Send the page-scoped correction in the existing guided thread.
2. Receive an empty assistant content field from the configured provider.
3. Observe the thread switch to `FAILED` with reason `agent provider returned empty content` and no
   event draft created.

Evidence screenshot:
`C:\Users\huanghai\.codex\visualizations\2026\08\06\019fd677-de66-7962-85a0-fbab9381cb1a\dogfood-event-table\screenshots\issue-014-empty-model-content-fails-run.png`

### ISSUE-015: An unclosed angle wrapper turns a page-read action into a completed answer

| Field | Value |
|---|---|
| Severity | medium |
| Category | reliability / agent protocol |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — the durable run and assistant message preserve the response |

**Description**

While continuing the 31 January event, DeepSeek returned an otherwise valid `source.page` action
whose whole response began with `<` but omitted the closing `>`. The parser treated the string as a
plain final answer, so run `RUN_cb8d3a2406ae461482b0bf834544364d` appeared `COMPLETED` after reading
only page 259 and created no event row. This is a silent workflow stop rather than a safe explicit
failure.

The parser now accepts this exact whole-response shape only when removing the single leading angle
bracket yields one complete JSON object. The same text embedded in prose remains a final answer, so
the compatibility rule does not search arbitrary prose for executable actions.

**Repro Steps**

1. Ask the guided agent to read pages 259–260 and propose the 31 January event.
2. After page 259, receive `<{"type":"tool_call",..."physical_page":260}}` without a closing `>`.
3. Observe the run complete with the wrapped tool request stored as assistant text and no draft row.

### ISSUE-016: One run can submit the same event batch more than once

| Field | Value |
|---|---|
| Severity | medium |
| Category | reliability / mutation boundary |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — duplicate completed tool calls are durable in the run ledger |

**Description**

During the 1 February extraction, the model successfully called `research_event.propose_batch`, then
called the same mutating tool again with a near-duplicate event instead of returning a final answer.
Both calls completed and created draft rows before the run wandered back to an unrelated page read.
The user had explicitly requested exactly one row, but the harness enforced only the batch payload,
not one successful mutation per run.

`research_event.propose_batch` is already a batch operation, so the runtime now permits only its first
successful call in a run. A later call is recorded as failed with an explicit instruction to return a
final answer; no second mutation occurs. Read-only tools remain repeatable.

**Repro Steps**

1. Ask for exactly one event covering physical pages 260–262.
2. Let the first `research_event.propose_batch` complete.
3. Observe a second completed call create a near-duplicate draft in the same run.

### ISSUE-017: A bottom note can be selected as the previous page's continuation endpoint

| Field | Value |
|---|---|
| Severity | high |
| Category | source location / page relation |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — compared against rendered physical pages 235–236 |

**Description**

On David physical page 235, the extractor classified the running signature `VOYAGE EN CRISE / i — J5`
as a footnote. The automatic relation builder treated every non-header/footer block as body text and
therefore proposed `P0235_B010 → P0236_B002`, skipping the actual unfinished paragraph in
`P0235_B009`. The relation was then mistakenly confirmed in the page review UI.

Automatic main-text continuation candidates now use paragraph blocks only. The page review UI also
exposes both endpoints and the continuation judgment as one auditable manual correction, so an
already-imported bad relation can be fixed without overwriting repaired source text or editing the
project database directly.

**Repro Steps**

1. Open David physical page 235 and inspect its relation to page 236.
2. Observe that the machine relation starts from the bottom signature block rather than the last body paragraph.
3. Compare the rendered pages and correct the relation to `P0235_B009 → P0236_B002`.

### ISSUE-018: A draft event keeps stale printed-page metadata after human page repair

| Field | Value |
|---|---|
| Severity | high |
| Category | evidence snapshot / approval |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — visible in the draft event metadata and project database |

**Description**

The David 13 January candidate was created before physical page 235 had its printed page reconstructed.
After the reviewer set it to printed page 225, the draft still listed only printed page 226. Approving
the row would therefore have preserved stale page metadata even though the linked page had already
been human-corrected.

Approval now refreshes page IDs, physical pages and printed pages from the exact currently verified
blocks immediately before the event row is approved. Rejected candidates retain their original draft
snapshot. The approval audit records that this refresh occurred.

**Repro Steps**

1. Create an event spanning physical pages 235–236 while page 235 has no printed page label.
2. Reconstruct page 235 as printed page 225 in the source review UI.
3. Approve the event and observe that the approved row now records printed pages 225–226.
