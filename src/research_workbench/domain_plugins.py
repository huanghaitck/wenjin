from __future__ import annotations

import hashlib
import asyncio
from functools import lru_cache
import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Awaitable, Callable

from .credential_store import delete_credential, read_credential, save_credential
from .model_settings import PROVIDER_PRESETS, PROVIDERS, discover_models, public_settings, reasoning_controls


PLUGIN_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
DOMAIN_MODEL_SETTINGS_FILE = "domain-model-settings.json"
DOMAIN_ROLE_FALLBACKS = {
    "domain_reasoning": "domain_agent", "vision_primary": "vision_ocr",
    "vision_secondary": "vision_secondary", "review_fallback": "review_secondary",
}


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


def _domain_model_path(config_root: Path) -> Path:
    return config_root.resolve() / DOMAIN_MODEL_SETTINGS_FILE


def _load_domain_models(config_root: Path) -> dict[str, Any]:
    path = _domain_model_path(config_root)
    if not path.is_file():
        return {"schema_version": 1, "plugins": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1 or not isinstance(value.get("plugins"), dict):
        raise ValueError("unsupported domain model settings")
    return value


def _save_domain_models(config_root: Path, value: dict[str, Any]) -> None:
    path = _domain_model_path(config_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _domain_credential_target(plugin_name: str, role_id: str) -> str:
    return f"Wenjin/DomainAgent/{plugin_name}/{role_id}"


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
            runtime_args = [str(value) for value in manifest["runtime"].get("args", [])]
            if Path(runtime_command).name.casefold() in {"python", "python.exe"}:
                module = str(manifest["runtime"].get("python_module") or "")
                if module:
                    runtime_args = ["-m", module, *runtime_args]
                elif manifest.get("name") == "computer-use":
                    runtime_args = ["-m", "research_workbench", *runtime_args]
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
                "runtime_args": runtime_args,
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


def public_domain_model_settings(config_root: Path, plugin_name: str) -> dict[str, Any]:
    plugin = next((item for item in plugin_state(config_root)["plugins"] if item.get("name") == plugin_name), None)
    if plugin is None:
        raise KeyError(f"unknown plugin: {plugin_name}")
    saved = _load_domain_models(config_root).get("plugins", {}).get(plugin_name, {})
    global_roles = {item["role"]: item for item in public_settings(config_root)["roles"]}
    roles = []
    for declaration in plugin.get("model_roles", []):
        role_id = str(declaration.get("id", ""))
        item = dict(saved.get(role_id) or {})
        provider = str(item.get("provider", "inherit"))
        fallback = global_roles.get(DOMAIN_ROLE_FALLBACKS.get(role_id, ""), {})
        if fallback.get("provider") == "auto":
            fallback = global_roles.get("main_reasoning", fallback)
        inherited = provider == "inherit"
        roles.append({
            **declaration, "provider": provider,
            "model": str(item.get("model", "")), "base_url": str(item.get("base_url", "")),
            "timeout_seconds": int(item.get("timeout_seconds", 90)),
            "preset_id": str(item.get("preset_id", "custom")),
            "has_secret": bool(read_credential(_domain_credential_target(plugin_name, role_id))) if not inherited else bool(fallback.get("has_secret")),
            "effective_provider": str(fallback.get("provider", "disabled")) if inherited else provider,
            "effective_model": str(fallback.get("model", "")) if inherited else str(item.get("model", "")),
            "effective_base_url": str(fallback.get("base_url", "")) if inherited else str(item.get("base_url", "")),
            "inherited_from": DOMAIN_ROLE_FALLBACKS.get(role_id, "") if inherited else "",
            "reasoning_controls": reasoning_controls(
                str(fallback.get("provider", "disabled")) if inherited else provider,
                str(fallback.get("model", "")) if inherited else str(item.get("model", "")),
                str(fallback.get("base_url", "")) if inherited else str(item.get("base_url", "")),
            ),
        })
    return {"plugin_name": plugin_name, "roles": roles, "provider_presets": PROVIDER_PRESETS}


def save_domain_model_role(config_root: Path, plugin_name: str, role_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    current = public_domain_model_settings(config_root, plugin_name)
    declaration = next((item for item in current["roles"] if item.get("id") == role_id), None)
    if declaration is None:
        raise KeyError(f"unknown domain model role: {role_id}")
    provider = str(payload.get("provider", "inherit")).strip().lower()
    if provider not in {*PROVIDERS, "inherit"} - {"auto"}:
        raise ValueError("unsupported domain model provider")
    model = str(payload.get("model", "")).strip()
    base_url = str(payload.get("base_url", "")).strip().rstrip("/")
    timeout = int(payload.get("timeout_seconds", 90))
    if provider not in {"inherit", "disabled"} and (not model or not base_url):
        raise ValueError("model and Base URL are required")
    if declaration.get("required") and provider == "disabled":
        raise ValueError("a required domain model role cannot be disabled")
    if not 5 <= timeout <= 600:
        raise ValueError("timeout_seconds must be between 5 and 600")
    target = _domain_credential_target(plugin_name, role_id)
    secret = str(payload.get("api_key", ""))
    if secret:
        save_credential(target, secret, f"Wenjin domain agent: {plugin_name}/{role_id}")
    if payload.get("clear_secret"):
        delete_credential(target)
    settings = _load_domain_models(config_root)
    plugin_settings = settings["plugins"].setdefault(plugin_name, {})
    plugin_settings[role_id] = {
        "provider": provider, "model": model, "base_url": base_url,
        "timeout_seconds": timeout, "preset_id": str(payload.get("preset_id", "custom")),
    }
    _save_domain_models(config_root, settings)
    _cached_mcp_tool_specs.cache_clear()
    return public_domain_model_settings(config_root, plugin_name)


def discover_domain_models(config_root: Path, plugin_name: str, role_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    settings = public_domain_model_settings(config_root, plugin_name)
    role = next((item for item in settings["roles"] if item.get("id") == role_id), None)
    if role is None:
        raise KeyError(f"unknown domain model role: {role_id}")
    provider = str(payload.get("provider") or role.get("provider", "inherit"))
    if provider == "inherit":
        raise ValueError("inherited roles use the parent Wenjin model list")
    secret = str(payload.get("api_key", "")) or read_credential(_domain_credential_target(plugin_name, role_id))
    return discover_models(
        config_root, DOMAIN_ROLE_FALLBACKS.get(role_id, "domain_agent"), provider,
        str(payload.get("base_url") or role.get("base_url", "")), secret,
    )


def domain_model_override(config_root: Path, plugin_name: str, role_id: str) -> dict[str, Any] | None:
    role = next((item for item in public_domain_model_settings(config_root, plugin_name)["roles"] if item.get("id") == role_id), None)
    if role is None or role.get("provider") == "inherit":
        return None
    return {
        "provider": role.get("provider", "disabled"), "model": role.get("model", ""),
        "base_url": role.get("base_url", ""), "timeout_seconds": role.get("timeout_seconds", 90),
        "api_key": read_credential(_domain_credential_target(plugin_name, role_id)),
        "reasoning_controls": role.get("reasoning_controls", {}),
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


def _plugin_model_environment(config_root: Path | None = None, plugin_name: str = "") -> dict[str, str]:
    environment = dict(os.environ)
    targets = {
        "TEXT_API": "HRW_DOMAIN_MODEL",
        "VISION_API": "HRW_OCR",
        "VISION_QA_API": "HRW_VISION_REVIEW",
        "FALLBACK_API": "HRW_REVIEW",
    }
    for target, source in targets.items():
        for source_suffix, target_suffix in (
            ("BASE_URL", "BASE_URL"), ("API_KEY", "KEY"),
            ("MODEL", "MODEL"), ("CONTEXT_WINDOW", "CONTEXT_WINDOW"),
        ):
            value = environment.get(f"{source}_{source_suffix}", "")
            if value and not environment.get(f"{target}_{target_suffix}"):
                environment[f"{target}_{target_suffix}"] = value
    if config_root is not None and plugin_name:
        settings = public_domain_model_settings(config_root, plugin_name)
        for role in settings["roles"]:
            target = str(role.get("env_prefix") or {
                "domain_reasoning": "TEXT_API", "vision_primary": "VISION_API",
                "vision_secondary": "VISION_QA_API", "review_fallback": "FALLBACK_API",
            }.get(str(role.get("id", "")), ""))
            if not target or role.get("provider") == "inherit":
                continue
            for suffix in ("BASE_URL", "KEY", "MODEL", "CONTEXT_WINDOW"):
                environment.pop(f"{target}_{suffix}", None)
            if role.get("provider") == "disabled":
                continue
            environment[f"{target}_BASE_URL"] = str(role.get("base_url", ""))
            environment[f"{target}_MODEL"] = str(role.get("model", ""))
            secret = read_credential(_domain_credential_target(plugin_name, str(role.get("id", ""))))
            if secret:
                environment[f"{target}_KEY"] = secret
    return environment


async def _call_mcp(
    command: str, args: list[str], cwd: str, tool_name: str,
    arguments: dict[str, Any], data_bindings: dict[str, Any],
    config_root: Path, plugin_name: str,
    progress_callback: Callable[[float, float | None, str | None], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as error:  # pragma: no cover - packaging gate reports this.
        raise RuntimeError("Wenjin MCP client dependency is not installed") from error
    environment = _plugin_model_environment(config_root, plugin_name)
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
            result = await session.call_tool(
                tool_name, arguments, progress_callback=progress_callback
            )
            return result.model_dump(mode="json")


@lru_cache(maxsize=32)
def _cached_mcp_tool_specs(command: str, args: tuple[str, ...], cwd: str, config_root: str, plugin_name: str) -> tuple[dict[str, Any], ...]:
    async def load() -> tuple[dict[str, Any], ...]:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as error:  # pragma: no cover - packaging gate reports this.
            raise RuntimeError("Wenjin MCP client dependency is not installed") from error
        parameters = StdioServerParameters(command=command, args=list(args), cwd=cwd or None, env=_plugin_model_environment(Path(config_root), plugin_name))
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return tuple(tool.model_dump(mode="json", by_alias=True) for tool in tools.tools)
    return asyncio.run(load())


def domain_plugin_tool_specs(config_root: Path, plugin_name: str) -> list[dict[str, Any]]:
    plugin = next(
        (item for item in plugin_state(config_root)["plugins"] if item.get("name") == plugin_name),
        None,
    )
    if plugin is None or plugin.get("status") != "ready":
        return []
    allowed = {str(value) for value in plugin.get("agent_tools", [])}
    return [
        item for item in _cached_mcp_tool_specs(
            str(plugin["runtime_command"]), tuple(plugin.get("runtime_args", [])),
            str(plugin.get("runtime_cwd", "")), str(config_root.resolve()), plugin_name,
        ) if str(item.get("name", "")) in allowed
    ]


def call_domain_plugin_tool(
    config_root: Path,
    plugin_name: str,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    progress_callback: Callable[[float, float | None, str | None], Awaitable[None]] | None = None,
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
        config_root.resolve(), plugin_name,
        progress_callback,
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
    registry = _load_registry(config_root)
    existing = next((item for item in registry["plugins"] if item.get("name") == copied["name"]), {})
    command = runtime_command.strip()
    if not command and not copied.get("runtime", {}).get("self_contained"):
        command = str(existing.get("runtime_command") or "")
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
    settings = _load_domain_models(config_root)
    settings["plugins"].pop(name, None)
    _save_domain_models(config_root, settings)
    for role in manifest.get("model_roles", []):
        delete_credential(_domain_credential_target(name, str(role.get("id", ""))))
    _cached_mcp_tool_specs.cache_clear()
    return plugin_state(config_root)
