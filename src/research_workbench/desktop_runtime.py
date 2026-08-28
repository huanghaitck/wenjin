from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .model_settings import apply_settings
from .agent_runtime import ensure_default_thread
from .service import initialize_project
from .web import serve
from .workspace import initialize_workspace
from .backups import backup_existing_projects
from .domain_plugins import install_domain_plugin, plugin_state
from .weixin_gateway import start_configured_gateway


def install_builtin_computer_use(config_root: Path) -> None:
    source = Path(__file__).resolve().parent / "builtin_plugins" / "computer-use"
    if not source.is_dir():
        return
    installed = next(
        (item for item in plugin_state(config_root)["plugins"] if item.get("name") == "computer-use"),
        None,
    )
    manifest = json.loads((source / "wenjin-plugin.json").read_text(encoding="utf-8"))
    if (
        installed and installed.get("status") == "ready"
        and installed.get("version") == manifest.get("version")
        and not installed.get("package_changed")
    ):
        return
    install_domain_plugin(config_root, source, runtime_command=sys.executable)


_install_builtin_computer_use = install_builtin_computer_use


def bootstrap_desktop(data_root: Path) -> dict[str, Any]:
    data_root = data_root.expanduser().resolve()
    workspace_root = data_root / "workspace"
    library_root = data_root / "library"
    config_root = data_root / "config"
    logs_root = data_root / "logs"
    for path in (workspace_root, library_root, config_root, logs_root):
        path.mkdir(parents=True, exist_ok=True)
    backup_existing_projects(data_root, "desktop_startup")
    project_root: Path | None = None
    registry = workspace_root / "workspace.json"
    if registry.is_file():
        saved = json.loads(registry.read_text(encoding="utf-8"))
        current = Path(str(saved.get("current_project", "")))
        if (current / "project.sqlite3").is_file():
            project_root = current
    if project_root is None:
        project_root = workspace_root / "projects" / "default-research-project"
        if not (project_root / "project.sqlite3").is_file():
            initialize_project(project_root, "我的历史研究")
    registry = initialize_workspace(workspace_root, project_root)
    project_root = Path(registry["current_project"])
    ensure_default_thread(project_root)
    install_builtin_computer_use(config_root)
    apply_settings(config_root)
    start_configured_gateway(config_root, project_root)
    return {
        "data_root": str(data_root), "workspace_root": str(workspace_root),
        "library_root": str(library_root), "config_root": str(config_root),
        "logs_root": str(logs_root), "project_root": str(project_root),
    }


def serve_desktop(data_root: Path, host: str, port: int, desktop_build: str = "development") -> None:
    paths = bootstrap_desktop(data_root)
    os.environ["HRW_DESKTOP_BUILD"] = desktop_build
    serve(
        Path(paths["project_root"]), host, port,
        Path(paths["library_root"]), Path(paths["workspace_root"]),
        Path(paths["config_root"]), True,
    )
