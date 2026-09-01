from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from .agent_runtime import ModelProfile, _append_run_event, _assigned_profile, _clean_final_text, _consume_run_controls, _model_action, _parse_action, _role_profile, _vision_file_call, harness_backend
from .attachments import inspect_attachment
from .db import connect, utc_now
from .domain_plugins import call_domain_plugin_tool, domain_model_override, domain_plugin_tool_specs, find_config_root, plugin_state, public_domain_model_settings


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _decode(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _plugin(project_root: Path, plugin_name: str) -> dict[str, Any]:
    plugin = next(
        (item for item in plugin_state(find_config_root(project_root))["plugins"] if item.get("name") == plugin_name),
        None,
    )
    if plugin is None or plugin.get("kind") == "system":
        raise KeyError(f"unknown domain pack: {plugin_name}")
    if plugin.get("status") != "ready":
        raise RuntimeError(f"domain pack runtime is not ready: {plugin.get('status')}")
    return plugin


def _domain_profile(project_root: Path, plugin_name: str, role_id: str, fallback_role: str) -> ModelProfile | None:
    try:
        override = domain_model_override(find_config_root(project_root), plugin_name, role_id)
    except KeyError:
        override = None
    if override is None:
        return _role_profile(fallback_role)
    if override["provider"] == "disabled":
        return None
    return ModelProfile(
        profile_id=f"domain:{plugin_name}:{role_id}", provider=str(override["provider"]),
        model=str(override["model"]), endpoint=str(override["base_url"]),
        capabilities=("text", "image") if "vision" in role_id else ("text",),
        credential_ref="windows-credential", status="available",
        api_key=str(override["api_key"]), timeout_seconds=float(override["timeout_seconds"]),
    )


def ensure_domain_session(project_root: Path, plugin_name: str) -> dict[str, Any]:
    plugin = _plugin(project_root, plugin_name)
    agent_id = str((plugin.get("agent") or {}).get("id") or f"{plugin_name}-researcher")
    title = str((plugin.get("agent") or {}).get("display_name") or plugin.get("display_name") or plugin_name)
    with connect(project_root) as connection:
        row = connection.execute(
            "SELECT * FROM domain_agent_sessions WHERE plugin_name=? AND agent_id=?",
            (plugin_name, agent_id),
        ).fetchone()
        if row is None:
            now, session_id = utc_now(), _id("DAS")
            connection.execute(
                """INSERT INTO domain_agent_sessions(
                       session_id, plugin_name, agent_id, title, status, memory_json, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, 'active', '{}', ?, ?)""",
                (session_id, plugin_name, agent_id, title, now, now),
            )
            row = connection.execute(
                "SELECT * FROM domain_agent_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
        elif str(row["title"]) != title:
            connection.execute(
                "UPDATE domain_agent_sessions SET title=?,updated_at=? WHERE session_id=?",
                (title, utc_now(), row["session_id"]),
            )
            row = connection.execute(
                "SELECT * FROM domain_agent_sessions WHERE session_id=?", (row["session_id"],)
            ).fetchone()
    return dict(row)


def _domain_history(
    project_root: Path, session_id: str, main_thread_id: str = "", limit: int = 12,
) -> list[dict[str, str]]:
    with connect(project_root) as connection:
        allowed_threads: set[str] = set()
        current = main_thread_id
        while current and current not in allowed_threads and len(allowed_threads) < 8:
            allowed_threads.add(current)
            parent = connection.execute(
                "SELECT parent_thread_id FROM thread_inheritance WHERE child_thread_id=?", (current,)
            ).fetchone()
            current = str(parent["parent_thread_id"]) if parent else ""
        rows = connection.execute(
            """SELECT role, content_json FROM domain_agent_messages
               WHERE session_id=? ORDER BY created_at DESC, message_id DESC LIMIT ?""",
            (session_id, max(limit * 5, limit)),
        ).fetchall()
    history = []
    for row in reversed(rows):
        payload = _decode(row["content_json"], {})
        if allowed_threads and str(payload.get("main_thread_id", "")) not in allowed_threads:
            continue
        if str(row["role"]) in {"user", "assistant"}:
            text = str(payload.get("text", ""))
            attachment_paths = []
            for reference in payload.get("attached_refs", []):
                try:
                    attachment = inspect_attachment(project_root, str(reference.get("attachment_id", "")))
                except (KeyError, FileNotFoundError):
                    continue
                attachment_paths.append({
                    "original_name": attachment["original_name"],
                    "tool_path": attachment["absolute_path"],
                    "media_type": attachment["media_type"],
                })
            if attachment_paths:
                text += "\n\nTHREAD_ATTACHMENTS " + _json(attachment_paths)
            history.append({"role": str(row["role"]), "content": text})
    return history[-limit:]


def _domain_prompt(plugin: dict[str, Any], tool_specs: list[dict[str, Any]] | None = None,
                   native_tools: bool = False) -> str:
    tools = [str(value) for value in plugin.get("agent_tools", [])]
    specs = {str(item.get("name", "")): item for item in (tool_specs or [])}
    actions = "\n".join(_json({
        "tool": name,
        "input_schema": specs.get(name, {}).get("inputSchema") or specs.get(name, {}).get("input_schema") or {},
    }) for name in tools)
    boundaries = "\n".join(f"- {value}" for value in plugin.get("boundaries", []))
    root = Path(str(plugin.get("installed_path", ""))).resolve()
    skill_texts = []
    if root.is_dir():
        for relative in plugin.get("skills", []):
            path = (root / str(relative)).resolve()
            if path.is_file() and path.is_relative_to(root):
                skill_texts.append(path.read_text(encoding="utf-8"))
    skill_context = "\n\n".join(skill_texts)[:30000]
    if native_tools:
        return f"""You are the stateful specialist Agent for {plugin.get('display_name') or plugin.get('name')}.
Use the exposed deterministic domain tools directly from the researcher's natural-language request.
Do not emit JSON tool protocols or hidden work language. Never claim a tool ran without its receipt.
Preserve row, page, source and file identity. Do not overwrite originals; generated files are candidates.
The main Agent remains responsible for cross-domain judgment, formal evidence and final computer authority.
Domain boundaries:
{boundaries or '- No additional boundary was declared.'}
Installed domain skill:
{skill_context or '- No separate domain skill was installed.'}
"""
    return f"""You are the stateful specialist subagent for {plugin.get('display_name') or plugin.get('name')}.
You have a private conversation and memory namespace. The main research agent remains responsible for
cross-domain judgment, formal evidence, manuscript changes and final computer authority.
Follow the installed domain skill below as your operating procedure. Prefer its deterministic program and
MCP tools over free-form inference. Do not replace an available program step with prose advice.
For an uploaded attachment, use the exact tool_path from ATTACHMENT_INSPECTION_RECEIPTS when a tool needs
an input_path. On later turns, “uploaded attachment” means the matching tool_path in THREAD_ATTACHMENTS,
not a previously generated candidate artifact, unless the researcher explicitly selects that artifact.
project_path is only the workbench-relative display path.
Return exactly one JSON action and no markdown outside a final answer. A tool action must be
{{"type":"tool_call","tool":"tool_name","arguments":{{...}}}}. The contracts below describe the
arguments; never copy input_schema into the action and never omit required arguments. Use only these tools:
{actions}
Or return {{"type":"final","content":"researcher-readable answer"}}.
Use the language of the researcher's latest message for the final answer; do not switch a Chinese task to English.
Never claim a tool ran without its receipt. Tool output is a candidate. Preserve row, page, source and file
identity. Do not overwrite an original workbook or database. Candidate files must use a new output path.
When a tool receipt contains do_not_retry_in_same_turn=true, report its partial/resumable state and run_id;
never repeat the same call in the current turn.
Domain boundaries:
{boundaries or '- No additional boundary was declared.'}
Installed domain skill:
{skill_context or '- No separate domain skill was installed.'}
"""


def _permission(plugin: dict[str, Any], tool_name: str) -> str:
    value = str((plugin.get("tool_permissions") or {}).get(tool_name, "sensitive"))
    return value if value in {"read", "routine", "sensitive", "forbidden"} else "sensitive"


def _tool_payload(result: dict[str, Any]) -> dict[str, Any]:
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for item in result.get("content", []):
        if item.get("type") != "text":
            continue
        text = str(item.get("text", ""))
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return result


def _nested_domain_tool_action(content: str) -> dict[str, Any] | None:
    parsed = _parse_action(content)
    if parsed.get("type") == "tool_call":
        return parsed
    start = content.rfind("\n{")
    if start >= 0:
        parsed = _parse_action(content[start + 1 :])
        if parsed.get("type") == "tool_call":
            return parsed
    return None


def _tool_requirements(plugin: dict[str, Any], content: str) -> list[dict[str, Any]]:
    requirements: dict[str, dict[str, Any]] = {}
    tools = {str(value) for value in plugin.get("agent_tools", [])}
    for tool_name in tools:
        if tool_name in content:
            requirements[tool_name] = {"tool": tool_name, "minimum_calls": 1, "paths": []}
            count_match = re.search(
                rf"{re.escape(tool_name)}[^。；;\n]{{0,24}}?([一二三四五六七八九十\d]+)次",
                content,
            )
            if count_match:
                token = count_match.group(1)
                numbers = {
                    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
                }
                requirements[tool_name]["minimum_calls"] = (
                    int(token) if token.isdigit() else numbers[token]
                )
    inspect_tool = "inspect_half_finished_workbook"
    if (
        inspect_tool in tools
        and re.search(r"(?:查看|检查|读取|识别).{0,8}(?:表头|前三行|前三条)", content)
        and re.search(r"[A-Za-z]:\\[^；;\n]+?\.(?:xlsx|xlsm)", content, flags=re.IGNORECASE)
    ):
        requirements[inspect_tool] = {"tool": inspect_tool, "minimum_calls": 1, "paths": []}
    if inspect_tool in requirements:
        paths = list(dict.fromkeys(re.findall(
            r"[A-Za-z]:\\[^；;\n]+?\.(?:xlsx|xlsm)", content, flags=re.IGNORECASE,
        )))
        requirements[inspect_tool]["paths"] = paths
        requirements[inspect_tool]["minimum_calls"] = max(1, len(paths))
    convert_tool = "convert_half_finished_workbook"
    if convert_tool in requirements:
        paths = list(dict.fromkeys(re.findall(
            r"[A-Za-z]:\\[^；;\n]+?\.(?:xlsx|xlsm|csv|tsv)", content, flags=re.IGNORECASE,
        )))
        requirements[convert_tool]["paths"] = paths
        requirements[convert_tool]["minimum_calls"] = max(1, len(paths))
    normalize_tool = "normalize_disaster_type"
    if normalize_tool in requirements:
        samples = set(re.findall(r"[①②③④⑤⑥⑦⑧⑨⑩]", content))
        requirements[normalize_tool]["minimum_calls"] = max(1, len(samples))
    grade_tool = "propagate_event_grades_to_all_rows"
    if (
        grade_tool in tools and "定等" in content
        and any(word in content for word in ("全部", "所有", "补齐"))
    ):
        requirements[grade_tool] = {"tool": grade_tool, "minimum_calls": 1, "paths": []}
    if "record_review_decisions" in tools and re.search(r"(?:复核决定|回答复核|写入.{0,8}复核|按我的回答)", content):
        requirements["record_review_decisions"] = {"tool": "record_review_decisions", "minimum_calls": 1, "paths": []}
    if "apply_review_workbook" in tools and re.search(r"(?:合并生成|新版主表|下一轮复核|完成合并)", content):
        requirements["apply_review_workbook"] = {"tool": "apply_review_workbook", "minimum_calls": 1, "paths": []}
    return list(requirements.values())


def _requirement_satisfied(requirement: dict[str, Any], observations: list[dict[str, Any]]) -> bool:
    calls = [
        item for item in observations
        if item.get("tool") == requirement["tool"]
        and item.get("result") is not None
        and not (isinstance(item.get("result"), dict) and item["result"].get("isError"))
    ]
    if len(calls) < int(requirement["minimum_calls"]):
        return False
    called_paths = {
        str((item.get("arguments") or {}).get("input_path", "")).casefold() for item in calls
    }
    return all(str(path).casefold() in called_paths for path in requirement.get("paths", []))


def _record_artifact(
    project_root: Path, session_id: str, run_id: str, tool_name: str, payload: dict[str, Any]
) -> None:
    candidate = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    output_paths = [
        str(candidate.get(key, "")) for key in (
            "output_path", "output_workbook", "workbook_path", "database_path",
            "main_workbook", "remaining_review_workbook", "audit_workbook",
        ) if candidate.get(key)
    ]
    output_paths.extend(str(value) for value in candidate.get("deliverables", []) if value)
    output_paths = list(dict.fromkeys(value for value in output_paths if value))
    if not output_paths:
        return
    with connect(project_root) as connection:
        for output_path in output_paths:
            path = Path(output_path).expanduser().resolve()
            try:
                relative = str(path.relative_to(project_root.resolve()))
            except ValueError:
                relative = str(path)
            connection.execute(
                """INSERT INTO domain_agent_artifacts(
                       artifact_id, session_id, run_id, artifact_type, title, project_path,
                       payload_json, status, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, 'candidate', ?)""",
                (_id("DAR"), session_id, run_id, tool_name, path.name, relative, _json(candidate), utc_now()),
            )


def _apply_domain_run_controls(project_root: Path, run_id: str) -> str:
    controls = _consume_run_controls(project_root, "domain", run_id)
    with connect(project_root) as connection:
        if controls["stop"]:
            connection.execute(
                "UPDATE domain_agent_runs SET status='STOPPED',updated_at=? WHERE run_id=?",
                (utc_now(), run_id),
            )
            return "stop"
    return "steer" if controls["steering"] else ""


def send_domain_message(
    project_root: Path, plugin_name: str, content: str,
    *, main_thread_id: str = "", access_mode: str = "ask", parent_run_id: str = "",
    attached_refs: list[dict[str, Any]] | None = None,
    reasoning_mode: str = "standard", reasoning_effort: str = "medium",
) -> dict[str, Any]:
    content = content.strip()
    request_text = content
    attached_refs = attached_refs or []
    if not content and not attached_refs:
        raise ValueError("domain-agent message is required")
    if access_mode not in {"ask", "research_assist", "full_computer"}:
        raise ValueError("unknown domain-agent access mode")
    if reasoning_mode not in {"standard", "deep"}:
        raise ValueError("unknown domain-agent reasoning mode")
    if reasoning_effort not in {"low", "medium", "high", "max"}:
        raise ValueError("unknown domain-agent reasoning effort")
    attachment_receipts = []
    for reference in attached_refs:
        attachment = inspect_attachment(project_root, str(reference.get("attachment_id", "")))
        attachment["tool_path"] = attachment["absolute_path"]
        if attachment["kind"] == "image":
            vision = _domain_profile(project_root, plugin_name, "vision_primary", "vision_ocr")
            if vision is None:
                raise ValueError("no vision/OCR model is configured for domain-agent image attachments")
            attachment["analysis"] = _vision_file_call(
                vision, Path(attachment["absolute_path"]),
                content or "Faithfully read this image for the selected domain agent.",
            )
            secondary = _domain_profile(project_root, plugin_name, "vision_secondary", "vision_secondary")
            if secondary is not None:
                attachment["secondary_analysis"] = _vision_file_call(
                    secondary, Path(attachment["absolute_path"]),
                    content or "Independently review this image. Report uncertainties and disagreements; do not copy another model.",
                )
                attachment["vision_review_required"] = True
        attachment.pop("absolute_path", None)
        attachment_receipts.append(attachment)
    if attachment_receipts:
        content += "\n\nATTACHMENT_INSPECTION_RECEIPTS " + _json(attachment_receipts)
    plugin = _plugin(project_root, plugin_name)
    session = ensure_domain_session(project_root, plugin_name)
    profile = _domain_profile(project_root, plugin_name, "domain_reasoning", "domain_agent") or _assigned_profile(project_root)
    now, run_id = utc_now(), _id("DRN")
    snapshot = {
        "profile_id": profile.profile_id, "provider": profile.provider, "model": profile.model,
        "plugin_name": plugin_name, "agent_id": session["agent_id"], "access_mode": access_mode,
        "reasoning_mode": reasoning_mode, "reasoning_effort": reasoning_effort,
    }
    with connect(project_root) as connection:
        connection.execute(
            "INSERT INTO domain_agent_messages(message_id,session_id,role,content_json,created_at) VALUES (?,?, 'user', ?, ?)",
            (_id("DMS"), session["session_id"], _json({
                "text": content.split("\n\nATTACHMENT_INSPECTION_RECEIPTS ", 1)[0],
                "main_thread_id": main_thread_id, "attached_refs": attached_refs,
            }), now),
        )
        connection.execute(
            """INSERT INTO domain_agent_runs(
                   run_id,session_id,main_thread_id,status,model_snapshot_json,created_at,updated_at
               ) VALUES (?,?,?,'RUNNING',?,?,?)""",
            (run_id, session["session_id"], main_thread_id or None, _json(snapshot), now, now),
        )
        if parent_run_id:
            _append_run_event(connection, parent_run_id, "domain_run_started", {
                "domain_run_id": run_id, "plugin_name": plugin_name,
            })
    observations: list[dict[str, Any]] = []
    requirements = _tool_requirements(plugin, content)
    embedded_receipts: list[dict[str, Any]] = []
    if "ATTACHMENT_INSPECTION_RECEIPTS " in request_text:
        try:
            parsed = json.loads(request_text.split("ATTACHMENT_INSPECTION_RECEIPTS ", 1)[1])
            embedded_receipts = [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []
            for item in embedded_receipts:
                if item.get("attachment_id") and not (item.get("tool_path") or item.get("absolute_path")):
                    item["tool_path"] = inspect_attachment(project_root, str(item["attachment_id"]))["absolute_path"]
            content = request_text.split("ATTACHMENT_INSPECTION_RECEIPTS ", 1)[0] + \
                "ATTACHMENT_INSPECTION_RECEIPTS " + _json(embedded_receipts)
        except json.JSONDecodeError:
            pass
    spreadsheet_paths = [
        str(item["tool_path"]) for item in attachment_receipts
        if item.get("kind") == "spreadsheet" and item.get("tool_path")
    ]
    spreadsheet_paths.extend(
        str(item.get("tool_path") or item.get("absolute_path"))
        for item in embedded_receipts
        if item.get("kind") == "spreadsheet" and (item.get("tool_path") or item.get("absolute_path"))
    )
    inspect_only = bool(
        spreadsheet_paths
        and re.search(r"(?:查看|检查|读取|识别|预览|盘点)", request_text)
        and not re.search(r"(?:转换|转成|生成|导出|输出|成品表|标准表|自定义表头|schema|22\s*列)", request_text, flags=re.IGNORECASE)
    )
    if (
        spreadsheet_paths
        and "inspect_half_finished_workbook" in {str(value) for value in plugin.get("agent_tools", [])}
        and (inspect_only or re.search(r"(?:查看|检查|读取|识别).{0,12}(?:表头|前三行|前三条|工作表)", request_text))
    ):
        requirements = [
            item for item in requirements if item.get("tool") != "inspect_half_finished_workbook"
        ] + [{
            "tool": "inspect_half_finished_workbook",
            "minimum_calls": len(spreadsheet_paths),
            "paths": spreadsheet_paths,
        }]
    contract_tools = {str(item["tool"]) for item in requirements}
    contract_tools.update(
        str(name) for name in plugin.get("agent_tools", []) if str(name) in request_text
    )
    tool_specs = [
        item for item in (
            domain_plugin_tool_specs(find_config_root(project_root), plugin_name)
            if plugin.get("runtime_command") else []
        ) if str(item.get("name", "")) in contract_tools
    ]
    if harness_backend() == "codex":
        from .codex_harness import run_domain_turn

        all_tool_specs = (
            domain_plugin_tool_specs(find_config_root(project_root), plugin_name)
            if plugin.get("runtime_command") else []
        )
        available_tool_specs = tool_specs if inspect_only else all_tool_specs
        domain_prompt = _domain_prompt(plugin, available_tool_specs, native_tools=True)
        if requirements:
            domain_prompt += (
                "\nREQUEST_TOOL_CONTRACT " + _json(requirements)
                + "\nComplete every required tool call before returning a final answer. "
                "In research_assist mode, routine candidate-file writes are allowed; only sensitive actions pause."
            )
        try:
            final = _clean_final_text(run_domain_turn(
                project_root, str(session["session_id"]), run_id, content, profile, plugin,
                available_tool_specs, domain_prompt,
                access_mode, reasoning_effort, parent_run_id, reasoning_mode,
                _domain_history(project_root, str(session["session_id"]), main_thread_id),
            ))
            with connect(project_root) as connection:
                current = connection.execute(
                    "SELECT status FROM domain_agent_runs WHERE run_id=?", (run_id,)
                ).fetchone()
                if current is not None and current["status"] == "STOPPED":
                    return domain_agent_view(project_root, str(session["session_id"]), main_thread_id)
                connection.execute(
                    "INSERT INTO domain_agent_messages(message_id,session_id,role,content_json,created_at) "
                    "VALUES (?,?, 'assistant', ?, ?)",
                    (_id("DMS"), session["session_id"], _json({
                        "text": final, "main_thread_id": main_thread_id,
                    }), utc_now()),
                )
                connection.execute(
                    "UPDATE domain_agent_runs SET status='COMPLETED',updated_at=? WHERE run_id=?",
                    (utc_now(), run_id),
                )
                connection.execute(
                    "UPDATE domain_agent_sessions SET updated_at=? WHERE session_id=?",
                    (utc_now(), session["session_id"]),
                )
                if parent_run_id:
                    _append_run_event(connection, parent_run_id, "domain_run_completed", {
                        "domain_run_id": run_id, "plugin_name": plugin_name,
                    })
            return domain_agent_view(project_root, str(session["session_id"]), main_thread_id)
        except Exception as error:
            with connect(project_root) as connection:
                connection.execute(
                    "UPDATE domain_agent_runs SET status='FAILED',error=?,updated_at=? WHERE run_id=?",
                    (str(error), utc_now(), run_id),
                )
                if parent_run_id:
                    _append_run_event(connection, parent_run_id, "domain_run_failed", {
                        "domain_run_id": run_id, "plugin_name": plugin_name, "error": str(error),
                    })
            raise
    tool_budget = min(48, max(
        {"low": 8, "medium": 16, "high": 24, "max": 24}[reasoning_effort],
        sum(int(item.get("minimum_calls", 1)) for item in requirements) + 4,
    ))
    invalid_action_retries = 0
    forced_final = ""
    try:
        for _ in range(tool_budget + 1):
            if _apply_domain_run_controls(project_root, run_id) == "stop":
                return domain_agent_view(project_root, session["session_id"], main_thread_id)
            action = {"type": "final", "content": forced_final} if forced_final else _model_action(
                profile, content, observations, tool_budget - len(observations),
                "DOMAIN_SUBAGENT: private memory; return candidates to the main agent.",
                _domain_history(project_root, session["session_id"], main_thread_id),
                system_prompt=_domain_prompt(plugin, tool_specs),
                reasoning_mode=reasoning_mode,
                reasoning_effort=reasoning_effort,
            )
            forced_final = ""
            control = _apply_domain_run_controls(project_root, run_id)
            if control == "stop":
                return domain_agent_view(project_root, session["session_id"], main_thread_id)
            if control == "steer":
                continue
            if action.get("type") == "final":
                nested = _nested_domain_tool_action(str(action.get("content", "")))
                if nested is not None:
                    action = nested
                else:
                    missing = [item for item in requirements if not _requirement_satisfied(item, observations)]
                    if missing:
                        observations.append({
                            "tool": "domain.completion_contract", "arguments": {"requirements": missing},
                            "result": None,
                            "error": "Complete every required domain tool call and every explicit input path before returning a final answer.",
                        })
                        continue
                    final = _clean_final_text(str(action.get("content", "")))
                    with connect(project_root) as connection:
                        connection.execute(
                            "INSERT INTO domain_agent_messages(message_id,session_id,role,content_json,created_at) VALUES (?,?, 'assistant', ?, ?)",
                            (_id("DMS"), session["session_id"], _json({
                                "text": final, "main_thread_id": main_thread_id,
                            }), utc_now()),
                        )
                        connection.execute(
                            "UPDATE domain_agent_runs SET status='COMPLETED',updated_at=? WHERE run_id=?",
                            (utc_now(), run_id),
                        )
                        connection.execute(
                            "UPDATE domain_agent_sessions SET updated_at=? WHERE session_id=?",
                            (utc_now(), session["session_id"]),
                        )
                        if parent_run_id:
                            _append_run_event(connection, parent_run_id, "domain_run_completed", {
                                "domain_run_id": run_id, "plugin_name": plugin_name,
                            })
                    return domain_agent_view(project_root, session["session_id"], main_thread_id)
            if action.get("type") != "tool_call":
                raise ValueError("domain subagent returned an invalid action")
            tool_name = str(action.get("tool", ""))
            arguments = action.get("arguments", {})
            if (
                "ATTACHMENT_INSPECTION_RECEIPTS" in content
                and tool_name in {"run_book_pages", "pdf_inspect", "pdf_render_page", "pdf_crop_page", "pdf_extract_text", "ocr_page_api"}
                and not any(phrase in content for phrase in ("处理原始PDF", "处理原始书目", "处理整书", "处理完整篇章"))
            ):
                observations.append({
                    "tool": tool_name, "arguments": arguments, "result": None,
                    "error": "This turn already contains attachment inspection receipts. Judge only those receipts; do not start book or PDF processing unless the researcher explicitly requested it.",
                })
                continue
            if tool_name not in {str(value) for value in plugin.get("agent_tools", [])}:
                if invalid_action_retries:
                    raise ValueError(f"domain tool is not allowlisted: {tool_name}")
                invalid_action_retries += 1
                observations.append({
                    "tool": "domain.model_response", "arguments": {}, "result": None,
                    "error": "Return one valid JSON action using an allowlisted domain tool.",
                })
                continue
            if not isinstance(arguments, dict):
                raise ValueError("domain tool arguments must be an object")
            exact_failures = [
                item for item in observations
                if item.get("tool") == tool_name and item.get("arguments") == arguments
                and (
                    item.get("error")
                    or (isinstance(item.get("result"), dict) and item["result"].get("isError"))
                )
            ]
            if len(exact_failures) >= 2:
                observations.append({
                    "tool": "domain.recovery", "arguments": {"blocked_tool": tool_name},
                    "result": None,
                    "error": "The same domain call failed twice. Change the arguments, use another approved tool, or return a concise user-facing blocker.",
                })
                continue
            duplicate = next((
                item for item in observations
                if item.get("tool") == tool_name
                and item.get("arguments") == arguments
                and item.get("result") is not None
                and not bool((item.get("result") or {}).get("isError"))
            ), None)
            if duplicate is not None:
                observations.append({
                    "tool": "domain.completion_contract", "arguments": {}, "result": None,
                    "error": f"{tool_name} already succeeded with the same arguments; use its receipt or continue to the next required tool.",
                })
                continue
            risk = _permission(plugin, tool_name)
            if risk == "forbidden" or (risk == "sensitive" and access_mode != "full_computer"):
                observations.append({
                    "tool": tool_name, "arguments": arguments, "result": None,
                    "error": f"permission {risk} requires a higher access mode",
                })
                continue
            call_id = _id("DTC")
            with connect(project_root) as connection:
                connection.execute(
                    """INSERT INTO domain_agent_tool_calls(
                           tool_call_id,run_id,tool_name,input_json,status,created_at
                       ) VALUES (?,?,?,?, 'RUNNING', ?)""",
                    (call_id, run_id, tool_name, _json(arguments), utc_now()),
                )
                if parent_run_id:
                    _append_run_event(connection, parent_run_id, "domain_tool_started", {
                        "domain_run_id": run_id, "domain_tool_call_id": call_id,
                        "tool": tool_name,
                    })
            async def report_progress(
                progress: float, total: float | None, message: str | None
            ) -> None:
                if not parent_run_id:
                    return
                with connect(project_root) as connection:
                    _append_run_event(connection, parent_run_id, "domain_tool_progress", {
                        "domain_run_id": run_id,
                        "domain_tool_call_id": call_id,
                        "tool": tool_name,
                        "progress": progress,
                        "total": total,
                        "message": message or "",
                    })

            result = call_domain_plugin_tool(
                find_config_root(project_root), plugin_name, tool_name, arguments,
                progress_callback=report_progress,
            )
            payload = _tool_payload(result)
            call_status = "FAILED" if bool(result.get("isError")) or bool(payload.get("isError")) else "COMPLETED"
            with connect(project_root) as connection:
                connection.execute(
                    """UPDATE domain_agent_tool_calls SET output_json=?,status=?,completed_at=?
                       WHERE tool_call_id=?""",
                    (_json(payload), call_status, utc_now(), call_id),
                )
                if parent_run_id:
                    _append_run_event(connection, parent_run_id, "domain_tool_completed", {
                        "domain_run_id": run_id, "domain_tool_call_id": call_id,
                        "tool": tool_name, "status": call_status,
                        "resumable": bool(payload.get("resumable")) if isinstance(payload, dict) else False,
                        "run_id": str(payload.get("run_id") or "") if isinstance(payload, dict) else "",
                    })
            if call_status == "COMPLETED":
                _record_artifact(project_root, session["session_id"], run_id, tool_name, payload)
            observations.append({"tool": tool_name, "arguments": arguments, "result": payload})
            if call_status == "FAILED":
                observations.append({
                    "tool": "domain.recovery", "arguments": {"failed_tool": tool_name},
                    "result": None,
                    "error": "Read the tool error, correct the smallest invalid argument, and retry once. Do not repeat the same failed call unchanged.",
                })
            if (
                call_status == "COMPLETED"
                and tool_name == "normalize_disaster_type"
                and "ATTACHMENT_INSPECTION_RECEIPTS" in content
            ):
                receipt_text = content.split("ATTACHMENT_INSPECTION_RECEIPTS ", 1)[1]
                try:
                    receipts = json.loads(receipt_text)
                except json.JSONDecodeError:
                    receipts = []
                analyses = [
                    str(item.get("analysis", "")).strip()
                    for item in receipts if isinstance(item, dict) and str(item.get("analysis", "")).strip()
                ]
                labels = "、".join(str(value) for value in payload.get("disaster_types", []))
                warnings = "；".join(str(value) for value in payload.get("warnings", []))
                forced_final = (
                    "图片识读回执：\n" + ("\n".join(analyses) or "未返回可用的图片文字。")
                    + "\n\n领域判定：" + (f"受控灾种候选为{labels}。" if labels else "未形成明确的受控灾种候选。")
                    + (f"{warnings}。" if warnings else "")
                )
        raise RuntimeError("domain subagent exhausted its tool budget")
    except Exception as error:
        with connect(project_root) as connection:
            connection.execute(
                "UPDATE domain_agent_runs SET status='FAILED',error=?,updated_at=? WHERE run_id=?",
                (str(error), utc_now(), run_id),
            )
            if parent_run_id:
                _append_run_event(connection, parent_run_id, "domain_run_failed", {
                    "domain_run_id": run_id, "plugin_name": plugin_name, "error": str(error),
                })
        raise


def domain_agent_view(
    project_root: Path, session_id: str, main_thread_id: str = "",
) -> dict[str, Any]:
    with connect(project_root) as connection:
        session = connection.execute(
            "SELECT * FROM domain_agent_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if session is None:
            raise KeyError(f"unknown domain-agent session: {session_id}")
        allowed_threads: set[str] = set()
        current = main_thread_id
        while current and current not in allowed_threads and len(allowed_threads) < 8:
            allowed_threads.add(current)
            parent = connection.execute(
                "SELECT parent_thread_id FROM thread_inheritance WHERE child_thread_id=?", (current,),
            ).fetchone()
            current = str(parent["parent_thread_id"]) if parent else ""
        messages = [dict(row) for row in connection.execute(
            "SELECT * FROM domain_agent_messages WHERE session_id=? ORDER BY created_at,message_id",
            (session_id,),
        )]
        runs = [dict(row) for row in connection.execute(
            "SELECT * FROM domain_agent_runs WHERE session_id=? ORDER BY created_at DESC", (session_id,),
        )]
        for message in messages:
            message["content"] = _decode(message.pop("content_json"), {})
            control_id = str(message["content"].get("run_control_id", ""))
            if control_id:
                control = connection.execute(
                    "SELECT status FROM agent_run_controls WHERE control_id=?", (control_id,),
                ).fetchone()
                message["run_control_status"] = str(control["status"]) if control else "deleted"
        if allowed_threads:
            messages = [
                message for message in messages
                if str(message["content"].get("main_thread_id", "")) in allowed_threads
            ]
            runs = [run for run in runs if str(run.get("main_thread_id") or "") in allowed_threads]
        for run in runs:
            run["model_snapshot"] = _decode(run.pop("model_snapshot_json"), {})
            run["tool_calls"] = []
            for row in connection.execute(
                "SELECT * FROM domain_agent_tool_calls WHERE run_id=? ORDER BY created_at", (run["run_id"],),
            ):
                item = dict(row)
                item["input"] = _decode(item.pop("input_json"), {})
                item["output"] = _decode(item.pop("output_json"), None)
                run["tool_calls"].append(item)
        artifacts = [dict(row) for row in connection.execute(
            "SELECT * FROM domain_agent_artifacts WHERE session_id=? ORDER BY created_at DESC", (session_id,),
        )]
        if allowed_threads:
            run_ids = {str(run["run_id"]) for run in runs}
            artifacts = [artifact for artifact in artifacts if str(artifact.get("run_id") or "") in run_ids]
        for artifact in artifacts:
            artifact["payload"] = _decode(artifact.pop("payload_json"), {})
            path = Path(artifact["project_path"])
            artifact["native_path"] = str(path if path.is_absolute() else (project_root / path).resolve())
    return {"session": dict(session), "messages": messages, "runs": runs, "artifacts": artifacts, "main_thread_id": main_thread_id}


def domain_agent_state(project_root: Path) -> dict[str, Any]:
    plugins = [
        item for item in plugin_state(find_config_root(project_root))["plugins"]
        if item.get("kind") != "system" and item.get("status") == "ready"
    ]
    sessions = []
    for plugin in plugins:
        session = ensure_domain_session(project_root, str(plugin["name"]))
        sessions.append({
            **session,
            "display_name": plugin.get("display_name") or plugin.get("name"),
            "description": plugin.get("description_zh") or plugin.get("description"),
            "agent_tools": plugin.get("agent_tools", []),
            "model_roles": plugin.get("model_roles", []),
            "model_settings": public_domain_model_settings(find_config_root(project_root), str(plugin["name"])),
            "workspace": plugin.get("workspace", {}),
        })
    return {"sessions": sessions, "count": len(sessions)}
