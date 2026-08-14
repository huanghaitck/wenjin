from __future__ import annotations

import json
import hashlib
import os
import queue
import re
import ssl
import threading
import uuid
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi

from .db import connect, utc_now
from .authoring import (
    authoring_state,
    create_historiography_entry,
    create_reading_job,
    list_reading_jobs,
    reading_job_batch,
    save_reading_note,
    validate_historiography_entry_payload,
)
from .research import list_retrievals
from .research_design import create_design_draft, current_shared_design
from .research_events import create_event_candidates, event_coverage, event_state
from .scholarship import research_state
from .service import list_sources, project_status, source_view
from .skill_registry import get_skill


MAIN_ROLE = "main_reasoning"
RUN_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}
MAX_TOOL_CALLS = 24
MAX_HISTORY_MESSAGES = 12
MAX_HISTORY_CHARS = 30000
MAX_HISTORY_MESSAGE_CHARS = 8000
SOURCE_LIST_DEFAULT_LIMIT = 20
SOURCE_LIST_MAX_LIMIT = 50
ARTIFACT_WRITING_TOOLS = {
    "research_design.propose",
    "research_event.propose_batch",
    "reading_job.create",
    "reading_note.save",
    "historiography.create",
    "save_research_note",
}


def _compact_authoring_state(project_root: Path) -> dict[str, Any]:
    """Return an index for agent routing without embedding whole drafts or reviews."""
    state = authoring_state(project_root)
    manuscripts = []
    for manuscript in state.get("manuscripts", []):
        sections = [
            {
                "section_id": section.get("section_id"),
                "heading": section.get("heading"),
                "section_order": section.get("section_order"),
                "current_version_id": section.get("current_version_id"),
                "character_count": len(str(section.get("content", ""))),
            }
            for section in manuscript.get("sections", [])
        ]
        review_groups = [
            {
                "review_group_id": group.get("review_group_id"),
                "template_id": group.get("template_id"),
                "created_at": group.get("created_at"),
                "is_current": group.get("is_current"),
                "reviewer_roles": [
                    report.get("reviewer_role") for report in group.get("reports", [])
                ],
            }
            for group in manuscript.get("review_groups", [])
        ]
        manuscripts.append({
            "manuscript_id": manuscript.get("manuscript_id"),
            "title": manuscript.get("title"),
            "status": manuscript.get("status"),
            "source_format": manuscript.get("source_format"),
            "updated_at": manuscript.get("updated_at"),
            "character_count": sum(section["character_count"] for section in sections),
            "sections": sections,
            "review_groups": review_groups,
        })
    reading_jobs = [
        {
            "job_id": job.get("job_id"),
            "title": job.get("title"),
            "question": job.get("question"),
            "mode": job.get("mode"),
            "source_ids": job.get("source_ids", []),
            "stop_condition": job.get("stop_condition"),
            "status": job.get("status"),
            "note_count": len(job.get("notes", [])),
        }
        for job in state.get("reading_jobs", [])
    ]
    return {
        "boundary": (
            "Compact index only. It intentionally omits manuscript text, reading-note text and "
            "review reports; request a bounded detail tool before quoting or revising content."
        ),
        "manuscripts": manuscripts,
        "reading_jobs": reading_jobs,
        "historiography": state.get("historiography", []),
        "journal_templates": state.get("journal_templates", []),
        "style_profiles": state.get("style_profiles", []),
        "submission_profiles": state.get("submission_profiles", []),
        "writing_model": state.get("writing_model", {}),
        "review_models": state.get("review_models", {}),
        "formal_research_readiness": state.get("formal_research_readiness", {}),
    }
SYSTEM_PROMPT = """You are the main agent in a local historical research workbench.
Use tools to inspect project facts. Never claim you read a source unless a tool returned it.
Return exactly one JSON object for exactly one action and no markdown. If several tools are needed,
request them one at a time and wait for each TOOL_RESULT before choosing the next action.
Available actions:
{"type":"tool_call","tool":"project.status","arguments":{}}
{"type":"tool_call","tool":"source.list","arguments":{"source_ids":["optional-exact-source-id"],"query":"optional title or id fragment","limit":20}}
{"type":"tool_call","tool":"source.search","arguments":{"query":"...","source_id":"optional","limit":10}}
{"type":"tool_call","tool":"source.page","arguments":{"page_id":"exact composite id"}}
{"type":"tool_call","tool":"source.page","arguments":{"source_id":"...","physical_page":249}}
{"type":"tool_call","tool":"research.state","arguments":{}}
{"type":"tool_call","tool":"research.plan_context","arguments":{}}
{"type":"tool_call","tool":"retrieval.list","arguments":{}}
{"type":"tool_call","tool":"authoring.state","arguments":{}}
{"type":"tool_call","tool":"authoring.section","arguments":{"section_id":"exact-section-id"}}
{"type":"tool_call","tool":"research_design.current","arguments":{}}
{"type":"tool_call","tool":"research_design.propose","arguments":{"title":"...","content":"...","change_summary":"..."}}
{"type":"tool_call","tool":"research_event.list","arguments":{"case_ids":["exact-case-id"],"statuses":["approved"],"detail":"summary"}}
{"type":"tool_call","tool":"research_event.coverage","arguments":{"case_ids":["exact-case-id"]}}
{"type":"tool_call","tool":"research_event.propose_batch","arguments":{"events":[{"case_id":"...","event_date":"...","source_id":"...","block_ids":["..."],"field_anchors":{"event_date":["block-id"],"route":["block-id"],"movement_mode":["block-id"],"genre":["block-id"],"participant_visibility":["block-id"],"outcome_destination":["block-id"],"original_text":["block-id"]},"route":"...","movement_mode":"...","investigation_object":"...","recording_technique":"...","genre":"...","chinese_participants":"...","participant_visibility":"...","institutional_task":"...","outcome_destination":"..."}]}}
{"type":"tool_call","tool":"reading_job.create","arguments":{"title":"...","question":"...","mode":"metadata|targeted|full","source_ids":["exact-source-id"],"stop_condition":"..."}}
{"type":"tool_call","tool":"reading_job.batch","arguments":{"job_id":"...","source_id":"...","after_physical_page":0,"page_limit":5}}
{"type":"tool_call","tool":"reading_note.save","arguments":{"job_id":"...","source_id":"...","physical_pages":[1,2],"content":"source-grounded reading analysis","complete":false}}
{"type":"tool_call","tool":"historiography.create","arguments":{"work_title":"...","position":"...","contribution":"...","limitation":"...","relevance":"...","source_refs":["exact-source-id"]}}
{"type":"tool_call","tool":"save_research_note","arguments":{"title":"...","content":"..."}}
{"type":"final","content":"..."}
Saving a note requires human approval. Keep notes explicit about blocked pages and uncertainty.
Follow an explicit user tool scope. Do not call unrelated state tools merely because they are available.
Retrieval results are leads, not evidence. Only approved evidence freezes may support drafting.
Prior thread messages preserve the research discussion but are not source evidence. Reinspect source pages
when a prior message mentions a fact that must enter an event, claim, quotation or draft.
If a tool reports a correctable locator or argument error, use the error to correct the call within the
explicit user scope. Do not repeat the same failed call, guess source content, or abandon the whole task.
Research event proposals are page-linked coding drafts, not frozen evidence. Human approval is required,
and even approved event rows cannot support drafting until their claims and evidence are separately frozen.
For event counts or coverage audits, call research_event.coverage with the exact intended case_ids instead
of hand-counting research_event.list. Keep other_approved_cases separate from the selected combined total.
For a comparison matrix, follow coverage with research_event.list using the same exact case_ids,
statuses=["approved"] and detail="summary". Request full event text only when the user needs quotations.
source.page reports each block's verification_state, use_state and usable_for_evidence flag. That flag is
true only after the cited block is human-verified or human-repaired on a human-checked page. Machine-parsed
or blocked text may help locate a repair target, but it must not support an event field, quotation or claim.
source.page also reports adjacent_relations for every continuation touching the page. Use each relation's
effective_value and verification_state; do not call a human-confirmed continuation unresolved.
Every non-empty source-derived event field must name its exact supporting blocks in field_anchors.
Movement mode, genre, participant visibility and outcome destination are comparison fields, not free
inference slots; leave them blank with a missing code when the cited blocks do not support them.
end_place is the journey endpoint. outcome_destination is where a research or knowledge product goes,
such as a publication, report, map, collection, specimen repository or institution; never put lodging,
a stopover or a route endpoint in outcome_destination.
NR, UNC and PND are missing-data codes, not source-field values. Leave the affected source-derived
field blank and put the code plus explanation in missing_reason; never invent an anchor for absence.
Do not cite one set of blocks while taking dates, places, participants or tasks from unanchored page context.
Preserve the source's speaker and epistemic status. If an author generalizes, interprets, infers,
reports hearsay or expresses uncertainty, write the event field as that author's statement rather
than an unqualified historical fact. Keep witnessed actions and measurements distinct from the
author's explanations and from information attributed to other people.
Normally omit original_text: the workbench copies the exact effective text from its original_text field anchors.
Supply original_text only when selecting a shorter verbatim substring, and never normalize spelling or typography.
source.list is a compact, bounded index, not a full project dump. When the researcher supplies an
exact source_id, call it with source_ids=["..."]; otherwise use query and a small limit. Its result
omits byte counts, full research_context and source text. Use source.page or the bounded reading tools
for detail. For source.list, use_state describes page-processing usability, not whether a work is
relevant, missing, or a prerequisite. Do not infer a research priority from blocked/partial alone.
Never translate a blocked, pending, partial or zero-page processing state into a claim that the
historical work itself is illegible, unavailable, absent or unusable. Say only that its local
page processing is unfinished unless source inspection independently establishes a material defect.
When locating a translation or other derivative against an original source, prioritize dates,
chronological sequence and neighboring pages; repeated lexical hits are only leads. A translation
of the same witness is a locator aid, not independent corroboration. If a relevant sentence is
unfinished at the bottom of a page, inspect the next physical page before reporting the passage.
Cross-page evidence requires a human-confirmed continuation relation in the workbench.
Use reading_job.create to persist bounded metadata, targeted or full reading work. Creation starts the
job; it does not read or complete it. Read at most ten physical pages at a time with reading_job.batch,
then save a concise source-grounded analysis with reading_note.save. Full reading can complete only after
every usable page of every assigned source is covered; blocked pages yield needs_repair. A reading note
is a scoped interpretation aid, never evidence by itself. Its source identity is supplied by the tool:
do not write or guess a source title/author inside content. If save fails on a blocked page, use the returned
source_identity and savable_physical_pages to correct the call. Use historiography.create only after the
named study has been read deeply enough to state its position, contribution, evidence path, limitation
and relation to the current research question. Pass the canonical_title returned by the reading tools as
work_title. Historiography entries remain candidates until a human approves them. Do not create
historiography from titles or abstracts.
Write final content for a researcher as readable prose with short headings or bullet lines.
Do not return a Python repr, JSON dump, or an object-shaped report unless the user explicitly asks for one.
Never expose or echo internal lines beginning with TOOL_RESULT in the final answer.
"""


@dataclass(frozen=True)
class ModelProfile:
    profile_id: str
    provider: str
    model: str
    endpoint: str
    capabilities: tuple[str, ...]
    credential_ref: str
    status: str
    api_key: str = ""
    timeout_seconds: float = 90.0


class ModelActionFormatError(ValueError):
    """The provider answered, but its action could not be parsed safely."""


class EmptyModelContentError(RuntimeError):
    """The provider returned a response envelope without usable content."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _decode(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    return json.loads(value)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _append_run_event(connection: Any, run_id: str, event_type: str, payload: dict[str, Any]) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM run_events WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    sequence = int(row["sequence"])
    connection.execute(
        "INSERT INTO run_events(run_id, sequence, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (run_id, sequence, event_type, _json(payload), utc_now()),
    )
    return sequence


def _saved_artifact_receipt(connection: Any, run_id: str) -> dict[str, Any]:
    placeholders = ",".join("?" for _ in ARTIFACT_WRITING_TOOLS)
    rows = connection.execute(
        f"""SELECT tool_call_id, tool_name FROM tool_calls
             WHERE run_id = ? AND status = 'COMPLETED'
               AND tool_name IN ({placeholders})
             ORDER BY created_at, tool_call_id""",
        (run_id, *sorted(ARTIFACT_WRITING_TOOLS)),
    ).fetchall()
    saved = [
        {"tool_call_id": str(row["tool_call_id"]), "tool": str(row["tool_name"])}
        for row in rows
    ]
    return {
        "artifacts_saved": bool(saved),
        "saved_artifact_count": len(saved),
        "saved_artifacts": saved,
    }


def sync_model_profiles(project_root: Path) -> list[dict[str, Any]]:
    now = utc_now()
    environment = _environment_profile()
    with connect(project_root) as connection:
        connection.execute(
            """INSERT INTO model_profiles(
                   profile_id, provider, model, endpoint, capabilities_json, credential_ref,
                   status, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(profile_id) DO UPDATE SET
                   model = excluded.model,
                   endpoint = excluded.endpoint,
                   capabilities_json = excluded.capabilities_json,
                   credential_ref = excluded.credential_ref,
                   status = excluded.status,
                   updated_at = excluded.updated_at""",
            ("builtin-mock", "mock", "deterministic-research-mock", "", _json(["text", "tool_calling"]),
             "none", "available", now, now),
        )
        if environment is not None:
            connection.execute(
                """INSERT INTO model_profiles(
                       profile_id, provider, model, endpoint, capabilities_json, credential_ref,
                       status, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(profile_id) DO UPDATE SET
                       provider = excluded.provider,
                       model = excluded.model,
                       endpoint = excluded.endpoint,
                       capabilities_json = excluded.capabilities_json,
                       credential_ref = excluded.credential_ref,
                       status = excluded.status,
                       updated_at = excluded.updated_at""",
                (environment.profile_id, environment.provider, environment.model, environment.endpoint,
                 _json(list(environment.capabilities)), environment.credential_ref, environment.status,
                 now, now),
            )
        else:
            connection.execute(
                "UPDATE model_profiles SET status = 'unavailable', updated_at = ? WHERE profile_id = 'environment-main'",
                (now,),
            )
        connection.execute(
            """INSERT OR IGNORE INTO model_assignments(role, profile_id, updated_at)
               VALUES (?, 'builtin-mock', ?)""",
            (MAIN_ROLE, now),
        )
        rows = connection.execute(
            """SELECT p.profile_id, p.provider, p.model, p.endpoint, p.capabilities_json,
                      p.credential_ref, p.status,
                      CASE WHEN a.role = ? THEN 1 ELSE 0 END AS assigned
               FROM model_profiles p
               LEFT JOIN model_assignments a ON a.profile_id = p.profile_id AND a.role = ?
               ORDER BY assigned DESC, p.provider, p.model""",
            (MAIN_ROLE, MAIN_ROLE),
        ).fetchall()
    return [_profile_public(dict(row)) for row in rows]


def _environment_profile() -> ModelProfile | None:
    provider = os.environ.get("HRW_AGENT_PROVIDER", "").strip().lower()
    model = os.environ.get("HRW_AGENT_MODEL", "").strip()
    endpoint = os.environ.get("HRW_AGENT_BASE_URL", "").strip()
    api_key = os.environ.get("HRW_AGENT_API_KEY", "").strip()
    if provider not in {"openai_compatible", "ollama"} or not model or not endpoint:
        return None
    if provider == "openai_compatible" and not api_key:
        return None
    return ModelProfile(
        profile_id="environment-main",
        provider=provider,
        model=model,
        endpoint=endpoint,
        capabilities=("text", "tool_calling"),
        credential_ref="env:HRW_AGENT_API_KEY" if provider == "openai_compatible" else "none",
        status="available",
        api_key=api_key,
        timeout_seconds=float(os.environ.get("HRW_AGENT_TIMEOUT_SECONDS", "90")),
    )


def _profile_public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_id": row["profile_id"],
        "provider": row["provider"],
        "model": row["model"],
        "endpoint": row["endpoint"],
        "capabilities": _decode(row["capabilities_json"], []),
        "credential_ref": row["credential_ref"],
        "status": row["status"],
        "assigned": bool(row.get("assigned", 0)),
    }


def assign_model(project_root: Path, profile_id: str, role: str = MAIN_ROLE) -> dict[str, Any]:
    if role != MAIN_ROLE:
        raise ValueError(f"M4 only supports role {MAIN_ROLE}")
    sync_model_profiles(project_root)
    with connect(project_root) as connection:
        profile = connection.execute(
            "SELECT profile_id, status FROM model_profiles WHERE profile_id = ?", (profile_id,)
        ).fetchone()
        if profile is None:
            raise KeyError(f"unknown model profile: {profile_id}")
        if profile["status"] != "available":
            raise ValueError(f"model profile is {profile['status']}")
        connection.execute(
            """INSERT INTO model_assignments(role, profile_id, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(role) DO UPDATE SET profile_id = excluded.profile_id, updated_at = excluded.updated_at""",
            (role, profile_id, utc_now()),
        )
    return {"role": role, "profile_id": profile_id}


def _assigned_profile(project_root: Path) -> ModelProfile:
    sync_model_profiles(project_root)
    with connect(project_root) as connection:
        row = connection.execute(
            """SELECT p.* FROM model_profiles p
               JOIN model_assignments a ON a.profile_id = p.profile_id
               WHERE a.role = ?""",
            (MAIN_ROLE,),
        ).fetchone()
    if row is None:
        raise RuntimeError("main model assignment is missing")
    api_key = ""
    timeout = 90.0
    if row["profile_id"] == "environment-main":
        current = _environment_profile()
        if current is None:
            raise ValueError("assigned environment model is no longer available")
        api_key = current.api_key
        timeout = current.timeout_seconds
    return ModelProfile(
        profile_id=str(row["profile_id"]), provider=str(row["provider"]), model=str(row["model"]),
        endpoint=str(row["endpoint"]), capabilities=tuple(_decode(row["capabilities_json"], [])),
        credential_ref=str(row["credential_ref"]), status=str(row["status"]), api_key=api_key,
        timeout_seconds=timeout,
    )


def create_thread(project_root: Path, title: str) -> dict[str, Any]:
    title = title.strip()
    if not title:
        raise ValueError("thread title is required")
    thread_id = _id("THR")
    now = utc_now()
    with connect(project_root) as connection:
        connection.execute(
            "INSERT INTO threads(thread_id, title, status, created_at, updated_at) VALUES (?, ?, 'active', ?, ?)",
            (thread_id, title, now, now),
        )
    return {"thread_id": thread_id, "title": title, "status": "active", "created_at": now}


def list_threads(project_root: Path) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        rows = connection.execute(
            """SELECT t.*,
                      (SELECT COUNT(*) FROM messages m WHERE m.thread_id = t.thread_id) AS message_count,
                      (SELECT status FROM runs r WHERE r.thread_id = t.thread_id ORDER BY created_at DESC LIMIT 1)
                        AS latest_run_status
               FROM threads t ORDER BY updated_at DESC, created_at DESC"""
        ).fetchall()
    return [dict(row) for row in rows]


def recover_interrupted_runs(project_root: Path) -> int:
    now = utc_now()
    with connect(project_root) as connection:
        rows = connection.execute(
            "SELECT run_id, goal_id FROM runs WHERE status = 'RUNNING'"
        ).fetchall()
        for row in rows:
            message = "Run was interrupted by an application restart."
            connection.execute(
                "UPDATE runs SET status = 'FAILED', error = ?, updated_at = ?, completed_at = ? WHERE run_id = ?",
                (message, now, now, row["run_id"]),
            )
            connection.execute(
                "UPDATE goals SET status = 'failed', completed_at = ? WHERE goal_id = ?",
                (now, row["goal_id"]),
            )
            receipt = _saved_artifact_receipt(connection, str(row["run_id"]))
            _append_run_event(
                connection, str(row["run_id"]), "run_failed", {"error": message, **receipt}
            )
    return len(rows)


def _fail_run(project_root: Path, run_id: str, error: Exception | str) -> bool:
    """Persist one terminal failure; repeated outer cleanup is intentionally a no-op."""
    message, now = str(error), utc_now()
    with connect(project_root) as connection:
        row = connection.execute(
            "SELECT goal_id, status FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown run: {run_id}")
        if row["status"] != "RUNNING":
            return False
        connection.execute(
            "UPDATE runs SET status = 'FAILED', error = ?, updated_at = ?, completed_at = ? WHERE run_id = ?",
            (message, now, now, run_id),
        )
        connection.execute(
            "UPDATE goals SET status = 'failed', completed_at = ? WHERE goal_id = ?",
            (now, row["goal_id"]),
        )
        receipt = _saved_artifact_receipt(connection, run_id)
        _append_run_event(connection, run_id, "run_failed", {"error": message, **receipt})
    return True


def thread_view(project_root: Path, thread_id: str) -> dict[str, Any]:
    with connect(project_root) as connection:
        thread = connection.execute("SELECT * FROM threads WHERE thread_id = ?", (thread_id,)).fetchone()
        if thread is None:
            raise KeyError(f"unknown thread: {thread_id}")
        messages = [dict(row) for row in connection.execute(
            "SELECT * FROM messages WHERE thread_id = ? ORDER BY created_at, message_id", (thread_id,)
        )]
        runs = [dict(row) for row in connection.execute(
            "SELECT * FROM runs WHERE thread_id = ? ORDER BY created_at DESC", (thread_id,)
        )]
        for message in messages:
            message["content"] = _decode(message.pop("content_json"), {})
            binding = connection.execute(
                "SELECT * FROM thread_context_bindings WHERE message_id = ?", (message["message_id"],)
            ).fetchone()
            if binding is not None:
                item = dict(binding)
                item["attached_refs"] = _decode(item.pop("attached_refs_json"), [])
                message["context_binding"] = item
        for run in runs:
            run["model_snapshot"] = _decode(run.pop("model_snapshot_json"), {})
            run["events"] = []
            run["tool_calls"] = []
            run["approvals"] = []
            for event in connection.execute(
                "SELECT * FROM run_events WHERE run_id = ? ORDER BY sequence", (run["run_id"],)
            ):
                item = dict(event)
                item["payload"] = _decode(item.pop("payload_json"), {})
                run["events"].append(item)
            for call in connection.execute(
                "SELECT * FROM tool_calls WHERE run_id = ? ORDER BY created_at", (run["run_id"],)
            ):
                item = dict(call)
                item["input"] = _decode(item.pop("input_json"), {})
                item["output"] = _decode(item.pop("output_json"), None)
                run["tool_calls"].append(item)
            for approval in connection.execute(
                "SELECT * FROM approvals WHERE run_id = ? ORDER BY created_at", (run["run_id"],)
            ):
                item = dict(approval)
                item["request"] = _decode(item.pop("request_json"), {})
                item["decision"] = _decode(item.pop("decision_json"), None)
                run["approvals"].append(item)
            run["artifact_receipt"] = _saved_artifact_receipt(connection, str(run["run_id"]))
    return {"thread": dict(thread), "messages": messages, "runs": runs}


def _thread_history(project_root: Path, thread_id: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
    with connect(project_root) as connection:
        rows = connection.execute(
            """SELECT message_id, role, content_json FROM messages
               WHERE thread_id = ? AND role IN ('user', 'assistant')
               ORDER BY created_at DESC, message_id DESC LIMIT ?""",
            (thread_id, MAX_HISTORY_MESSAGES + 1),
        ).fetchall()
    truncated = len(rows) > MAX_HISTORY_MESSAGES
    rows = rows[:MAX_HISTORY_MESSAGES]
    remaining = MAX_HISTORY_CHARS
    selected: list[dict[str, str]] = []
    for row in rows:
        text = str(_decode(row["content_json"], {}).get("text", "")).strip()
        if not text:
            continue
        if str(row["role"]) == "assistant" and _looks_like_internal_tool_transcript(text):
            truncated = True
            continue
        if len(text) > MAX_HISTORY_MESSAGE_CHARS:
            half = (MAX_HISTORY_MESSAGE_CHARS - 25) // 2
            text = text[:half] + "\n...[message clipped]...\n" + text[-half:]
            truncated = True
        if len(text) > remaining:
            if remaining < 200:
                truncated = True
                break
            half = max(80, (remaining - 25) // 2)
            text = text[:half] + "\n...[history clipped]...\n" + text[-half:]
            truncated = True
        selected.append({"message_id": str(row["message_id"]), "role": str(row["role"]), "content": text})
        remaining -= len(text)
        if remaining <= 0:
            break
    selected.reverse()
    return selected, {
        "message_ids": [item["message_id"] for item in selected],
        "truncated": truncated,
        "character_count": sum(len(item["content"]) for item in selected),
    }


def _resolve_skill_invocation(content: str) -> tuple[str, dict[str, Any] | None, str]:
    match = re.match(r"^/([A-Za-z0-9_.-]+)(?:\s+(.*))?$", content, re.DOTALL)
    if not match:
        return content, None, ""
    skill = get_skill(match.group(1))
    if skill["placement"] != "user_action":
        raise ValueError(f"skill is managed by the harness and cannot be invoked directly: {skill['name']}")
    program = skill.get("agent_program") or {}
    request_text = (match.group(2) or "").strip() or program.get("default_prompt", "")
    if not request_text:
        raise ValueError("slash skill invocation requires a research request")
    snapshot = {
        "name": skill["name"], "sha256": skill["sha256"], "skill_file": skill["skill_file"],
        "invocation": skill["invocation"], "agent_program": program,
    }
    skill_context = (
        "ACTIVE_VERSIONED_SKILL\n"
        f"name={skill['name']}\nsha256={skill['sha256']}\n"
        "Follow these instructions only within the workbench tool and approval boundaries. "
        "Program-level evidence and write gates take precedence.\n\n"
        + skill["instructions"]
    )
    return request_text, snapshot, skill_context


def send_message(project_root: Path, thread_id: str, content: str,
                 context: dict[str, Any] | None = None,
                 planning_mode: str = "guided_execution") -> dict[str, Any]:
    content = content.strip()
    if not content:
        raise ValueError("message content is required")
    if planning_mode not in {"independent_planning", "guided_execution"}:
        raise ValueError(f"unknown planning mode: {planning_mode}")
    resolved_content, active_skill, skill_context = _resolve_skill_invocation(content)
    profile = _assigned_profile(project_root)
    shared_design = current_shared_design(project_root) if planning_mode == "guided_execution" else None
    history, history_receipt = (
        _thread_history(project_root, thread_id)
        if planning_mode == "guided_execution"
        else ([], {"message_ids": [], "truncated": False, "character_count": 0})
    )
    now = utc_now()
    message_id, goal_id, run_id = _id("MSG"), _id("GOL"), _id("RUN")
    snapshot = {
        "role": MAIN_ROLE, "profile_id": profile.profile_id, "provider": profile.provider,
        "model": profile.model, "endpoint": profile.endpoint,
        "planning_mode": planning_mode,
        "shared_design_id": shared_design["design_id"] if shared_design else "",
        "history_policy": "bounded_thread_history" if history else "withheld_or_empty",
        "history_message_ids": history_receipt["message_ids"],
        "history_truncated": history_receipt["truncated"],
        "history_character_count": history_receipt["character_count"],
        "active_skill": active_skill,
    }
    with connect(project_root) as connection:
        thread = connection.execute("SELECT thread_id FROM threads WHERE thread_id = ?", (thread_id,)).fetchone()
        if thread is None:
            raise KeyError(f"unknown thread: {thread_id}")
        waiting = connection.execute(
            "SELECT run_id FROM runs WHERE thread_id = ? AND status = 'WAITING_FOR_APPROVAL' LIMIT 1",
            (thread_id,),
        ).fetchone()
        if waiting is not None:
            raise ValueError("this thread has a run waiting for approval")
        connection.execute(
            "INSERT INTO messages(message_id, thread_id, role, content_json, created_at) VALUES (?, ?, 'user', ?, ?)",
            (message_id, thread_id, _json({"text": content}), now),
        )
        if context:
            manuscript_id = str(context.get("manuscript_id", ""))
            revision_id = str(context.get("revision_id", ""))
            section_id = str(context.get("section_id", ""))
            if manuscript_id and connection.execute(
                "SELECT 1 FROM manuscripts WHERE manuscript_id = ?", (manuscript_id,)
            ).fetchone() is None:
                raise KeyError(f"unknown manuscript: {manuscript_id}")
            if revision_id and connection.execute(
                "SELECT 1 FROM document_revisions WHERE revision_id = ?", (revision_id,)
            ).fetchone() is None:
                raise KeyError(f"unknown document revision: {revision_id}")
            selection = str(context.get("selection_text", ""))
            attached = context.get("attached_refs", [])
            if not isinstance(attached, list):
                raise ValueError("attached_refs must be a list")
            connection.execute(
                """INSERT INTO thread_context_bindings(binding_id, message_id, thread_id, manuscript_id,
                   revision_id, section_id, node_id, selection_hash, selection_text, attached_refs_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_id("CTX"), message_id, thread_id, manuscript_id or None, revision_id or None,
                 section_id or None, str(context.get("node_id", "")) or None,
                 hashlib.sha256(selection.encode("utf-8")).hexdigest() if selection else "",
                 selection, _json(attached), now),
            )
        connection.execute(
            "INSERT INTO goals(goal_id, thread_id, objective, status, created_at) VALUES (?, ?, ?, 'active', ?)",
            (goal_id, thread_id, content, now),
        )
        connection.execute(
            """INSERT INTO runs(
                   run_id, thread_id, goal_id, status, model_snapshot_json, created_at, updated_at
               ) VALUES (?, ?, ?, 'RUNNING', ?, ?, ?)""",
            (run_id, thread_id, goal_id, _json(snapshot), now, now),
        )
        connection.execute("UPDATE threads SET updated_at = ? WHERE thread_id = ?", (now, thread_id))
        _append_run_event(connection, run_id, "run_started", {
            "objective": content, "model": snapshot, "planning_mode": planning_mode,
        })
        _append_run_event(connection, run_id, "user_message", {"message_id": message_id})
    try:
        objective = resolved_content
        if context:
            objective += "\n\nCURRENT_RESEARCH_CONTEXT " + _json({
                "manuscript_id": context.get("manuscript_id", ""),
                "revision_id": context.get("revision_id", ""),
                "section_id": context.get("section_id", ""),
                "node_id": context.get("node_id", ""),
                "selection_text": context.get("selection_text", ""),
                "attached_refs": context.get("attached_refs", []),
            })
        design_context = (
            "INDEPENDENT_PLANNING: The researcher baseline and shared design are intentionally withheld. "
            "Develop a proposal from the stated task and inspected sources; do not claim knowledge of a hidden plan."
            if planning_mode == "independent_planning"
            else "APPROVED_SHARED_RESEARCH_DESIGN " + _json(shared_design) if shared_design
            else "GUIDED_EXECUTION: This project has no approved shared research design."
        )
        if skill_context:
            design_context += "\n\n" + skill_context
        _advance_run(project_root, run_id, objective, profile, design_context, history)
    except Exception as error:
        _fail_run(project_root, run_id, error)
        raise
    return thread_view(project_root, thread_id)


def _advance_run(project_root: Path, run_id: str, objective: str, profile: ModelProfile,
                 design_context: str = "", history: list[dict[str, str]] | None = None) -> None:
    observations: list[dict[str, Any]] = []
    empty_content_retries = 0
    action_format_retries = 0
    internal_transcript_retries = 0
    required_tool = _explicit_required_tool(objective)
    missing_tool_retries = 0
    for _ in range(MAX_TOOL_CALLS + 1):
        remaining = MAX_TOOL_CALLS - len(observations)
        try:
            action = _mock_action(project_root, observations) if profile.provider == "mock" else _model_action(
                profile, objective, observations, remaining, design_context, history
            )
        except TimeoutError as error:
            _fail_run(project_root, run_id, error)
            raise
        except EmptyModelContentError as error:
            if empty_content_retries:
                raise
            empty_content_retries += 1
            message = str(error)
            with connect(project_root) as connection:
                _append_run_event(connection, run_id, "model_response_empty", {"error": message})
            observations.append({
                "tool": "model.response",
                "arguments": {},
                "result": None,
                "error": message + ". Retry the same action once and return one JSON object.",
            })
            continue
        except ModelActionFormatError as error:
            message = f"invalid model action: {error}"
            with connect(project_root) as connection:
                _append_run_event(connection, run_id, "model_action_invalid", {"error": message})
            if action_format_retries >= 1:
                raise RuntimeError(message) from error
            action_format_retries += 1
            observations.append({
                "tool": "model.response",
                "arguments": {},
                "result": None,
                "error": message + ". Return one shorter valid JSON object and retry the same action.",
            })
            continue
        action_type = action.get("type")
        if action_type == "final":
            final_content = str(action.get("content", ""))
            if _looks_like_internal_tool_transcript(final_content):
                message = "internal TOOL_RESULT transcripts are not a researcher-readable final answer"
                with connect(project_root) as connection:
                    _append_run_event(connection, run_id, "model_action_invalid", {"error": message})
                if internal_transcript_retries >= 1:
                    raise RuntimeError(message)
                internal_transcript_retries += 1
                observations.append({
                    "tool": "model.response",
                    "arguments": {},
                    "result": None,
                    "error": message + ". Synthesize the requested conclusions in readable prose now.",
                })
                continue
            completion_tool = required_tool or _claimed_unexecuted_write_tool(
                objective, final_content, observations
            )
            required_tool_attempted = completion_tool and any(
                item.get("tool") == completion_tool
                for item in observations
            )
            if completion_tool and not required_tool_attempted:
                if missing_tool_retries >= 2:
                    raise RuntimeError(f"required tool was not attempted in this run: {completion_tool}")
                missing_tool_retries += 1
                message = (
                    f"The researcher explicitly required one {completion_tool} attempt in this run, "
                    "but none has occurred. Continue using tools now; do not describe a future step as the final answer."
                    if required_tool else
                    f"One {completion_tool} attempt is required before this run can claim the write occurred, "
                    "but none has occurred. Continue using tools now; do not describe an unexecuted write as completed."
                )
                with connect(project_root) as connection:
                    _append_run_event(connection, run_id, "required_tool_missing", {
                        "tool": completion_tool, "attempt": missing_tool_retries,
                    })
                observations.append({
                    "tool": "run.completion_contract",
                    "arguments": {"required_tool": completion_tool},
                    "result": None,
                    "error": message,
                })
                continue
            _complete_run(project_root, run_id, final_content)
            return
        if action_type != "tool_call":
            raise ValueError("model action must be tool_call or final")
        if remaining == 0:
            raise RuntimeError("agent exhausted the tool-call budget without returning a final response")
        tool_name = str(action.get("tool", ""))
        arguments = action.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")
        prior_batch_calls = [item for item in observations if item.get("tool") == tool_name]
        batch_retry_blocked = (
            tool_name == "research_event.propose_batch"
            and prior_batch_calls
            and (
                any(item.get("result") is not None for item in prior_batch_calls)
                or len(prior_batch_calls) >= 2
                or _forbids_failed_batch_retry(objective)
            )
        )
        if batch_retry_blocked:
            message = (
                "research_event.propose_batch already succeeded, exhausted its one correction, "
                "or the researcher forbade correction after validation failure; return a final response"
            )
            with connect(project_root) as connection:
                _append_run_event(connection, run_id, "tool_retry_blocked", {"tool": tool_name})
            observations.append({
                "tool": "run.completion_contract",
                "arguments": {"blocked_tool": tool_name},
                "result": None,
                "error": message,
            })
            continue
        try:
            result = _execute_tool(project_root, run_id, tool_name, arguments)
        except (KeyError, ValueError) as error:
            observations.append({
                "tool": tool_name,
                "arguments": arguments,
                "result": None,
                "error": str(error),
            })
            continue
        if isinstance(result, dict) and result.get("waiting_for_approval"):
            return
        observations.append({"tool": tool_name, "arguments": arguments, "result": result})
        if tool_name == "research_event.propose_batch" and required_tool == tool_name:
            created = result if isinstance(result, list) else []
            event_ids = [str(item.get("event_id", "")) for item in created if isinstance(item, dict)]
            suffix = f"（{', '.join(value for value in event_ids if value)}）" if event_ids else ""
            _complete_run(
                project_root,
                run_id,
                f"工作台已保存 {len(created)} 条待审事件候选{suffix}。"
                "本轮按一次写入约束结束；候选仍须逐条对照原页后由研究者决定。",
            )
            return
    raise RuntimeError("agent exhausted the tool-call budget without returning a final response")


def _explicit_required_tool(objective: str) -> str:
    patterns = (
        r"(?:恰好|只)\s*成功调用一次\s+`?([a-z][a-z0-9_.]+)`?",
        r"(?:恰好|只)?\s*调用(?:成功)?一次\s+`?([a-z][a-z0-9_.]+)`?",
        r"(?:再|重新|务必|必须|请)?\s*调用\s*`?([a-z][a-z0-9_.]+)`?\s*(?:恰好|只)?一次",
    )
    for pattern in patterns:
        match = re.search(pattern, objective, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def _forbids_failed_batch_retry(objective: str) -> bool:
    return bool(re.search(r"(?:失败|校验失败).{0,12}(?:不要|不得|禁止).{0,6}(?:重试|再试|再次调用)", objective))


def _claimed_unexecuted_write_tool(
    objective: str, final_content: str, observations: list[dict[str, Any]],
) -> str:
    if "research_event.propose_batch" not in objective:
        return ""
    if any(item.get("tool") == "research_event.propose_batch" for item in observations):
        return ""
    if re.search(r"(?:现|已|已经|完成)(?:提交|创建|新增)|提交了\s*\d+\s*条", final_content):
        return "research_event.propose_batch"
    return ""


def _looks_like_internal_tool_transcript(text: str) -> bool:
    return bool(re.search(
        r"(?is)(?:^\s*TOOL_RESULT\s+[\[{]|<\s*(?:tool_calls?|invoke)\b|"
        r"<\s*｜｜DSML｜｜(?:tool_calls|invoke)\b)",
        text,
    ))


def _mock_action(project_root: Path, observations: list[dict[str, Any]]) -> dict[str, Any]:
    tools = [item["tool"] for item in observations]
    if "project.status" not in tools:
        return {"type": "tool_call", "tool": "project.status", "arguments": {}}
    if "source.list" not in tools:
        return {"type": "tool_call", "tool": "source.list", "arguments": {}}
    if "source.page" not in tools:
        source_index = next(item["result"] for item in observations if item["tool"] == "source.list")
        sources = source_index.get("sources", []) if isinstance(source_index, dict) else source_index
        if sources:
            view = source_view(project_root, sources[0]["source_id"])
            if view["pages"]:
                return {
                    "type": "tool_call", "tool": "source.page",
                    "arguments": {"page_id": view["pages"][0]["page_id"]},
                }
    if "research.state" not in tools:
        return {"type": "tool_call", "tool": "research.state", "arguments": {}}
    if "authoring.state" not in tools:
        return {"type": "tool_call", "tool": "authoring.state", "arguments": {}}
    status = next(item["result"] for item in observations if item["tool"] == "project.status")
    source_index = next(item["result"] for item in observations if item["tool"] == "source.list")
    sources = source_index.get("sources", []) if isinstance(source_index, dict) else source_index
    page = next((item["result"] for item in observations if item["tool"] == "source.page"), None)
    research = next(item["result"] for item in observations if item["tool"] == "research.state")
    authoring = next(item["result"] for item in observations if item["tool"] == "authoring.state")
    lines = [
        "# 项目检查札记", "",
        f"- 当前来源数：{status.get('source_count', len(sources))}",
        f"- 待处理异常：{status.get('open_anomaly_count', 0)}",
        f"- 研究可用来源：{status.get('usable_source_count', 0)}",
        f"- 候选主张：{len(research['claims'])}",
        f"- 已批准证据冻结：{sum(item['status'] == 'approved' for item in research['freezes'])}",
        f"- 当前稿件：{len(authoring['manuscripts'])}",
    ]
    if sources:
        lines.append(f"- 首个来源：{sources[0]['title']}（{sources[0]['use_state']}）")
    if page:
        lines.append(f"- 已查看物理页：{page['physical_page']}（{page['use_state']}）")
    lines.extend(["", "本札记只依据工作台返回的项目状态；被阻断页面仍需回到原 PDF 人工复核。"])
    return {
        "type": "tool_call", "tool": "save_research_note",
        "arguments": {"title": "项目来源与异常检查", "content": "\n".join(lines)},
    }


def _model_action(
    profile: ModelProfile,
    objective: str,
    observations: list[dict[str, Any]],
    remaining_tool_calls: int = MAX_TOOL_CALLS,
    design_context: str = "",
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    budget_instruction = (
        "No tool calls remain. Return a final answer now using only the tool results already provided."
        if remaining_tool_calls == 0
        else f"You may make at most {remaining_tool_calls} more tool call(s). Reserve one model turn for the final answer."
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": budget_instruction},
        {"role": "system", "content": design_context},
    ]
    messages.extend(
        {"role": item["role"], "content": item["content"]}
        for item in (history or [])
    )
    messages.append({"role": "user", "content": objective})
    for observation in observations:
        messages.append({"role": "user", "content": "TOOL_RESULT " + _json(observation)})
    if profile.provider == "openai_compatible":
        endpoint = profile.endpoint.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        raw = _post_json(
            endpoint,
            {"model": profile.model, "temperature": 0, "messages": messages},
            {"Authorization": f"Bearer {profile.api_key}"}, profile.timeout_seconds,
        )
        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise RuntimeError("agent provider response did not contain message content") from error
    elif profile.provider == "ollama":
        endpoint = profile.endpoint.rstrip("/")
        if not endpoint.endswith("/api/chat"):
            endpoint += "/api/chat"
        raw = _post_json(
            endpoint,
            {"model": profile.model, "stream": False, "format": "json", "messages": messages,
             "options": {"temperature": 0}},
            {}, profile.timeout_seconds,
        )
        content = raw.get("message", {}).get("content", "")
    else:
        raise ValueError(f"unsupported agent provider: {profile.provider}")
    if not isinstance(content, str) or not content.strip():
        raise EmptyModelContentError("agent provider returned empty content")
    try:
        return _parse_action(content)
    except (json.JSONDecodeError, ValueError) as error:
        raise ModelActionFormatError(str(error)) from error


def _parse_action(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    if dsml_action := _parse_dsml_action(text):
        return dsml_action
    if tagged_action := _parse_tagged_tool_action(text):
        return tagged_action
    if bracketed := re.fullmatch(r"<\s*(\{.*\})\s*>", text, flags=re.DOTALL):
        text = bracketed.group(1).strip()
    elif text.startswith("<{") and text.endswith("}"):
        # DeepSeek occasionally emits an otherwise complete action with only
        # the opening angle bracket. Accept it only when it wraps the whole
        # response; prose containing an example remains a safe final answer.
        candidate = text[1:].strip()
        try:
            parsed, end = json.JSONDecoder(strict=False).raw_decode(candidate)
        except json.JSONDecodeError:
            pass
        else:
            if not candidate[end:].strip() and isinstance(parsed, dict):
                text = candidate
    while wrapped := re.fullmatch(r"<json_logic>\s*(.*?)\s*</json_logic>", text, flags=re.DOTALL):
        text = wrapped.group(1).strip()
    if nested_tool_action := _parse_repeated_tool_call_wrappers(text):
        return nested_tool_action
    if re.match(r"(?is)^\s*<\s*tool_call\b", text):
        raise ValueError("malformed or ambiguous nested tool_call wrapper")
    while wrapped := re.fullmatch(
        r"<(json_logic)>\s*(.*?)\s*</\1>", text, flags=re.DOTALL
    ):
        text = wrapped.group(2).strip()
    decoder = json.JSONDecoder(strict=False)
    if not text.startswith(("{", "[")):
        candidate_start = text.rfind("\n{")
        if candidate_start >= 0:
            candidate = text[candidate_start + 1:].strip()
            if '"type"' in candidate and '"tool_call"' in candidate:
                action, end = decoder.raw_decode(candidate)
                if not candidate[end:].strip() and isinstance(action, dict) and action.get("type") == "tool_call":
                    return action
        return {"type": "final", "content": text}
    action, end = decoder.raw_decode(text)
    remainder = text[end:].strip()
    while remainder:
        _, end = decoder.raw_decode(remainder)
        remainder = remainder[end:].strip()
    if not isinstance(action, dict):
        raise ValueError("agent response JSON must be an object")
    return _normalize_action(action)


def _parse_repeated_tool_call_wrappers(text: str) -> dict[str, Any] | None:
    """Recover one unambiguous JSON action from DeepSeek's repeated wrapper form."""
    remainder = text.strip()
    attributes: list[str] = []
    while opening := re.match(r"<tool_call\b([^>]*)>\s*", remainder, flags=re.IGNORECASE):
        attributes.append(opening.group(1))
        remainder = remainder[opening.end():]
    if not attributes:
        return None
    closing_count = 0
    while closing := re.search(r"\s*</tool_call>\s*$", remainder, flags=re.IGNORECASE):
        closing_count += 1
        remainder = remainder[:closing.start()]
    if not 1 <= closing_count <= len(attributes):
        raise ValueError("nested tool_call wrapper has invalid closing tags")
    try:
        decoded_remainder = unescape(remainder.strip())
        payload, end = json.JSONDecoder(strict=False).raw_decode(decoded_remainder)
    except json.JSONDecodeError as error:
        raise ValueError("nested tool_call wrapper does not contain one JSON object") from error
    if decoded_remainder[end:].strip() or not isinstance(payload, dict):
        raise ValueError("nested tool_call wrapper must contain exactly one JSON object")

    attribute_tools = {
        match.group(2)
        for value in attributes
        for match in re.finditer(
            r"\b(?:name|tool|function)\s*=\s*(['\"])([a-z][a-z0-9_.]+)\1",
            value,
            flags=re.IGNORECASE,
        )
    }
    if len(attribute_tools) > 1:
        raise ValueError("nested tool_call wrappers name multiple tools")

    normalized = _normalize_action(payload)
    if normalized.get("type") == "tool_call":
        tool = normalized.get("tool")
        arguments = normalized.get("arguments", {})
        if not isinstance(tool, str) or not re.fullmatch(r"[a-z][a-z0-9_.]+", tool):
            raise ValueError("nested tool_call JSON is missing a valid tool")
        if not isinstance(arguments, dict):
            raise ValueError("nested tool_call arguments must be a JSON object")
        if attribute_tools and tool not in attribute_tools:
            raise ValueError("nested tool_call wrapper conflicts with its JSON tool")
        return {**normalized, "arguments": arguments}
    if normalized.get("type") == "final":
        raise ValueError("nested tool_call wrapper cannot contain a final action")
    if len(attribute_tools) != 1:
        raise ValueError("nested tool_call arguments require one wrapper tool name")
    return {"type": "tool_call", "tool": next(iter(attribute_tools)), "arguments": payload}


def _parse_tagged_tool_action(text: str) -> dict[str, Any] | None:
    """Parse DeepSeek's XML-like tool form, including its observed mismatched closer."""
    invoke = re.fullmatch(
        r'(?:<tool_calls>\s*)?<invoke\s+name="([a-z][a-z0-9_.]+)">\s*'
        r'(.*?)\s*</invoke>(?:\s*</tool_calls>)?',
        text,
        flags=re.DOTALL,
    )
    if invoke:
        arguments: dict[str, Any] = {}
        remainder = invoke.group(2).strip()
        parameter_pattern = re.compile(
            r'<parameter\s+([^>]+)>(.*?)</parameter>', flags=re.DOTALL,
        )
        matches = list(parameter_pattern.finditer(remainder))
        if not matches or parameter_pattern.sub("", remainder).strip():
            raise ValueError("tagged invoke contains malformed parameters")
        for match in matches:
            name_match = re.search(r'\bname="([a-zA-Z_][a-zA-Z0-9_]*)"', match.group(1))
            if not name_match:
                raise ValueError("tagged invoke parameter is missing a valid name")
            value = unescape(match.group(2)).strip()
            try:
                arguments[name_match.group(1)] = json.loads(value)
            except json.JSONDecodeError:
                arguments[name_match.group(1)] = value
        return {"type": "tool_call", "tool": invoke.group(1), "arguments": arguments}
    wrapped = re.fullmatch(
        r"<tool_call>\s*<type>tool_call</type>\s*"
        r"<tool>([a-z][a-z0-9_.]+)</tool>\s*"
        r"<arguments>(.*?)</arguments>\s*</(?:tool_call|invoke)>",
        text,
        flags=re.DOTALL,
    )
    if not wrapped:
        return None
    arguments = json.loads(unescape(wrapped.group(2)).strip() or "{}")
    if not isinstance(arguments, dict):
        raise ValueError("tagged tool arguments must be a JSON object")
    return {"type": "tool_call", "tool": wrapped.group(1), "arguments": arguments}


def _normalize_action(action: dict[str, Any]) -> dict[str, Any]:
    """Accept unambiguous local-model aliases without weakening the action contract."""
    if action.get("type") in {"tool_call", "final"}:
        return action
    action_type = action.get("action")
    if action_type in {"tool_call", "final"}:
        return {**action, "type": action_type}
    if isinstance(action.get("tool"), str) and isinstance(action.get("arguments", {}), dict):
        return {**action, "type": "tool_call"}
    for key in ("final", "final_answer", "response"):
        if isinstance(action.get(key), str):
            return {"type": "final", "content": action[key]}
    return action


def _parse_dsml_action(text: str) -> dict[str, Any] | None:
    wrapped = re.fullmatch(
        r'<\s*｜｜DSML｜｜tool_calls\s*>\s*'
        r'<\s*｜｜DSML｜｜invoke\s+name="([a-z][a-z0-9_.]+)"\s*>\s*'
        r'(.*?)\s*'
        r'</\s*｜｜DSML｜｜invoke\s*>\s*'
        r'</\s*｜｜DSML｜｜tool_calls\s*>',
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if wrapped is None:
        return None
    tool, body = wrapped.groups()
    parameter_pattern = re.compile(
        r'<\s*｜｜DSML｜｜parameter\s+([^>]*)>(.*?)'
        r'</\s*｜｜DSML｜｜parameter\s*>',
        flags=re.DOTALL | re.IGNORECASE,
    )
    arguments: dict[str, Any] = {}
    end = 0
    for parameter in parameter_pattern.finditer(body):
        if body[end:parameter.start()].strip():
            return None
        attributes = dict(re.findall(r'([a-z_][a-z0-9_-]*)="([^"]*)"', parameter.group(1), re.IGNORECASE))
        value_text = unescape(parameter.group(2).strip())
        if "arguments" in attributes:
            if arguments:
                return None
            try:
                packed_arguments = json.loads(value_text or unescape(attributes["arguments"]))
            except json.JSONDecodeError:
                return None
            if not isinstance(packed_arguments, dict):
                return None
            arguments.update(packed_arguments)
            end = parameter.end()
            continue
        name = attributes.get("argument") or attributes.get("name", "")
        if not name or name in arguments:
            return None
        if attributes.get("string", "").lower() == "true":
            value: Any = value_text
        else:
            try:
                value = json.loads(value_text)
            except json.JSONDecodeError:
                value = value_text
        arguments[name] = value
        end = parameter.end()
    if body[end:].strip():
        return None
    return {"type": "tool_call", "tool": tool, "arguments": arguments}


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    outcome: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def request_worker() -> None:
        try:
            outcome.put((True, _post_json_blocking(url, payload, headers, timeout)))
        except BaseException as error:
            outcome.put((False, error))

    worker = threading.Thread(target=request_worker, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise TimeoutError(f"agent provider step exceeded {timeout:g} seconds")
    succeeded, value = outcome.get_nowait()
    if not succeeded:
        raise value
    return value


def _post_json_blocking(
    url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float
) -> dict[str, Any]:
    request = Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers}, method="POST",
    )
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context(cafile=certifi.where())) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = _http_error_detail(error)
        raise RuntimeError(f"agent provider returned HTTP {error.code}{detail}") from error
    except URLError as error:
        raise RuntimeError(f"agent provider could not be reached: {error.reason}") from error
    if not isinstance(result, dict):
        raise RuntimeError("agent provider response was not a JSON object")
    return result


def _read_authoring_section(project_root: Path, section_id: str) -> dict[str, Any]:
    if not section_id:
        raise ValueError("authoring.section requires section_id")
    with connect(project_root) as connection:
        row = connection.execute(
            """SELECT s.section_id, s.manuscript_id, s.section_order, s.heading,
                      s.current_version_id, v.content
               FROM manuscript_sections s
               JOIN section_versions v ON v.version_id = s.current_version_id
               WHERE s.section_id = ?""",
            (section_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"unknown manuscript section: {section_id}")
    return dict(row)


def _compact_source_list(project_root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    source_ids = arguments.get("source_ids", [])
    if not isinstance(source_ids, list) or any(not isinstance(value, str) for value in source_ids):
        raise ValueError("source.list source_ids must be a list of exact source ids")
    requested_ids = [value.strip() for value in source_ids if value.strip()]
    if len(requested_ids) > SOURCE_LIST_MAX_LIMIT:
        raise ValueError(f"source.list accepts at most {SOURCE_LIST_MAX_LIMIT} source_ids")
    query = str(arguments.get("query", "")).strip().casefold()
    try:
        limit = int(arguments.get("limit", SOURCE_LIST_DEFAULT_LIMIT))
    except (TypeError, ValueError) as error:
        raise ValueError("source.list limit must be an integer") from error
    if not 1 <= limit <= SOURCE_LIST_MAX_LIMIT:
        raise ValueError(f"source.list limit must be between 1 and {SOURCE_LIST_MAX_LIMIT}")

    sources = list_sources(project_root)
    if requested_ids:
        by_id = {str(item["source_id"]): item for item in sources}
        missing = [source_id for source_id in requested_ids if source_id not in by_id]
        if missing:
            raise KeyError(f"unknown source(s): {', '.join(missing)}")
        matched = [by_id[source_id] for source_id in requested_ids]
    elif query:
        matched = [
            item for item in sources
            if query in str(item.get("source_id", "")).casefold()
            or query in str(item.get("title", "")).casefold()
            or query in str(item.get("original_name", "")).casefold()
        ]
    else:
        matched = sources
    selected = matched[:limit]
    return {
        "sources": [
            {
                "source_id": item.get("source_id", ""),
                "title": item.get("title", ""),
                "original_name": item.get("original_name", ""),
                "processing_state": item.get("processing_state", ""),
                "use_state": item.get("use_state", ""),
                "page_count": item.get("page_count", 0),
                "citation_verification_status": item.get(
                    "citation_verification_status", "UNVERIFIED"
                ),
            }
            for item in selected
        ],
        "total_count": len(matched),
        "returned_count": len(selected),
        "has_more": len(matched) > len(selected),
        "limit": limit,
        "query": str(arguments.get("query", "")).strip(),
        "requested_source_ids": requested_ids,
        "boundary": (
            "Compact source index only; it omits source text, byte counts and full research context. "
            "Use source.page or bounded reading tools for source detail."
        ),
    }


def _compact_reading_batch(payload: dict[str, Any]) -> dict[str, Any]:
    """Preserve complete page text without repeating metadata for every PDF block."""
    compact = {key: value for key, value in payload.items() if key != "pages"}
    compact["pages"] = [
        {
            "page_id": page.get("page_id", ""),
            "physical_page": page.get("physical_page"),
            "printed_page": page.get("printed_page"),
            "verification_state": page.get("verification_state", ""),
            "use_state": page.get("use_state", ""),
            "text": "\n".join(
                str(block.get("text", "")).strip()
                for block in page.get("blocks", [])
                if str(block.get("text", "")).strip()
            ),
        }
        for page in payload.get("pages", [])
    ]
    compact["boundary"] = (
        "Complete text for the returned pages, separated by exact page identity. "
        "Block geometry is omitted here; use source.page for block-level evidence work."
    )
    return compact


def _execute_tool(project_root: Path, run_id: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    allowed = {"project.status", "source.list", "source.search", "source.page", "research.state", "research.plan_context", "retrieval.list", "authoring.state", "authoring.section", "research_design.current", "research_design.propose", "research_event.list", "research_event.coverage", "research_event.propose_batch", "reading_job.create", "reading_job.batch", "reading_note.save", "historiography.create", "save_research_note"}
    if tool_name not in allowed:
        raise ValueError(f"unknown M4 tool: {tool_name}")
    call_id, now = _id("TCL"), utc_now()
    with connect(project_root) as connection:
        connection.execute(
            """INSERT INTO tool_calls(
                   tool_call_id, run_id, tool_name, input_json, status, created_at
               ) VALUES (?, ?, ?, ?, 'RUNNING', ?)""",
            (call_id, run_id, tool_name, _json(arguments), now),
        )
        _append_run_event(connection, run_id, "tool_started", {"tool_call_id": call_id, "tool": tool_name})
    try:
        if tool_name == "project.status":
            result: Any = project_status(project_root)
        elif tool_name == "source.list":
            result = _compact_source_list(project_root, arguments)
        elif tool_name == "source.search":
            result = _search_source_blocks(
                project_root,
                str(arguments.get("query", "")),
                str(arguments.get("source_id", "")),
                int(arguments.get("limit", 10)),
            )
        elif tool_name == "source.page":
            result = _read_page(
                project_root,
                str(arguments.get("page_id", "")),
                str(arguments.get("source_id", "")),
                arguments.get("physical_page"),
            )
        elif tool_name == "research.state":
            result = _agent_research_state(project_root)
        elif tool_name == "research.plan_context":
            result = _planning_context(project_root)
        elif tool_name == "retrieval.list":
            result = list_retrievals(project_root)
        elif tool_name == "authoring.state":
            result = _compact_authoring_state(project_root)
        elif tool_name == "authoring.section":
            result = _read_authoring_section(project_root, str(arguments.get("section_id", "")))
        elif tool_name == "research_design.current":
            with connect(project_root) as connection:
                run = connection.execute(
                    "SELECT model_snapshot_json FROM runs WHERE run_id = ?", (run_id,)
                ).fetchone()
            snapshot = _decode(run["model_snapshot_json"], {}) if run else {}
            result = ({"withheld": True, "reason": "independent_planning"}
                      if snapshot.get("planning_mode") == "independent_planning"
                      else current_shared_design(project_root))
        elif tool_name == "research_design.propose":
            title = str(arguments.get("title", "")).strip()
            content = str(arguments.get("content", "")).strip()
            if not title or not content:
                raise ValueError("research_design.propose requires title and content")
            with connect(project_root) as connection:
                run = connection.execute(
                    "SELECT model_snapshot_json FROM runs WHERE run_id = ?", (run_id,)
                ).fetchone()
            snapshot = _decode(run["model_snapshot_json"], {}) if run else {}
            current = current_shared_design(project_root)
            result = create_design_draft(
                project_root, title, content, "shared_design", "model",
                str(snapshot.get("model", "research-agent")),
                str(arguments.get("change_summary", "")),
                current["design_id"] if current else "", run_id, snapshot,
            )
        elif tool_name == "research_event.list":
            case_ids = arguments.get("case_ids")
            statuses = arguments.get("statuses")
            if case_ids is not None and not isinstance(case_ids, list):
                raise ValueError("research_event.list case_ids must be a list")
            if statuses is not None and not isinstance(statuses, list):
                raise ValueError("research_event.list statuses must be a list")
            result = event_state(
                project_root,
                case_ids,
                statuses,
                str(arguments.get("detail", "full")),
            )
        elif tool_name == "research_event.coverage":
            case_ids = arguments.get("case_ids")
            if case_ids is not None and not isinstance(case_ids, list):
                raise ValueError("research_event.coverage case_ids must be a list")
            result = event_coverage(project_root, case_ids)
        elif tool_name == "research_event.propose_batch":
            with connect(project_root) as connection:
                prior = connection.execute(
                    """SELECT status FROM tool_calls
                       WHERE run_id = ? AND tool_name = ? AND tool_call_id <> ?
                       ORDER BY created_at""",
                    (run_id, tool_name, call_id),
                ).fetchall()
            if any(row["status"] == "COMPLETED" for row in prior) or len(prior) >= 2:
                raise ValueError(
                    "research_event.propose_batch already succeeded or exhausted its one "
                    "validation correction; return a final response"
                )
            events = arguments.get("events", [])
            if not isinstance(events, list):
                raise ValueError("research_event.propose_batch requires an events list")
            with connect(project_root) as connection:
                run = connection.execute(
                    "SELECT model_snapshot_json FROM runs WHERE run_id = ?", (run_id,)
                ).fetchone()
            snapshot = _decode(run["model_snapshot_json"], {}) if run else {}
            result = create_event_candidates(
                project_root, events, str(snapshot.get("model", "research-agent")), "model", snapshot,
            )
        elif tool_name == "reading_job.create":
            source_ids = arguments.get("source_ids", [])
            if not isinstance(source_ids, list):
                raise ValueError("reading_job.create source_ids must be a list")
            result = create_reading_job(
                project_root,
                str(arguments.get("title", "")),
                str(arguments.get("question", "")),
                str(arguments.get("mode", "")),
                [str(value) for value in source_ids],
                str(arguments.get("stop_condition", "")),
            )
        elif tool_name == "reading_job.batch":
            result = _compact_reading_batch(reading_job_batch(
                project_root,
                str(arguments.get("job_id", "")),
                str(arguments.get("source_id", "")),
                int(arguments.get("after_physical_page", 0)),
                int(arguments.get("page_limit", 5)),
            ))
        elif tool_name == "reading_note.save":
            physical_pages = arguments.get("physical_pages", [])
            if not isinstance(physical_pages, list):
                raise ValueError("reading_note.save physical_pages must be a list")
            result = save_reading_note(
                project_root,
                str(arguments.get("job_id", "")),
                str(arguments.get("source_id", "")),
                [int(value) for value in physical_pages],
                str(arguments.get("content", "")),
                bool(arguments.get("complete", False)),
            )
        elif tool_name == "historiography.create":
            result = create_historiography_entry(
                project_root, validate_historiography_entry_payload(project_root, arguments)
            )
        else:
            title = str(arguments.get("title", "")).strip()
            content = str(arguments.get("content", "")).strip()
            if not title or not content:
                raise ValueError("save_research_note requires title and content")
            approval_id = _id("APR")
            request_payload = {"title": title, "content": content}
            with connect(project_root) as connection:
                connection.execute(
                    "UPDATE tool_calls SET status = 'WAITING_FOR_APPROVAL' WHERE tool_call_id = ?", (call_id,)
                )
                connection.execute(
                    """INSERT INTO approvals(
                           approval_id, run_id, tool_call_id, status, request_json, created_at
                       ) VALUES (?, ?, ?, 'pending', ?, ?)""",
                    (approval_id, run_id, call_id, _json(request_payload), utc_now()),
                )
                connection.execute(
                    "UPDATE runs SET status = 'WAITING_FOR_APPROVAL', updated_at = ? WHERE run_id = ?",
                    (utc_now(), run_id),
                )
                _append_run_event(
                    connection, run_id, "approval_requested",
                    {"approval_id": approval_id, "tool_call_id": call_id, "tool": tool_name},
                )
            return {"waiting_for_approval": True, "approval_id": approval_id}
    except Exception as error:
        with connect(project_root) as connection:
            connection.execute(
                """UPDATE tool_calls SET status = 'FAILED', error = ?, completed_at = ?
                   WHERE tool_call_id = ?""",
                (str(error), utc_now(), call_id),
            )
            _append_run_event(
                connection, run_id, "tool_failed",
                {"tool_call_id": call_id, "tool": tool_name, "error": str(error)},
            )
        raise
    with connect(project_root) as connection:
        connection.execute(
            """UPDATE tool_calls SET status = 'COMPLETED', output_json = ?, completed_at = ?
               WHERE tool_call_id = ?""",
            (_json(result), utc_now(), call_id),
        )
        _append_run_event(
            connection, run_id, "tool_completed", {"tool_call_id": call_id, "tool": tool_name}
        )
    return result


def _http_error_detail(error: HTTPError) -> str:
    try:
        payload = json.loads(error.read().decode("utf-8", "replace"))
    except (json.JSONDecodeError, OSError):
        return ""
    detail = payload.get("error", payload) if isinstance(payload, dict) else {}
    if not isinstance(detail, dict):
        return ""
    code = str(detail.get("code", "")).strip()
    message = str(detail.get("message", "")).strip()
    summary = " · ".join(value for value in (code, message) if value)
    return f": {summary[:300]}" if summary else ""


def _planning_context(project_root: Path) -> dict[str, Any]:
    status = project_status(project_root)
    sources = list_sources(project_root)
    research = research_state(project_root)
    return {
        "project": {
            "title": status.get("title", ""),
            "source_count": status.get("source_count", len(sources)),
            "open_anomaly_count": status.get("open_anomaly_count", 0),
        },
        "source_state_semantics": {
            "processing_state": "Describes the local ingestion or verification workflow, not the historical value or existence of the work.",
            "use_state": "Describes what the current local copy may be used for; blocked or partial does not mean the work is absent from scholarship.",
            "zero_pages": "Means this workspace has no usable pages yet; it is not evidence that the source lacks content.",
        },
        "sources": [
            {
                "source_id": item["source_id"], "title": item["title"],
                "use_state": item["use_state"], "page_count": item.get("page_count", 0),
                "research_context": item.get("research_context", {}),
            }
            for item in sources
        ],
        "research_counts": {
            "claims": len(research.get("claims", [])),
            "evidence": sum(len(item.get("evidence", [])) for item in research.get("claims", [])),
            "freezes": len(research.get("freezes", [])),
            "approved_freezes": sum(item.get("status") == "approved" for item in research.get("freezes", [])),
            "event_rows": event_state(project_root)["counts"],
        },
        "freeze_summaries": [
            {
                "freeze_id": item.get("freeze_id", ""), "title": item.get("title", ""),
                "status": item.get("status", ""),
                "claim_count": len(item.get("payload", {}).get("claims", [])),
            }
            for item in research.get("freezes", [])
        ],
        "boundary": "This compact planning context is project state, not source evidence. Inspect original pages before evidence use.",
    }


def _agent_research_state(project_root: Path) -> dict[str, Any]:
    research = research_state(project_root)
    reading_jobs = list_reading_jobs(project_root)
    return {
        "counts": {
            "claims": len(research.get("claims", [])),
            "evidence": sum(len(item.get("evidence", [])) for item in research.get("claims", [])),
            "freezes": len(research.get("freezes", [])),
            "approved_freezes": sum(item.get("status") == "approved" for item in research.get("freezes", [])),
            "artifacts": len(research.get("artifacts", [])),
            "browser_sessions": len(research.get("browser_sessions", [])),
            "memory_candidates": len(research.get("memory_candidates", [])),
            "reading_jobs": len(reading_jobs),
        },
        "claims": [
            {"claim_id": item.get("claim_id", ""), "text": item.get("text", ""),
             "status": item.get("status", ""), "evidence_count": len(item.get("evidence", []))}
            for item in research.get("claims", [])[:30]
        ],
        "freezes": [
            {"freeze_id": item.get("freeze_id", ""), "title": item.get("title", ""),
             "status": item.get("status", ""),
             "claim_count": len(item.get("payload", {}).get("claims", []))}
            for item in research.get("freezes", [])[:20]
        ],
        "reading_jobs": [
            {
                "job_id": item.get("job_id", ""),
                "title": item.get("title", ""),
                "mode": item.get("mode", ""),
                "source_ids": item.get("source_ids", []),
                "status": item.get("status", ""),
                "stop_condition": item.get("stop_condition", ""),
                "note_count": len(item.get("notes", [])),
            }
            for item in reading_jobs[:20]
        ],
        "boundary": (
            "Compact index only. Reading jobs expose exact assignments but omit note and source text; "
            "use reading_job.batch for bounded pages. Inspect exact sources and verified pages before evidence use."
        ),
    }


def _read_page(
    project_root: Path,
    page_id: str = "",
    source_id: str = "",
    physical_page: Any = None,
) -> dict[str, Any]:
    page_id, source_id = page_id.strip(), source_id.strip()
    if not page_id and (not source_id or physical_page in (None, "")):
        raise ValueError("source.page requires page_id or source_id with physical_page")
    with connect(project_root) as connection:
        if page_id:
            row = connection.execute(
                "SELECT page_id, source_id FROM pages WHERE page_id = ?", (page_id,)
            ).fetchone()
        else:
            try:
                physical_page = int(physical_page)
            except (TypeError, ValueError) as error:
                raise ValueError("physical_page must be an integer") from error
            row = connection.execute(
                """SELECT page_id, source_id FROM pages
                   WHERE source_id = ? AND physical_page = ?""",
                (source_id, physical_page),
            ).fetchone()
    if row is None:
        locator = page_id or f"{source_id} physical page {physical_page}"
        raise KeyError(f"unknown page: {locator}")
    page_id = str(row["page_id"])
    view = source_view(project_root, str(row["source_id"]))
    page = next(item for item in view["pages"] if item["page_id"] == page_id)
    page_block_ids = {block["block_id"] for block in page["blocks"]}
    page_is_checked = page["verification_state"] in {
        "human_spot_checked", "human_verified", "human_repaired",
    }
    anomalies = [
        item for item in view["anomalies"]
        if item["status"] == "open" and item["target_id"] in {page_id, *(b["block_id"] for b in page["blocks"])}
    ]
    return {
        "page_id": page_id,
        "physical_page": page["physical_page"],
        "printed_page": page["printed_page"],
        "verification_state": page["verification_state"],
        "use_state": page["use_state"],
        "blocks": [
            {"block_id": block["block_id"], "order": block["block_order"], "type": block["block_type"],
             "text": block["effective_text"],
             "verification_state": block["verification_state"],
             "use_state": block["use_state"],
             "usable_for_evidence": (
                 block["use_state"] == "research_usable"
                 and block["verification_state"] in {"human_verified", "human_repaired"}
                 and page_is_checked
             )}
            for block in page["blocks"]
        ],
        "adjacent_relations": [
            {
                "relation_id": relation["relation_id"],
                "from_block_id": relation["from_block_id"],
                "to_block_id": relation["to_block_id"],
                "relation_type": relation["relation_type"],
                "effective_value": relation["effective_value"],
                "verification_state": relation["verification_state"],
            }
            for relation in view["relations"]
            if relation["from_block_id"] in page_block_ids
            or relation["to_block_id"] in page_block_ids
        ],
        "open_anomalies": anomalies,
    }


def _search_source_blocks(project_root: Path, query: str, source_id: str = "", limit: int = 10) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        raise ValueError("source.search requires query")
    variants: list[str] = []
    for value in re.split(r"\s+(?i:OR)\s+|[/／|]", query):
        value = value.strip()
        if value and value.casefold() not in {item.casefold() for item in variants}:
            variants.append(value)
    variants = variants or [query]
    limit = max(1, min(limit, 30))
    sql = """SELECT s.source_id, s.title, p.page_id, p.physical_page, p.printed_page,
                    p.page_type,
                    p.verification_state AS page_verification_state, p.use_state AS page_use_state,
                    b.block_id, b.verification_state AS block_verification_state,
                    b.use_state AS block_use_state, COALESCE(b.human_text, b.machine_text) AS text
             FROM blocks b JOIN pages p ON p.page_id = b.page_id
             JOIN sources s ON s.source_id = p.source_id
             WHERE b.use_state != 'superseded' AND COALESCE(b.human_text, b.machine_text) LIKE ?"""
    if source_id:
        sql += " AND s.source_id = ?"
    sql += " ORDER BY s.created_at, p.physical_page, b.block_order LIMIT ?"
    with connect(project_root) as connection:
        groups = []
        for value in variants:
            parameters: list[Any] = [f"%{value}%"]
            if source_id:
                parameters.append(source_id)
            parameters.append(limit)
            groups.append(connection.execute(sql, parameters).fetchall())
    rows = []
    seen: set[str] = set()
    for index in range(limit):
        for group in groups:
            if index >= len(group):
                continue
            row = group[index]
            if row["block_id"] in seen:
                continue
            rows.append(row)
            seen.add(row["block_id"])
            if len(rows) >= limit:
                break
        if len(rows) >= limit:
            break
    return [
        {
            **dict(row),
            "text": str(row["text"])[:1200],
            "matched_queries": [value for value in variants if value.casefold() in str(row["text"]).casefold()],
        }
        for row in rows
    ]


def decide_approval(
    project_root: Path,
    approval_id: str,
    approved: bool,
    reviewer: str,
    reason: str,
    edited_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reviewer, reason = reviewer.strip(), reason.strip()
    if not reviewer or not reason:
        raise ValueError("reviewer and reason are required")
    with connect(project_root) as connection:
        row = connection.execute(
            """SELECT a.*, tc.tool_name, tc.status AS tool_status, r.thread_id, r.goal_id
               FROM approvals a
               JOIN tool_calls tc ON tc.tool_call_id = a.tool_call_id
               JOIN runs r ON r.run_id = a.run_id
               WHERE a.approval_id = ?""",
            (approval_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown approval: {approval_id}")
        if row["status"] != "pending":
            raise ValueError(f"approval is already {row['status']}")
        request_payload = _decode(row["request_json"], {})
    final_request = edited_request if edited_request is not None else request_payload
    if not isinstance(final_request, dict):
        raise ValueError("edited request must be an object")
    output: dict[str, Any]
    if approved:
        title = str(final_request.get("title", "")).strip()
        content = str(final_request.get("content", "")).strip()
        if not title or not content:
            raise ValueError("approved note requires title and content")
        output = _write_note(project_root, approval_id, title, content)
        final_text = f"研究札记已由 {reviewer} 核准并保存：{output['project_path']}"
        tool_status, approval_status, run_status, goal_status = "COMPLETED", "approved", "COMPLETED", "complete"
    else:
        output = {"saved": False, "reason": reason}
        final_text = f"研究札记提案已被 {reviewer} 拒绝；未写入项目。理由：{reason}"
        tool_status, approval_status, run_status, goal_status = "REJECTED", "rejected", "COMPLETED", "complete"
    now = utc_now()
    decision = {
        "approved": approved, "reviewer": reviewer, "reason": reason,
        "edited_request": final_request, "output": output,
    }
    with connect(project_root) as connection:
        current = connection.execute("SELECT status FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
        if current is None or current["status"] != "pending":
            raise ValueError("approval state changed before decision")
        connection.execute(
            "UPDATE approvals SET status = ?, decision_json = ?, decided_at = ? WHERE approval_id = ?",
            (approval_status, _json(decision), now, approval_id),
        )
        connection.execute(
            """UPDATE tool_calls SET status = ?, output_json = ?, completed_at = ?
               WHERE tool_call_id = ?""",
            (tool_status, _json(output), now, row["tool_call_id"]),
        )
        connection.execute(
            """UPDATE runs SET status = ?, updated_at = ?, completed_at = ? WHERE run_id = ?""",
            (run_status, now, now, row["run_id"]),
        )
        connection.execute(
            "UPDATE goals SET status = ?, completed_at = ? WHERE goal_id = ?",
            (goal_status, now, row["goal_id"]),
        )
        message_id = _id("MSG")
        connection.execute(
            "INSERT INTO messages(message_id, thread_id, role, content_json, created_at) VALUES (?, ?, 'assistant', ?, ?)",
            (message_id, row["thread_id"], _json({"text": final_text}), now),
        )
        connection.execute("UPDATE threads SET updated_at = ? WHERE thread_id = ?", (now, row["thread_id"]))
        _append_run_event(connection, row["run_id"], "approval_decided", {"approval_id": approval_id, **decision})
        _append_run_event(connection, row["run_id"], "assistant_message", {"message_id": message_id})
        _append_run_event(connection, row["run_id"], "run_completed", {"approved": approved})
    return thread_view(project_root, str(row["thread_id"]))


def _write_note(project_root: Path, approval_id: str, title: str, content: str) -> dict[str, Any]:
    notes = project_root / "research" / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    path = notes / f"{approval_id}.md"
    payload = f"---\ntitle: {_json(title)}\napproval_id: {approval_id}\n---\n\n{content.rstrip()}\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != payload:
            raise FileExistsError(f"approval note exists with different content: {path}")
        return {"saved": True, "project_path": path.relative_to(project_root).as_posix()}
    temporary = path.with_suffix(".md.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)
    return {"saved": True, "project_path": path.relative_to(project_root).as_posix()}


def _complete_run(project_root: Path, run_id: str, content: str) -> None:
    text = content.strip() or "Agent 已完成本次检查。"
    now = utc_now()
    with connect(project_root) as connection:
        row = connection.execute("SELECT thread_id, goal_id, status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown run: {run_id}")
        if row["status"] in RUN_TERMINAL:
            return
        message_id = _id("MSG")
        connection.execute(
            "INSERT INTO messages(message_id, thread_id, role, content_json, created_at) VALUES (?, ?, 'assistant', ?, ?)",
            (message_id, row["thread_id"], _json({"text": text}), now),
        )
        connection.execute(
            "UPDATE runs SET status = 'COMPLETED', updated_at = ?, completed_at = ? WHERE run_id = ?",
            (now, now, run_id),
        )
        connection.execute(
            "UPDATE goals SET status = 'complete', completed_at = ? WHERE goal_id = ?", (now, row["goal_id"])
        )
        connection.execute("UPDATE threads SET updated_at = ? WHERE thread_id = ?", (now, row["thread_id"]))
        _append_run_event(connection, run_id, "assistant_message", {"message_id": message_id})
        _append_run_event(connection, run_id, "run_completed", {})
