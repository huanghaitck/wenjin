from __future__ import annotations

import json
import base64
import hashlib
import mimetypes
import os
import queue
import re
import ssl
import sys
import threading
import uuid
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import certifi

from .db import connect, utc_now
from .agent_profile import agent_profile_prompt
from .authoring import (
    authoring_state,
    create_historiography_entry,
    create_reading_job,
    list_reading_jobs,
    reading_job_batch,
    save_reading_note,
    validate_historiography_entry_payload,
)
from .research import list_retrievals, retrieval_record, search as search_research
from .research_design import create_design_draft, current_shared_design
from .research_events import create_event_candidates, event_coverage, event_state
from .scholarship import (
    inspect_controlled_browser,
    create_browser_session,
    launch_controlled_browser,
    navigate_controlled_browser,
    read_controlled_browser,
    research_state,
)
from .service import list_sources, project_status, source_view
from .skill_registry import discover_skills, get_skill
from .model_settings import ROLES, reasoning_controls
from .domain_plugins import call_domain_plugin_tool, find_config_root, plugin_state, repair_domain_plugin
from .domain_plugins import validate_domain_plugin
from .plugin_sdk import create_local_skill, create_plugin_project
from .attachments import inspect_attachment
from .library import library_assets, library_graph, library_status, search_library, work_detail
from .project_library import add_library_file_to_project
from .system_health import diagnose_system, repair_system


MAIN_ROLE = "main_reasoning"
RUN_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}
MAX_TOOL_CALLS = 24
ACCESS_MODES = {"ask", "research_assist", "full_computer"}
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


def harness_backend() -> str:
    configured = os.environ.get("WENJIN_HARNESS_BACKEND", "").strip().casefold()
    if configured in {"codex", "legacy"}:
        return configured
    return "legacy" if any("unittest" in str(value).casefold() for value in sys.argv) else "codex"


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


def _compact_retrievals(project_root: Path, record_id: str = "", limit: int = 30) -> dict[str, Any]:
    limit = max(1, min(int(limit), 100))
    if not record_id:
        records = list_retrievals(project_root)
        return {
            "records": [
                {
                    "record_id": item["record_id"], "provider": item["provider"],
                    "query": item["query"], "status": item["status"],
                    "result_count": item["result_count"], "created_at": item["created_at"],
                }
                for item in records[:limit]
            ],
            "boundary": "Choose one record_id to inspect captured bibliographic results.",
        }
    record = retrieval_record(project_root, record_id)
    results = [
        {
            "result_id": item["result_id"], "title": item["title"],
            "authors": item["authors"], "publication_year": item["publication_year"],
            "container_title": item["container_title"], "doi": item["doi"],
            "url": item["url"], "qualification": item["qualification"],
            "route": item.get("route"), "route_reason": item.get("route_reason"),
        }
        for item in record.get("results", [])[:limit]
    ]
    return {
        "record": {
            "record_id": record["record_id"], "provider": record["provider"],
            "query": record["query"], "status": record["status"],
            "result_count": record["result_count"], "filters": record["filters"],
        },
        "results": results,
        "returned_count": len(results),
        "has_more": len(record.get("results", [])) > len(results),
        "boundary": (
            "Captured titles and metadata are discovery leads. Recommend what the researcher should "
            "download, but do not claim any item was read until its file is acquired and verified."
        ),
    }
SYSTEM_PROMPT = """You are a general local computer-use agent optimized for humanities and social-science research.
 Retain broad Codex/Hermes-style capability for files, web research, office applications, local programs,
 coding and reusable Skills; apply stronger source, evidence and writing gates only when the task is scholarly.
 Natural-language intent is sufficient: do not ask the user to restate a clear request as tool names or JSON.
Use tools to inspect project facts. Never claim you read a source unless a tool returned it.
Return exactly one JSON object for exactly one action and no markdown. If several tools are needed,
request them one at a time and wait for each TOOL_RESULT before choosing the next action.
 Available actions:
 {"type":"tool_call","tool":"system.diagnose","arguments":{}}
 {"type":"tool_call","tool":"system.repair","arguments":{}}
 {"type":"tool_call","tool":"project.status","arguments":{}}
{"type":"tool_call","tool":"source.list","arguments":{"source_ids":["optional-exact-source-id"],"query":"optional title or id fragment","limit":20}}
{"type":"tool_call","tool":"source.search","arguments":{"query":"...","source_id":"optional","limit":10}}
{"type":"tool_call","tool":"source.page","arguments":{"page_id":"exact composite id"}}
{"type":"tool_call","tool":"source.page","arguments":{"source_id":"...","physical_page":249}}
{"type":"tool_call","tool":"library.search","arguments":{"query":"short title author or subject keywords","tags":[],"limit":10}}
{"type":"tool_call","tool":"library.work","arguments":{"work_id":"exact-work-id"}}
{"type":"tool_call","tool":"library.add_to_project","arguments":{"work_id":"exact-work-id","file_id":"exact-current-pdf-or-docx-file-id"}}
{"type":"tool_call","tool":"research.state","arguments":{}}
{"type":"tool_call","tool":"research.plan_context","arguments":{}}
{"type":"tool_call","tool":"retrieval.list","arguments":{"record_id":"optional exact retrieval record","limit":30}}
{"type":"tool_call","tool":"research.search","arguments":{"provider":"crossref|openalex|zotero","query":"...","limit":10}}
{"type":"tool_call","tool":"plugin.list","arguments":{}}
{"type":"tool_call","tool":"plugin.repair","arguments":{"plugin_name":"exact installed plugin"}}
{"type":"tool_call","tool":"plugin.call","arguments":{"plugin_name":"exact installed plugin","tool_name":"approved tool","arguments":{}}}
{"type":"tool_call","tool":"domain_agent.list","arguments":{}}
{"type":"tool_call","tool":"domain_agent.consult","arguments":{"plugin_name":"exact installed domain pack","question":"bounded specialist question"}}
{"type":"tool_call","tool":"skill.list","arguments":{}}
{"type":"tool_call","tool":"skill.read","arguments":{"name":"exact user-action skill name"}}
{"type":"tool_call","tool":"skill.create","arguments":{"name":"lower-case-skill-name","display_name":"...","description":"...","instructions":"complete reusable instructions","allow_implicit_invocation":true}}
{"type":"tool_call","tool":"attachment.inspect","arguments":{"attachment_id":"ATT_...","prompt":"what to inspect"}}
{"type":"tool_call","tool":"computer.roots","arguments":{}}
{"type":"tool_call","tool":"computer.file_search","arguments":{"roots":["D:\\\\Research"],"query":"disaster","extensions":[".zip",".sqlite"],"max_results":100}}
{"type":"tool_call","tool":"computer.windows","arguments":{"limit":30}}
{"type":"tool_call","tool":"computer.snapshot","arguments":{"window_handle":0,"depth":3,"limit":250}}
{"type":"tool_call","tool":"computer.capture","arguments":{}}
{"type":"tool_call","tool":"computer.runtime_status","arguments":{}}
{"type":"tool_call","tool":"computer.runtime_repair","arguments":{"component":"python|powershell7"}}
{"type":"tool_call","tool":"computer.focus","arguments":{"ref":"exact-ref-from-latest-snapshot"}}
{"type":"tool_call","tool":"computer.click","arguments":{"ref":"exact-ref-from-latest-snapshot"}}
{"type":"tool_call","tool":"computer.click_coordinates","arguments":{"x":100,"y":100}}
{"type":"tool_call","tool":"computer.type","arguments":{"ref":"exact-ref-from-latest-snapshot","text":"..."}}
{"type":"tool_call","tool":"computer.keys","arguments":{"keys":"{Ctrl}c"}}
{"type":"tool_call","tool":"computer.launch","arguments":{"executable":"absolute executable path","args":[],"cwd":"optional absolute directory"}}
{"type":"tool_call","tool":"computer.run","arguments":{"executable":"absolute executable path","args":["explicit","arguments"],"cwd":"optional absolute directory","timeout":300}}
{"type":"tool_call","tool":"domain_pack.validate","arguments":{"plugin_root":"absolute existing domain-pack folder"}}
{"type":"tool_call","tool":"domain_pack.create","arguments":{"parent":"absolute parent folder","name":"lower-case project name","display_name":"...","description":"..."}}
{"type":"tool_call","tool":"browser.snapshot","arguments":{"session_id":"exact-visible-session-id"}}
{"type":"tool_call","tool":"browser.start","arguments":{"url":"https://example.com/page-or-search"}}
{"type":"tool_call","tool":"browser.read","arguments":{"session_id":"exact-visible-session-id"}}
{"type":"tool_call","tool":"browser.open","arguments":{"session_id":"exact-visible-session-id","url":"same-domain-http-or-https-url"}}
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
For a vague library request, translate the researcher's wording into two to four short title, author, place,
period, or subject keywords. Search with short keywords, inspect likely works, and retry one synonym when the
first query is empty. Do not call an empty query merely to dump the whole library. When the researcher asks to
adopt a work, inspect library.work, choose an available exact PDF or DOCX file_id, then call
library.add_to_project. Adoption automatically creates page-linked PDF text or DOCX locator text and must pass
the active approval policy; never imply that merely linking a bibliography has cleaned or read the source.
Follow an explicit user tool scope. Do not call unrelated state tools merely because they are available.
Retrieval results are leads, not evidence. For logged-in database results, first list records and then
inspect the selected record_id. You may recommend which titles the researcher should download based on
metadata and the research question, but never claim those works were read. Only approved evidence freezes
may support drafting.
Use plugin.list only when the user requests a small-domain capability. plugin.call accepts only tools
explicitly approved by the installed plugin manifest; plugin output remains a candidate and cannot bypass
Wenjin source, evidence, writing or review gates.
 If plugin.list reports package_changed or runtime_missing and the user asked to fix it, call plugin.repair once.
It reinstalls from the recorded local ZIP/directory and revalidates the self-contained runtime. If that source no
 longer exists, ask the user to import the ZIP again; do not search for unrelated workflow scripts.
 Use system.diagnose for a general Wenjin self-check. It is read-only. Call system.repair only after the user
 explicitly asks to repair; it backs up the project and repairs only plugins with a recorded local source.
 It never installs optional runtimes, restores databases, changes research rules, or overwrites source/output files.
Use domain_agent.consult when a stateful installed specialist should work through a bounded domain task.
The specialist has an isolated thread and tool history. Treat its answer and artifacts as candidates; you
remain responsible for cross-domain judgment and must not present a candidate artifact as approved.
For ordinary-language research requests, use the implicit skill catalog in context. Call skill.read for the
smallest matching research skill before applying it; users do not need to type slash commands.
Use skill.create only after the user has supplied or approved a stable purpose, trigger boundary and complete
instructions. The new Skill is installed in Wenjin's local Skill directory and becomes discoverable without
turning it into a domain Agent or MCP service.
When CURRENT_RESEARCH_CONTEXT includes attached_refs, inspect each relevant attachment before answering.
An attachment is project context, not a verified source or approved evidence.
Computer Use is already routed through the installed system pack. For a request to locate files on the
researcher's computer, call computer.roots and then computer.file_search; do not claim that local file
access is unavailable before attempting those tools. Search is bounded and returns names and metadata,
not file contents. Search common_folders before whole drive roots. If a whole-drive search returns zero
matches with truncated=true, retry once against the most relevant common folder before reporting no result.
Packaged Wenjin and self-contained Domain Agents do not require system Python or PowerShell. When a matching
Domain Agent is installed, consult it instead of searching the disk for its workflow scripts or probing Python
packages. For an explicit external script, call computer.runtime_status first. Use the exact returned Python or
PowerShell 7 path; never invent powershell1 and never treat the WindowsApps zero-byte Python alias as installed.
Only call computer.runtime_repair after the user asked to repair the optional runtime; it is a sensitive action
and must pass the active approval policy. Do not import a broad package list in one command merely to test it.
If an explicit external script reports one missing Python package, use the resolved interpreter to inspect that
one module and, after approval, install only that named dependency. Do not infer missing packages from filenames.
Use computer.windows/snapshot before control refs. State-changing computer tools obey
the run's Ask, Auto-approve or Full access policy. Never inspect password controls, credentials or CAPTCHA.
Use domain_pack.create only when the researcher explicitly asks to create a reusable domain pack and
has supplied its scope, material types, operations, field/schema needs, permission classes and data
boundary. It writes an engineering scaffold only after those orchestration choices are explicit; it is
not a finished scholarly method. domain_pack.validate is read-only.
Browser tools operate only on a visible session that the researcher opened from the Research Browser.
They may inspect rendered state, read the active page and navigate to a same-domain URL. They cannot
click controls, fill forms, log in, solve CAPTCHA, pay, download or submit. Browser text is a discovery
lead and must be acquired and verified as a project source before evidentiary use.
browser.start may create and open a visible, domain-bounded session for an explicit HTTP(S) URL. Use it for
ordinary URL lookup or web search instead of claiming that internet access is unavailable. Logged-in actions
and consequential submissions still remain under the existing approval boundary.
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


COMPUTER_TOOL_ALIASES = {
    "computer.status": "computer_status",
    "computer.runtime_status": "runtime_status",
    "computer.runtime_repair": "repair_runtime",
    "computer.roots": "filesystem_roots",
    "computer.file_search": "file_search",
    "computer.windows": "window_list",
    "computer.snapshot": "desktop_snapshot",
    "computer.capture": "screen_capture",
    "computer.focus": "focus_control",
    "computer.click": "click_control",
    "computer.click_coordinates": "click_coordinates",
    "computer.type": "type_text",
    "computer.keys": "press_keys",
    "computer.launch": "launch_program",
    "computer.run": "run_command",
}


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
    timeout_seconds: float = 180.0


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


def _clean_final_text(value: str) -> str:
    return re.sub(
        r"^(?:final\s+(?:answer|response)|assistant\s+final|最终(?:回答|答复))\s*:\s*",
        "", value.strip(), count=1, flags=re.IGNORECASE,
    ).strip()


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


def queue_run_control(
    project_root: Path, run_kind: str, action: str, content: str = "",
    *, thread_id: str = "", session_id: str = "",
) -> dict[str, Any]:
    if run_kind not in {"main", "domain"} or action not in {"steer", "stop"}:
        raise ValueError("unknown run control")
    content = content.strip()
    if action == "steer" and not content:
        raise ValueError("steering message is required")
    with connect(project_root) as connection:
        if run_kind == "main":
            row = connection.execute(
                "SELECT run_id,thread_id FROM runs WHERE thread_id=? AND status='RUNNING' ORDER BY created_at DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
        else:
            query = (
                "SELECT run_id,main_thread_id AS thread_id FROM domain_agent_runs "
                "WHERE session_id=? AND status='RUNNING'"
            )
            params: tuple[str, ...] = (session_id,)
            if thread_id:
                query += " AND main_thread_id=?"
                params += (thread_id,)
            row = connection.execute(query + " ORDER BY created_at DESC LIMIT 1", params).fetchone()
        if row is None:
            raise ValueError("there is no running agent task to control")
        control_id, now = _id("CTL"), utc_now()
        connection.execute(
            "INSERT INTO agent_run_controls(control_id,run_kind,run_id,action,content,status,created_at) VALUES (?,?,?,?,?,'pending',?)",
            (control_id, run_kind, row["run_id"], action, content, now),
        )
        linked_domain_run_ids: list[str] = []
        if run_kind == "main" and action == "stop":
            linked_domain_run_ids = [str(item["run_id"]) for item in connection.execute(
                "SELECT run_id FROM domain_agent_runs WHERE main_thread_id=? AND status='RUNNING'",
                (row["thread_id"],),
            ).fetchall()]
            connection.executemany(
                "INSERT INTO agent_run_controls(control_id,run_kind,run_id,action,content,status,created_at) "
                "VALUES (?,'domain',?,'stop','','pending',?)",
                [(_id("CTL"), domain_run_id, now) for domain_run_id in linked_domain_run_ids],
            )
        if action == "steer":
            if run_kind == "main":
                connection.execute(
                    "INSERT INTO messages(message_id,thread_id,role,content_json,created_at) VALUES (?,?, 'user', ?, ?)",
                    (_id("MSG"), row["thread_id"], _json({"text": content, "steering_for_run": row["run_id"], "run_control_id": control_id}), now),
                )
            else:
                session = connection.execute(
                    "SELECT session_id FROM domain_agent_runs WHERE run_id=?", (row["run_id"],)
                ).fetchone()
                connection.execute(
                    "INSERT INTO domain_agent_messages(message_id,session_id,role,content_json,created_at) VALUES (?,?, 'user', ?, ?)",
                    (_id("DMS"), session["session_id"], _json({"text": content, "main_thread_id": row["thread_id"] or "", "steering_for_run": row["run_id"], "run_control_id": control_id}), now),
                )
        return {"control_id": control_id, "run_id": row["run_id"], "action": action,
                "status": "pending", "linked_domain_run_ids": linked_domain_run_ids}


def revise_run_control(
    project_root: Path, control_id: str, *, content: str = "", delete: bool = False,
) -> dict[str, Any]:
    with connect(project_root) as connection:
        row = connection.execute(
            "SELECT * FROM agent_run_controls WHERE control_id=?", (control_id,),
        ).fetchone()
        if row is None:
            raise KeyError("unknown run control")
        if row["status"] != "pending" or row["action"] != "steer":
            raise ValueError("only a queued direction update can be edited or deleted")
        table = "messages" if row["run_kind"] == "main" else "domain_agent_messages"
        message = connection.execute(
            f"SELECT message_id,content_json FROM {table} WHERE json_extract(content_json,'$.run_control_id')=?",
            (control_id,),
        ).fetchone()
        if delete:
            if message is not None:
                connection.execute(f"DELETE FROM {table} WHERE message_id=?", (message["message_id"],))
            connection.execute("DELETE FROM agent_run_controls WHERE control_id=?", (control_id,))
            return {"control_id": control_id, "deleted": True}
        content = content.strip()
        if not content:
            raise ValueError("steering message is required")
        connection.execute(
            "UPDATE agent_run_controls SET content=? WHERE control_id=?", (content, control_id),
        )
        if message is not None:
            payload = json.loads(message["content_json"])
            payload["text"] = content
            connection.execute(
                f"UPDATE {table} SET content_json=? WHERE message_id=?",
                (_json(payload), message["message_id"]),
            )
        return {"control_id": control_id, "deleted": False, "content": content}


def _consume_run_controls(project_root: Path, run_kind: str, run_id: str) -> dict[str, Any]:
    with connect(project_root) as connection:
        rows = connection.execute(
            "SELECT * FROM agent_run_controls WHERE run_kind=? AND run_id=? AND status='pending' ORDER BY created_at,control_id",
            (run_kind, run_id),
        ).fetchall()
        if rows:
            connection.executemany(
                "UPDATE agent_run_controls SET status='applied',applied_at=? WHERE control_id=?",
                [(utc_now(), row["control_id"]) for row in rows],
            )
    return {
        "stop": any(row["action"] == "stop" for row in rows),
        "steering": [str(row["content"]) for row in rows if row["action"] == "steer"],
    }


def _apply_main_run_controls(
    project_root: Path, run_id: str, observations: list[dict[str, Any]],
) -> str:
    controls = _consume_run_controls(project_root, "main", run_id)
    with connect(project_root) as connection:
        for message in controls["steering"]:
            _append_run_event(connection, run_id, "user_steering", {"content": message})
            observations.append({"tool": "user.steering", "arguments": {}, "result": {"message": message}})
        if controls["stop"]:
            connection.execute(
                "UPDATE runs SET status='STOPPED',updated_at=?,completed_at=? WHERE run_id=?",
                (utc_now(), utc_now(), run_id),
            )
            _append_run_event(connection, run_id, "run_stopped", {})
            return "stop"
    return "steer" if controls["steering"] else ""


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
    mock_enabled = (
        os.environ.get("HRW_ENABLE_MOCK_MODEL", "").strip() == "1"
        or any("unittest" in str(argument).casefold() for argument in sys.argv)
    )
    with connect(project_root) as connection:
        if mock_enabled:
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
        else:
            connection.execute(
                "DELETE FROM model_assignments WHERE profile_id = 'builtin-mock'"
            )
            connection.execute("DELETE FROM model_profiles WHERE profile_id = 'builtin-mock'")
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
        assigned = connection.execute(
            "SELECT 1 FROM model_assignments WHERE role = ?", (MAIN_ROLE,)
        ).fetchone()
        if assigned is None and environment is not None:
            connection.execute(
                "INSERT INTO model_assignments(role, profile_id, updated_at) VALUES (?, ?, ?)",
                (MAIN_ROLE, environment.profile_id, now),
            )
        elif assigned is None and mock_enabled:
            connection.execute(
                "INSERT INTO model_assignments(role, profile_id, updated_at) VALUES (?, 'builtin-mock', ?)",
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
        timeout_seconds=float(os.environ.get("HRW_AGENT_TIMEOUT_SECONDS", "180")),
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
        "reasoning_controls": reasoning_controls(row["provider"], row["model"], row["endpoint"]),
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


def clear_model_assignment(project_root: Path, role: str = MAIN_ROLE) -> dict[str, Any]:
    if role != MAIN_ROLE:
        raise ValueError(f"M4 only supports role {MAIN_ROLE}")
    with connect(project_root) as connection:
        connection.execute("DELETE FROM model_assignments WHERE role = ?", (role,))
    return {"role": role, "profile_id": ""}


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
    timeout = 180.0
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


def create_thread(project_root: Path, title: str, parent_thread_id: str = "") -> dict[str, Any]:
    title = title.strip()
    if not title:
        raise ValueError("thread title is required")
    thread_id = _id("THR")
    now = utc_now()
    with connect(project_root) as connection:
        if parent_thread_id and connection.execute(
            "SELECT 1 FROM threads WHERE thread_id=?", (parent_thread_id,)
        ).fetchone() is None:
            raise KeyError(f"unknown parent thread: {parent_thread_id}")
        connection.execute(
            "INSERT INTO threads(thread_id, title, status, created_at, updated_at) VALUES (?, ?, 'active', ?, ?)",
            (thread_id, title, now, now),
        )
        if parent_thread_id:
            connection.execute(
                "INSERT INTO thread_inheritance(child_thread_id,parent_thread_id,created_at) VALUES (?,?,?)",
                (thread_id, parent_thread_id, now),
            )
    return {
        "thread_id": thread_id, "title": title, "status": "active", "created_at": now,
        "parent_thread_id": parent_thread_id,
    }


def rename_thread(project_root: Path, thread_id: str, title: str) -> dict[str, Any]:
    title = title.strip()
    if not title:
        raise ValueError("thread title is required")
    with connect(project_root) as connection:
        row = connection.execute("SELECT thread_id FROM threads WHERE thread_id=?", (thread_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown thread: {thread_id}")
        connection.execute(
            "UPDATE threads SET title=?,updated_at=? WHERE thread_id=?",
            (title[:120], utc_now(), thread_id),
        )
    return {"thread_id": thread_id, "title": title[:120]}


def _maybe_title_thread(project_root: Path, thread_id: str, content: str) -> None:
    with connect(project_root) as connection:
        row = connection.execute("SELECT title FROM threads WHERE thread_id=?", (thread_id,)).fetchone()
    if row is None or not str(row["title"]).startswith(("新的研究", "New research")):
        return
    profile = _role_profile("title_generation")
    if profile is None:
        return
    title = _plain_model_call(profile, [{"role": "system", "content": "Return one concise thread title, at most 28 Chinese characters or 12 English words. No quotes, labels, punctuation suffix, or explanation."},{"role": "user", "content": content[:4000]}]).strip().splitlines()[0][:80]
    if title:
        with connect(project_root) as connection:
            connection.execute("UPDATE threads SET title=?,updated_at=? WHERE thread_id=?", (title, utc_now(), thread_id))


def ensure_default_thread(project_root: Path) -> dict[str, Any]:
    with connect(project_root) as connection:
        row = connection.execute(
            "SELECT thread_id, title, status, created_at FROM threads ORDER BY created_at LIMIT 1"
        ).fetchone()
    return dict(row) if row is not None else create_thread(project_root, "新的研究讨论")


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
        domain_rows = connection.execute(
            "SELECT run_id FROM domain_agent_runs WHERE status = 'RUNNING'"
        ).fetchall()
        message = "Domain subagent run was interrupted by an application restart."
        for row in domain_rows:
            connection.execute(
                "UPDATE domain_agent_runs SET status='FAILED',error=?,updated_at=? WHERE run_id=?",
                (message, now, row["run_id"]),
            )
            connection.execute(
                "UPDATE domain_agent_tool_calls SET status='FAILED',output_json=?,completed_at=? "
                "WHERE run_id=? AND status='RUNNING'",
                (_json({"error": message}), now, row["run_id"]),
            )
    return len(rows) + len(domain_rows)


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
        thread = dict(thread)
        inherited = connection.execute(
            "SELECT parent_thread_id FROM thread_inheritance WHERE child_thread_id=?", (thread_id,)
        ).fetchone()
        thread["parent_thread_id"] = str(inherited["parent_thread_id"]) if inherited else ""
        messages = [dict(row) for row in connection.execute(
            "SELECT * FROM messages WHERE thread_id = ? ORDER BY created_at, message_id", (thread_id,)
        )]
        runs = [dict(row) for row in connection.execute(
            "SELECT * FROM runs WHERE thread_id = ? ORDER BY created_at DESC", (thread_id,)
        )]
        for message in messages:
            message["content"] = _decode(message.pop("content_json"), {})
            control_id = str(message["content"].get("run_control_id", ""))
            if control_id:
                control = connection.execute(
                    "SELECT status FROM agent_run_controls WHERE control_id=?", (control_id,),
                ).fetchone()
                message["run_control_status"] = str(control["status"]) if control else "deleted"
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
                call = next(
                    (value for value in run["tool_calls"] if value["tool_call_id"] == item["tool_call_id"]),
                    None,
                )
                item["tool_name"] = call["tool_name"] if call else ""
                run["approvals"].append(item)
            run["artifact_receipt"] = _saved_artifact_receipt(connection, str(run["run_id"]))
    return {"thread": thread, "messages": messages, "runs": runs}


def _thread_history(project_root: Path, thread_id: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
    with connect(project_root) as connection:
        lineage, current = [], thread_id
        while current and current not in lineage and len(lineage) < 8:
            lineage.append(current)
            parent = connection.execute(
                "SELECT parent_thread_id FROM thread_inheritance WHERE child_thread_id=?", (current,)
            ).fetchone()
            current = str(parent["parent_thread_id"]) if parent else ""
        all_rows = []
        for inherited_thread_id in reversed(lineage):
            all_rows.extend(connection.execute(
                """SELECT message_id, role, content_json FROM messages
                   WHERE thread_id = ? AND role IN ('user', 'assistant')
                   ORDER BY created_at, message_id""",
                (inherited_thread_id,),
            ).fetchall())
        rows = list(all_rows)
    prepared: list[dict[str, str]] = []
    truncated = False
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
        prepared.append({"message_id": str(row["message_id"]), "role": str(row["role"]), "content": text})
    configured_window = int(os.environ.get("HRW_AGENT_CONTEXT_WINDOW", "0") or 0)
    if not configured_window:
        configured_window = 1_000_000 if "deepseek-v4" in os.environ.get("HRW_AGENT_MODEL", "").casefold() else 128_000
    threshold_tokens = int(configured_window * .9)
    estimated_tokens = sum(max(1, (len(item["content"]) + 1) // 2) for item in prepared)
    selected = prepared
    compacted = estimated_tokens >= threshold_tokens and len(prepared) > 8
    if compacted:
        recent, older, recent_tokens = [], list(prepared), 0
        recent_budget = max(8_000, int(configured_window * .35))
        while older and (recent_tokens < recent_budget or len(recent) < 8):
            item = older.pop()
            recent.insert(0, item)
            recent_tokens += max(1, (len(item["content"]) + 1) // 2)
        source = "\n\n".join(f"[{item['role']} {item['message_id']}]\n{item['content']}" for item in older)
        profile = _role_profile("context_compression") or _assigned_profile(project_root)
        summary = _plain_model_call(profile, [{"role": "system", "content": "Compress earlier conversation without inventing facts. Preserve user goals, decisions, file paths, source and page identifiers, citations, unresolved questions, permissions and promised deliverables. Omit social filler and repeated wording."},{"role": "user", "content": source}])[:24000]
        selected = [{"message_id": "COMPACTED_HISTORY", "role": "system", "content": "EARLIER_CONVERSATION_COMPACTED\n" + summary}, *recent]
        truncated = True
    return selected, {
        "message_ids": [item["message_id"] for item in selected],
        "truncated": truncated,
        "character_count": sum(len(item["content"]) for item in selected),
        "context_window_tokens": configured_window,
        "compression_threshold_tokens": threshold_tokens,
        "estimated_tokens_before_compression": estimated_tokens,
        "compacted": compacted,
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


def _role_profile(role: str) -> ModelProfile | None:
    definition = ROLES.get(role)
    if not definition:
        return None
    prefix = definition["prefix"]
    provider = os.environ.get(f"{prefix}_PROVIDER", "").strip().lower()
    model = os.environ.get(f"{prefix}_MODEL", "").strip()
    endpoint = os.environ.get(f"{prefix}_BASE_URL", "").strip()
    api_key = os.environ.get(f"{prefix}_API_KEY", "").strip()
    if provider not in {"ollama", "openai_compatible"} or not model or not endpoint:
        return None
    if provider == "openai_compatible" and not api_key:
        return None
    return ModelProfile(
        profile_id=f"role-{role}", provider=provider, model=model, endpoint=endpoint,
        capabilities=("text",), credential_ref="environment", status="available",
        api_key=api_key,
        timeout_seconds=int(os.environ.get(f"{prefix}_TIMEOUT_SECONDS", "90") or "90"),
    )


def _plain_model_call(profile: ModelProfile, messages: list[dict[str, str]]) -> str:
    if profile.provider == "openai_compatible":
        endpoint = profile.endpoint.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        raw = _post_json(
            endpoint, {"model": profile.model, "temperature": 0, "messages": messages},
            {"Authorization": f"Bearer {profile.api_key}"}, profile.timeout_seconds,
        )
        content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
    elif profile.provider == "ollama":
        endpoint = profile.endpoint.rstrip("/")
        if not endpoint.endswith("/api/chat"):
            endpoint += "/api/chat"
        raw = _post_json(
            endpoint, {"model": profile.model, "stream": False, "messages": messages,
                       "options": {"temperature": 0}}, {}, profile.timeout_seconds,
        )
        content = raw.get("message", {}).get("content", "")
    else:
        raise ValueError(f"unsupported advisory provider: {profile.provider}")
    if not isinstance(content, str) or not content.strip():
        raise EmptyModelContentError("advisory model returned empty content")
    return content.strip()


def _vision_file_call(profile: ModelProfile, path: Path, prompt: str) -> str:
    raw = path.read_bytes()
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("image attachment exceeds the 20 MB vision limit")
    encoded = base64.b64encode(raw).decode("ascii")
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    if profile.provider == "ollama":
        endpoint = profile.endpoint.rstrip("/")
        if not endpoint.endswith("/api/chat"):
            endpoint += "/api/chat"
        payload = {
            "model": profile.model, "stream": False,
            "messages": [{"role": "user", "content": prompt, "images": [encoded]}],
            "options": {"temperature": 0},
        }
        response = _post_json(endpoint, payload, {}, profile.timeout_seconds)
        content = response.get("message", {}).get("content", "")
    else:
        endpoint = profile.endpoint.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        payload = {
            "model": profile.model, "temperature": 0,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
            ]}],
        }
        response = _post_json(
            endpoint, payload, {"Authorization": f"Bearer {profile.api_key}"}, profile.timeout_seconds,
        )
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not isinstance(content, str) or not content.strip():
        raise EmptyModelContentError("vision model returned empty content")
    return content.strip()


def _moa_guidance(
    objective: str,
    history: list[dict[str, str]],
    observations: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    if os.environ.get("HRW_MOA_ENABLED") != "1":
        return []
    roles = list(dict.fromkeys(
        value.strip() for value in os.environ.get("HRW_MOA_REFERENCE_ROLES", "").split(",")
        if value.strip() and value.strip() != MAIN_ROLE
    ))
    results: list[dict[str, str]] = []
    for role in roles:
        profile = _role_profile(role)
        if profile is None:
            results.append({"role": role, "error": "role unavailable"})
            continue
        messages = [{
            "role": "system",
            "content": (
                "You are a private advisory model for a humanities research agent. "
                "Analyze the request, identify evidence risks, useful research moves and competing interpretations. "
                "Do not call tools, do not address the researcher, and do not claim that an action was executed."
            ),
        }]
        messages.extend(history[-6:])
        messages.append({"role": "user", "content": objective})
        if observations:
            messages.append({
                "role": "user",
                "content": "Current bounded tool receipts:\n" + _json(observations[-6:]),
            })
        try:
            results.append({"role": role, "content": _plain_model_call(profile, messages)[:12000]})
        except Exception as error:
            results.append({"role": role, "error": str(error)[:500]})
    return results


def _format_moa_guidance(items: list[dict[str, str]]) -> str:
    usable = [item for item in items if item.get("content")]
    if not usable:
        return ""
    return (
        "PRIVATE_MOA_ADVICE\n"
        "These are fallible advisory views, not tool results or source evidence. Compare them, then make your own "
        "decision. You remain the only acting model and the only model allowed to call tools.\n"
        + "\n\n".join(f"[{item['role']}]\n{item['content']}" for item in usable)
    )


def _implicit_skill_catalog() -> str:
    skills = [
        {"name": item["name"], "description": item["description"]}
        for item in discover_skills()
        if item["placement"] == "user_action"
        and bool((item.get("agent_program") or {}).get("allow_implicit_invocation"))
    ]
    return "IMPLICIT_RESEARCH_SKILLS " + _json(skills) if skills else ""


def send_message(project_root: Path, thread_id: str, content: str,
                 context: dict[str, Any] | None = None,
                 planning_mode: str = "guided_execution",
                 access_mode: str = "ask",
                 reasoning_mode: str = "standard",
                 reasoning_effort: str = "medium") -> dict[str, Any]:
    content = content.strip()
    if not content:
        raise ValueError("message content is required")
    if planning_mode not in {"independent_planning", "guided_execution"}:
        raise ValueError(f"unknown planning mode: {planning_mode}")
    if access_mode not in ACCESS_MODES:
        raise ValueError(f"unknown agent access mode: {access_mode}")
    if reasoning_mode not in {"standard", "deep"}:
        raise ValueError(f"unknown reasoning mode: {reasoning_mode}")
    if reasoning_effort not in {"low", "medium", "high", "max"}:
        raise ValueError(f"unknown reasoning effort: {reasoning_effort}")
    resolved_content, active_skill, skill_context = _resolve_skill_invocation(content)
    _maybe_title_thread(project_root, thread_id, resolved_content)
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
        "access_mode": access_mode,
        "reasoning_mode": reasoning_mode,
        "reasoning_effort": reasoning_effort,
        "harness_backend": harness_backend(),
        "shared_design_id": shared_design["design_id"] if shared_design else "",
        "history_policy": "bounded_thread_history" if history else "withheld_or_empty",
        "history_message_ids": history_receipt["message_ids"],
        "history_truncated": history_receipt["truncated"],
        "history_character_count": history_receipt["character_count"],
        "history_compacted": history_receipt.get("compacted", False),
        "context_window_tokens": history_receipt.get("context_window_tokens", 0),
        "compression_threshold_tokens": history_receipt.get("compression_threshold_tokens", 0),
        "active_skill": active_skill,
        "moa": {
            "enabled": os.environ.get("HRW_MOA_ENABLED") == "1",
            "reference_roles": [
                value for value in os.environ.get("HRW_MOA_REFERENCE_ROLES", "").split(",") if value
            ],
            "fanout": os.environ.get("HRW_MOA_FANOUT", "user_turn"),
        },
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
            "access_mode": access_mode,
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
        design_context += "\n\n" + agent_profile_prompt(project_root)
        implicit_skills = _implicit_skill_catalog()
        if implicit_skills:
            design_context += "\n\n" + implicit_skills
        domain_catalog = _domain_agent_catalog(project_root)
        if domain_catalog:
            design_context += "\n\n" + domain_catalog
        design_context += (
            "\n\nAGENT_ACCESS_MODE " + access_mode + ". ask pauses every state-changing computer "
            "action; research_assist auto-approves routine actions but pauses sensitive execution; "
            "full_computer auto-approves all tools exposed by the installed Computer Use and domain "
            "packs for this run. Password controls, credential extraction, CAPTCHA solving and payment "
            "confirmation remain unavailable in every mode."
        )
        attachment_ids = list(dict.fromkeys(
            re.findall(r'"attachment_id"\s*:\s*"(ATT_[a-f0-9]+)"', objective)
        ))
        if (
            snapshot["harness_backend"] == "codex"
            and (attachment_ids or _matching_domain_agent(project_root, objective, history))
        ):
            _advance_run(
                project_root, run_id, objective, profile, design_context, history,
                reasoning_mode=reasoning_mode, reasoning_effort=reasoning_effort,
            )
            return thread_view(project_root, thread_id)
        if snapshot["harness_backend"] == "codex":
            from .codex_harness import run_turn

            moa_guidance = _moa_guidance(objective, history)
            if moa_guidance:
                design_context += "\n\n" + _format_moa_guidance(moa_guidance)
                with connect(project_root) as connection:
                    _append_run_event(connection, run_id, "moa_advice_ready", {
                        "reference_roles": [item["role"] for item in moa_guidance],
                        "failed_roles": [item["role"] for item in moa_guidance if item.get("error")],
                        "fanout": os.environ.get("HRW_MOA_FANOUT", "user_turn"),
                    })
            result_text = run_turn(
                project_root, thread_id, run_id, objective, profile, design_context,
                access_mode, reasoning_mode, reasoning_effort, history,
            )
            with connect(project_root) as connection:
                current = connection.execute(
                    "SELECT status FROM runs WHERE run_id=?", (run_id,)
                ).fetchone()
            if current is not None and current["status"] == "RUNNING":
                _complete_run(project_root, run_id, result_text)
        else:
            _advance_run(
                project_root, run_id, objective, profile, design_context, history,
                reasoning_mode=reasoning_mode, reasoning_effort=reasoning_effort,
            )
    except Exception as error:
        _fail_run(project_root, run_id, error)
        raise
    return thread_view(project_root, thread_id)


def _advance_run(project_root: Path, run_id: str, objective: str, profile: ModelProfile,
                 design_context: str = "", history: list[dict[str, str]] | None = None,
                 reasoning_mode: str = "standard", reasoning_effort: str = "medium",
                 initial_observations: list[dict[str, Any]] | None = None) -> None:
    observations: list[dict[str, Any]] = list(initial_observations or [])
    moa_fanout = os.environ.get("HRW_MOA_FANOUT", "user_turn")
    explicit_required = _explicit_required_tool(objective)
    attachment_ids = list(dict.fromkeys(re.findall(r'"attachment_id"\s*:\s*"(ATT_[a-f0-9]+)"', objective)))
    domain_plugin = _matching_domain_agent(project_root, objective, history or [])
    if explicit_required and domain_plugin:
        plugin = next(
            (item for item in _ready_domain_agents(project_root) if item["name"] == domain_plugin),
            None,
        )
        if plugin is None or explicit_required not in plugin.get("agent_tools", []):
            domain_plugin = ""
    required_tool = explicit_required or (
        "attachment.inspect" if attachment_ids else "domain_agent.consult" if domain_plugin else ""
    )
    if attachment_ids and not observations:
        receipts = []
        for attachment_id in attachment_ids:
            receipt = _execute_tool(
                project_root, run_id, "attachment.inspect", {"attachment_id": attachment_id}
            )
            observations.append({
                "tool": "attachment.inspect", "arguments": {"attachment_id": attachment_id},
                "result": receipt,
            })
            receipts.append(receipt)
        if not domain_plugin and any(
            isinstance(item, dict) and item.get("kind") == "spreadsheet" for item in receipts
        ):
            spreadsheet_agents = [
                item for item in _ready_domain_agents(project_root)
                if "inspect_half_finished_workbook" in item.get("agent_tools", [])
            ]
            if len(spreadsheet_agents) == 1:
                domain_plugin = str(spreadsheet_agents[0]["name"])
        if domain_plugin:
            domain_result = _execute_tool(
                project_root, run_id, "domain_agent.consult",
                {
                    "plugin_name": domain_plugin,
                    "question": objective + "\n\nATTACHMENT_INSPECTION_RECEIPTS " + _json(receipts),
                    "new_thread": _new_domain_thread_requested(objective),
                },
            )
            latest = domain_result.get("latest_message") if isinstance(domain_result, dict) else None
            latest_run = domain_result.get("latest_run") if isinstance(domain_result, dict) else None
            if isinstance(latest_run, dict) and latest_run.get("status") != "COMPLETED":
                raise RuntimeError(str(latest_run.get("error") or "领域 Agent 未完成本轮任务"))
            content = str(((latest or {}).get("content") or {}).get("text", "")).strip()
            _complete_run(project_root, run_id, content or "领域 Agent 已根据附件完成处理。")
            return
    if domain_plugin and not attachment_ids and not any(item.get("tool") == "domain_agent.consult" for item in observations):
        result = _execute_tool(
            project_root, run_id, "domain_agent.consult",
            {"plugin_name": domain_plugin, "question": objective,
             "new_thread": _new_domain_thread_requested(objective)},
        )
        latest = result.get("latest_message") if isinstance(result, dict) else None
        latest_run = result.get("latest_run") if isinstance(result, dict) else None
        if isinstance(latest_run, dict) and latest_run.get("status") != "COMPLETED":
            raise RuntimeError(str(latest_run.get("error") or "领域 Agent 未完成本轮任务"))
        content = str(((latest or {}).get("content") or {}).get("text", "")).strip()
        _complete_run(
            project_root, run_id,
            content or "领域Agent已完成本轮处理；结果仍为候选，需在项目中复核后采用。",
        )
        return
    moa_guidance = _moa_guidance(objective, history or [])
    if moa_guidance:
        with connect(project_root) as connection:
            _append_run_event(connection, run_id, "moa_advice_ready", {
                "reference_roles": [item["role"] for item in moa_guidance],
                "failed_roles": [item["role"] for item in moa_guidance if item.get("error")],
                "fanout": moa_fanout,
            })
    empty_content_retries = 0
    action_format_retries = 0
    model_request_retries = 0
    internal_transcript_retries = 0
    missing_tool_retries = 0
    tool_budget = {"low": 8, "medium": 16, "high": MAX_TOOL_CALLS, "max": MAX_TOOL_CALLS}[reasoning_effort]
    for _ in range(tool_budget + 1):
        if _apply_main_run_controls(project_root, run_id, observations) == "stop":
            return
        remaining = tool_budget - len(observations)
        if observations and moa_fanout == "per_iteration":
            moa_guidance = _moa_guidance(objective, history or [], observations)
        private_guidance = _format_moa_guidance(moa_guidance)
        try:
            action = _mock_action(project_root, observations) if profile.provider == "mock" else _model_action(
                profile, objective, observations, remaining,
                design_context + ("\n\n" + private_guidance if private_guidance else ""), history,
                SYSTEM_PROMPT, reasoning_mode, reasoning_effort,
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
        except RuntimeError as error:
            if model_request_retries or not _is_transient_model_error(str(error)):
                raise
            model_request_retries += 1
            with connect(project_root) as connection:
                _append_run_event(connection, run_id, "model_request_retry", {
                    "attempt": model_request_retries, "error": str(error),
                })
            continue
        control = _apply_main_run_controls(project_root, run_id, observations)
        if control == "stop":
            return
        if control == "steer":
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
            if attachment_ids:
                inspected = {
                    str((item.get("arguments") or {}).get("attachment_id", ""))
                    for item in observations
                    if item.get("tool") == "attachment.inspect" and item.get("result") is not None
                }
                missing_attachments = [value for value in attachment_ids if value not in inspected]
                if missing_attachments:
                    if missing_tool_retries >= 2:
                        raise RuntimeError("attached files were not inspected: " + ", ".join(missing_attachments))
                    missing_tool_retries += 1
                    observations.append({
                        "tool": "run.completion_contract",
                        "arguments": {"missing_attachments": missing_attachments},
                        "result": None,
                        "error": "Inspect every attached file before returning a final answer.",
                    })
                    continue
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
        exact_failures = [
            item for item in observations
            if item.get("tool") == tool_name and item.get("arguments") == arguments
            and item.get("result") is None and item.get("error")
        ]
        if len(exact_failures) >= 2:
            with connect(project_root) as connection:
                _append_run_event(connection, run_id, "tool_retry_blocked", {
                    "tool": tool_name, "reason": "same_call_failed_twice",
                })
            observations.append({
                "tool": "run.recovery", "arguments": {"blocked_tool": tool_name},
                "result": None,
                "error": "The same call failed twice. Use a different tool, correct different arguments, or return a concise user-facing blocker.",
            })
            continue
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
            with connect(project_root) as connection:
                _append_run_event(connection, run_id, "tool_correction_requested", {
                    "tool": tool_name, "error": str(error), "attempt": len(exact_failures) + 1,
                })
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
        if (
            tool_name == "attachment.inspect" and not domain_plugin
            and isinstance(result, dict) and result.get("kind") == "spreadsheet"
        ):
            spreadsheet_agents = [
                item for item in _ready_domain_agents(project_root)
                if "inspect_half_finished_workbook" in item.get("agent_tools", [])
            ]
            if len(spreadsheet_agents) == 1:
                domain_plugin = str(spreadsheet_agents[0]["name"])
        if tool_name == "attachment.inspect" and domain_plugin:
            inspected = {
                str((item.get("arguments") or {}).get("attachment_id", ""))
                for item in observations
                if item.get("tool") == "attachment.inspect" and item.get("result") is not None
            }
            if all(value in inspected for value in attachment_ids):
                receipts = [
                    item.get("result") for item in observations
                    if item.get("tool") == "attachment.inspect" and item.get("result") is not None
                ]
                domain_result = _execute_tool(
                    project_root, run_id, "domain_agent.consult",
                    {
                        "plugin_name": domain_plugin,
                        "question": objective + "\n\nATTACHMENT_INSPECTION_RECEIPTS " + _json(receipts),
                        "new_thread": _new_domain_thread_requested(objective),
                    },
                )
                latest = domain_result.get("latest_message") if isinstance(domain_result, dict) else None
                content = str(((latest or {}).get("content") or {}).get("text", "")).strip()
                _complete_run(
                    project_root, run_id,
                    content or "领域 Agent 已根据附件识读回执完成处理；结果仍为候选。",
                )
                return
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
    if re.search(
        r"(?:请|帮我|替我|现在)?\s*(?:查找|搜索|寻找|定位|检查).{0,24}"
        r"(?:电脑|磁盘|硬盘|文件夹).{0,24}(?:文件|领域包|安装包)",
        objective,
    ):
        return "computer.file_search"
    if re.search(r"(?:检查|诊断|查看|确认).{0,30}(?:Python|PowerShell|pwsh|运行环境|脚本环境|依赖)", objective, re.I):
        return "computer.runtime_status"
    if re.search(r"(?:修复|安装|补齐).{0,30}(?:Python|PowerShell|pwsh|运行环境|脚本环境)", objective, re.I):
        return "computer.runtime_repair"
    if re.search(r"(?:修复|重装|恢复).{0,24}(?:领域\s*Agent|领域包|插件).{0,24}(?:运行|工具|环境|安装)?", objective, re.I):
        return "plugin.repair"
    if re.search(r"(?:系统|问津|工作台).{0,16}(?:自检|诊断|健康检查)|(?:自检|诊断).{0,16}(?:系统|问津|工作台)", objective, re.I):
        return "system.diagnose"
    if re.search(r"(?:系统|问津|工作台).{0,16}(?:自修复|安全修复|自动修复)|(?:自修复|安全修复).{0,16}(?:系统|问津|工作台)", objective, re.I):
        return "system.repair"
    return ""


def _new_domain_thread_requested(objective: str) -> bool:
    normalized = re.sub(r"\s+", "", objective).lower()
    action = any(word in normalized for word in ("新建", "创建", "另建", "另开", "新开", "重新开", "单独开", "另起"))
    scope = any(word in normalized for word in ("领域agent", "领域智能体", "领域代理", "智能体", "subagent"))
    target = any(word in normalized for word in ("线程", "对话", "会话", "任务"))
    no_reuse = ("不复用" in normalized or "不要复用" in normalized or "别复用" in normalized) and target
    return (action and scope and target) or (scope and no_reuse)


def _ready_domain_agents(project_root: Path) -> list[dict[str, Any]]:
    from .domain_plugins import find_config_root, plugin_state

    return [
        item for item in plugin_state(find_config_root(project_root))["plugins"]
        if item.get("kind") != "system" and item.get("status") == "ready" and item.get("agent")
    ]


def _domain_agent_catalog(project_root: Path) -> str:
    agents = [
        {
            "plugin_name": item["name"],
            "description": item.get("description_zh") or item.get("description", ""),
            "routing_triggers": (item.get("agent") or {}).get("routing_triggers", []),
            "tools": item.get("agent_tools", []),
        }
        for item in _ready_domain_agents(project_root)
    ]
    if not agents:
        return ""
    return (
        "INSTALLED_DOMAIN_SUBAGENTS " + _json(agents) + "\n"
        "When the user's ordinary-language request matches a routing trigger, consult the matching specialist "
        "with domain_agent.consult inside this same main conversation. Reuse its persistent private session; "
        "do not ask the user to open a domain workspace or create another research thread."
    )


def _natural_domain_tool(project_root: Path, objective: str) -> str:
    return "domain_agent.consult" if _matching_domain_agent(project_root, objective) else ""


def _matching_domain_agent(
    project_root: Path,
    objective: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    if re.search(r"(?:领域包|插件|subagent|agent).{0,20}(?:界面|架构|设计|安装|删除|开发|调试)", objective, re.I):
        return ""
    agents = _ready_domain_agents(project_root)
    if len(agents) == 1 and re.search(
        r"(?:继续|沿用|恢复|续跑|接着).{0,80}(?:原|同一|上一轮)?\s*(?:领域\s*)?(?:sub)?agent",
        objective,
        re.I,
    ):
        return str(agents[0]["name"])
    for item in agents:
        agent = item.get("agent") or {}
        triggers = list(agent.get("routing_triggers", []))
        for values in (agent.get("tool_triggers") or {}).values():
            triggers.extend(values if isinstance(values, list) else [])
        if any(str(trigger).strip() and str(trigger) in objective for trigger in triggers):
            return str(item["name"])
    if re.search(r"(?:继续|上一轮|刚才|断点续跑|恢复运行|接着)", objective):
        context = "\n".join(str(item.get("content") or "") for item in (history or [])[-6:])
        for item in agents:
            agent = item.get("agent") or {}
            triggers = list(agent.get("routing_triggers", []))
            for values in (agent.get("tool_triggers") or {}).values():
                triggers.extend(values if isinstance(values, list) else [])
            if any(str(trigger).strip() and str(trigger) in context for trigger in triggers):
                return str(item["name"])
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
    if "save_research_note" in tools:
        return {"type": "final", "content": "项目检查已经完成，研究札记已保存并记录审批回执。"}
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
    system_prompt: str = SYSTEM_PROMPT,
    reasoning_mode: str = "standard",
    reasoning_effort: str = "medium",
) -> dict[str, Any]:
    budget_instruction = (
        "No tool calls remain. Return a final answer now using only the tool results already provided."
        if remaining_tool_calls == 0
        else f"You may make at most {remaining_tool_calls} more tool call(s). Reserve one model turn for the final answer."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": budget_instruction},
        {"role": "system", "content": design_context},
    ]
    if reasoning_mode == "deep":
        messages.append({"role": "system", "content": "DEEP_REASONING_MODE: verify the plan, tool choice, and completion criteria before acting."})
    messages.extend(
        {"role": item["role"], "content": item["content"]}
        for item in (history or [])
    )
    messages.append({"role": "user", "content": objective})
    for observation in observations:
        messages.append({"role": "user", "content": "TOOL_RESULT " + _json(observation)})
    timeout = _adaptive_model_timeout(
        profile.timeout_seconds, reasoning_mode, reasoning_effort, len(observations),
    )
    if profile.provider == "openai_compatible":
        endpoint = profile.endpoint.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        payload: dict[str, Any] = {
            "model": profile.model, "temperature": 0, "messages": messages,
        }
        if "deepseek" in profile.model.casefold() or "deepseek" in profile.endpoint.casefold():
            payload["thinking"] = {"type": "enabled" if reasoning_mode == "deep" else "disabled"}
            if reasoning_mode == "deep":
                payload["reasoning_effort"] = reasoning_effort
        raw = _post_json(
            endpoint,
            payload,
            {"Authorization": f"Bearer {profile.api_key}"}, timeout,
        )
        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise RuntimeError("agent provider response did not contain message content") from error
    elif profile.provider == "ollama":
        endpoint = profile.endpoint.rstrip("/")
        if not endpoint.endswith("/api/chat"):
            endpoint += "/api/chat"
        ollama_payload: dict[str, Any] = {
            "model": profile.model, "stream": False, "format": "json", "messages": messages,
            "options": {"temperature": 0},
        }
        model_name = profile.model.casefold()
        if "gpt-oss" in model_name:
            ollama_payload["think"] = reasoning_effort
        elif any(name in model_name for name in ("qwen3", "deepseek-r1", "deepseek-v3.1")):
            ollama_payload["think"] = reasoning_mode == "deep"
        raw = _post_json(
            endpoint,
            ollama_payload,
            {}, timeout,
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


def _adaptive_model_timeout(
    configured: float, reasoning_mode: str, reasoning_effort: str, observation_count: int,
) -> float:
    """Keep quick turns quick while giving deep or tool-heavy turns enough time."""
    timeout = max(15.0, min(float(configured or 180), 1800.0))
    if reasoning_mode == "deep":
        timeout = max(timeout, 300.0 if reasoning_effort in {"high", "max"} else 240.0)
    if observation_count >= 4:
        timeout = max(timeout, min(600.0, 180.0 + observation_count * 20.0))
    return timeout


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


def _is_transient_model_error(message: str) -> bool:
    text = message.casefold()
    return bool(
        re.search(r"http (?:408|425|429|5\d\d)\b", text)
        or any(value in text for value in (
            "could not be reached", "connection reset", "connection refused",
            "server disconnected", "temporarily unavailable",
        ))
    )


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


def _run_access_mode(project_root: Path, run_id: str) -> str:
    with connect(project_root) as connection:
        row = connection.execute(
            "SELECT model_snapshot_json FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    snapshot = _decode(row["model_snapshot_json"], {}) if row else {}
    return str(snapshot.get("access_mode", "ask"))


def _run_thread_id(project_root: Path, run_id: str) -> str:
    with connect(project_root) as connection:
        row = connection.execute("SELECT thread_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
    return str(row["thread_id"]) if row else ""


def _plugin_tool_risk(project_root: Path, plugin_name: str, tool_name: str) -> str:
    plugin = next(
        (
            item for item in plugin_state(find_config_root(project_root))["plugins"]
            if item.get("name") == plugin_name
        ),
        None,
    )
    if plugin is None:
        raise KeyError(f"unknown plugin: {plugin_name}")
    if tool_name not in {str(value) for value in plugin.get("agent_tools", [])}:
        raise ValueError(f"plugin tool is not approved for the main agent: {tool_name}")
    risk = str((plugin.get("tool_permissions") or {}).get(tool_name, "sensitive"))
    if risk not in {"read", "routine", "sensitive", "forbidden"}:
        raise ValueError(f"plugin tool has an invalid permission class: {risk}")
    if risk == "forbidden":
        raise ValueError(f"plugin tool is forbidden for the main agent: {tool_name}")
    return risk


def _must_pause_for_permission(access_mode: str, risk: str) -> bool:
    if risk == "read":
        return False
    if access_mode == "ask":
        return True
    if access_mode == "research_assist":
        return risk == "sensitive"
    return False


def _pause_tool_for_approval(
    project_root: Path, run_id: str, call_id: str, tool_name: str,
    request_payload: dict[str, Any], risk: str,
) -> dict[str, Any]:
    approval_id, now = _id("APR"), utc_now()
    with connect(project_root) as connection:
        connection.execute(
            "UPDATE tool_calls SET status = 'WAITING_FOR_APPROVAL' WHERE tool_call_id = ?",
            (call_id,),
        )
        connection.execute(
            """INSERT INTO approvals(
                   approval_id, run_id, tool_call_id, status, request_json, created_at
               ) VALUES (?, ?, ?, 'pending', ?, ?)""",
            (approval_id, run_id, call_id, _json(request_payload), now),
        )
        connection.execute(
            "UPDATE runs SET status = 'WAITING_FOR_APPROVAL', updated_at = ? WHERE run_id = ?",
            (now, run_id),
        )
        _append_run_event(connection, run_id, "approval_requested", {
            "approval_id": approval_id, "tool_call_id": call_id,
            "tool": tool_name, "risk": risk,
        })
    return {"waiting_for_approval": True, "approval_id": approval_id, "risk": risk}


def _record_auto_approval(
    project_root: Path, run_id: str, call_id: str, tool_name: str,
    request_payload: dict[str, Any], output: dict[str, Any], access_mode: str, risk: str,
) -> None:
    approval_id, now = _id("APR"), utc_now()
    decision = {
        "approved": True, "reviewer": f"access-mode:{access_mode}",
        "reason": f"auto-approved {risk} computer action",
        "edited_request": request_payload, "output": output,
        "access_mode": access_mode, "risk": risk,
    }
    with connect(project_root) as connection:
        connection.execute(
            """INSERT INTO approvals(
                   approval_id, run_id, tool_call_id, status, request_json,
                   decision_json, created_at, decided_at
               ) VALUES (?, ?, ?, 'approved', ?, ?, ?, ?)""",
            (approval_id, run_id, call_id, _json(request_payload), _json(decision), now, now),
        )
        _append_run_event(connection, run_id, "approval_auto_decided", {
            "approval_id": approval_id, "tool_call_id": call_id, "tool": tool_name,
            "access_mode": access_mode, "risk": risk,
        })


def _execute_tool(project_root: Path, run_id: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    allowed = {"harness.status", "system.diagnose", "system.repair", "project.status", "source.list", "source.search", "source.page", "library.status", "library.search", "library.assets", "library.work", "library.add_to_project", "library.graph", "research.state", "research.plan_context", "retrieval.list", "research.search", "plugin.list", "plugin.call", "plugin.repair", "domain_agent.list", "domain_agent.consult", "skill.list", "skill.read", "skill.create", "attachment.inspect", "domain_pack.validate", "domain_pack.create", "browser.start", "browser.snapshot", "browser.read", "browser.open", "authoring.state", "authoring.section", "research_design.current", "research_design.propose", "research_event.list", "research_event.coverage", "research_event.propose_batch", "reading_job.create", "reading_job.batch", "reading_note.save", "historiography.create", "save_research_note", *COMPUTER_TOOL_ALIASES}
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
        if tool_name in COMPUTER_TOOL_ALIASES:
            plugin_tool = COMPUTER_TOOL_ALIASES[tool_name]
            risk = _plugin_tool_risk(project_root, "computer-use", plugin_tool)
            access_mode = _run_access_mode(project_root, run_id)
            request_payload = {
                "plugin_name": "computer-use", "tool_name": plugin_tool,
                "arguments": dict(arguments), "risk": risk,
            }
            if _must_pause_for_permission(access_mode, risk):
                return _pause_tool_for_approval(
                    project_root, run_id, call_id, tool_name, request_payload, risk
                )
            result = call_domain_plugin_tool(
                find_config_root(project_root), "computer-use", plugin_tool, dict(arguments),
            )
            if risk != "read":
                _record_auto_approval(
                    project_root, run_id, call_id, tool_name, request_payload,
                    result, access_mode, risk,
                )
        elif tool_name == "harness.status":
            from .codex_harness import harness_status
            result = harness_status()
        elif tool_name == "system.diagnose":
            result = diagnose_system(project_root, find_config_root(project_root))
        elif tool_name == "system.repair":
            config_root = find_config_root(project_root)
            request_payload = {"risk": "routine"}
            access_mode = _run_access_mode(project_root, run_id)
            if _must_pause_for_permission(access_mode, "routine"):
                return _pause_tool_for_approval(project_root, run_id, call_id, tool_name, request_payload, "routine")
            result = repair_system(project_root, config_root)
            _record_auto_approval(project_root, run_id, call_id, tool_name, request_payload, result, access_mode, "routine")
        elif tool_name == "project.status":
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
        elif tool_name == "library.status":
            result = library_status(project_root)
        elif tool_name == "library.search":
            tags = arguments.get("tags", [])
            if not isinstance(tags, list):
                raise ValueError("library.search tags must be a list")
            limit = max(1, min(int(arguments.get("limit", 20)), 50))
            result = search_library(
                project_root, str(arguments.get("query", "")), [str(value) for value in tags]
            )[:limit]
        elif tool_name == "library.assets":
            result = library_assets(project_root, str(arguments.get("kind", "")))[:100]
        elif tool_name == "library.work":
            result = work_detail(project_root, str(arguments.get("work_id", "")))
        elif tool_name == "library.add_to_project":
            work_id = str(arguments.get("work_id", "")).strip()
            file_id = str(arguments.get("file_id", "")).strip()
            if not work_id or not file_id:
                raise ValueError("library.add_to_project requires work_id and file_id")
            access_mode = _run_access_mode(project_root, run_id)
            request_payload = {"work_id": work_id, "file_id": file_id}
            if _must_pause_for_permission(access_mode, "routine"):
                return _pause_tool_for_approval(
                    project_root, run_id, call_id, tool_name, request_payload, "routine"
                )
            result = add_library_file_to_project(
                project_root, Path(library_status(project_root)["library_root"]), work_id, file_id
            )
            _record_auto_approval(
                project_root, run_id, call_id, tool_name, request_payload,
                result, access_mode, "routine",
            )
        elif tool_name == "library.graph":
            result = library_graph(
                project_root, str(arguments.get("query", "")),
                max(1, min(int(arguments.get("limit", 100)), 500)),
                include_reading_notes=bool(arguments.get("include_reading_notes", False)),
            )
        elif tool_name == "research.state":
            result = _agent_research_state(project_root)
        elif tool_name == "research.plan_context":
            result = _planning_context(project_root)
        elif tool_name == "retrieval.list":
            result = _compact_retrievals(
                project_root,
                str(arguments.get("record_id", "")),
                int(arguments.get("limit", 30)),
            )
        elif tool_name == "research.search":
            result = search_research(
                project_root, str(arguments.get("provider", "crossref")),
                str(arguments.get("query", "")), int(arguments.get("limit", 10)),
            )
            profile = _role_profile("web_research")
            if profile is not None:
                result["model_advice"] = _plain_model_call(profile, [{"role": "system", "content": "Organize these discovery records for a humanities researcher. Identify likely relevance, noise, missing searches and acquisition priorities. Do not claim any item was read and preserve every returned URL."},{"role": "user", "content": _json(result)[:30000]}])[:12000]
        elif tool_name == "plugin.list":
            state = plugin_state(find_config_root(project_root))
            result = {
                "plugins": [
                    {
                        "name": item.get("name"), "display_name": item.get("display_name"),
                        "description": item.get("description"), "status": item.get("status"),
                        "agent_tools": item.get("agent_tools", []),
                        "data_packs": item.get("data_packs", []),
                    }
                    for item in state.get("plugins", [])
                ],
                "boundary": state.get("boundary", ""),
            }
        elif tool_name == "plugin.call":
            plugin_name = str(arguments.get("plugin_name", ""))
            plugin_tool = str(arguments.get("tool_name", ""))
            plugin_arguments = dict(arguments.get("arguments", {}))
            risk = _plugin_tool_risk(project_root, plugin_name, plugin_tool)
            access_mode = _run_access_mode(project_root, run_id)
            request_payload = {
                "plugin_name": plugin_name, "tool_name": plugin_tool,
                "arguments": plugin_arguments, "risk": risk,
            }
            if _must_pause_for_permission(access_mode, risk):
                return _pause_tool_for_approval(
                    project_root, run_id, call_id, tool_name, request_payload, risk
                )
            result = call_domain_plugin_tool(
                find_config_root(project_root), plugin_name, plugin_tool, plugin_arguments,
            )
            if risk != "read":
                _record_auto_approval(
                    project_root, run_id, call_id, tool_name, request_payload,
                    result, access_mode, risk,
                )
        elif tool_name == "plugin.repair":
            plugin_name = str(arguments.get("plugin_name", "")).strip()
            request_payload = {"plugin_name": plugin_name, "risk": "routine"}
            access_mode = _run_access_mode(project_root, run_id)
            if _must_pause_for_permission(access_mode, "routine"):
                return _pause_tool_for_approval(
                    project_root, run_id, call_id, tool_name, request_payload, "routine"
                )
            result = repair_domain_plugin(find_config_root(project_root), plugin_name)
            _record_auto_approval(
                project_root, run_id, call_id, tool_name, request_payload,
                result, access_mode, "routine",
            )
        elif tool_name == "domain_agent.list":
            from .domain_agents import domain_agent_state
            result = domain_agent_state(project_root)
        elif tool_name == "domain_agent.consult":
            from .domain_agents import send_domain_message
            plugin_name = str(arguments.get("plugin_name", ""))
            question = str(arguments.get("question", ""))
            parent_thread_id = _run_thread_id(project_root, run_id)
            prefix = f"领域 Agent｜{plugin_name}｜"
            existing = None
            if not bool(arguments.get("new_thread", False)):
                with connect(project_root) as connection:
                    existing = connection.execute(
                        "SELECT t.thread_id,t.title FROM threads t JOIN thread_inheritance i "
                        "ON i.child_thread_id=t.thread_id WHERE i.parent_thread_id=? AND t.title LIKE ? "
                        "ORDER BY t.created_at LIMIT 1",
                        (parent_thread_id, f"{prefix}%"),
                    ).fetchone()
            domain_thread = dict(existing) if existing else create_thread(
                project_root, f"{prefix}{question.strip()[:36] or '新任务'}",
                parent_thread_id=parent_thread_id,
            )
            view = send_domain_message(
                project_root, plugin_name, question,
                main_thread_id=domain_thread["thread_id"],
                access_mode=_run_access_mode(project_root, run_id),
                parent_run_id=run_id,
            )
            result = {
                "session": view["session"],
                "domain_thread_id": domain_thread["thread_id"],
                "latest_message": view["messages"][-1] if view["messages"] else None,
                "latest_run": view["runs"][0] if view["runs"] else None,
                "candidate_artifacts": view["artifacts"][:10],
                "boundary": "Specialist output is a candidate; the main agent retains final authority.",
            }
        elif tool_name == "skill.list":
            result = {
                "skills": [
                    {
                        "name": item["name"], "description": item["description"],
                        "implicit": bool((item.get("agent_program") or {}).get("allow_implicit_invocation")),
                    }
                    for item in discover_skills() if item["placement"] == "user_action"
                ]
            }
        elif tool_name == "skill.read":
            skill = get_skill(str(arguments.get("name", "")))
            if skill["placement"] != "user_action":
                raise ValueError("only user-action research skills can be read by the main agent")
            result = {
                "name": skill["name"], "sha256": skill["sha256"],
                "instructions": skill["instructions"],
                "boundary": "Workbench evidence, permission and write gates take precedence.",
            }
        elif tool_name == "skill.create":
            request_payload = {
                "name": str(arguments.get("name", "")),
                "display_name": str(arguments.get("display_name", "")),
                "description": str(arguments.get("description", "")),
                "instructions": str(arguments.get("instructions", "")),
                "allow_implicit_invocation": bool(arguments.get("allow_implicit_invocation", True)),
                "risk": "sensitive",
            }
            access_mode = _run_access_mode(project_root, run_id)
            if _must_pause_for_permission(access_mode, "sensitive"):
                return _pause_tool_for_approval(
                    project_root, run_id, call_id, tool_name, request_payload, "sensitive"
                )
            result = create_local_skill(
                find_config_root(project_root), request_payload["name"],
                request_payload["description"], request_payload["instructions"],
                request_payload["display_name"], request_payload["allow_implicit_invocation"],
            )
            _record_auto_approval(
                project_root, run_id, call_id, tool_name, request_payload,
                result, access_mode, "sensitive",
            )
        elif tool_name == "attachment.inspect":
            result = inspect_attachment(project_root, str(arguments.get("attachment_id", "")))
            if result["kind"] == "image":
                profile = _role_profile("vision_ocr")
                if profile is None:
                    raise ValueError("no vision/OCR model is configured for image attachments")
                result["analysis"] = _vision_file_call(
                    profile, Path(result["absolute_path"]),
                    str(arguments.get("prompt", "Describe the chart or image faithfully.")),
                )
                secondary = _role_profile("vision_secondary")
                if secondary is not None:
                    result["secondary_analysis"] = _vision_file_call(
                        secondary, Path(result["absolute_path"]),
                        "Independently review the same image and identify uncertain or conflicting readings.",
                    )
                    result["vision_review_required"] = True
            result.pop("absolute_path", None)
        elif tool_name == "domain_pack.validate":
            result = validate_domain_plugin(Path(str(arguments.get("plugin_root", ""))))
        elif tool_name == "domain_pack.create":
            request_payload = {
                "parent": str(arguments.get("parent", "")),
                "name": str(arguments.get("name", "")),
                "display_name": str(arguments.get("display_name", "")),
                "description": str(arguments.get("description", "")),
                "risk": "sensitive",
            }
            access_mode = _run_access_mode(project_root, run_id)
            if _must_pause_for_permission(access_mode, "sensitive"):
                return _pause_tool_for_approval(
                    project_root, run_id, call_id, tool_name, request_payload, "sensitive"
                )
            result = create_plugin_project(
                Path(request_payload["parent"]), request_payload["name"],
                request_payload["display_name"], request_payload["description"],
            )
            _record_auto_approval(
                project_root, run_id, call_id, tool_name, request_payload,
                result, access_mode, "sensitive",
            )
        elif tool_name == "browser.start":
            url = str(arguments.get("url", "")).strip()
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("browser URL must use http or https")
            request_payload = {"url": url, "allowed_domain": parsed.hostname, "risk": "routine"}
            access_mode = _run_access_mode(project_root, run_id)
            if _must_pause_for_permission(access_mode, "routine"):
                return _pause_tool_for_approval(
                    project_root, run_id, call_id, tool_name, request_payload, "routine"
                )
            session = create_browser_session(project_root, url, parsed.hostname)
            result = launch_controlled_browser(project_root, session["session_id"])
            _record_auto_approval(
                project_root, run_id, call_id, tool_name, request_payload,
                result, access_mode, "routine",
            )
        elif tool_name == "browser.snapshot":
            result = inspect_controlled_browser(
                project_root, str(arguments.get("session_id", ""))
            )
        elif tool_name == "browser.read":
            result = read_controlled_browser(
                project_root, str(arguments.get("session_id", ""))
            )
        elif tool_name == "browser.open":
            request_payload = {
                "session_id": str(arguments.get("session_id", "")),
                "url": str(arguments.get("url", "")), "risk": "routine",
            }
            access_mode = _run_access_mode(project_root, run_id)
            if _must_pause_for_permission(access_mode, "routine"):
                return _pause_tool_for_approval(
                    project_root, run_id, call_id, tool_name, request_payload, "routine"
                )
            result = navigate_controlled_browser(
                project_root, request_payload["session_id"], request_payload["url"],
            )
            _record_auto_approval(
                project_root, run_id, call_id, tool_name, request_payload,
                result, access_mode, "routine",
            )
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
                run = connection.execute(
                    "SELECT model_snapshot_json FROM runs WHERE run_id = ?", (run_id,)
                ).fetchone()
            snapshot = _decode(run["model_snapshot_json"], {}) if run else {}
            access_mode = str(snapshot.get("access_mode", "ask"))
            if access_mode in {"research_assist", "full_computer"}:
                result = _write_note(project_root, approval_id, title, content)
                now = utc_now()
                decision = {
                    "approved": True,
                    "reviewer": f"access-mode:{access_mode}",
                    "reason": "auto-approved allowlisted local research note",
                    "edited_request": request_payload,
                    "access_mode": access_mode,
                }
                with connect(project_root) as connection:
                    connection.execute(
                        """INSERT INTO approvals(
                               approval_id, run_id, tool_call_id, status, request_json,
                               decision_json, created_at, decided_at
                           ) VALUES (?, ?, ?, 'approved', ?, ?, ?, ?)""",
                        (approval_id, run_id, call_id, _json(request_payload), _json(decision), now, now),
                    )
                    _append_run_event(connection, run_id, "approval_auto_decided", {
                        "approval_id": approval_id, "tool_call_id": call_id,
                        "tool": tool_name, "access_mode": access_mode,
                    })
            else:
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


def _resume_approved_run(project_root: Path, run_id: str) -> None:
    with connect(project_root) as connection:
        run = connection.execute(
            """SELECT r.model_snapshot_json, g.objective
               FROM runs r JOIN goals g ON g.goal_id=r.goal_id WHERE r.run_id=?""",
            (run_id,),
        ).fetchone()
        calls = connection.execute(
            """SELECT tool_name, input_json, output_json, error, status
               FROM tool_calls WHERE run_id=? ORDER BY created_at""",
            (run_id,),
        ).fetchall()
    if run is None:
        raise KeyError(f"unknown run: {run_id}")
    snapshot = _decode(run["model_snapshot_json"], {})
    objective, active_skill, skill_context = _resolve_skill_invocation(str(run["objective"]))
    planning_mode = str(snapshot.get("planning_mode", "independent_planning"))
    history = _thread_history(project_root, _run_thread_id(project_root, run_id))[0] if planning_mode == "guided_execution" else []
    shared_design = current_shared_design(project_root) if planning_mode == "guided_execution" else None
    design_context = (
        "APPROVED_SHARED_RESEARCH_DESIGN " + _json(shared_design) if shared_design
        else "INDEPENDENT_PLANNING: Continue the approved run using its recorded tool receipts."
    )
    if active_skill and skill_context:
        design_context += "\n\n" + skill_context
    design_context += "\n\n" + agent_profile_prompt(project_root)
    domain_catalog = _domain_agent_catalog(project_root)
    if domain_catalog:
        design_context += "\n\n" + domain_catalog
    design_context += "\n\nAGENT_ACCESS_MODE " + str(snapshot.get("access_mode", "ask"))
    observations = [{
        "tool": str(call["tool_name"]), "arguments": _decode(call["input_json"], {}),
        "result": _decode(call["output_json"], None) if call["status"] == "COMPLETED" else None,
        "error": str(call["error"] or "") or None,
    } for call in calls if call["status"] in {"COMPLETED", "FAILED"}]
    if snapshot.get("harness_backend") == "codex":
        from .codex_harness import run_turn

        continuation = (
            "用户已经明确处理了上一项审批。请依据下列已执行工具回执继续原任务；"
            "不要重复同一动作，也不要把候选结果说成已批准证据。\n"
            + _json(observations)
        )
        _complete_run(project_root, run_id, run_turn(
            project_root, _run_thread_id(project_root, run_id), run_id, continuation,
            _assigned_profile(project_root), design_context,
            str(snapshot.get("access_mode", "ask")),
            str(snapshot.get("reasoning_mode", "standard")),
            str(snapshot.get("reasoning_effort", "medium")),
            history,
        ))
        return
    _advance_run(
        project_root, run_id, objective, _assigned_profile(project_root), design_context, history,
        reasoning_mode=str(snapshot.get("reasoning_mode", "standard")),
        reasoning_effort=str(snapshot.get("reasoning_effort", "medium")),
        initial_observations=observations,
    )


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
        resume_after_approval = connection.execute(
            "SELECT 1 FROM run_events WHERE run_id=? AND event_type='run_completed' LIMIT 1",
            (row["run_id"],),
        ).fetchone() is None
        request_payload = _decode(row["request_json"], {})
    final_request = edited_request if edited_request is not None else request_payload
    if not isinstance(final_request, dict):
        raise ValueError("edited request must be an object")
    output: dict[str, Any]
    if approved:
        if row["tool_name"] == "system.repair":
            output = repair_system(project_root, find_config_root(project_root))
            final_text = f"系统安全修复已由 {reviewer} 核准并执行。"
        elif row["tool_name"] == "plugin.repair":
            output = repair_domain_plugin(
                find_config_root(project_root), str(final_request.get("plugin_name", "")),
            )
            final_text = f"领域 Agent 安装副本已由 {reviewer} 核准并修复。"
        elif row["tool_name"] == "plugin.call" or str(row["tool_name"]).startswith("computer."):
            output = call_domain_plugin_tool(
                find_config_root(project_root),
                str(final_request.get("plugin_name", "")),
                str(final_request.get("tool_name", "")),
                dict(final_request.get("arguments", {})),
            )
            final_text = f"Computer Use 动作已由 {reviewer} 核准并执行。"
        elif row["tool_name"] == "browser.start":
            url = str(final_request.get("url", "")).strip()
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("browser URL must use http or https")
            session = create_browser_session(project_root, url, parsed.hostname)
            output = launch_controlled_browser(project_root, session["session_id"])
            final_text = f"受控浏览器已由 {reviewer} 核准并打开。"
        elif row["tool_name"] == "browser.open":
            output = navigate_controlled_browser(
                project_root,
                str(final_request.get("session_id", "")),
                str(final_request.get("url", "")),
            )
            final_text = f"浏览器导航已由 {reviewer} 核准并执行。"
        elif row["tool_name"] == "domain_pack.create":
            output = create_plugin_project(
                Path(str(final_request.get("parent", ""))),
                str(final_request.get("name", "")),
                str(final_request.get("display_name", "")),
                str(final_request.get("description", "")),
            )
            final_text = f"领域包工程骨架已由 {reviewer} 核准并创建：{output['plugin_root']}"
        elif row["tool_name"] == "save_research_note":
            title = str(final_request.get("title", "")).strip()
            content = str(final_request.get("content", "")).strip()
            if not title or not content:
                raise ValueError("approved note requires title and content")
            output = _write_note(project_root, approval_id, title, content)
            final_text = f"研究札记已由 {reviewer} 核准并保存：{output['project_path']}"
        elif row["tool_name"] == "library.add_to_project":
            output = add_library_file_to_project(
                project_root,
                Path(library_status(project_root)["library_root"]),
                str(final_request.get("work_id", "")),
                str(final_request.get("file_id", "")),
            )
            final_text = f"所选图书馆版本已由 {reviewer} 核准采用并自动清洗。"
        else:
            raise ValueError(f"approval execution is not implemented for tool: {row['tool_name']}")
        tool_status, approval_status = "COMPLETED", "approved"
        run_status, goal_status = ("RUNNING", "active") if resume_after_approval else ("COMPLETED", "complete")
    else:
        output = {"saved": False, "reason": reason}
        final_text = f"待执行动作已被 {reviewer} 拒绝；没有改变电脑或项目。理由：{reason}"
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
            (run_status, now, None if approved and resume_after_approval else now, row["run_id"]),
        )
        connection.execute(
            "UPDATE goals SET status = ?, completed_at = ? WHERE goal_id = ?",
            (goal_status, None if approved and resume_after_approval else now, row["goal_id"]),
        )
        _append_run_event(connection, row["run_id"], "approval_decided", {"approval_id": approval_id, **decision})
        if approved:
            _append_run_event(connection, row["run_id"], "tool_completed", {"tool_call_id": row["tool_call_id"], "tool": row["tool_name"]})
            if not resume_after_approval:
                message_id = _id("MSG")
                connection.execute(
                    "INSERT INTO messages(message_id, thread_id, role, content_json, created_at) VALUES (?, ?, 'assistant', ?, ?)",
                    (message_id, row["thread_id"], _json({"text": final_text}), now),
                )
                _append_run_event(connection, row["run_id"], "assistant_message", {"message_id": message_id})
        else:
            message_id = _id("MSG")
            connection.execute(
                "INSERT INTO messages(message_id, thread_id, role, content_json, created_at) VALUES (?, ?, 'assistant', ?, ?)",
                (message_id, row["thread_id"], _json({"text": final_text}), now),
            )
            connection.execute("UPDATE threads SET updated_at = ? WHERE thread_id = ?", (now, row["thread_id"]))
            _append_run_event(connection, row["run_id"], "assistant_message", {"message_id": message_id})
            _append_run_event(connection, row["run_id"], "run_completed", {"approved": False})
    if approved and resume_after_approval:
        try:
            _resume_approved_run(project_root, str(row["run_id"]))
        except Exception as error:
            _fail_run(project_root, str(row["run_id"]), error)
            raise
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
    text = _clean_final_text(content) or "Agent 已完成本次检查。"
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
