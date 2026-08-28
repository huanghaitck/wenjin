# ADR 0001｜Runtime, model roles and Bookflow reuse

Status: accepted for future implementation; no model runtime is implemented in M1.
Date: 2026-08-09

## Decision

The workbench will use one local application runtime with role-based model assignments. A single
model does not need every capability.

Planned roles:

- `main`: research coordination and text reasoning;
- `vision`: page image, layout and difficult-character analysis;
- `translation`: foreign-language translation of verified logical units;
- `review`: independent bounded review when required.

A text-only main model may request a structured page-analysis task from a vision helper. The helper
returns an artifact with page/block anchors and uncertainty; the main model consumes that artifact
instead of pretending it saw the page. Helper output remains machine-derived until the normal page
and evidence gates are satisfied.

## API and credentials

- M1 uses fixtures and deterministic mock behavior only.
- Development may read explicitly named environment variables from an uncommitted `.env` later.
- Production credentials will use Windows Credential Manager.
- Missing credentials produce a visible unavailable capability; the runtime does not silently switch
  to a paid provider.

## Ollama

Local Ollama is a required future provider. Role assignments may mix local and remote models. On the
development machine, the 2026-08-09 probe found local Qwen3.5 text models and a Qwen3-VL visual model;
these are environment observations, not hard-coded product requirements.

The first Ollama implementation should use its local HTTP/OpenAI-compatible surface and only the
model roles actually needed by the active milestone. It must not create a generic multi-agent mesh.

## Bookflow translation reuse

Bookflow already contains proven assets worth extracting under a separate approved milestone:

- `providers/base.py`: text translation and vision protocols;
- `providers/mock.py`: deterministic provider doubles;
- `provider_registry.py`: configurable providers and role selection;
- `credential_store.py`: Windows credential storage;
- `translation_cache.py`: immutable content-addressed translation cache;
- translation-unit, pause/resume and output reconstruction experience.

The workbench will not import Bookflow through a sibling path and will not copy its translation domain
state machine. A later task will extract or adapt the smallest reusable pieces into workbench-owned
interfaces. Translation inputs must be verified logical blocks with stable source-page anchors;
translations remain derivatives and never replace source text.

## Consequences

- Text-only local models remain useful without weakening page verification.
- Visual and translation costs can be routed independently.
- M1 stays dependency-free and testable without credentials.
- Reuse is deliberate and bounded instead of coupling two applications.
