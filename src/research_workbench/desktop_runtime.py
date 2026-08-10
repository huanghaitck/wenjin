from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .model_settings import apply_settings
from .service import initialize_project
from .web import serve
from .workspace import initialize_workspace


def bootstrap_desktop(data_root: Path) -> dict[str, Any]:
    data_root = data_root.expanduser().resolve()
    workspace_root = data_root / "workspace"
    library_root = data_root / "library"
    config_root = data_root / "config"
    logs_root = data_root / "logs"
    for path in (workspace_root, library_root, config_root, logs_root):
        path.mkdir(parents=True, exist_ok=True)
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
    initialize_workspace(workspace_root, project_root)
    apply_settings(config_root)
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
