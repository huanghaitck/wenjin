from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from .backups import backup_project
from .domain_plugins import plugin_state, repair_domain_plugin

if os.name == "nt":
    from .computer_use_mcp import runtime_status
else:
    def runtime_status() -> dict[str, Any]:
        return {
            "desktop_pack": {"installed": False, "status": "not_applicable"},
            "boundary": "Windows Computer Use is not available on this platform.",
        }


def _database_integrity(path: Path) -> str:
    if not path.is_file():
        return "missing"
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()


def diagnose_system(project_root: Path, config_root: Path) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    project_integrity = _database_integrity(project_root / "project.sqlite3")
    if project_integrity != "ok":
        issues.append({"component": "project_database", "status": project_integrity, "repair": "restore_backup"})
    try:
        plugins = plugin_state(config_root)
        for plugin in plugins.get("plugins", []):
            if plugin.get("status") != "ready" or plugin.get("package_changed"):
                issues.append({
                    "component": f"plugin:{plugin.get('name')}",
                    "status": "package_changed" if plugin.get("package_changed") else str(plugin.get("status")),
                    "repair": "reinstall_from_recorded_source",
                })
    except Exception as error:
        plugins = {"count": 0, "plugins": [], "error": str(error)}
        issues.append({"component": "plugins", "status": "invalid_manifest_or_receipt", "repair": "reimport_verified_package"})
    runtimes = runtime_status()
    return {
        "status": "ok" if not issues else "attention_required",
        "build_id": os.getenv("HRW_DESKTOP_BUILD", "development"),
        "project_database": {"status": project_integrity},
        "plugins": plugins,
        "optional_runtimes": runtimes,
        "issues": issues,
        "boundary": "Diagnosis is read-only. Safe repair never changes research rules, source files, credentials, or existing candidate outputs.",
    }


def repair_system(project_root: Path, config_root: Path) -> dict[str, Any]:
    before = diagnose_system(project_root, config_root)
    backup = backup_project(project_root, config_root.parent / "backups", "system_repair")
    repaired: list[str] = []
    for plugin in before.get("plugins", {}).get("plugins", []):
        if plugin.get("status") == "ready" and not plugin.get("package_changed"):
            continue
        source = Path(str(plugin.get("source_path") or ""))
        if source.exists():
            repair_domain_plugin(config_root, str(plugin["name"]))
            repaired.append(str(plugin["name"]))
    after = diagnose_system(project_root, config_root)
    return {
        "status": "repaired" if repaired else "no_safe_change",
        "backup_id": backup.get("backup_id"),
        "repaired_plugins": repaired,
        "remaining_issues": after["issues"],
        "boundary": "Optional runtime installation, database restoration, and package reimport still require a separate explicit decision.",
    }
