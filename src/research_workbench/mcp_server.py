from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TextIO

from .agent_profile import public_agent_profile
from .authoring import authoring_state, manuscript_detail
from .library import search_library
from .service import list_sources, project_status, source_view


PROTOCOL_VERSION = "2025-06-18"


def _tools() -> list[dict[str, Any]]:
    return [
        {"name": "project_status", "description": "Return the current research project's status and counts.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
        {"name": "library_search", "description": "Search the local research library by title, author, tag, or indexed text.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "tag": {"type": "string"}}, "additionalProperties": False}},
        {"name": "source_list", "description": "List sources registered in the current project and their qualification state.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
        {"name": "source_detail", "description": "Read one registered source, including pages and citation metadata.", "inputSchema": {"type": "object", "properties": {"source_id": {"type": "string"}}, "required": ["source_id"], "additionalProperties": False}},
        {"name": "manuscript_list", "description": "List manuscripts, bounded reading tasks, and historiography entries.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
        {"name": "manuscript_detail", "description": "Read the current version and section structure of one manuscript.", "inputSchema": {"type": "object", "properties": {"manuscript_id": {"type": "string"}}, "required": ["manuscript_id"], "additionalProperties": False}},
    ]


def _call(project_root: Path, library_root: Path | None, name: str, arguments: dict[str, Any]) -> Any:
    if name == "project_status":
        return project_status(project_root)
    if name == "library_search":
        tag = str(arguments.get("tag", "")).strip()
        return search_library(project_root, str(arguments.get("query", "")), [tag] if tag else [], library_root)
    if name == "source_list":
        return list_sources(project_root)
    if name == "source_detail":
        return source_view(project_root, str(arguments["source_id"]))
    if name == "manuscript_list":
        return authoring_state(project_root)
    if name == "manuscript_detail":
        return manuscript_detail(project_root, str(arguments["manuscript_id"]))
    raise KeyError(f"unknown MCP tool: {name}")


def handle_request(project_root: Path, library_root: Path | None, request: dict[str, Any]) -> dict[str, Any] | None:
    method = str(request.get("method", ""))
    request_id = request.get("id")
    if request_id is None and method.startswith("notifications/"):
        return None
    try:
        if method == "initialize":
            result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}, "resources": {"subscribe": False, "listChanged": False}, "prompts": {"listChanged": False}}, "serverInfo": {"name": "wenjin-research", "title": "问津研究服务", "version": "0.1.1"}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": _tools()}
        elif method == "tools/call":
            params = request.get("params") or {}
            value = _call(project_root, library_root, str(params.get("name", "")), dict(params.get("arguments") or {}))
            result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2)}], "structuredContent": value if isinstance(value, dict) else {"items": value}, "isError": False}
        elif method == "resources/list":
            result = {"resources": [{"uri": "wenjin://project/status", "name": "Current project status", "mimeType": "application/json"}, {"uri": "wenjin://agent/profile", "name": "Active research persona", "mimeType": "application/json"}]}
        elif method == "resources/read":
            uri = str((request.get("params") or {}).get("uri", ""))
            if uri == "wenjin://project/status":
                value = project_status(project_root)
            elif uri == "wenjin://agent/profile":
                value = public_agent_profile(project_root)
            else:
                raise KeyError(f"unknown MCP resource: {uri}")
            result = {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(value, ensure_ascii=False, indent=2)}]}
        elif method == "prompts/list":
            result = {"prompts": [{"name": "research_status_review", "description": "Review the current project's sources, evidence, writing, and unresolved gaps.", "arguments": []}]}
        elif method == "prompts/get":
            if str((request.get("params") or {}).get("name", "")) != "research_status_review":
                raise KeyError("unknown MCP prompt")
            result = {"description": "Bounded project status review", "messages": [{"role": "user", "content": {"type": "text", "text": "请检查当前项目的来源资格、阅读覆盖、证据冻结、稿件版本和未决缺口；区分已核事实、研究判断与待核事项。"}}]}
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": str(exc)}}


def build_mcp_server(project_root: Path, library_root: Path | None = None) -> Any:
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations

    root = project_root.resolve()
    server = FastMCP("wenjin-research")
    readonly = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

    @server.tool(name="project_status", annotations=readonly)
    def mcp_project_status() -> dict:
        """Return the current Wenjin research project's status and counts."""
        return project_status(root)

    @server.tool(name="library_search", annotations=readonly)
    def mcp_library_search(query: str = "", tag: str = "") -> list[dict[str, Any]]:
        """Search the local research library by title, author, tag or indexed text."""
        return search_library(root, query, [tag] if tag else [], library_root)

    @server.tool(name="source_list", annotations=readonly)
    def mcp_source_list() -> list[dict[str, Any]]:
        """List sources registered in the current project and their qualification state."""
        return list_sources(root)

    @server.tool(name="source_detail", annotations=readonly)
    def mcp_source_detail(source_id: str) -> dict[str, Any]:
        """Read one registered source, including pages and citation metadata."""
        return source_view(root, source_id)

    @server.tool(name="manuscript_list", annotations=readonly)
    def mcp_manuscript_list() -> dict[str, Any]:
        """List manuscripts, bounded reading tasks and historiography entries."""
        return authoring_state(root)

    @server.tool(name="manuscript_detail", annotations=readonly)
    def mcp_manuscript_detail(manuscript_id: str) -> dict[str, Any]:
        """Read the current version and section structure of one manuscript."""
        return manuscript_detail(root, manuscript_id)

    @server.resource("wenjin://project/status")
    def mcp_project_resource() -> str:
        return json.dumps(project_status(root), ensure_ascii=False, indent=2)

    @server.resource("wenjin://agent/profile")
    def mcp_profile_resource() -> str:
        return json.dumps(public_agent_profile(root), ensure_ascii=False, indent=2)

    @server.prompt(name="research_status_review")
    def mcp_research_status_review() -> str:
        return (
            "请检查当前项目的来源资格、阅读覆盖、证据冻结、稿件版本和未决缺口；"
            "区分已核事实、研究判断与待核事项。"
        )

    return server


def serve_stdio(project_root: Path, library_root: Path | None = None, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    if stdin is not sys.stdin or stdout is not sys.stdout:
        raise ValueError("FastMCP stdio uses the process standard streams")
    build_mcp_server(project_root, library_root).run(transport="stdio")
