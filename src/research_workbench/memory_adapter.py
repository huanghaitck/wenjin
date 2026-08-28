from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .db import append_audit, connect, project_id, utc_now


SETTINGS_FILE = "memory-adapters.json"
TARGETS = {"historical", "engineering"}


def _settings_path(config_root: Path) -> Path:
    return config_root.resolve() / SETTINGS_FILE


def memory_settings(config_root: Path) -> dict[str, Any]:
    path = _settings_path(config_root)
    value = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    targets = {}
    for key in TARGETS:
        raw = str(value.get(key, "")).strip()
        root = Path(raw).expanduser().resolve() if raw else None
        targets[key] = {
            "path": str(root) if root else "",
            "available": bool(root and root.is_dir()),
            "writable": bool(root and root.is_dir() and _writable(root)),
        }
    return {
        "targets": targets,
        "boundary": (
            "Only approved_local candidates can be promoted. Promotion writes one draft Markdown "
            "card to the selected local vault inbox and never copies full conversations or source files."
        ),
    }


def _writable(root: Path) -> bool:
    try:
        probe = root / ".wenjin-write-probe"
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def save_memory_settings(config_root: Path, historical: str = "", engineering: str = "") -> dict[str, Any]:
    value: dict[str, str] = {}
    for key, raw in (("historical", historical), ("engineering", engineering)):
        raw = raw.strip()
        if not raw:
            value[key] = ""
            continue
        root = Path(raw).expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"memory vault does not exist: {root}")
        value[key] = str(root)
    path = _settings_path(config_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return memory_settings(config_root)


def _candidate(project_root: Path, candidate_id: str) -> dict[str, Any]:
    with connect(project_root) as connection:
        row = connection.execute(
            "SELECT * FROM memory_candidates WHERE candidate_id = ?", (candidate_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown memory candidate: {candidate_id}")
        project = connection.execute("SELECT project_id, title FROM projects LIMIT 1").fetchone()
    item = dict(row)
    item["source_refs"] = json.loads(item.pop("source_refs_json"))
    item["project_id"], item["project_title"] = project["project_id"], project["title"]
    return item


def promote_memory_candidate(
    project_root: Path, config_root: Path, candidate_id: str, target: str,
) -> dict[str, Any]:
    if target not in TARGETS:
        raise ValueError("memory target must be historical or engineering")
    candidate = _candidate(project_root, candidate_id)
    if candidate["status"] != "approved_local":
        raise ValueError("only approved_local memory candidates can be promoted")
    settings = memory_settings(config_root)
    root_value = settings["targets"][target]
    if not root_value["writable"]:
        raise RuntimeError(f"configured {target} memory vault is unavailable or read-only")
    root = Path(root_value["path"])
    inbox = root / "90_INBOX"
    inbox.mkdir(parents=True, exist_ok=True)
    destination = inbox / f"WENJIN-{candidate_id}.md"
    source_lines = "\n".join(f'  - "{str(value).replace(chr(34), chr(39))}"' for value in candidate["source_refs"])
    text = (
        "---\n"
        f'id: "WENJIN-{candidate_id}"\n'
        f'title: "问津候选：{candidate["category"].replace(chr(34), chr(39))}"\n'
        'note_type: "memory_candidate"\n'
        'status: "draft"\n'
        f'target_memory: "{target}"\n'
        f'project_id: "{candidate["project_id"]}"\n'
        f'created: "{candidate.get("decided_at") or candidate["created_at"]}"\n'
        "source_refs:\n" + source_lines + "\n"
        "---\n\n"
        f"# {candidate['category']}\n\n{candidate['content'].strip()}\n\n"
        "## 来源回链\n\n"
        f"- 问津项目：{candidate['project_title']}（{candidate['project_id']}）\n"
        + "\n".join(f"- {value}" for value in candidate["source_refs"]) + "\n"
    )
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if destination.is_file():
        existing = hashlib.sha256(destination.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        if existing != digest:
            raise RuntimeError("memory destination already exists with different content")
        status = "already_promoted"
    else:
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(destination)
        status = "promoted"
    receipt = {
        "candidate_id": candidate_id, "target": target, "status": status,
        "path": str(destination), "sha256": digest, "promoted_at": utc_now(),
    }
    with connect(project_root) as connection:
        append_audit(connection, "memory_candidate_promoted", "memory_candidate", candidate_id, receipt)
    return receipt


def memory_promotion_receipts(project_root: Path) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        rows = connection.execute(
            """SELECT payload_json, created_at FROM audit_events
               WHERE event_type = 'memory_candidate_promoted'
               ORDER BY created_at DESC"""
        ).fetchall()
    result = []
    for row in rows:
        item = json.loads(row["payload_json"])
        item["audit_created_at"] = row["created_at"]
        result.append(item)
    return result
