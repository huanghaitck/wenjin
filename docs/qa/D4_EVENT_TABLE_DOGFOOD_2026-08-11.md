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

### ISSUE-019: The agent describes the next page read and completes without the required mutation

| Field | Value |
|---|---|
| Severity | medium |
| Category | agent completion / task contract |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — two completed runs preserve the premature final messages |

**Description**

When explicitly instructed to read through the next date boundary and make exactly one successful
`research_event.propose_batch` call, DeepSeek read pages 236–237 and completed with “continue reading
page 238.” A corrective run read page 238 and again completed with “continue reading page 239.” The
model described its next action instead of executing it, while the harness marked both runs complete.

The runtime now recognizes only the narrow, explicit Chinese completion form “恰好/只成功调用一次
`tool.name`.” If that named tool has not completed in the current run, a final response is rejected and
the omission is returned to the model as a bounded completion-contract error. Negative instructions
such as “不要调用” are not inferred as requirements, and ordinary natural-language tasks remain
unchanged.

**Repro Steps**

1. Ask the guided agent to read from page 236 to the next date boundary and explicitly require one
   successful `research_event.propose_batch` call.
2. Let it read one or two pages and return a final sentence promising another page read.
3. Observe that the unpatched run becomes `COMPLETED` without an event; after the fix, the same final
   answer triggers `required_tool_missing` and the run continues with its existing page observations.

### ISSUE-020: A travel author's generalization is flattened into an unqualified fact

| Field | Value |
|---|---|
| Severity | high |
| Category | source criticism / event semantics |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — compared against David physical pages 236–238 |

**Description**

For David's 14 January 1873 event, the model summarized a long first-person explanation as “Chinese
cemetery customs and burial institutions.” The page supports that David wrote this explanation, but
does not independently establish every institutional claim inside it. Flattening the speaker and the
claim type would let a travel author's generalization enter the comparison table as an unqualified
historical fact.

The event harness now requires source-derived fields to preserve both speaker and epistemic status.
Witnessed actions and measurements must remain distinct from the author's interpretation, inference,
uncertainty and attributed information. During GUI approval, the field was revised to identify the
passage as David's statement and to reserve independent factual use pending corroboration.

**Repro Steps**

1. Ask the guided agent to code David's 14 January entry from physical pages 236–238.
2. Inspect the proposed investigation field for the cemetery discussion.
3. Observe whether David's explanation is preserved as a source statement or rewritten as a fact
   about Chinese institutions.

### ISSUE-021: Natural completion wording does not activate the required-tool contract

| Field | Value |
|---|---|
| Severity | medium |
| Category | agent completion / task contract |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — run receipt and thread history preserve the premature final message |

**Description**

After source repair, the operator asked DeepSeek to read pages 239–240 and “再调用
`research_event.propose_batch` 一次”. The model returned “读取法文原件物理页239以重新核对该日条目全文”
and the run completed without creating a new draft. The existing completion guard recognized only the fixed phrase
“恰好/只成功调用一次 tool.name”, so ordinary Chinese word order did not activate the same contract.

The runtime now recognizes both the original narrow phrase and explicit forms such as “再调用 tool.name 一次”.
It still requires the word “一次”, so ordinary discussion of a tool or a negative instruction is not converted into a
mutation requirement.

**Repro Steps**

1. Ask the guided agent to read two pages and then call `research_event.propose_batch` once, using the natural word
   order “再调用 research_event.propose_batch 一次”.
2. Let the model return a final sentence promising or describing the first page read.
3. Before the fix the run becomes `COMPLETED`; after the fix the runtime returns `required_tool_missing` and keeps the
   same run active until the named tool succeeds or the bounded retry fails.

### ISSUE-022: Internal tool transcripts can be accepted as a completed researcher answer

| Field | Value |
|---|---|
| Severity | high |
| Category | agent completion / conversation boundary |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A — run `RUN_9ba56ab24060428bbbd869ddeeb69730` preserves the malformed final message |

**Description**

During a bounded search for Piassetsky's actual departure from Hanzhong, DeepSeek completed its search and two page
reads but returned a plain-text sequence beginning with `TOOL_RESULT` instead of the requested A–E research summary.
The plain-text fallback treated that internal transcript as a safe final answer, exposed tool payloads in the main
conversation and marked the run complete.

The runtime now rejects any proposed final answer containing an internal `TOOL_RESULT` line, returns a concise format
error to the same model run and asks for a researcher-readable synthesis. Previously stored malformed assistant
transcripts are also excluded from bounded thread history so one bad completion cannot contaminate later turns.

**Repro Steps**

1. Run a guided task that performs `source.search` followed by one or more `source.page` calls.
2. Let the provider return the accumulated internal transcript as plain final text beginning with `TOOL_RESULT`.
3. Before the fix the run becomes `COMPLETED` and displays the transcript; after the fix it records
   `model_action_invalid` and continues until the model returns readable research prose or exhausts the bounded run.

**Live regression verification**

Run `RUN_09fb814f2d0b40b1a7c6060e204dac9d` exercised the repaired runtime through the real GUI with
`deepseek-v4-flash`. The model called `source.page` exactly once for physical page 106, called no write tool, and
returned a readable A/B/C source assessment without exposing `TOOL_RESULT` or JSON. Its recorded bounded-history
snapshot excludes malformed message `MSG_ff493f5dca4e422c9deac4b224f10688`, confirming that an already stored bad
transcript no longer contaminates a later guided run.

### ISSUE-023: Configured visual repair model has no actionable proposal control

| Field | Value |
|---|---|
| Severity | high |
| Category | functional / source repair |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A - static state captured in `screenshots/piassetsky-p109-before.png` |

**Description**

On Piassetsky physical page 109 the repair panel reports `needs_review · partial`, identifies the configured visual
helper as `ollama · qwen3-vl:4b-instruct-q4_K_M`, and says that the page has no model proposal. However, the visible
panel provides no “生成当前页建议” control. DOM inspection confirms that the sole `#ocrPropose` button is rendered
with the `hidden` attribute, so a normal researcher cannot ask the configured visual helper to propose a repair for
the page.

**Repro Steps**

1. Open the Piassetsky volume II facsimile from Project Sources.
2. Jump to physical page 109, whose source state is `needs_review · partial`.
3. Inspect the “模型修复建议” panel: the visual profile and empty-state text are visible, but the proposal action is
   absent. See `screenshots/piassetsky-p109-before.png`.

### ISSUE-024: A collapsed visual OCR response cannot preserve paragraph structure

| Field | Value |
|---|---|
| Severity | high |
| Category | functional / source repair |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A - static proposal captured in `screenshots/piassetsky-p109-collapsed-proposal.png` |

**Description**

The real `qwen3-vl:4b-instruct-q4_K_M` call for Piassetsky physical page 109 returned the printed page number and four
visible paragraphs inside one OCR block, separated by blank lines. The proposal editor can correct text inside a
block but cannot split that block. Accepting the proposal unchanged would therefore collapse paragraph and cross-page
structure even though the model response contains enough separators to preserve it.

The normalizer now splits a sole OCR block on explicit blank-line paragraph boundaries. If the first separated line
is a standalone decimal page number and no printed page was otherwise supplied, it is moved into the proposal's
printed-page candidate. Both recoveries remain warnings in the pending proposal and still require human review.

**Repro Steps**

1. On physical page 109, request a proposal from the configured visual helper.
2. Wait for the pending proposal to appear.
3. Observe that the pre-fix proposal contains one editable block beginning with `651` and four paragraphs separated
   by blank lines. See `screenshots/piassetsky-p109-collapsed-proposal.png`.

### ISSUE-025: Source-repair controls overlap in the normal desktop viewport

| Field | Value |
|---|---|
| Severity | high |
| Category | visual / functional |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A - static overlap captured in `screenshots/source-repair-controls-overlap.png` |

**Description**

At the normal 1258-pixel test viewport, the repair panel's intrinsic form width exceeds its grid column and its fixed
row layout is shorter than the required controls. The “保存页码关系” button therefore extends across the visual-model
row and covers “生成当前页建议”; the browser correctly refuses a normal click because it would land on the page-number
button. The repair panel now uses one vertical scroll surface, zero-minimum grid columns for its review form, and
natural-height sections, so controls remain in document order without overlapping.

**Repro Steps**

1. Open an unverified PDF page with a configured visual helper at the default desktop viewport.
2. Attempt to click “生成当前页建议”.
3. Observe that the page-number save control covers the visual-model action. See
   `screenshots/source-repair-controls-overlap.png`.

### ISSUE-026: Human reviewer cannot restore a block omitted by visual OCR

| Field | Value |
|---|---|
| Severity | high |
| Category | functional / source repair |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A - pending proposal captured in `screenshots/piassetsky-p111-missing-date-block.png` |

**Description**

The real visual-model proposal for Piassetsky physical page 111 omitted the independently printed date heading
`21 МАЯ.`. The reviewer could edit the three proposed blocks but could neither insert the missing heading nor remove
an unusable block. Accepting the proposal would therefore erase a visible temporal boundary from the page structure.

The pending-proposal editor now lets the reviewer add or delete blocks before acceptance. Final block order is
recomputed from the reviewed page sequence, so model-provided order values cannot leave gaps after a deletion.

**Repro Steps**

1. Open physical page 111 and request a proposal from the configured visual helper.
2. Compare the three proposed blocks with the original page, where `21 МАЯ.` appears between the first and second
   prose blocks.
3. Before the fix, observe that no control can add the missing heading. See
   `screenshots/piassetsky-p111-missing-date-block.png`.

**Live regression verification**

The still-pending real proposal survived the server restart and exposed the new add/delete controls. Through the
workbench UI, the reviewer retained the first proposed slot for the page-opening continuation, changed the second
slot to the missing `21 МАЯ.` heading, used the third slot for the morning-departure paragraph, and added a fourth
slot for the landscape paragraph. The reviewed page was accepted as printed page 653, and relation
P110 B2 -> P111 B1 was then confirmed as a continuation. The accepted four-block result is captured in
`screenshots/piassetsky-p111-repaired-4blocks.png`.

### ISSUE-027: Saving a printed-page mapping discards pending human OCR edits

| Field | Value |
|---|---|
| Severity | critical |
| Category | functional / source repair / edit preservation |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A - preserved by the accepted P112 proposal and audit trail |

**Description**

While reviewing Piassetsky physical page 112, the reviewer replaced a collapsed, incomplete visual-model response
with three source-checked blocks and then saved the printed-page mapping. That action reloaded the source
asynchronously and silently restored the original pending proposal. The following acceptance therefore committed the
old model text instead of the reviewed text.

Saving a printed-page mapping now updates the current page label without reloading the source or replacing unsaved
proposal edits. A previously human-repaired page can also be revised again as a full page: blocks may be added or
removed, and the new correction creates a fresh audit-backed repair instead of treating the first human decision as
irreversible.

### ISSUE-028: GLM-4.6V-Flash page transcription times out in implicit thinking mode

| Field | Value |
|---|---|
| Severity | high |
| Category | model adapter / visual OCR |
| URL | `http://127.0.0.1:8766/` |
| Repro Video | N/A - the failed P115 request left no proposal by design |

**Description**

The configured `glm-4.6v-flash` profile passed the provider connection test but its first real page request ended with
`The read operation timed out`. The official model documentation exposes an explicit thinking-mode switch; the
generic adapter had omitted it, allowing a transcription-only request to spend time in the model's reasoning phase.

The adapter now sends `thinking: {type: disabled}` only for GLM-4.6V-family requests and reports provider timeouts
with the configured duration. Other OpenAI-compatible visual profiles keep the existing payload.

**Live provider verification**

A replacement key passed the authenticated `/models` probe. A single, non-concurrent retry against Piassetsky
physical page 115 still returned HTTP 429. A bounded diagnostic call exposed provider code `1305` and the message
that the model was currently overloaded. This distinguishes provider capacity from an invalid key, local
concurrency or a page-validation failure. Visual requests are now serialized process-wide at one concurrent call,
and the UI reports only the provider's bounded `code` and `message` fields.

### ISSUE-029: Planning mode selection is not retained across a browser refresh

| Field | Value |
|---|---|
| Severity | medium |
| Category | conversation / researcher intent |
| URL | `http://127.0.0.1:8766/` |

**Description**

The independent-versus-guided planning selector previously lived only in transient page state. A browser refresh
returned it to independent planning, making it easy to hide the approved shared design unintentionally before a
follow-up run. The selection is now retained in browser-session storage and remains explicit in every run snapshot;
the researcher's hidden baseline is still never injected into independent mode.

### ISSUE-030: A failed batch proposal could be retried despite a one-call instruction

| Field | Value |
|---|---|
| Severity | high |
| Category | agent harness / mutation boundary |
| URL | `http://127.0.0.1:8766/` |

**Description**

During the real 22 May event run, the first `research_event.propose_batch` action failed validation because its
`original_text` field lacked a complete anchor. The previous guard counted only completed calls, so the model could
submit the mutating batch tool again even though the researcher had required one call and no retry on failure.

The runtime now treats the first batch-tool action as the sole attempt regardless of success. A later model action
for the same tool is blocked before a second tool-call record or mutation is created, and the run records
`tool_retry_blocked`. A failed first attempt may be summarized to the researcher, but cannot be silently corrected by
performing the mutation again in the same run.

### ISSUE-031: Low-resolution page images make old-script OCR structurally unreliable

| Field | Value |
|---|---|
| Severity | high |
| Category | model adapter / source repair |
| URL | `http://127.0.0.1:8766/` |

**Description**

The first visual-model trials used the ordinary two-times page render. On the 1880 Russian facsimile this encouraged
modernized spelling, missing date headings and unstable punctuation even when the printed page remained readable to a
human reviewer. Model-assistance requests now use a four-times derived render while the original PDF remains the
source authority. The high-resolution image is retained inside the source's derived folder with its own digest; it is
still only a proposal input and never becomes citable evidence.

### ISSUE-032: Candidate-aware OCR can preserve useful structure and copy old OCR errors

| Field | Value |
|---|---|
| Severity | medium |
| Category | model quality / human review boundary |
| URL | `http://127.0.0.1:8766/` |

**Description**

The `page-ocr-v2` prompt gives the visual model the existing page text as an explicitly untrusted candidate. This
substantially improved paragraph recovery and old-Russian spelling preservation, but the live `glm-4.6v` proposal for
physical page 118 also copied candidate errors such as `іпелъ`, `с.идѣть`, `значить` and the scientific name
`Genicus tancolo`. It also left `23 МАЯ.` inside prose and retained layout-only line-end hyphens.

The result confirms the intended boundary: candidate text may help alignment, but the rendered original page is the
authority and the proposal remains unusable until a reviewer edits and accepts it. Through the real workbench UI the
reviewer rebuilt page 118 as four prose/heading blocks plus the footnote
`Зеленый дятелъ (Gecinus tancolo Gould).`, saved printed page 660 and then accepted the proposal.
The accepted page and its two corrected cross-page relations are captured in
`screenshots/piassetsky-p118-glm46v-repaired.png`.

### ISSUE-033: Full-page repair can silently move a confirmed cross-page relation onto a footnote

| Field | Value |
|---|---|
| Severity | critical |
| Category | source repair / page relation provenance |
| URL | `http://127.0.0.1:8766/` |

**Description**

Accepting the rebuilt physical page 118 changed its block count and order. Because full-page repair reused block IDs
by order, the existing P118-to-P119 relation retained `P0118_B005`, although that ID now represented the footnote
rather than the final prose paragraph. The UI therefore displayed a valid-looking, previously confirmed relation from
the bird-name footnote into the next page's prose.

Full-page repair now snapshots every affected endpoint before replacing blocks and compares it with the reviewed
blocks afterwards. A semantically matching endpoint may move to its new block ID without losing the human decision;
minor text correction does not invalidate it. If no sufficiently similar endpoint survives, the relation is reset to
`needs_review`, its prior human value is cleared, and a new two-page location anomaly is opened. It can no longer
silently retain human approval for different content.

**Live regression context**

The already-accepted P118 relation was corrected through the workbench to P118 block 4 -> P119 block 1 and confirmed
as a continuation. The preceding boundaries P115 block 2 -> P116 block 1, P116 block 4 -> P117 block 1 and P117 block
2 -> P118 block 1 were also checked against adjacent original pages. Printed-page mappings 657-660 are now visible
for physical pages 115-118, and the saved P116/P118 proposal edits survived the separate page-number save action.

### ISSUE-034: The approved comparison design contains fields that the event harness cannot store

| Field | Value |
|---|---|
| Severity | critical |
| Category | research harness / comparison schema |
| URL | `http://127.0.0.1:8769/` |

**Description**

The approved research design requires event-level comparison of movement mode, source genre, participant visibility
and outcome destination. The live three-case inventory audit could not assess those dimensions because neither the
event table nor `research_event.propose_batch` exposed them. This was a harness omission rather than a source gap; if
left unchanged, another 30-50 rows per case would accumulate in a schema that cannot answer the approved question.

Project schema 12 adds `movement_mode`, `genre`, `participant_visibility` and `outcome_destination` to the existing
event rows. The proposal contract, field-level anchor rules, event editor and task specification expose the same four
fields. Existing events migrate in place with empty values and remain approved; the application does not invent
backfill values.

Approved rows can now be revised by a human without replacing their event IDs. Every new non-empty source-derived
field still requires explicit anchors belonging to the event, the original text and verified-page gates are rerun,
and the audit trail records changed values and anchors as `research_event_revised`. In the live workbench,
`EVT_df920c3550044f428d46a53edfa7ce1b` was revised against P0116_B002 to code role-visible but unnamed Chinese
soldiers and one porter, while movement mode, genre and outcome destination remained PND. The UI displayed schema 12,
the new comparison fields and the saved revision.
