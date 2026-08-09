from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .db import connect, utc_now
from .research import list_retrievals
from .scholarship import research_state
from .service import list_sources, project_status, source_view


MAIN_ROLE = "main_reasoning"
RUN_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}
SYSTEM_PROMPT = """You are the main agent in a local historical research workbench.
Use tools to inspect project facts. Never claim you read a source unless a tool returned it.
Return exactly one JSON object and no markdown.
Available actions:
{"type":"tool_call","tool":"project.status","arguments":{}}
{"type":"tool_call","tool":"source.list","arguments":{}}
{"type":"tool_call","tool":"source.page","arguments":{"page_id":"..."}}
{"type":"tool_call","tool":"research.state","arguments":{}}
{"type":"tool_call","tool":"retrieval.list","arguments":{}}
{"type":"tool_call","tool":"save_research_note","arguments":{"title":"...","content":"..."}}
{"type":"final","content":"..."}
Saving a note requires human approval. Keep notes explicit about blocked pages and uncertainty.
Retrieval results are leads, not evidence. Only approved evidence freezes may support drafting.
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
    return {"thread": dict(thread), "messages": messages, "runs": runs}


def send_message(project_root: Path, thread_id: str, content: str) -> dict[str, Any]:
    content = content.strip()
    if not content:
        raise ValueError("message content is required")
    profile = _assigned_profile(project_root)
    now = utc_now()
    message_id, goal_id, run_id = _id("MSG"), _id("GOL"), _id("RUN")
    snapshot = {
        "role": MAIN_ROLE, "profile_id": profile.profile_id, "provider": profile.provider,
        "model": profile.model, "endpoint": profile.endpoint,
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
        _append_run_event(connection, run_id, "run_started", {"objective": content, "model": snapshot})
        _append_run_event(connection, run_id, "user_message", {"message_id": message_id})
    try:
        _advance_run(project_root, run_id, content, profile)
    except Exception as error:
        with connect(project_root) as connection:
            connection.execute(
                "UPDATE runs SET status = 'FAILED', error = ?, updated_at = ?, completed_at = ? WHERE run_id = ?",
                (str(error), utc_now(), utc_now(), run_id),
            )
            connection.execute(
                "UPDATE goals SET status = 'failed', completed_at = ? WHERE goal_id = ?", (utc_now(), goal_id)
            )
            _append_run_event(connection, run_id, "run_failed", {"error": str(error)})
        raise
    return thread_view(project_root, thread_id)


def _advance_run(project_root: Path, run_id: str, objective: str, profile: ModelProfile) -> None:
    observations: list[dict[str, Any]] = []
    for step in range(8):
        action = _mock_action(project_root, observations) if profile.provider == "mock" else _model_action(
            profile, objective, observations
        )
        action_type = action.get("type")
        if action_type == "final":
            _complete_run(project_root, run_id, str(action.get("content", "")))
            return
        if action_type != "tool_call":
            raise ValueError("model action must be tool_call or final")
        tool_name = str(action.get("tool", ""))
        arguments = action.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")
        result = _execute_tool(project_root, run_id, tool_name, arguments)
        if isinstance(result, dict) and result.get("waiting_for_approval"):
            return
        observations.append({"tool": tool_name, "arguments": arguments, "result": result})
    raise RuntimeError("agent exceeded the M4 step limit")


def _mock_action(project_root: Path, observations: list[dict[str, Any]]) -> dict[str, Any]:
    tools = [item["tool"] for item in observations]
    if "project.status" not in tools:
        return {"type": "tool_call", "tool": "project.status", "arguments": {}}
    if "source.list" not in tools:
        return {"type": "tool_call", "tool": "source.list", "arguments": {}}
    if "source.page" not in tools:
        sources = next(item["result"] for item in observations if item["tool"] == "source.list")
        if sources:
            view = source_view(project_root, sources[0]["source_id"])
            if view["pages"]:
                return {
                    "type": "tool_call", "tool": "source.page",
                    "arguments": {"page_id": view["pages"][0]["page_id"]},
                }
    if "research.state" not in tools:
        return {"type": "tool_call", "tool": "research.state", "arguments": {}}
    status = next(item["result"] for item in observations if item["tool"] == "project.status")
    sources = next(item["result"] for item in observations if item["tool"] == "source.list")
    page = next((item["result"] for item in observations if item["tool"] == "source.page"), None)
    research = next(item["result"] for item in observations if item["tool"] == "research.state")
    lines = [
        "# 项目检查札记", "",
        f"- 当前来源数：{status.get('source_count', len(sources))}",
        f"- 待处理异常：{status.get('open_anomaly_count', 0)}",
        f"- 研究可用来源：{status.get('usable_source_count', 0)}",
        f"- 候选主张：{len(research['claims'])}",
        f"- 已批准证据冻结：{sum(item['status'] == 'approved' for item in research['freezes'])}",
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


def _model_action(profile: ModelProfile, objective: str, observations: list[dict[str, Any]]) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": objective},
    ]
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
        raise RuntimeError("agent provider returned empty content")
    return _parse_action(content)


def _parse_action(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    action = json.loads(text)
    if not isinstance(action, dict):
        raise ValueError("agent response JSON must be an object")
    return action


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    request = Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers}, method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(f"agent provider returned HTTP {error.code}") from error
    except URLError as error:
        raise RuntimeError("agent provider could not be reached") from error
    if not isinstance(result, dict):
        raise RuntimeError("agent provider response was not a JSON object")
    return result


def _execute_tool(project_root: Path, run_id: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    allowed = {"project.status", "source.list", "source.page", "research.state", "retrieval.list", "save_research_note"}
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
            result = list_sources(project_root)
        elif tool_name == "source.page":
            result = _read_page(project_root, str(arguments.get("page_id", "")))
        elif tool_name == "research.state":
            result = research_state(project_root)
        elif tool_name == "retrieval.list":
            result = list_retrievals(project_root)
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


def _read_page(project_root: Path, page_id: str) -> dict[str, Any]:
    if not page_id:
        raise ValueError("source.page requires page_id")
    with connect(project_root) as connection:
        row = connection.execute("SELECT source_id FROM pages WHERE page_id = ?", (page_id,)).fetchone()
    if row is None:
        raise KeyError(f"unknown page: {page_id}")
    view = source_view(project_root, str(row["source_id"]))
    page = next(item for item in view["pages"] if item["page_id"] == page_id)
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
             "text": block["effective_text"]}
            for block in page["blocks"]
        ],
        "open_anomalies": anomalies,
    }


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
