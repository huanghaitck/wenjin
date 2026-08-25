from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .domain_plugins import validate_domain_plugin


def _name(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not value or len(value) > 64:
        raise ValueError("plugin name must normalize to 1-64 lower-case characters")
    return value


def _module(name: str) -> str:
    return name.replace("-", "_")


def create_local_skill(
    config_root: Path, name: str, description: str, instructions: str,
    display_name: str = "", allow_implicit_invocation: bool = True,
) -> dict[str, Any]:
    name, description, instructions = _name(name), description.strip(), instructions.strip()
    if not description or not instructions:
        raise ValueError("skill description and instructions are required")
    root = config_root.resolve() / "skills" / name
    if root.exists():
        raise FileExistsError(f"skill already exists: {root}")
    (root / "agents").mkdir(parents=True)
    skill = (
        f"---\nname: {name}\ndescription: {description}\n---\n\n"
        f"# {display_name.strip() or name}\n\n{instructions}\n"
    )
    (root / "SKILL.md").write_text(skill, encoding="utf-8")
    (root / "agents" / "openai.yaml").write_text(
        f"display_name: {display_name.strip() or name}\n"
        f"short_description: {description}\n"
        f"default_prompt: Use the {name} skill for the current task.\n"
        f"allow_implicit_invocation: {'true' if allow_implicit_invocation else 'false'}\n",
        encoding="utf-8",
    )
    return {"name": name, "skill_root": str(root), "skill_file": str(root / "SKILL.md")}


def create_plugin_project(
    parent: Path, name: str, display_name: str, description: str,
) -> dict[str, Any]:
    name, display_name, description = _name(name), display_name.strip(), description.strip()
    if not display_name or not description:
        raise ValueError("plugin display name and description are required")
    root = parent.resolve() / name
    if root.exists():
        raise FileExistsError(f"plugin project already exists: {root}")
    module = _module(name)
    for directory in (
        root / ".codex-plugin", root / "skills" / name,
        root / "src" / module, root / "tests",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    wenjin = {
        "schema_version": 1, "name": name, "version": "0.1.0",
        "display_name": display_name, "description": description, "kind": "domain",
        "compatible_wenjin": ">=0.1.1,<0.2.0",
        "runtime": {"type": "mcp_stdio", "command": f"{name}-mcp", "args": []},
        "skills": [f"skills/{name}/SKILL.md"], "agent_tools": ["plugin_status"],
        "tool_permissions": {"plugin_status": "read"},
        "local_data_sources": [],
        "contributions": {
            "methods": [], "schemas": [], "processors": [],
            "graph_adapters": [], "ui_panels": [],
        },
        "permissions": {
            "network": "none", "filesystem": "plugin_project_root_only",
            "formal_evidence_write": "forbidden", "review_queue_write": "forbidden",
        },
        "data_packs": [],
        "boundaries": ["插件输出是候选；不得绕过问津来源、证据和写作审批。"],
    }
    (root / "wenjin-plugin.json").write_text(json.dumps(wenjin, ensure_ascii=False, indent=2), encoding="utf-8")
    codex = {
        "name": name, "version": "0.1.0", "description": description,
        "author": {"name": "Plugin developer"}, "skills": "./skills/", "mcpServers": "./.mcp.json",
        "interface": {
            "displayName": display_name, "shortDescription": description[:100],
            "longDescription": description, "developerName": "Plugin developer",
            "category": "Research", "capabilities": ["Local", "MCP"],
            "defaultPrompt": [f"检查{display_name}插件状态。"],
        },
    }
    (root / ".codex-plugin" / "plugin.json").write_text(json.dumps(codex, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / ".mcp.json").write_text(json.dumps({
        "mcpServers": {name: {"command": f"{name}-mcp", "args": []}},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "skills" / name / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {display_name}\n\n"
        "只在用户明确调用本领域能力时使用。插件结果保持候选状态，正式证据仍回到问津原页和人工审批。\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        "[build-system]\nrequires = [\"setuptools>=68\"]\nbuild-backend = \"setuptools.build_meta\"\n\n"
        f"[project]\nname = \"{name}\"\nversion = \"0.1.0\"\ndescription = \"{description}\"\n"
        "requires-python = \">=3.11\"\ndependencies = [\"mcp>=1.10,<2\"]\n\n"
        f"[project.scripts]\n{name}-mcp = \"{module}.mcp_server:main\"\n\n"
        "[tool.setuptools.packages.find]\nwhere = [\"src\"]\n",
        encoding="utf-8",
    )
    (root / "src" / module / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    (root / "src" / module / "mcp_server.py").write_text(
        "from mcp.server.fastmcp import FastMCP\nfrom mcp.types import ToolAnnotations\n\n"
        f"server = FastMCP(\"{name}\")\nreadonly = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)\n\n"
        "@server.tool(annotations=readonly)\ndef plugin_status() -> dict:\n"
        f"    return {{\"name\": \"{name}\", \"version\": \"0.1.0\", \"status\": \"ready\"}}\n\n"
        "def main() -> None:\n    server.run(transport=\"stdio\")\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_manifest.py").write_text(
        "import json\nfrom pathlib import Path\n\ndef test_manifest():\n"
        "    root=Path(__file__).parents[1]\n    data=json.loads((root/'wenjin-plugin.json').read_text(encoding='utf-8'))\n"
        f"    assert data['name']=='{name}'\n    assert data['runtime']['type']=='mcp_stdio'\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        f"# {display_name}\n\n{description}\n\n"
        "This Wenjin domain-pack engineering scaffold contains a versioned manifest, one Skill, "
        "an MCP stdio runtime, permission declarations, contribution slots, local-data slots, "
        "and a manifest test. Replace the sample status tool with bounded domain tools; keep "
        "formal evidence and manuscript writes behind Wenjin approvals.\n\n"
        "## Develop\n\n```powershell\npython -m pip install -e .\npytest\n"
        f"{name}-mcp\n```\n",
        encoding="utf-8",
    )
    validation = validate_domain_plugin(root)
    return {"plugin_root": str(root), **validation}
