# Wenjin | Humanities and Social Science Research Workbench User Manual

English | [中文](USER_MANUAL_ZH.md)

Version: 0.1.3 (the installer is not code-signed)

Verified: 2026-08-28

Scope: local literature organization, PDF repair, research dialogue, web discovery, evidence control, writing, and Word export

> **Boundary of this release**
>
> Wenjin is a local-first research workbench. It is not an unattended “write my paper” system and it does not replace Microsoft Word, Zotero, CNKI, or Obsidian. A feature that is not visible in the interface should not be assumed to exist. Restricted databases are not downloaded through unattended automation. The desktop application creates integrity-checked backups containing the project database and project artifacts; external long-term memory accepts only explicitly approved candidates.

## 0. Five-minute quick start for first-time AI users

1. **Open Wenjin.** On first launch, select **Configure main model**. Choose **Not now** only when you want to use the library and manual page tools without AI.
2. **Connect a model.** For DeepSeek or another hosted service, select the provider, enter the API key, refresh the model list, choose a model, and test the connection. Choose Ollama when it is already installed locally; Ollama does not require an API key.
3. **Create a project.** Open Project Workspace, create a project, and use a title that will still identify the research later. Do not mix unrelated papers in one project.
4. **Add material.** The easiest method is **+ Attach files** in chat. The same file is archived in the Research Library and exact duplicate bytes reuse one file version. You may also upload in the library or inventory a computer folder and approve selected candidates.
5. **Ask in ordinary language.** No command syntax is required. Example: “Inspect the spreadsheet I just uploaded. Report header and dirty-row problems first. Do not modify the file yet.” State the object, requested action, forbidden action, and stopping point whenever possible.
6. **Read run status.** The conversation shows public actions such as “searching files” and “tool returned,” not hidden chain-of-thought. Pending approvals and artifacts appear in the side panel.
7. **Approve carefully.** Ask mode pauses before opening a controlled site, clicking the computer, launching a program, running a command, or writing a file. Inspect the arguments, enter a decision reason, and approve. The same run continues automatically after approval.
8. **Open results.** In the desktop application, use **Open artifact** or double-click supported image and table artifacts. OCR, extracted tables, and charts remain candidates until human review.

When you do not know which workspace to use, state the goal in Research Chat. The main Agent inspects the current project, chooses the smallest necessary Skill, tool, or Domain Agent, and identifies decisions that still belong to the researcher.

## 1. Three principles to remember

1. **The original file remains authoritative.** Cleaned text, translations, model answers, and summaries are working derivatives. When a claim is uncertain, return to the exact page in the original PDF.
2. **Models produce candidates.** OCR repair, research plans, evidence, memory, and formal writing all pass through human decisions. “Pending” or “candidate” does not mean approved.
3. **Keep different kinds of information in different layers.** The library, project knowledge, Agent runs, and long-term memory have different purposes. Chat history and search results do not silently become durable knowledge.

## 2. The seven main workspaces

### 2.1 Project workspace

The Project Workspace is the default home. It lists registered local projects, shows the current project's phase and object counts, and surfaces source-page issues, pending decisions, recommended next actions, and recent activity.

The desktop application can create a project under a folder chosen by the researcher or register an existing Wenjin directory that contains `project.sqlite3`. The ordinary create button uses Wenjin's default application-data folder. Conversations, evidence, manuscripts, and run records remain project-specific, while the research library can reuse the same work and exact file version across projects.

Phase labels and next actions are navigation derived from existing project objects; they are not claims that the research itself has reached a particular intellectual conclusion. Version 0.1.3 does not delete or move project folders from inside the application. If a project is moved, register its new folder; Wenjin replaces the stale path for that project identity.

### 2.2 Research chat

Research chat is the default home page. Give each thread one bounded task, for example:

- verify whether a traveler actually arrived at a named place on a stated date;
- find every passage about pack animals and specimen cases in one volume;
- compare distance, movement cost, and local participants across several journeys;
- check whether a draft has turned hearsay into eyewitness testimony.

The right-hand Research Context panel exposes project sources, research plan, event register, library, web research, evidence and claims, evidence freeze and writing, research browser, and memory candidates. A saved conversation is useful for continuity but is not evidence.

Two planning modes are available:

- **Independent planning** withholds the researcher-intent baseline, approved shared plan, and previous thread history. Use it to see what a model proposes independently.
- **Execute the shared plan** loads the human-approved plan and a bounded recent thread history. Previous conversation still does not replace source pages.

Create a thread with the plus button before sending the first message. If no main model is available, configure and test one under **AI & Agent**.

Each thread also has an Agent access mode: Ask for approval, Auto-approve routine research, or Full access. These modes are described in Section 5.

#### Agent runtime and continuous threads

**AI & Agent — Status** shows the bundled Codex app-server, SDK version, and runtime availability. Project, library, source, evidence, writing, and Domain Agent operations share this one thread/turn lifecycle, while the actual research data remains in Wenjin's project and library databases. Users do not install a separate Codex application and do not need to know MCP or internal tool names.

Continuing with the same model reuses the app-server thread. A model switch, branch, or restored Wenjin thread seeds the new model thread with bounded recent discussion for continuity; conversation still does not become source evidence. Pressing Enter during a run steers the current turn. The stop symbol interrupts at a safe boundary and never restarts by itself. At about 90% of the model context window, app-server compaction runs automatically without deleting project sources, evidence, manuscripts, or the run ledger.

DeepSeek and compatible hosted endpoints use the Responses API. Ollama uses Codex's built-in local provider. Model tool reliability varies; when a small local model does not pass the connection and tool-call checks, choose another configured model rather than allowing a mock or silent fallback. MoA runs once per user turn, and adviser models cannot call tools.

#### Let the main Agent orchestrate existing capabilities

The main Agent can coordinate project tools instead of merely answering questions. For example:

```text
Check whether these PDFs already have usable text. Process existing text directly; use visual OCR only for pages that need it. Produce candidate Markdown, but do not write formal evidence.
```

The Agent first reads project state, then selects among reusable Skills, Computer Use, web research, the Writing Studio, and installed Domain Agents. It should reuse existing capabilities before proposing a new extension. A bounded specialist task may be delegated inside the current run; sustained specialist work can continue in the Domain Agent workspace.

#### Let the main Agent create a controlled extension

You may say “Help me create a Skill for this material” or “Help me create a Domain Agent.” The main Agent first asks about purpose, inputs, tools, permissions, outputs, and stopping conditions. Only after those answers and the required approval may it call `skill.create` or the Domain Agent project creator.

“Self-extension” means creating a versioned, validated Skill or Domain Agent project. It does not allow a model to silently rewrite Wenjin core. File creation, program launch, and commands still follow the selected access mode. New extensions cannot bypass source-page, evidence, writing, or release gates. New users should keep **Ask for approval** and inspect every target path and argument before a write.

### 2.3 Domain Agent

Domain Agents are for sustained tasks that require specialist terminology, schemas, databases, and deterministic tools. A Domain Agent has its own thread, isolated memory, allowlisted tools, and candidate artifacts. The main Agent may delegate a bounded task to it from Research Chat, or the researcher may open the Domain Agent workspace and speak to it directly.

The left sidebar imports a ZIP or extracted directory, selects an installed Agent, or starts **Create Agent**. Guided creation first creates a project and a dedicated chat. The main Agent asks one necessary question at a time: research object and stopping rule, materials, fields and databases, permissions, outputs, and human final review. It creates the project only after those boundaries are clear.

Each installed Agent has an explicit **Uninstall** action. After confirmation, Wenjin removes the installed copy, that Agent's model overrides, and its secure credentials. It does not delete the original ZIP, source project, user-bound local database, or historical records already stored in Wenjin projects.

The central composer accepts PDF, DOCX, spreadsheets, text, images, and spatial files. Files uploaded through either main chat or Domain Agent chat are also archived in the Research Library. Exact duplicate bytes reuse one file version rather than creating another copy. Archival does not mean that a file has been read or qualified as evidence.

The pills below the Agent title are model roles. Select one to configure domain reasoning, primary vision, secondary vision review, or fallback review in the right sidebar. Overrides are stored by domain package plus role. Several Agents may share an API endpoint, Ollama port, or credential without overwriting one another, while an individual Agent may use a separate credential when cost, quota, or data boundaries require it.

While a run is active, the Send button becomes a stop symbol. Clicking it requests a stop at the next safe boundary. Typing another message and pressing Enter during the run queues a direction update; after the update is consumed, the same run continues automatically. A user-stopped run never restarts by itself: send a new instruction to continue. Pending direction updates can be edited or deleted.

The right sidebar shows the current tool activity and newest artifacts first; older artifacts are collapsed. In the desktop application, click **Open artifact** or double-click a supported artifact to open it with the system application. Access mode, model, reasoning mode, and reasoning effort remain in the composer; unsupported controls stay hidden.

A self-contained Domain Agent may also be used by Codex or another MCP stdio host. Inside Wenjin it uses an isolated app-server thread, private memory, and dynamic domain tools; MCP stdio is the external portability boundary. Wenjin injects the selected model roles and local-data bindings when launching an external MCP process. Other hosts may use the blank environment template shipped by the Agent; distributed packages must not contain populated credentials.

The complete Gazetteer Disaster History Agent includes its standard 22-column template and a self-contained `gazetteer-agent-mcp.exe`. “Standard table”, “22 columns”, and “finished table” use that built-in template. A custom schema is used only when the researcher explicitly requests different fields. On a new computer the Agent does not require system Python or PowerShell. If a plugin copy is damaged, the main Agent can revalidate and reinstall it once from the recorded local ZIP after approval.

### 2.4 Research library

The library answers “What work is this, which edition is it, and where is the exact file?” It does not decide whether a page supports a claim.

One work may have multiple editions and file locations: an original-language scan, an abridged translation, an OCR locator, and a researcher-corrected working translation. Wenjin separates work, edition, file, and exact file version. A file fingerprint distinguishes exact copies; a one-character correction creates a new file version without necessarily creating a different work.

Seven editable shelves are provided:

- Primary Sources
- Articles
- Monographs
- Personal Papers and Drafts
- Reading Notes
- Reference Works and Catalogs
- Unclassified

Changing a shelf does not move the original file or change citation eligibility.

Reading notes are excluded from every graph by default, and unclassified files remain outside the graph until their bibliographic status is decided. Reading notes are included only for a query in which the researcher explicitly requests them; this does not change their shelf or evidence status.

The **Knowledge Graph** has three switchable views with separate legends. **Work relations** shows bibliographically classified works and projected same-author, same-journal, same-publisher, citation, material-use, review, translation, and mention relations. Selected relations appear normally; clearing a relation filter hides both its edges and its legend item. Citation, material-use, review, translation, and mention relations use matching directed dashed arrows; citations are red. An article and a monograph do not gain a same-publisher edge merely because the same organization appears in both records. **Bibliographic entities** expands works, authors, journals or publishers, years, and material types. **Project-content entities** shows sources, pages, Markdown blocks, events, entities, claims, and evidence. The graph chooses COSE, fCoSE, or a hierarchical layout according to graph size and structure. Click once to focus a neighborhood; double-click to open the same Works and versions card in the right sidebar. A work already adopted into the current project can open that exact project source directly.

The preview comes from the limited pages inspected during intake. Use it to decide what deserves further reading or which version fits the question. It does not mean that the complete work has been read and it is not evidence. Model-inferred causation, interpersonal relations, and events are not automatically promoted into the graph.

Bibliographic relations and project content remain separate data layers. Exact registered titles found in page-linked Markdown create traceable citation or mention relations, while the project-content layer follows source, page, block, event, entity, claim, and evidence links. Aliases, homonyms, and translation variants are not merged automatically; normalize them in the event register or author-alias table first.

The **Source Chronicle** contains only human-approved event records that retain an exact source version and page link. It can be filtered and exported as Markdown. A chronicle is not a claim that the surviving corpus has been exhausted.

### 2.5 Writing studio

The Writing Studio manages manuscript structure, sections, tables, notes, review, and venue export. Every save creates a new revision; older revisions are not overwritten.

Wenjin is not a full Word clone. Use it for research structure, evidence anchors, and version control. Export to Word for final pagination, typography, headers, and submission layout, then reimport the edited DOCX as a new revision.

### 2.6 Skills and integrations

This workspace separates user-invoked Skills, internal harness workflows, and external integrations. Clicking **Invoke in chat** inserts a slash command, for example:

```text
/historical-literature-search find public primary sources for a bounded period and region
```

Natural-language requests also expose the versioned catalog of Skills that permit implicit use. The main Agent reads the smallest matching Skill before applying it; users do not have to know the slash command.

**AI & Agent — Skills and plugins** can import a local Codex plugin folder or ZIP containing `.codex-plugin/plugin.json`. Skill-only plugins are copied into Wenjin's local Skill directory. A plugin declaring one standard MCP server receives a local adapter manifest without changing the upstream source; every imported MCP tool starts as sensitive. Version 0.1.3 does not import populated environment blocks, account sessions, proprietary Codex Desktop bundled runtimes, or plugins with several MCP servers. Those cases stop with a configuration message instead of silently weakening permissions.

Creating a thread from an existing conversation inherits bounded parent context without copying messages or reading unrelated threads. The chat composer accepts versioned PDF, DOCX, spreadsheet, text, and image attachments. Attachments remain conversational context until inspected and do not become verified sources or evidence automatically. Access mode is on the left of the composer and the main model is on the right; reasoning effort stays hidden unless a model explicitly advertises support.

A Skill does not bypass page verification, source qualification, evidence approval, or writing approval. The run records the Skill and Agent-program fingerprints. Instruction packages do not receive arbitrary permission to execute every script in their folder.

The current project can also be exposed to another Agent through:

```powershell
wenjin mcp-server C:\Research\my-project
```

The MCP server provides bounded project status, source details, pages, library results, and manuscript structure. Formal writes remain approval-gated.

Version 0.1.3 also supplies the manifest, Skill, permission-bounded MCP runtime, and local-data binding contract used by Domain Agents. Install, creation, model-role configuration, and specialist chat live in the separate **Domain Agent** workspace. This page lists reusable Skills, internal workflows, and external integrations. The public core does not preinstall a disciplinary Agent or user dataset.

Source developers can create the neutral engineering scaffold with:

```powershell
wenjin plugin-create my-domain-plugin --output .\plugins
```

### 2.7 AI & Agent

This workspace shows software and schema versions, main and auxiliary models, MoA, research persona, memory, Skills, MCP, connectors, domain packs, Computer Use, and privacy boundaries. Domain reasoning, primary vision, secondary vision review, translation, web research, context compression, title generation, and secondary review can each use a separate model. Auto follows the main model; Disabled skips that role. Context compression runs near 90 percent of the selected model's context window. MoA remains an optional advisory pass and does not replace these direct routes.

The **two-way Codex bridge** has two directions. Codex can inspect the current Wenjin project through read-only MCP. Wenjin can start an explicitly requested, sandboxed Codex task while reusing the local Codex login; it never reads or stores Codex credentials.

The **Weixin connection** is experimental in version 0.1.3. It uses a QR code so approved private contacts can continue the current Wenjin research conversation through ordinary Weixin. Sign-in information is kept in Windows secure credentials. Version 0.1.3 replies only to inbound private text. Group chat, proactive push, scheduled messages, and files are not enabled. If an Agent action pauses for approval, the Weixin reply asks the researcher to review it in the desktop application.

The **Runtime** page can create an immediate backup. Wenjin first uses SQLite's online backup API for a consistent database, then bundles source copies, cleaned derivatives, research notes, manuscripts, reviews, and exports. Logs and temporary files are excluded. Registered projects outside the default Wenjin directory are included in startup backup checks. Restore creates a new project copy and never overwrites the active project.

The **Memory** page configures separate local historical and engineering vaults. Only an `approved_local` candidate may be promoted, and promotion writes one draft card to the target vault's `90_INBOX`. It does not copy full conversations, OCR drafts, or source files.

## 3. First use: create a project

### 3.0 Connect a main model

On the first launch, Wenjin asks for a real main model. Choose local Ollama or an OpenAI-compatible service such as DeepSeek, refresh the provider's model list, then save and test the connection. The production client does not expose Mock and never falls back to it after an API configuration failure. Choose **Not now** if you only need the library or manual page verification; research chat and other model-dependent actions remain disabled.

The first time a project opens, Wenjin automatically creates an empty **New research discussion** thread. Additional task-specific threads can still be added later.

### 3.0.5 Decide whether a Domain Agent is necessary

Use the main Agent first for ordinary discovery, reading, spreadsheet work, and writing. Install or create a Domain Agent only when a sustained workflow repeatedly needs specialist rules, stable fields, a domain database, or dedicated tools. When uncertain, ask: “First decide whether this needs the main Agent, an existing Skill, or a Domain Agent. Do not create a new project yet.”

### 3.1 Create the project

1. Use **New project in Wenjin workspace**. In the desktop application, choose **New project in a local folder** when you want to control its location.
2. Use a durable, recognizable title that names the research object.
3. Avoid titles such as “New project 1” or “final paper.”
4. Confirm that the new project is selected in the Project Workspace and inspect the displayed project path.

One project should correspond to a reasonably stable question or manuscript. Unrelated papers should not share a project database.

### 3.2 Establish a research plan

Open Research Plan and write the researcher baseline before asking a model for a plan. Include at least:

- the formal research objective;
- overall and core periods;
- core cases;
- the comparison unit;
- the hierarchy of materials;
- interpretive boundaries that must not be crossed;
- a stopping rule for further searching.

A model draft never overwrites the researcher baseline. Downstream Agents and reviewers use only a human-approved shared design.

### 3.3 Import or connect literature

Use either:

1. **Add from the research library** when the work may support several projects.
2. **Import a project-private PDF** for material specific to the current project.

For scattered files:

1. select an explicit folder in the library;
2. start a read-only inventory;
3. review proposals derived from filenames, metadata, and bounded sample text;
4. approve selected records or use suggested-classification bulk registration.

Inventory is asynchronous and resumes after refresh. Results are paginated. PDF triage reads no more than the first ten pages; DOCX, Markdown, and TXT use bounded leading text. DOC, EPUB, CAJ, and common image files are reported but cannot be registered through the current parser. Keep a CAJ original and create a PDF or page-text derivative with a conversion receipt.

Inventory does not move, delete, rename, or rewrite files. Scan focused folders rather than an entire system drive.

After registration:

1. verify title, responsibility, edition, publication data, tags, and shelf;
2. click **Add to current project sources** to copy the exact PDF version into the project and start page processing.

DOCX may be used as a locator but is not page-qualified original evidence. If the original file changes or disappears, inventory again; Wenjin does not pretend that the older bytes remain accessible.

## 4. PDF processing and human repair

### 4.1 Why processing is necessary

Searchable PDF text may still be unsafe because of missing text layers, wrong column order, headers mixed with prose, broken cross-page sentences, reversed notes, mismatched physical and printed pages, or OCR errors in names and numbers.

Wenjin represents a document as physical pages, printed-page labels, layout blocks, and cross-page relations. Citations use the printed page; the physical page is a navigation locator.

Two reading derivatives are available:

- **Current reading Markdown** uses the current effective text and may include blocks not yet individually checked.
- **Verified-only Markdown** includes only human-verified or human-repaired research-usable blocks.

Both retain source-version, physical-page, printed-page, and block identifiers. They do not replace the original page image.

### 4.2 Review anomalies

Open a project source from the library or Research Context and inspect:

- page-image legibility;
- text-image agreement;
- separation of prose, notes, headers, footers, and page numbers;
- cross-page continuation;
- the printed-page label;
- whether the page or source is usable, partially usable, or blocked.

### 4.3 Local and full-page repair

Prefer a local block correction for a local error. Use full-page repair for image-only pages, systemic ordering failure, or many interacting errors.

A repair records old and new content, page location, reviewer, reason, and time. A practical sequence is:

1. enter reviewer and reason;
2. save the printed-page label from the original header or footer;
3. inspect prose/title, notes, and header/footer groups;
4. correct erroneous blocks and verify correct blocks;
5. use the two-column reorder helper only as a proposal, then inspect every block;
6. confirm cross-page endpoints;
7. verify the page only after blocking anomalies are resolved.

**Reject document identity** is for the wrong or systemically unusable file, not a few OCR characters.

Bibliographic metadata has a separate gate. Verify author, title, edition, place, publisher, year, journal, volume, issue, and page range from a title page, copyright page, or article first page. Verified page text does not imply verified bibliography.

### 4.4 Visual/OCR models

A visual model can propose transcription and layout for a scan or failed text layer. Its output never replaces the page automatically:

1. select the page;
2. request a proposal;
3. compare and edit it against the image;
4. accept or reject it;
5. only an accepted repair becomes effective text.

The main reasoning model and visual/OCR role may be configured separately.

## 5. Models, MoA, persona, and permissions

Configure the main model first. Version 0.1.2 has direct workflows for vision/OCR, translation, and secondary review. Web-material organization, context compression, and title/abstract naming are marked reserved: they are not routed automatically and currently participate only when selected as MoA advisers. Roles can be disabled, follow the main model, use local Ollama, or use an OpenAI-compatible endpoint.

Provider presets fill common base URLs. **Refresh model list** reads the endpoint's current model IDs for Ollama and compatible `/models` APIs; manual entry remains available. Use **Test connection** before research work.

The versioned **Research Persona** controls address, disciplinary orientation, initiative, and collaboration preferences. It cannot remove evidence, approval, version, or privacy rules.

**Mixture of Agents** lets advisory models produce independent views before the main model synthesizes and acts. Advisers cannot call tools. A failed adviser does not abort the acting model. Enable MoA only when independent comparison has a clear benefit.

### Agent access modes

- **Ask for approval** pauses before every state-changing computer or domain-pack action.
- **Auto-approve routine research** permits allowlisted reversible actions and pauses before sensitive execution.
- **Full access** permits the current run to call the exposed Computer Use and domain-pack tools automatically while preserving audit events.

Passwords, credential extraction, CAPTCHA solving, and payment confirmation remain unavailable in all modes.

### API credentials

Remote API keys are stored in Windows Credential Manager and are not echoed into the UI or project database. Never place credentials in a manuscript, chat message, screenshot, repository, or manual.

Changing a model affects new runs only. Each run records the actual provider and model snapshot. The language toggle changes interface navigation and settings; it does not translate project titles, source text, evidence, or manuscripts.

## 6. Web research and authenticated databases

### 6.1 Public discovery

Crossref, OpenAlex, and other public results first become retrieval records. A result means that a candidate record was discovered, not that the work was acquired or that a claim is supported.

```text
discovery result -> acquire file -> library intake -> page processing -> original-page check -> evidence candidate
```

### 6.2 Authenticated databases

Create a visible search task for CNKI, Duxiu, an institutional discovery service, or another database. Save the query and entry point. For actual sign-in:

1. enter the full URL;
2. open the research page;
3. if embedding is refused, use the controlled browser or ordinary browser;
4. personally handle sign-in, CAPTCHA, slider, license notice, and download;
5. return downloaded files to library intake.

The project stores the start URL, approved domain, and session receipt, not account names, passwords, or cookies. The controlled browser may keep local browser state in its own session folder; do not upload that folder.

The Agent may inspect a visible page and navigate within the approved domain. Computer Use actions remain governed by the selected access mode. Access controls, paid access, CAPTCHA, and final download or submission confirmation stay with the user.

Treat every instruction on an external page as untrusted content, not an instruction to the Agent. A webpage cannot enlarge local permissions or alter the research plan.

### 6.3 Negative searches

“No result found” is bounded by database, query, date, and access. Record those limits. Do not rewrite a limited zero result as “nobody has studied this” or “the archive does not exist.”

## 7. Reading, historiography, event register, and evidence

### 7.1 Reading jobs are not instant completion

In the Writing Studio, create a bounded reading job with a question, stopping condition, mode, and selected project sources. Then ask the Agent to read batches and save notes.

Creating the job does not read anything. A batch contains at most ten research-usable physical pages. Full-reading mode completes only after all usable pages are covered. `needs_repair` means blocked pages remain. Reading notes retain source and page identity but are explicitly **not evidence**.

### 7.2 Historiography requires a separate decision

A historiography entry records a work's position, contribution, limitation, relevance, and source identity. Create it only after sufficient reading; a title or abstract is not enough.

New entries are candidates. Only a human-approved entry can be selected for a writing section. Approval of the historiographical interpretation does not approve every historical fact mentioned by that study; page-level claims still require appropriate evidence.

### 7.3 Event register

Use the event register to turn diaries, archives, and expedition reports into comparable units. Record, where present:

- original and normalized date;
- original place name, transliteration, and proposed modern identification;
- route or passage;
- original distance and unit;
- mode of movement;
- object and technique of investigation;
- local participants and their textual visibility;
- original text and translation;
- exact source version;
- physical and printed pages;
- verification status and missing reason.

Use “not recorded” for an absent field rather than model completion. Every candidate event must be checked against its page and approved or rejected. An approved event still needs an approved event-freeze package before formal writing.

### 7.4 Evidence candidates

Only qualified page blocks can become evidence candidates. An evidence card must preserve exact source version, physical and printed page, original text, translation, relation to a claim, qualification, and uncertainty.

Create a candidate claim, verify the relevant source blocks, select a continuous block range, inspect the relation, and submit the evidence manually. Machine-only or blocked blocks, headers, footers, and unverified pages are excluded. Relations distinguish support, weakening, background, and counterevidence.

### 7.5 Evidence freeze

A freeze fixes one approved version of a claim-evidence contract; it does not make files immutable. Before approval, check direction, original pages, counterevidence, translations, prohibited formulations, reviewer, time, and reason.

Wenjin currently offers ordinary claim-evidence freezes and event-register freezes. They cannot be mixed into one newly created package through the UI. A pending freeze cannot drive formal drafting. A section selects one approved freeze and then a bounded evidence subset.

## 8. Writing studio

### 8.1 Sections and revisions

Create a manuscript or transfer a freeze-backed trial draft. Insert sections and tables around the current section. Saving creates a new immutable revision. Direct editing is not auto-saved; save before switching project or closing the app.

### 8.2 Discuss current text

The manuscript discussion thread stores the manuscript, revision, section, exact selection snapshot, selected text, and attached references. Discussion does not change the manuscript until a separate writing proposal is approved.

### 8.3 Section drafting and selection revision

Freeze-backed section drafting receives one approved freeze and selected evidence. Historiography is selected separately. Model output enters a comparison proposal and must pass evidence-contract checks before a human decision creates a new section version.

Selection-only revision is evidence-preserving polish, not arbitrary rewriting:

- select one unique continuous text range;
- select a complete single table, not cells or a mixed table-and-prose range;
- frozen evidence may be added only through the explicit approved-evidence supplement controls;
- existing numbers, quotations, citations, evidence markers, and qualifications are protected;
- a malformed table or edit outside the selection is rejected;
- approval saves a complete new section version while preserving unselected text.

If the UI reports that the approved section and central document differ, explicitly synchronize before export.

### 8.4 Prose revision and style profiles

Polish may change language but not facts, causal strength, quotations, page numbers, or evidence boundaries. The historical prose revision workflow detects internal process language, repetitive summaries, and template-like prose while protecting evidence markers.

A style profile must remain one author and one comparable corpus. One article is `OBSERVED_ONCE`; at least three independent, fully verified articles plus human approval are required for `STABLE_PROFILE`, and five are recommended. Adding a sample reopens the decision. Profiles learn high-level structure, rhythm, evidence organization, and avoidances rather than copying distinctive sentences.

Research sources and style samples are separate roles. A monograph or single article cannot establish a stable journal style.

### 8.5 Notes and citations

Select an exact anchor before inserting a note. Model-generated notes are candidates; author, title, edition, publisher, and page require human verification.

Internal `[EVID:...]` and `[CITE:...]` markers are traceability anchors, not reader-facing citations. The selected venue template converts eligible markers into footnotes or sequential references during export.

### 8.6 Multi-role review

The main model can run separate argument, source, and citation-editor reviews. A configured secondary model can add an adversarial review. Reports are problem lists and do not edit the manuscript automatically.

Review receives the current venue preview, approved research design, cited frozen evidence, and qualified original-page context. Never replace a printed page with a PDF physical page because a model suggests it.

## 9. Venue templates, Markdown, and Word

### 9.1 Select a template

The editor toolbar and sidebar use the same versioned template rules. The English interface defaults to a Chicago Notes and Bibliography research-paper template. Always verify current venue requirements before submission.

### 9.2 Export Markdown

Inspect the Markdown for unresolved internal markers, reference order, number reuse, printed pages, abstracts, keywords, and author metadata.

### 9.3 Export Word

Inspect pagination, tables, multilingual fonts, note anchors, bibliography, and author/funding/address placeholders. An export with missing submission metadata may be useful for review but remains `BLOCKED` for submission.

### 9.4 Word round trip

Open the exported document in Microsoft Word, save changes, and reimport it as a new revision. Native Word launch, file chooser, and reimport are available only in the installed Windows desktop app.

Round-trip fidelity is bounded. Comments, tracked changes, field codes, pre-existing footnotes, embedded objects, and complex merged cells require manual review. Wenjin-created approved footnotes are genuine Word footnotes, but final numbering and pagination still depend on the target Word version.

## 10. Information, knowledge, and memory layers

### Layer 1: Research library — what materials exist locally

Works, editions, file locations, exact versions, tags, and bibliography. The library database can serve several projects and does not store one manuscript's final argument.

### Layer 2: Project knowledge — what this project has approved

Approved plans, event records, page repairs, evidence, claims, freezes, manuscripts, reviews, and export receipts. This is the primary source of project state.

### Layer 3: Agent process — what was done to complete a task

Threads, runs, tools, approvals, searches, and browser receipts. This layer supports recovery and audit. Failed attempts and conversation remain process records.

### Layer 4: Long-term memory — what may be reusable across projects

Nothing is promoted automatically. A candidate needs stable source IDs, project approval, and a second explicit promotion action. Promotion writes a draft card to the configured vault's `90_INBOX`, not a copy of the complete conversation or source.

Good candidates include multi-source verified findings, bounded negative-search results, approved methods, multi-sample style observations, version relations, place aliases, and terminology. Do not promote credentials, casual chat, one model answer, unverified OCR or translation, bare links, rejected plans, or content recoverable directly from the project database.

## 11. Versions, backups, and recovery

Do not confuse:

1. a file version: exact PDF or DOCX bytes;
2. a research-object version: repair, plan, freeze, or manuscript revision;
3. a software/schema version.

The manuscript Versions page lists revision identifiers, fingerprints, and import/export fidelity receipts. It does not provide an arbitrary one-click rollback. Restore content by importing a prior Markdown/DOCX or by restoring a complete backup as a new project copy. Do not edit SQLite directly.

The desktop app creates online SQLite backups when a complete project has changed. Runtime controls can create an immediate backup and restore it as a separate project. Keep independent milestone exports and application-data backups for archival safety. Windows Credential Manager stores secrets separately.

Git is for source code; it does not replace research-object revisions.

## 12. Troubleshooting

### A page or database will not open

Confirm that the local service is running. An institutional site may refuse embedding; use the controlled or ordinary browser, complete sign-in personally, then import the acquired file.

### A model does not respond

Check the assigned role, provider, model ID, endpoint, key, and **Test connection** result. For Ollama, confirm that the service and selected model are running. Wenjin does not silently switch to a paid provider.

### “Model action format error” or raw tool syntax appears

Wenjin attempts one controlled format retry. If it still fails, the run is marked failed rather than successful. Already saved research artifacts are reported separately.

### `database locked`

Wait for the active import, inventory, writing, or approval operation. Close duplicate Wenjin windows and do not write the project with an external SQLite editor.

### OCR looks fluent but disagrees with the page

Reject it. Fluency is not evidence. An error in prose, name, number, or page blocks evidence use until repaired.

### Why can a search result not be cited?

It proves only that a database returned a record. Acquire the work, identify the version, inspect the original page, and pass evidence qualification.

### Why does export say `BLOCKED`?

Typical reasons are missing author metadata, unverified bibliography, absent printed pages, candidate notes, unresolved markers, or a venue template that needs rechecking.

### Why can selection revision not start?

The approved section may be unsynchronized, the range may be discontinuous or non-unique, only part of a table may be selected, or another proposal may still be pending.

### Why is a reading job `running` or `needs_repair`?

Creating a job is not reading it. `running` means usable pages remain; `needs_repair` means current usable pages are covered but blocked pages prevent completion.

### Why can a library candidate not be approved?

Unsupported formats, read errors, unchanged duplicates, and informational candidates are not approvable. Preserve the original and prepare a supported PDF, DOCX, Markdown, or TXT derivative when appropriate.

### Can the Agent remember everything automatically?

No. Reliable long-term memory should be small, sourced, approved, and reusable. The complete process already remains in the project.

## 13. Recommended daily sequence

```text
establish researcher baseline
-> import and identify materials
-> repair pages and printed-page relations
-> build the event register
-> run bounded supplementary searches
-> return to original pages and create evidence
-> connect claims, limits, and counterevidence
-> approve an evidence freeze
-> draft section by section
-> inspect the venue export preview
-> run multi-role review
-> complete Word proofing
-> add final submission metadata
```

If a source error appears late, return to the page or evidence layer. Do not hide it with vaguer prose. Wenjin is useful only when every claim can return to material, every revision can return to a version, and every automated action remains within the researcher's authority.
