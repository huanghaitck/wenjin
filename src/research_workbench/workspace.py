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


def _deduplicate_projects(projects: list[dict[str, Any]], current_project: str = "") -> list[dict[str, Any]]:
    """Keep one registry entry per project identity, preferring an available/current path."""
    selected: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    current_resolved = str(Path(current_project).resolve()) if current_project else ""
    for item in projects:
        project_id = str(item.get("project_id", ""))
        key = project_id or str(Path(item["path"]).resolve())
        candidate_path = str(Path(item["path"]).resolve())
        candidate_available = (Path(candidate_path) / "project.sqlite3").is_file()
        existing = selected.get(key)
        if existing is None:
            selected[key] = {**item, "path": candidate_path}
            order.append(key)
            continue
        existing_path = str(Path(existing["path"]).resolve())
        existing_available = (Path(existing_path) / "project.sqlite3").is_file()
        if candidate_path == current_resolved or (candidate_available and not existing_available):
            selected[key] = {**item, "path": candidate_path}
    return [selected[key] for key in order]


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
    projects_root = workspace_root / "projects"
    if projects_root.is_dir():
        known_paths = {str(Path(item["path"]).resolve()) for item in registry["projects"]}
        for candidate in sorted(projects_root.iterdir()):
            if not candidate.is_dir() or not (candidate / "project.sqlite3").is_file():
                continue
            candidate_path = str(candidate.resolve())
            if candidate_path in known_paths:
                continue
            status = project_status(candidate)
            registry["projects"].append({
                "project_id": status["project_id"], "title": status["title"], "path": candidate_path,
            })
            known_paths.add(candidate_path)
    current = Path(registry.get("current_project", ""))
    if not registry.get("current_project") or not (current / "project.sqlite3").is_file():
        registry["current_project"] = resolved
    current = Path(registry["current_project"])
    if current.name == "default-research-project":
        current_status = project_status(current)
        recovered = []
        for item in registry["projects"]:
            root = Path(item["path"])
            if root == current or not (root / "project.sqlite3").is_file():
                continue
            status = project_status(root)
            if status["source_count"] > 0:
                recovered.append((status["source_count"], root.stat().st_mtime, str(root.resolve())))
        if current_status["source_count"] == 0 and recovered:
            registry["current_project"] = max(recovered)[2]
    registry["projects"] = _deduplicate_projects(
        registry["projects"], registry.get("current_project", "")
    )
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


def create_workspace_project(workspace_root: Path, title: str, parent_root: Path | None = None) -> dict[str, Any]:
    title = title.strip()
    if not title:
        raise ValueError("project title is required")
    workspace_root = workspace_root.resolve()
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", title).strip("-")[:40] or "project"
    parent = parent_root.expanduser().resolve() if parent_root else workspace_root / "projects"
    if parent_root and not parent.is_dir():
        raise FileNotFoundError(f"selected project parent folder does not exist: {parent}")
    parent.mkdir(parents=True, exist_ok=True)
    project_root = parent / f"{slug}-{uuid.uuid4().hex[:8]}"
    created = initialize_project(project_root, title)
    registry_path = workspace_root / REGISTRY
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["projects"].append({
        "project_id": created["project_id"], "title": title, "path": str(project_root),
    })
    registry["current_project"] = str(project_root)
    _write(registry_path, registry)
    return {**created, "workspace": workspace_view(workspace_root)}


def register_workspace_project(workspace_root: Path, project_root: Path) -> dict[str, Any]:
    workspace_root = workspace_root.resolve()
    project_root = project_root.expanduser().resolve()
    if not (project_root / "project.sqlite3").is_file():
        raise FileNotFoundError("selected folder is not a Wenjin project")
    status = project_status(project_root)
    registry_path = workspace_root / REGISTRY
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    resolved = str(project_root)
    registry["projects"] = [
        item for item in registry["projects"] if item["project_id"] != status["project_id"]
    ]
    registry["projects"].append({
        "project_id": status["project_id"], "title": status["title"], "path": resolved,
    })
    registry["current_project"] = resolved
    _write(registry_path, registry)
    return {**status, "project_root": resolved, "workspace": workspace_view(workspace_root)}


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
