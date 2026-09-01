from __future__ import annotations

import json
import os
import threading
import time
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openai_codex.client import CodexClient, CodexConfig

from .db import connect, utc_now


_HOSTS: dict[tuple[str, str, str, str], "_Host"] = {}
_HOSTS_LOCK = threading.Lock()
_THREAD_FILE_LOCK = threading.Lock()

_NATIVE_TOOLS = {
    "harness.status": "检查问津 Codex app-server 内核、SDK、内置二进制与活动主机状态。",
    "project.status": "读取当前项目题名、阶段、来源与处理数量。",
    "source.list": "按 source_ids、query 和 limit 查看有界来源目录。",
    "source.search": "按 query、可选 source_id 和 limit 检索已入库史料文本。",
    "source.page": "按 page_id，或 source_id 与 physical_page，读取一页及其证据状态。",
    "library.status": "读取研究图书馆的作品、版本、文件与扫描数量。",
    "library.search": "按 query、tags 和 limit 检索图书馆书目。",
    "library.assets": "按 kind=tables、maps 或 images 查看图书馆资料。",
    "library.work": "按 work_id 读取作品、版本、文件与项目关联详情。",
    "library.add_to_project": "把明确的图书馆 work_id 与 file_id 采用到当前项目，并自动建立可回查的 PDF 页面或 DOCX 定位文本。",
    "library.graph": "按 query 和 limit 读取书目与实体知识图谱。",
    "research.state": "读取论点、证据冻结、阅读任务和研究产物的紧凑索引。",
    "research.plan_context": "读取项目当前研究规划所需的紧凑上下文。",
    "retrieval.list": "列出联网检索记录，或按 record_id 查看一项检索结果。",
    "plugin.list": "列出已安装领域插件及其运行状态。",
    "domain_agent.list": "列出当前可用的领域 Agent。",
    "skill.list": "列出问津可在对话中使用的研究 Skills。",
    "skill.read": "按 name 读取一个 Skill 的完整说明。",
    "attachment.inspect": "按 attachment_id 检查当前对话附件。",
    "domain_pack.validate": "只读校验一个领域 Agent 工程目录。",
    "browser.snapshot": "查看已打开研究浏览器会话的当前状态。",
    "browser.read": "读取已打开研究浏览器会话的当前网页正文。",
    "authoring.state": "读取文章、章节、阅读与评审状态的紧凑索引。",
    "authoring.section": "按 section_id 读取一个写作章节。",
    "research_design.current": "读取当前已共享的研究设计。",
    "research_event.list": "按 case_ids、statuses 与 detail 查看逐事件记录。",
    "research_event.coverage": "按 case_ids 计算逐事件覆盖情况。",
    "research.search": "按 provider、query 和 limit 执行有界联网书目检索。",
    "plugin.call": "调用已安装插件清单中明确开放的工具。",
    "plugin.repair": "按已记录来源修复一个已安装插件。",
    "system.diagnose": "只读检查项目数据库、插件构建身份和可选运行环境。",
    "system.repair": "备份项目后，仅修复有可靠来源记录的损坏插件。",
    "domain_agent.consult": "让指定领域 Agent 在隔离会话中处理一个有界问题。",
    "skill.create": "按用户已明确的目的、边界与说明创建本地 Skill。",
    "domain_pack.create": "按用户已明确的范围创建领域 Agent 工程骨架。",
    "browser.start": "为明确网址打开受控研究浏览器会话。",
    "browser.open": "在已有受控会话中打开同域网址。",
    "research_design.propose": "保存一份候选研究设计。",
    "research_event.propose_batch": "保存一批带来源锚点的候选逐事件记录。",
    "reading_job.create": "创建一个有界阅读任务。",
    "reading_job.batch": "读取阅读任务中的下一小批原页。",
    "reading_note.save": "保存带来源页范围的阅读分析。",
    "historiography.create": "保存一条候选学术史条目。",
    "save_research_note": "保存一份研究札记；请求批准模式下会暂停等待用户决定。",
}

_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "harness.status": {"type": "object", "properties": {}, "additionalProperties": False},
    "system.diagnose": {"type": "object", "properties": {}, "additionalProperties": False},
    "system.repair": {"type": "object", "properties": {}, "additionalProperties": False},
    "project.status": {"type": "object", "properties": {}, "additionalProperties": False},
    "source.list": {"type": "object", "properties": {"source_ids": {"type": "array", "items": {"type": "string"}}, "query": {"type": "string"}, "limit": {"type": "integer"}}, "additionalProperties": False},
    "source.search": {"type": "object", "properties": {"query": {"type": "string"}, "source_id": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"], "additionalProperties": False},
    "source.page": {"type": "object", "properties": {"page_id": {"type": "string"}, "source_id": {"type": "string"}, "physical_page": {"type": "integer"}}, "additionalProperties": False},
    "library.status": {"type": "object", "properties": {}, "additionalProperties": False},
    "library.search": {"type": "object", "properties": {"query": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer"}}, "additionalProperties": False},
    "library.assets": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["tables", "maps", "images"]}}, "required": ["kind"], "additionalProperties": False},
    "library.work": {"type": "object", "properties": {"work_id": {"type": "string"}}, "required": ["work_id"], "additionalProperties": False},
    "library.add_to_project": {"type": "object", "properties": {"work_id": {"type": "string"}, "file_id": {"type": "string"}}, "required": ["work_id", "file_id"], "additionalProperties": False},
    "library.graph": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}, "include_reading_notes": {"type": "boolean"}}, "additionalProperties": False},
    "research.state": {"type": "object", "properties": {}, "additionalProperties": False},
    "research.plan_context": {"type": "object", "properties": {}, "additionalProperties": False},
    "retrieval.list": {"type": "object", "properties": {"record_id": {"type": "string"}, "limit": {"type": "integer"}}, "additionalProperties": False},
    "research.search": {"type": "object", "properties": {"provider": {"type": "string", "enum": ["crossref", "openalex", "zotero"]}, "query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["provider", "query"], "additionalProperties": False},
    "plugin.list": {"type": "object", "properties": {}, "additionalProperties": False},
    "plugin.call": {"type": "object", "properties": {"plugin_name": {"type": "string"}, "tool_name": {"type": "string"}, "arguments": {"type": "object"}}, "required": ["plugin_name", "tool_name", "arguments"], "additionalProperties": False},
    "plugin.repair": {"type": "object", "properties": {"plugin_name": {"type": "string"}}, "required": ["plugin_name"], "additionalProperties": False},
    "domain_agent.list": {"type": "object", "properties": {}, "additionalProperties": False},
    "domain_agent.consult": {"type": "object", "properties": {"plugin_name": {"type": "string"}, "question": {"type": "string"}, "new_thread": {"type": "boolean"}}, "required": ["plugin_name", "question"], "additionalProperties": False},
    "skill.list": {"type": "object", "properties": {}, "additionalProperties": False},
    "skill.read": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"], "additionalProperties": False},
    "skill.create": {"type": "object", "properties": {"name": {"type": "string"}, "display_name": {"type": "string"}, "description": {"type": "string"}, "instructions": {"type": "string"}, "allow_implicit_invocation": {"type": "boolean"}}, "required": ["name", "display_name", "description", "instructions"], "additionalProperties": False},
    "attachment.inspect": {"type": "object", "properties": {"attachment_id": {"type": "string"}, "prompt": {"type": "string"}}, "required": ["attachment_id"], "additionalProperties": False},
    "domain_pack.validate": {"type": "object", "properties": {"plugin_root": {"type": "string"}}, "required": ["plugin_root"], "additionalProperties": False},
    "domain_pack.create": {"type": "object", "properties": {"parent": {"type": "string"}, "name": {"type": "string"}, "display_name": {"type": "string"}, "description": {"type": "string"}}, "required": ["parent", "name", "display_name", "description"], "additionalProperties": False},
    "browser.start": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"], "additionalProperties": False},
    "browser.snapshot": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"], "additionalProperties": False},
    "browser.read": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"], "additionalProperties": False},
    "browser.open": {"type": "object", "properties": {"session_id": {"type": "string"}, "url": {"type": "string"}}, "required": ["session_id", "url"], "additionalProperties": False},
    "authoring.state": {"type": "object", "properties": {}, "additionalProperties": False},
    "authoring.section": {"type": "object", "properties": {"section_id": {"type": "string"}}, "required": ["section_id"], "additionalProperties": False},
    "research_design.current": {"type": "object", "properties": {}, "additionalProperties": False},
    "research_design.propose": {"type": "object", "properties": {"title": {"type": "string"}, "content": {"type": "string"}, "change_summary": {"type": "string"}}, "required": ["title", "content"], "additionalProperties": False},
    "research_event.list": {"type": "object", "properties": {"case_ids": {"type": "array", "items": {"type": "string"}}, "statuses": {"type": "array", "items": {"type": "string"}}, "detail": {"type": "string"}}, "additionalProperties": False},
    "research_event.coverage": {"type": "object", "properties": {"case_ids": {"type": "array", "items": {"type": "string"}}}, "additionalProperties": False},
    "research_event.propose_batch": {"type": "object", "properties": {"events": {"type": "array", "items": {"type": "object"}}}, "required": ["events"], "additionalProperties": False},
    "reading_job.create": {"type": "object", "properties": {"title": {"type": "string"}, "question": {"type": "string"}, "mode": {"type": "string"}, "source_ids": {"type": "array", "items": {"type": "string"}}, "stop_condition": {"type": "string"}}, "required": ["title", "question", "mode", "source_ids", "stop_condition"], "additionalProperties": False},
    "reading_job.batch": {"type": "object", "properties": {"job_id": {"type": "string"}, "source_id": {"type": "string"}, "after_physical_page": {"type": "integer"}, "page_limit": {"type": "integer"}}, "required": ["job_id", "source_id"], "additionalProperties": False},
    "reading_note.save": {"type": "object", "properties": {"job_id": {"type": "string"}, "source_id": {"type": "string"}, "physical_pages": {"type": "array", "items": {"type": "integer"}}, "content": {"type": "string"}, "complete": {"type": "boolean"}}, "required": ["job_id", "source_id", "physical_pages", "content"], "additionalProperties": False},
    "historiography.create": {"type": "object", "properties": {"work_title": {"type": "string"}, "position": {"type": "string"}, "contribution": {"type": "string"}, "limitation": {"type": "string"}, "relevance": {"type": "string"}, "source_refs": {"type": "array", "items": {"type": "string"}}}, "required": ["work_title", "position", "contribution", "limitation", "relevance", "source_refs"], "additionalProperties": False},
    "save_research_note": {"type": "object", "properties": {"title": {"type": "string"}, "content": {"type": "string"}}, "required": ["title", "content"], "additionalProperties": False},
}

_EAGER_TOOLS = {
    "harness.status", "system.diagnose", "system.repair",
    "project.status", "source.list", "source.search", "source.page",
    "library.status", "library.search", "library.assets", "library.work", "library.add_to_project", "library.graph",
    "research.state", "research.plan_context", "retrieval.list", "research.search",
    "plugin.list", "domain_agent.list", "domain_agent.consult", "skill.list", "skill.read",
    "attachment.inspect", "browser.start", "browser.snapshot", "browser.read", "browser.open",
    "computer.status", "computer.runtime_status", "computer.roots", "computer.file_search", "computer.run",
    "computer.windows", "computer.snapshot", "computer.capture", "authoring.state",
}


def _wire_name(tool_name: str) -> str:
    return tool_name.replace(".", "__")


def _tool_name(wire_name: str) -> str:
    return wire_name.replace("__", ".")


def _dynamic_tools(project_root: Path) -> list[dict[str, Any]]:
    from .agent_runtime import COMPUTER_TOOL_ALIASES
    from .domain_plugins import domain_plugin_tool_specs, find_config_root

    tools = {
        **_NATIVE_TOOLS,
        **{name: f"调用问津 Computer Use 的 {plugin_name} 能力。" for name, plugin_name in COMPUTER_TOOL_ALIASES.items()},
    }
    computer_specs = {
        str(item.get("name", "")): item.get("inputSchema")
        for item in domain_plugin_tool_specs(find_config_root(project_root), "computer-use")
    }
    computer_schemas = {
        alias: computer_specs.get(plugin_name)
        for alias, plugin_name in COMPUTER_TOOL_ALIASES.items()
    }
    eager = [
        {
            "type": "function",
            "name": "wenjin__" + _wire_name(name),
            "description": description,
            "inputSchema": _TOOL_SCHEMAS.get(name) or computer_schemas.get(name)
            or {"type": "object", "additionalProperties": True},
        }
        for name, description in tools.items()
        if name in _EAGER_TOOLS
    ]
    deferred = [
        {
            "type": "function", "name": _wire_name(name), "description": description,
            "inputSchema": _TOOL_SCHEMAS.get(name) or computer_schemas.get(name)
            or {"type": "object", "additionalProperties": True},
            "deferLoading": True,
        }
        for name, description in tools.items()
        if name not in _EAGER_TOOLS
    ]
    return eager + [{
        "type": "namespace", "name": "wenjin",
        "description": "问津按需加载的研究、写作、领域 Agent 与 Computer Use 工具。",
        "tools": deferred,
    }]


def _thread_file(project_root: Path) -> Path:
    return project_root / "runtime" / "codex_threads.json"


def _load_thread_id(project_root: Path, wenjin_thread_id: str, profile_key: str) -> str:
    path = _thread_file(project_root)
    with _THREAD_FILE_LOCK:
        if not path.exists():
            return ""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        return str(data.get(profile_key, {}).get(wenjin_thread_id, ""))


def _save_thread_id(project_root: Path, wenjin_thread_id: str, profile_key: str, codex_thread_id: str) -> None:
    path = _thread_file(project_root)
    with _THREAD_FILE_LOCK:
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, json.JSONDecodeError):
            data = {}
        data.setdefault(profile_key, {})[wenjin_thread_id] = codex_thread_id
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


def _event(project_root: Path, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    from .agent_runtime import _append_run_event

    with connect(project_root) as connection:
        _append_run_event(connection, run_id, event_type, payload)


def _tool_result(value: Any, success: bool = True) -> dict[str, Any]:
    return {
        "contentItems": [{
            "type": "inputText",
            "text": json.dumps(value, ensure_ascii=False, default=str),
        }],
        "success": success,
    }


def _stream_turn(host: "_Host", thread_id: str, run_id: str, content: str,
                 params: dict[str, Any], run_kind: str) -> tuple[str, bool]:
    from .agent_runtime import _append_run_event, _consume_run_controls

    started = host.client.turn_start(thread_id, content, params=params)
    turn_id = started.turn.id
    finished = threading.Event()
    stopped = threading.Event()

    def watch() -> None:
        while not finished.wait(0.25):
            controls = _consume_run_controls(host.project_root, run_kind, run_id)
            for message in controls["steering"]:
                if run_kind == "main":
                    with connect(host.project_root) as connection:
                        _append_run_event(connection, run_id, "user_steering", {"content": message})
                host.client.turn_steer(thread_id, turn_id, message)
            if not controls["stop"]:
                continue
            host.client.turn_interrupt(thread_id, turn_id)
            now = utc_now()
            with connect(host.project_root) as connection:
                if run_kind == "main":
                    connection.execute(
                        "UPDATE runs SET status='STOPPED',updated_at=?,completed_at=? WHERE run_id=?",
                        (now, now, run_id),
                    )
                    _append_run_event(connection, run_id, "run_stopped", {})
                else:
                    connection.execute(
                        "UPDATE domain_agent_runs SET status='STOPPED',updated_at=? WHERE run_id=?",
                        (now, run_id),
                    )
            stopped.set()
            return

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    chunks: list[str] = []
    compact_needed = False
    try:
        while True:
            notification = host.client.next_turn_notification(turn_id)
            if notification.method == "item/agentMessage/delta":
                chunks.append(str(getattr(notification.payload, "delta", "")))
            if notification.method == "thread/tokenUsage/updated":
                usage = getattr(notification.payload, "token_usage", None)
                total = getattr(getattr(usage, "total", None), "total_tokens", 0)
                window = getattr(usage, "model_context_window", 0) or 0
                compact_needed = bool(window and total >= int(window * 0.9))
            if notification.method == "turn/completed":
                turn = getattr(notification.payload, "turn", None)
                error = getattr(turn, "error", None)
                if error is not None and not stopped.is_set():
                    raise RuntimeError(str(getattr(error, "message", error)))
                break
    finally:
        finished.set()
        watcher.join(timeout=1)
        host.client.unregister_turn_notifications(turn_id)
    if compact_needed and not stopped.is_set():
        host.client.thread_compact(thread_id)
        if run_kind == "main":
            with connect(host.project_root) as connection:
                _append_run_event(connection, run_id, "context_compaction_started", {"threshold": 0.9})
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            status = host.client.thread_read(thread_id).thread.status.root
            if status.__class__.__name__ == "IdleThreadStatus":
                break
            time.sleep(0.25)
    return "".join(chunks).strip(), stopped.is_set()


@dataclass
class _Host:
    project_root: Path
    profile_key: str
    client: CodexClient
    model_provider: str = "wenjin"
    active_runs: dict[str, str] = field(default_factory=dict)
    domain_runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def handle_request(self, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        params = params or {}
        if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
            return {"decision": "decline"}
        if method != "item/tool/call":
            return {}
        thread_id = str(params.get("threadId", ""))
        raw_tool = str(params.get("tool", ""))
        if raw_tool.startswith("wenjin__"):
            params = {**params, "namespace": "wenjin", "tool": raw_tool.removeprefix("wenjin__")}
            raw_tool = str(params["tool"])
        elif raw_tool.startswith("domain__"):
            params = {**params, "namespace": "domain", "tool": raw_tool.removeprefix("domain__")}
            raw_tool = str(params["tool"])
        if not params.get("namespace") and "." in raw_tool:
            namespace, raw_tool = raw_tool.split(".", 1)
            params = {**params, "namespace": namespace, "tool": raw_tool}
        if thread_id in self.domain_runs:
            return self._handle_domain_tool(params, self.domain_runs[thread_id])
        run_id = self.active_runs.get(thread_id, "")
        tool = _tool_name(str(params.get("tool", "")))
        namespace = str(params.get("namespace", ""))
        try:
            from .agent_runtime import COMPUTER_TOOL_ALIASES
            if namespace != "wenjin" or tool not in {*_NATIVE_TOOLS, *COMPUTER_TOOL_ALIASES}:
                raise KeyError(f"unknown Wenjin native tool: {namespace}.{tool}")
            if not run_id:
                raise RuntimeError("native tool call is not bound to an active Wenjin run")
            from .agent_runtime import _execute_tool

            arguments = params.get("arguments", {})
            result = _execute_tool(
                self.project_root, run_id, tool,
                arguments if isinstance(arguments, dict) else {},
            )
            if isinstance(result, dict) and isinstance(result.get("structuredContent"), dict):
                result = result["structuredContent"]
            return _tool_result(result)
        except Exception as error:
            return _tool_result({"error": str(error)}, success=False)

    def _handle_domain_tool(self, params: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
        tool_name = str(params.get("tool", ""))
        arguments = params.get("arguments", {})
        if str(params.get("namespace", "")) != "domain" or tool_name not in binding["tools"]:
            return _tool_result({"error": f"domain tool is not allowlisted: {tool_name}"}, False)
        if not isinstance(arguments, dict):
            return _tool_result({"error": "domain tool arguments must be an object"}, False)
        from .domain_agents import _id, _json, _permission, _record_artifact, _tool_payload
        from .domain_plugins import call_domain_plugin_tool, find_config_root

        risk = _permission(binding["plugin"], tool_name)
        if risk == "forbidden" or (risk == "sensitive" and binding["access_mode"] != "full_computer"):
            return _tool_result({"error": f"permission {risk} requires a higher access mode"}, False)
        encoded_arguments = _json(arguments)
        with connect(self.project_root) as connection:
            duplicate = connection.execute(
                "SELECT output_json FROM domain_agent_tool_calls "
                "WHERE run_id=? AND tool_name=? AND input_json=? AND status='COMPLETED' "
                "ORDER BY completed_at DESC LIMIT 1",
                (binding["run_id"], tool_name, encoded_arguments),
            ).fetchone()
        if duplicate is not None:
            payload = json.loads(duplicate["output_json"])
            if isinstance(payload, dict):
                payload = {**payload, "already_succeeded": True,
                           "instruction": "Use this receipt; do not repeat the same tool call."}
            return _tool_result(payload)
        call_id = _id("DTC")
        with connect(self.project_root) as connection:
            connection.execute(
                "INSERT INTO domain_agent_tool_calls(tool_call_id,run_id,tool_name,input_json,status,created_at) "
                "VALUES (?,?,?,?, 'RUNNING', ?)",
                (call_id, binding["run_id"], tool_name, encoded_arguments, utc_now()),
            )
        try:
            result = call_domain_plugin_tool(
                find_config_root(self.project_root), binding["plugin_name"], tool_name, arguments,
            )
            payload = _tool_payload(result)
            status = "FAILED" if bool(result.get("isError")) or bool(payload.get("isError")) else "COMPLETED"
            with connect(self.project_root) as connection:
                connection.execute(
                    "UPDATE domain_agent_tool_calls SET output_json=?,status=?,completed_at=? "
                    "WHERE tool_call_id=?",
                    (_json(payload), status, utc_now(), call_id),
                )
                if binding.get("parent_run_id"):
                    from .agent_runtime import _append_run_event
                    _append_run_event(connection, binding["parent_run_id"], "domain_tool_completed", {
                        "domain_run_id": binding["run_id"], "domain_tool_call_id": call_id,
                        "tool": tool_name, "status": status,
                    })
            if status == "COMPLETED":
                _record_artifact(
                    self.project_root, binding["session_id"], binding["run_id"], tool_name, payload,
                )
            return _tool_result(payload, status == "COMPLETED")
        except Exception as error:
            with connect(self.project_root) as connection:
                connection.execute(
                    "UPDATE domain_agent_tool_calls SET status='FAILED',output_json=?,completed_at=? "
                    "WHERE tool_call_id=?", (_json({"error": str(error)}), utc_now(), call_id),
                )
            return _tool_result({"error": str(error)}, False)


def _host(project_root: Path, profile: Any, purpose: str = "main") -> _Host:
    credential_fingerprint = hashlib.sha256(profile.api_key.encode("utf-8")).hexdigest()[:12]
    key = (
        str(project_root.resolve()), profile.provider, profile.endpoint,
        f"{profile.model}:{purpose}:{credential_fingerprint}",
    )
    with _HOSTS_LOCK:
        existing = _HOSTS.get(key)
        if existing is not None:
            return existing
        runtime_home = project_root / "runtime" / "codex_home"
        runtime_home.mkdir(parents=True, exist_ok=True)
        provider_id = "ollama" if profile.provider == "ollama" else "wenjin"
        endpoint = profile.endpoint.rstrip("/")
        if provider_id == "ollama" and not endpoint.endswith("/v1"):
            endpoint += "/v1"
        overrides = (
            ('model_provider="ollama"', 'oss_provider="ollama"')
            if provider_id == "ollama" else (
                f'model_provider="{provider_id}"',
                f'model_providers.{provider_id}.name="Wenjin configured model"',
                f'model_providers.{provider_id}.base_url={json.dumps(endpoint)}',
                f'model_providers.{provider_id}.env_key="WENJIN_CODEX_API_KEY"',
                f'model_providers.{provider_id}.wire_api="responses"',
                f'model_providers.{provider_id}.requires_openai_auth=false',
            )
        )
        runtime_env = {
            "CODEX_HOME": str(runtime_home),
            "WENJIN_CODEX_API_KEY": profile.api_key or "ollama",
        }
        if provider_id == "ollama":
            runtime_env["CODEX_OSS_BASE_URL"] = endpoint
        config = CodexConfig(
            cwd=str(project_root),
            env=runtime_env,
            config_overrides=overrides,
            client_name="wenjin",
            client_title="Wenjin Research Workbench",
        )
        holder: dict[str, _Host] = {}
        client = CodexClient(config, approval_handler=lambda method, params: holder["host"].handle_request(method, params))
        created = _Host(
            project_root.resolve(), f"{profile.provider}:{profile.endpoint}:{profile.model}:{purpose}",
            client, provider_id,
        )
        holder["host"] = created
        client.start()
        client.initialize()
        _HOSTS[key] = created
        return created


def run_turn(project_root: Path, wenjin_thread_id: str, run_id: str, objective: str,
             profile: Any, instructions: str, access_mode: str, reasoning_mode: str,
             reasoning_effort: str, history: list[dict[str, str]] | None = None) -> str:
    host = _host(project_root, profile)
    with host.lock:
        codex_thread_id = _load_thread_id(project_root, wenjin_thread_id, host.profile_key)
        if codex_thread_id:
            try:
                host.client.thread_resume(codex_thread_id, {"cwd": str(project_root)})
            except Exception:
                codex_thread_id = ""
        new_thread = not codex_thread_id
        if new_thread:
            started = host.client.thread_start({
                "cwd": str(project_root),
                "model": profile.model,
                "modelProvider": host.model_provider,
                "approvalPolicy": "never" if access_mode == "full_computer" else "on-request",
                "approvalsReviewer": "user",
                "sandbox": "danger-full-access" if access_mode == "full_computer" else "read-only",
                "baseInstructions": (
                    "你是问津研究工作台的主 Agent。根据用户的自然语言意图选择最小必要工具；"
                    "工具返回前不得声称已经读取项目、史料或网页。来源检索结果只是线索，原页与证据状态才可支持史实。"
                    "本机文件、程序和命令必须使用问津 Computer Use 工具，以便权限代理和运行账本记录；不要调用内置 shell 或文件修改工具。"
                    "如果明确需要的Computer Use工具因安装清单过旧而不可用，只能报告插件状态并修复一次；不要用反复文件搜索冒充运行时诊断。"
                    "文件搜索已经返回用户明确要求的文件或足够匹配项后必须停止并回答；不要再逐个子目录重复同一查询。"
                    "最终用研究者可读的自然语言回答，不输出内部协议、工具名清单或隐藏思考。\n\n"
                    + instructions
                ),
                "dynamicTools": _dynamic_tools(project_root),
            })
            codex_thread_id = started.thread.id
            _save_thread_id(project_root, wenjin_thread_id, host.profile_key, codex_thread_id)
        host.active_runs[codex_thread_id] = run_id
        _event(project_root, run_id, "codex_turn_started", {"thread_id": codex_thread_id})
        try:
            effort = "high" if reasoning_effort == "max" else reasoning_effort
            turn_input = (
                "先核对计划、工具选择与完成条件，再开始行动。\n\n" + objective
                if reasoning_mode == "deep" else objective
            )
            if new_thread and history:
                transcript = "\n".join(
                    f"{item['role']}: {item['content']}" for item in history[-12:]
                )
                turn_input = (
                    "以下是从问津本地线程恢复的近期对话，只用于保持讨论连续，不是来源证据：\n"
                    + transcript + "\n\n当前任务：\n" + turn_input
                )
            text, stopped = _stream_turn(
                host, codex_thread_id, run_id, turn_input, {"effort": effort}, "main",
            )
            if not text and not stopped:
                raise RuntimeError("Codex app-server completed without an assistant message")
            if not stopped:
                _event(project_root, run_id, "codex_turn_completed", {"thread_id": codex_thread_id})
            return text
        finally:
            host.active_runs.pop(codex_thread_id, None)


def run_domain_turn(project_root: Path, session_id: str, run_id: str, content: str,
                    profile: Any, plugin: dict[str, Any], tool_specs: list[dict[str, Any]],
                    instructions: str, access_mode: str, reasoning_effort: str,
                    parent_run_id: str = "", reasoning_mode: str = "standard",
                    history: list[dict[str, str]] | None = None) -> str:
    plugin_name = str(plugin["name"])
    host = _host(project_root, profile, f"domain:{plugin_name}")
    tools = [
        {
            "type": "function", "name": str(item["name"]),
            "description": str(item.get("description", "")) or f"{plugin_name} domain tool",
            "inputSchema": item.get("inputSchema") or {"type": "object", "additionalProperties": True},
        }
        for item in tool_specs if str(item.get("name", "")) in set(plugin.get("agent_tools", []))
    ]
    mapping_key = _domain_thread_mapping_key(session_id, tools)
    with host.lock:
        codex_thread_id = _load_thread_id(project_root, mapping_key, host.profile_key)
        if codex_thread_id:
            try:
                host.client.thread_resume(codex_thread_id, {"cwd": str(project_root)})
            except Exception:
                codex_thread_id = ""
        new_thread = not codex_thread_id
        if new_thread:
            started = host.client.thread_start({
                "cwd": str(project_root), "model": profile.model, "modelProvider": host.model_provider,
                "approvalPolicy": "never", "sandbox": "read-only",
                "baseInstructions": instructions,
                "dynamicTools": [{**item, "name": "domain__" + item["name"]} for item in tools],
            })
            codex_thread_id = started.thread.id
            _save_thread_id(project_root, mapping_key, host.profile_key, codex_thread_id)
        host.domain_runs[codex_thread_id] = {
            "run_id": run_id, "session_id": session_id, "plugin_name": plugin_name,
            "plugin": plugin, "tools": {item["name"] for item in tools},
            "access_mode": access_mode, "parent_run_id": parent_run_id,
        }
        try:
            effort = "high" if reasoning_effort == "max" else reasoning_effort
            turn_input = (
                "先核对计划、工具选择与完成条件，再开始行动。\n\n" + content
                if reasoning_mode == "deep" else content
            )
            if new_thread and history:
                transcript = "\n".join(
                    f"{item['role']}: {item['content']}" for item in history[-12:]
                )
                turn_input = (
                    "以下是该领域 Agent 隔离会话的近期对话，只用于任务连续性：\n"
                    + transcript + "\n\n当前任务：\n" + turn_input
                )
            text, stopped = _stream_turn(
                host, codex_thread_id, run_id, turn_input, {"effort": effort}, "domain",
            )
            if not text and not stopped:
                raise RuntimeError("Codex domain turn completed without an assistant message")
            return text
        finally:
            host.domain_runs.pop(codex_thread_id, None)


def _domain_thread_mapping_key(session_id: str, tools: list[dict[str, Any]]) -> str:
    payload = json.dumps(tools, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{session_id}:tools-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]}"


def close_hosts() -> None:
    with _HOSTS_LOCK:
        hosts = list(_HOSTS.values())
        _HOSTS.clear()
    for host in hosts:
        host.client.close()


def harness_status() -> dict[str, Any]:
    import openai_codex
    from codex_cli_bin import bundled_codex_path

    binary = bundled_codex_path()
    with _HOSTS_LOCK:
        active_hosts = len(_HOSTS)
    return {
        "backend": "codex-app-server",
        "sdk_version": openai_codex.__version__,
        "binary_available": binary.is_file(),
        "binary_path": str(binary),
        "active_hosts": active_hosts,
        "forced_legacy": os.environ.get("WENJIN_HARNESS_BACKEND", "").strip().casefold() == "legacy",
    }
