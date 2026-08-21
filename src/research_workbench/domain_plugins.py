from __future__ import annotations

import hashlib
import asyncio
import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any


PLUGIN_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def _registry_path(config_root: Path) -> Path:
    return config_root.resolve() / "plugins" / "registry.json"


def _load_registry(config_root: Path) -> dict[str, Any]:
    path = _registry_path(config_root)
    if not path.is_file():
        return {"schema_version": 1, "plugins": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1 or not isinstance(value.get("plugins"), list):
        raise ValueError("unsupported Wenjin plugin registry")
    return value


def _save_registry(config_root: Path, value: dict[str, Any]) -> None:
    path = _registry_path(config_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _manifest(plugin_root: Path) -> tuple[dict[str, Any], str]:
    root = plugin_root.resolve()
    path = root / "wenjin-plugin.json"
    if not path.is_file():
        raise FileNotFoundError(f"Wenjin plugin manifest is missing: {path}")
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    required = {"schema_version", "name", "version", "display_name", "description", "kind", "runtime"}
    missing = sorted(required - set(value))
    if missing:
        raise ValueError("Wenjin plugin manifest is missing: " + ", ".join(missing))
    if value["schema_version"] != 1:
        raise ValueError("unsupported Wenjin plugin schema")
    if not PLUGIN_NAME.fullmatch(str(value["name"])):
        raise ValueError("plugin name must be lower-case hyphen-case")
    if not SEMVER.fullmatch(str(value["version"])):
        raise ValueError("plugin version must use semantic versioning")
    runtime = value["runtime"]
    if not isinstance(runtime, dict) or runtime.get("type") != "mcp_stdio" or not runtime.get("command"):
        raise ValueError("0.1.1 plugins require an mcp_stdio runtime command")
    for relative in value.get("skills", []):
        candidate = (root / relative).resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise ValueError(f"plugin skill escapes the package or is missing: {relative}")
    inputs = value.get("local_data_sources", [])
    if not isinstance(inputs, list):
        raise ValueError("local_data_sources must be a list")
    seen_inputs: set[str] = set()
    for item in inputs:
        if not isinstance(item, dict) or not PLUGIN_NAME.fullmatch(str(item.get("id", ""))):
            raise ValueError("local data source ids must use lower-case hyphen-case")
        if item["id"] in seen_inputs:
            raise ValueError(f"duplicate local data source id: {item['id']}")
        seen_inputs.add(item["id"])
        if item.get("kind", "file") not in {"file", "directory"}:
            raise ValueError("local data source kind must be file or directory")
        extensions = item.get("extensions", [])
        if not isinstance(extensions, list) or any(
            not isinstance(extension, str) or not extension.startswith(".") for extension in extensions
        ):
            raise ValueError("local data source extensions must be a list of dotted suffixes")
    contributions = value.get("contributions", {})
    if not isinstance(contributions, dict):
        raise ValueError("plugin contributions must be an object")
    for key in ("methods", "schemas", "processors", "graph_adapters", "ui_panels"):
        entries = contributions.get(key, [])
        if not isinstance(entries, list) or any(not isinstance(entry, str) for entry in entries):
            raise ValueError(f"plugin contribution {key} must be a list of strings")
    return value, hashlib.sha256(raw).hexdigest()


def validate_domain_plugin(plugin_root: Path) -> dict[str, Any]:
    value, digest = _manifest(plugin_root)
    return {"manifest": value, "manifest_sha256": digest, "status": "valid"}


def _command_available(command: str) -> bool:
    path = Path(command)
    return path.is_file() if path.is_absolute() else bool(shutil.which(command))


def _runtime_command(root: Path, runtime: dict[str, Any], override: str = "") -> str:
    if override:
        return override
    command = str(runtime["command"])
    path = Path(command)
    if not path.is_absolute() and ("/" in command or "\\" in command):
        return str((root / path).resolve())
    return command


def plugin_state(config_root: Path) -> dict[str, Any]:
    registry = _load_registry(config_root)
    plugins = []
    for item in registry["plugins"]:
        root = Path(item["installed_path"])
        try:
            manifest, current_hash = _manifest(root)
            runtime_command = _runtime_command(root, manifest["runtime"], str(item.get("runtime_command") or ""))
            source_path = Path(item.get("source_path") or root)
            runtime_base = root if manifest["runtime"].get("self_contained") else source_path
            runtime_cwd = runtime_base
            if manifest["runtime"].get("cwd"):
                runtime_cwd = (runtime_base / str(manifest["runtime"]["cwd"])).resolve()
            status = "ready" if _command_available(runtime_command) else "runtime_missing"
            bindings = dict(item.get("data_bindings") or {})
            local_data_sources = []
            for descriptor in manifest.get("local_data_sources", []):
                binding = dict(bindings.get(str(descriptor["id"])) or {})
                bound_path = Path(str(binding.get("path", ""))) if binding.get("path") else None
                local_data_sources.append({
                    **descriptor,
                    "binding": binding,
                    "bound": bool(bound_path and bound_path.exists()),
                    "available": bool(bound_path and bound_path.exists()),
                })
            plugins.append({
                **manifest,
                "installed_path": str(root),
                "manifest_sha256": current_hash,
                "installed_manifest_sha256": item["manifest_sha256"],
                "package_changed": current_hash != item["manifest_sha256"],
                "runtime_command": runtime_command,
                "runtime_args": [str(value) for value in manifest["runtime"].get("args", [])],
                "runtime_cwd": str(runtime_cwd),
                "runtime_available": _command_available(runtime_command),
                "status": status,
                "data_bindings": bindings,
                "local_data_sources": local_data_sources,
            })
        except Exception as error:
            plugins.append({
                "name": item.get("name", "unknown"), "display_name": item.get("name", "unknown"),
                "installed_path": str(root), "status": "invalid", "error": str(error),
                "runtime_available": False, "data_packs": [], "skills": [],
            })
    return {
        "plugins": plugins,
        "count": len(plugins),
        "boundary": (
            "Plugins contribute skills, data-pack metadata and an MCP runtime. They do not receive "
            "direct database write access or bypass Wenjin evidence approvals."
        ),
    }


def find_config_root(project_root: Path) -> Path:
    import os
    configured = os.getenv("WENJIN_CONFIG_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    current = project_root.resolve()
    for parent in (current, *current.parents):
        candidate = parent / "config"
        if (candidate / "plugins" / "registry.json").is_file():
            return candidate.resolve()
    return (project_root.resolve() / ".wenjin" / "config").resolve()


async def _call_mcp(command: str, args: list[str], cwd: str, tool_name: str,
                    arguments: dict[str, Any], data_bindings: dict[str, Any]) -> dict[str, Any]:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as error:  # pragma: no cover - packaging gate reports this.
        raise RuntimeError("Wenjin MCP client dependency is not installed") from error
    environment = dict(os.environ)
    environment["WENJIN_PLUGIN_DATA_BINDINGS"] = json.dumps(
        data_bindings, ensure_ascii=False, sort_keys=True
    )
    parameters = StdioServerParameters(command=command, args=args, cwd=cwd or None, env=environment)
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            if tool_name not in {tool.name for tool in tools.tools}:
                raise KeyError(f"plugin tool is not exposed by the MCP server: {tool_name}")
            result = await session.call_tool(tool_name, arguments)
            return result.model_dump(mode="json")


def call_domain_plugin_tool(
    config_root: Path,
    plugin_name: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    state = plugin_state(config_root)
    plugin = next((item for item in state["plugins"] if item.get("name") == plugin_name), None)
    if plugin is None:
        raise KeyError(f"unknown plugin: {plugin_name}")
    if plugin.get("status") != "ready":
        raise RuntimeError(f"plugin runtime is not ready: {plugin.get('status')}")
    allowed = {str(value) for value in plugin.get("agent_tools", [])}
    if tool_name not in allowed:
        raise ValueError(f"plugin tool is not approved for the main agent: {tool_name}")
    if not isinstance(arguments, dict):
        raise ValueError("plugin tool arguments must be an object")
    return asyncio.run(_call_mcp(
        str(plugin["runtime_command"]), list(plugin.get("runtime_args", [])),
        str(plugin.get("runtime_cwd", "")), tool_name, arguments,
        dict(plugin.get("data_bindings") or {}),
    ))


def install_domain_plugin(
    config_root: Path,
    source_root: Path,
    *,
    runtime_command: str = "",
) -> dict[str, Any]:
    source_root = source_root.resolve()
    if source_root.is_file():
        if source_root.suffix.casefold() != ".zip":
            raise ValueError("plugin package must be a folder or .zip file")
        plugins_root = config_root.resolve() / "plugins"
        plugins_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".incoming-", dir=plugins_root) as directory:
            extracted = Path(directory)
            with zipfile.ZipFile(source_root) as archive:
                for member in archive.infolist():
                    candidate = (extracted / member.filename).resolve()
                    if extracted not in candidate.parents and candidate != extracted:
                        raise ValueError("plugin zip contains a path outside the package root")
                archive.extractall(extracted)
            candidates = [extracted] if (extracted / "wenjin-plugin.json").is_file() else [
                path for path in extracted.iterdir()
                if path.is_dir() and (path / "wenjin-plugin.json").is_file()
            ]
            if len(candidates) != 1:
                raise ValueError("plugin zip must contain exactly one wenjin-plugin.json root")
            return install_domain_plugin(
                config_root, candidates[0], runtime_command=runtime_command,
            )
    manifest, manifest_hash = _manifest(source_root)
    destination = config_root.resolve() / "plugins" / manifest["name"]
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_root, destination)
    copied, copied_hash = _manifest(destination)
    if copied_hash != manifest_hash or copied["name"] != manifest["name"]:
        raise RuntimeError("plugin copy verification failed")
    command = runtime_command.strip()
    registry = _load_registry(config_root)
    existing = next((item for item in registry["plugins"] if item.get("name") == copied["name"]), {})
    registry["plugins"] = [item for item in registry["plugins"] if item.get("name") != copied["name"]]
    registry["plugins"].append({
        "name": copied["name"],
        "version": copied["version"],
        "installed_path": str(destination),
        "source_path": str(source_root),
        "manifest_sha256": copied_hash,
        "runtime_command": command,
        "data_bindings": dict(existing.get("data_bindings") or {}),
    })
    _save_registry(config_root, registry)
    return plugin_state(config_root)


def bind_domain_plugin_data(
    config_root: Path, name: str, source_id: str, local_path: str
) -> dict[str, Any]:
    registry = _load_registry(config_root)
    record = next((item for item in registry["plugins"] if item.get("name") == name), None)
    if record is None:
        raise KeyError(f"unknown plugin: {name}")
    root = Path(record["installed_path"])
    manifest, _digest = _manifest(root)
    descriptor = next(
        (item for item in manifest.get("local_data_sources", []) if item.get("id") == source_id),
        None,
    )
    if descriptor is None:
        raise KeyError(f"plugin does not declare local data source: {source_id}")
    path = Path(local_path).expanduser().resolve()
    kind = str(descriptor.get("kind", "file"))
    if kind == "file" and not path.is_file():
        raise FileNotFoundError(f"local data file is unavailable: {path}")
    if kind == "directory" and not path.is_dir():
        raise FileNotFoundError(f"local data directory is unavailable: {path}")
    extensions = {str(value).casefold() for value in descriptor.get("extensions", [])}
    if kind == "file" and extensions and path.suffix.casefold() not in extensions:
        raise ValueError(
            "local data file type is not accepted; expected " + ", ".join(sorted(extensions))
        )
    identity: dict[str, Any] = {
        "path": str(path), "kind": kind,
        "size": path.stat().st_size if path.is_file() else None,
        "modified_ns": path.stat().st_mtime_ns,
    }
    if path.is_file():
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        identity["sha256"] = digest.hexdigest()
    bindings = dict(record.get("data_bindings") or {})
    bindings[source_id] = identity
    record["data_bindings"] = bindings
    _save_registry(config_root, registry)
    return plugin_state(config_root)


def remove_domain_plugin(config_root: Path, name: str) -> dict[str, Any]:
    if not PLUGIN_NAME.fullmatch(name):
        raise ValueError("invalid plugin name")
    registry = _load_registry(config_root)
    matches = [item for item in registry["plugins"] if item.get("name") == name]
    if not matches:
        raise KeyError(f"unknown plugin: {name}")
    manifest, _digest = _manifest(Path(matches[0]["installed_path"]))
    if manifest.get("kind") == "system":
        raise ValueError("system domain packs cannot be removed")
    destination = (config_root.resolve() / "plugins" / name).resolve()
    if destination.parent != (config_root.resolve() / "plugins"):
        raise ValueError("plugin path escapes config root")
    if destination.is_dir():
        shutil.rmtree(destination)
    registry["plugins"] = [item for item in registry["plugins"] if item.get("name") != name]
    _save_registry(config_root, registry)
    return plugin_state(config_root)
