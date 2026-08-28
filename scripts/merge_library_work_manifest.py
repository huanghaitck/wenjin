from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

from research_workbench.library import _add_tag, _refresh_search, _sync_work_graph
from research_workbench.library_store import connect_library, library_database_path


def _delete_empty_work(connection, work_id: str) -> None:
    if connection.execute("SELECT 1 FROM library_files WHERE work_id=?", (work_id,)).fetchone():
        return
    if connection.execute("SELECT 1 FROM library_project_links WHERE work_id=?", (work_id,)).fetchone():
        raise ValueError(f"cannot remove project-linked work: {work_id}")
    node = connection.execute("SELECT node_id FROM knowledge_nodes WHERE node_type='work' AND normalized_label=?", (work_id.casefold(),)).fetchone()
    if node:
        connection.execute("DELETE FROM knowledge_edges WHERE source_node_id=? OR target_node_id=?", (node["node_id"], node["node_id"]))
        connection.execute("DELETE FROM knowledge_nodes WHERE node_id=?", (node["node_id"],))
    connection.execute("DELETE FROM knowledge_edges WHERE work_id=?", (work_id,))
    connection.execute("DELETE FROM work_tags WHERE work_id=?", (work_id,))
    connection.execute("DELETE FROM work_search WHERE work_id=?", (work_id,))
    connection.execute("DELETE FROM editions WHERE work_id=?", (work_id,))
    connection.execute("DELETE FROM works WHERE work_id=?", (work_id,))


def apply_manifest(root: Path, manifest_path: Path, apply: bool = False) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    receipt = {"apply": apply, "groups": manifest.get("groups", []), "source_files_deleted": False}
    if not apply:
        return receipt
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = root / f"library-before-work-manifest-{stamp}.sqlite3"
    shutil.copy2(library_database_path(root), backup); receipt["backup"] = str(backup)
    with connect_library(root) as connection:
        for group in manifest.get("groups", []):
            target = group["target_work_id"]
            if not connection.execute("SELECT 1 FROM works WHERE work_id=?", (target,)).fetchone():
                raise KeyError(f"unknown target work: {target}")
            touched = {target}
            for member in group.get("members", []):
                row = connection.execute("SELECT file_id,edition_id,work_id FROM library_files WHERE path=?", (member["path"],)).fetchone()
                if not row:
                    raise KeyError(f"unregistered file: {member['path']}")
                if row["work_id"] != target and connection.execute("SELECT 1 FROM library_project_links WHERE work_id=?", (row["work_id"],)).fetchone():
                    raise ValueError(f"source work is linked to a project: {row['work_id']}")
                connection.execute("UPDATE editions SET work_id=?,edition_label=? WHERE edition_id=?", (target, member.get("edition_label", "待核版本"), row["edition_id"]))
                connection.execute("UPDATE library_files SET work_id=? WHERE file_id=?", (target, row["file_id"]))
                touched.add(row["work_id"])
            for path in group.get("remove_paths", []):
                row = connection.execute("SELECT file_id,edition_id,work_id FROM library_files WHERE path=?", (path,)).fetchone()
                if not row:
                    continue
                if connection.execute("SELECT 1 FROM library_project_links WHERE work_id=?", (row["work_id"],)).fetchone():
                    raise ValueError(f"cannot remove project-linked file: {path}")
                connection.execute("DELETE FROM file_versions WHERE file_id=?", (row["file_id"],))
                connection.execute("DELETE FROM library_files WHERE file_id=?", (row["file_id"],))
                if not connection.execute("SELECT 1 FROM library_files WHERE edition_id=?", (row["edition_id"],)).fetchone():
                    connection.execute("DELETE FROM editions WHERE edition_id=?", (row["edition_id"],))
                touched.add(row["work_id"])
            connection.execute(
                "UPDATE works SET canonical_title=?,author=?,material_type=?,updated_at=datetime('now') WHERE work_id=?",
                (group["canonical_title"], group.get("author", ""), group.get("material_type", "book_or_document"), target),
            )
            connection.execute(
                "DELETE FROM work_tags WHERE work_id=? AND tag_id IN (SELECT tag_id FROM tags WHERE name LIKE 'shelf:%' OR name LIKE 'material:%')",
                (target,),
            )
            _add_tag(connection, target, f"material:{group.get('material_type', 'book_or_document')}", "system")
            if group.get("shelf"):
                _add_tag(connection, target, f"shelf:{group['shelf']}", "system")
            for work_id in touched:
                if work_id != target:
                    _delete_empty_work(connection, work_id)
            _refresh_search(connection, target); _sync_work_graph(connection, target)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply a reviewed work/version relationship manifest without changing source files.")
    parser.add_argument("library_root", type=Path); parser.add_argument("manifest", type=Path)
    parser.add_argument("--apply", action="store_true"); args = parser.parse_args()
    print(json.dumps(apply_manifest(args.library_root.resolve(), args.manifest.resolve(), args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
