# Wenjin 0.1.4 maintenance and roadmap

## Release baseline

0.1.4 keeps one Agent lifecycle: the bundled Codex app-server. Wenjin owns projects, the research library, sources, evidence, writing, approvals, receipts, and Domain Agent installation. Domain Agents remain separately versioned, self-contained tool providers with isolated sessions and memory.

Every release candidate must pass these gates before packaging:

1. Python regression tests and JavaScript syntax checks;
2. main MCP Inspector contract checks;
3. installed Domain Agent tool-contract checks and representative calls;
4. Playwright checks for chat, settings, help, sidebar layout, and thread creation;
5. a natural-language run that uses real tools and creates an inspectable receipt;
6. installer or offline-bundle extraction, manifest, build identity, startup, and rollback checks on a clean data root.

## Maintenance policy

- **Patch release:** regression fixes, packaging corrections, accessibility, copy, and deterministic tool fixes. No schema or research-method change without a migration and tests.
- **Minor release:** new visible workflow, database migration, new Domain Agent contract, or substantial UI change. Existing projects and plugin receipts must remain readable.
- **Domain Agent release:** independent from the core version. The plugin manifest, runtime receipt, data receipt, tool schema, and Skill must share a verified build identity.
- **Online update:** remains disabled until a signed update endpoint and signing key exist. Until then, distribute a complete installer and a verified offline bundle; never simulate silent updates with ad-hoc replacement scripts.

## Self-diagnosis and repair boundary

The visible **Run diagnostics** action is read-only and reports project database integrity, installed plugin identity, and optional runtime state. The natural-language request “run a read-only Wenjin system check” calls the same tool.

**Repair safe items** is deliberately narrow. It creates a project backup and can reinstall only a damaged plugin whose original local package is still recorded and available. It cannot change source files, evidence, research rules, credentials, local databases of unknown provenance, or arbitrary application source code. A broader code repair remains a main-Agent task and requires the user to grant the corresponding computer permission.

## Interface roadmap after 0.1.4

Research and coding should share projects, threads, permissions, artifacts, and the same Agent lifecycle, but they do not need identical workspaces:

- **Research mode:** library, original pages, evidence, chronology, writing, and human decisions remain primary.
- **Coding mode:** repository tree, diffs, tests, terminal receipts, and review become primary.

This is a post-0.1.4 feature. It should be implemented as two presentations of the same state, not as a second harness or a duplicate project system.

## Next priorities

1. finish signed online updates when release infrastructure exists;
2. add clean-machine installer and rollback automation to CI;
3. expand accessibility and English-interface regression coverage;
4. deepen the research workspace after the UI baseline is stable, including clearer research-state navigation and less repetitive approval interaction;
5. improve source chronicles as saved, reusable research views with better cross-source comparison, naming, filtering, and export;
6. add coding-mode presentation without weakening the research workflow;
7. keep new disciplinary capabilities in versioned Domain Agents rather than enlarging the core.
