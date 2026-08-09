from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from .service import initialize_project, project_status


REGISTRY = "workspace.json"


def _write(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def initialize_workspace(workspace_root: Path, project_root: Path) -> dict[str, Any]:
    workspace_root = workspace_root.resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    path = workspace_root / REGISTRY
    if path.is_file():
        registry = json.loads(path.read_text(encoding="utf-8"))
    else:
        registry = {"schema_version": 1, "current_project": "", "projects": []}
    resolved = str(project_root.resolve())
    if not any(item["path"] == resolved for item in registry["projects"]):
        status = project_status(project_root)
        registry["projects"].append({
            "project_id": status["project_id"], "title": status["title"], "path": resolved,
        })
    current = Path(registry.get("current_project", ""))
    if not registry.get("current_project") or not (current / "project.sqlite3").is_file():
        registry["current_project"] = resolved
    _write(path, registry)
    return registry


def workspace_view(workspace_root: Path) -> dict[str, Any]:
    path = workspace_root.resolve() / REGISTRY
    if not path.is_file():
        raise FileNotFoundError(f"workspace registry does not exist: {path}")
    registry = json.loads(path.read_text(encoding="utf-8"))
    projects = []
    for item in registry["projects"]:
        root = Path(item["path"])
        if (root / "project.sqlite3").is_file():
            status = project_status(root)
            projects.append({**item, "available": True, "source_count": status["source_count"]})
        else:
            projects.append({**item, "available": False, "source_count": 0})
    return {**registry, "projects": projects}


def create_workspace_project(workspace_root: Path, title: str) -> dict[str, Any]:
    title = title.strip()
    if not title:
        raise ValueError("project title is required")
    workspace_root = workspace_root.resolve()
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", title).strip("-")[:40] or "project"
    project_root = workspace_root / "projects" / f"{slug}-{uuid.uuid4().hex[:8]}"
    created = initialize_project(project_root, title)
    registry_path = workspace_root / REGISTRY
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["projects"].append({
        "project_id": created["project_id"], "title": title, "path": str(project_root),
    })
    registry["current_project"] = str(project_root)
    _write(registry_path, registry)
    return {**created, "workspace": workspace_view(workspace_root)}


def select_workspace_project(workspace_root: Path, project_id: str) -> Path:
    path = workspace_root.resolve() / REGISTRY
    registry = json.loads(path.read_text(encoding="utf-8"))
    match = next((item for item in registry["projects"] if item["project_id"] == project_id), None)
    if match is None:
        raise KeyError(f"unknown workspace project: {project_id}")
    root = Path(match["path"])
    if not (root / "project.sqlite3").is_file():
        raise FileNotFoundError(f"project is unavailable: {root}")
    registry["current_project"] = str(root)
    _write(path, registry)
    return root
