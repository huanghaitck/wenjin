from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_signature(project_root: Path, database: Path) -> str:
    values = []
    for path in sorted(project_root.rglob("*")):
        if not path.is_file() or path == database or path.name in {
            database.name + "-wal", database.name + "-shm",
        }:
            continue
        relative = path.relative_to(project_root)
        if relative.parts and relative.parts[0] in {"logs", "tmp"}:
            continue
        stat = path.stat()
        values.append(f"{relative.as_posix()}:{stat.st_size}:{stat.st_mtime_ns}")
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()


def _project_identity(database: Path) -> tuple[str, str]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        row = connection.execute("SELECT project_id, title FROM projects LIMIT 1").fetchone()
    finally:
        connection.close()
    if not row:
        raise ValueError(f"project database has no project identity: {database}")
    return str(row[0]), str(row[1])


def _manifest(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, list) else []


def _write_manifest(path: Path, value: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def backup_project(project_root: Path, backup_root: Path, reason: str = "manual") -> dict[str, Any]:
    project_root, backup_root = project_root.resolve(), backup_root.resolve()
    database = project_root / "project.sqlite3"
    if not database.is_file():
        raise FileNotFoundError(f"project database is missing: {database}")
    project_id, title = _project_identity(database)
    destination_root = backup_root / "projects" / project_id
    manifest_path = destination_root / "manifest.json"
    entries = _manifest(manifest_path)
    signature = _source_signature(project_root, database)
    backup_id = f"BKP_{uuid.uuid4().hex}"
    target = destination_root / f"{_stamp()}-{backup_id}.sqlite3"
    target.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(database)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()
    check = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    if integrity != "ok":
        target.unlink(missing_ok=True)
        raise RuntimeError(f"backup integrity check failed: {integrity}")
    database_hash = _sha256(target)
    if entries and entries[-1].get("database_sha256") == database_hash and entries[-1].get("source_signature") == signature:
        target.unlink(missing_ok=True)
        return {**entries[-1], "status": "unchanged"}
    archive = target.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(target, "project.sqlite3")
        for source in sorted(project_root.rglob("*")):
            if not source.is_file() or source == database or source.name in {
                database.name + "-wal", database.name + "-shm",
            }:
                continue
            relative = source.relative_to(project_root)
            if relative.parts and relative.parts[0] in {"logs", "tmp"}:
                continue
            bundle.write(source, relative.as_posix())
    yaml_source = project_root / "project.yaml"
    yaml_target = target.with_suffix(".yaml")
    if yaml_source.is_file():
        shutil.copy2(yaml_source, yaml_target)
    entry = {
        "backup_id": backup_id, "project_id": project_id, "title": title,
        "source_project_root": str(project_root), "source_signature": signature,
        "database_path": str(target), "database_sha256": database_hash,
        "database_bytes": target.stat().st_size, "project_yaml_path": str(yaml_target) if yaml_target.is_file() else "",
        "project_archive_path": str(archive), "project_archive_sha256": _sha256(archive),
        "project_archive_bytes": archive.stat().st_size,
        "reason": reason, "created_at": _now(), "status": "created",
    }
    entries.append(entry)
    _write_manifest(manifest_path, entries)
    return entry


def backup_existing_projects(data_root: Path, reason: str = "startup") -> dict[str, Any]:
    data_root = data_root.resolve()
    projects_root, backup_root = data_root / "workspace" / "projects", data_root / "backups"
    receipts, failures = [], []
    candidates: dict[str, Path] = {}
    if projects_root.is_dir():
        for project in sorted(projects_root.iterdir()):
            if (project / "project.sqlite3").is_file():
                candidates[str(project.resolve())] = project.resolve()
    registry = data_root / "workspace" / "workspace.json"
    if registry.is_file():
        try:
            registered = json.loads(registry.read_text(encoding="utf-8")).get("projects", [])
            for item in registered:
                project = Path(str(item.get("path", ""))).expanduser().resolve()
                if (project / "project.sqlite3").is_file():
                    candidates[str(project)] = project
        except (json.JSONDecodeError, OSError, TypeError):
            failures.append({"project_root": str(registry), "error": "workspace registry could not be read"})
    for project in sorted(candidates.values(), key=lambda value: str(value).lower()):
        try:
            receipts.append(backup_project(project, backup_root, reason))
        except Exception as error:
            failures.append({"project_root": str(project), "error": str(error)})
    return {"receipts": receipts, "failures": failures, "backup_root": str(backup_root)}


def list_backups(backup_root: Path) -> list[dict[str, Any]]:
    root = backup_root.resolve() / "projects"
    entries: list[dict[str, Any]] = []
    if root.is_dir():
        for manifest in root.glob("*/manifest.json"):
            entries.extend(_manifest(manifest))
    return sorted(entries, key=lambda item: item.get("created_at", ""), reverse=True)


def restore_backup(backup_root: Path, workspace_root: Path, backup_id: str) -> dict[str, Any]:
    matches = [item for item in list_backups(backup_root) if item.get("backup_id") == backup_id]
    if not matches:
        raise KeyError(f"unknown backup: {backup_id}")
    item = matches[0]
    source = Path(item["database_path"]).resolve()
    if not source.is_file() or _sha256(source) != item["database_sha256"]:
        raise RuntimeError("backup file is missing or no longer matches its receipt")
    slug = "restored-" + re_safe_slug(str(item.get("title", "project")))
    destination = workspace_root.resolve() / "projects" / f"{slug}-{uuid.uuid4().hex[:8]}"
    destination.mkdir(parents=True, exist_ok=False)
    archive_value = str(item.get("project_archive_path", ""))
    archive = Path(archive_value).resolve() if archive_value else None
    if archive and archive.is_file() and _sha256(archive) == item.get("project_archive_sha256"):
        with zipfile.ZipFile(archive) as bundle:
            destination_root = destination.resolve()
            for member in bundle.infolist():
                target = (destination / member.filename).resolve()
                if target != destination_root and destination_root not in target.parents:
                    raise RuntimeError("backup archive contains an unsafe path")
            bundle.extractall(destination)
    else:
        shutil.copy2(source, destination / "project.sqlite3")
    yaml_source = Path(str(item.get("project_yaml_path", "")))
    if yaml_source.is_file():
        shutil.copy2(yaml_source, destination / "project.yaml")
    return {"backup_id": backup_id, "restored_project_root": str(destination), "status": "restored_copy"}


def re_safe_slug(value: str) -> str:
    import re
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", value).strip("-")[:40] or "project"
