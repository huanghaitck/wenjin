from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

from research_workbench.library import _refresh_search, _sync_work_graph
from research_workbench.library_store import connect_library, library_database_path


def consolidate(root: Path, audit_path: Path, apply: bool = False) -> dict:
    audit = json.loads(audit_path.read_text(encoding="utf-8-sig"))
    safe_groups = [
        group for group in audit.get("groups", [])
        if all(member["jaccard_to_current"] >= 0.95 and member["containment_to_current"] >= 0.98 for member in group["members"])
    ]
    planned = []
    with connect_library(root) as connection:
        for group in safe_groups:
            registered = []
            for member in group["members"]:
                row = connection.execute(
                    """SELECT f.file_id,f.edition_id,f.work_id,f.path,
                              (SELECT COUNT(*) FROM library_project_links l WHERE l.work_id=f.work_id) AS project_links
                       FROM library_files f WHERE f.path=?""",
                    (member["path"],),
                ).fetchone()
                if row:
                    registered.append(dict(row) | {"recommended_current": member["recommended_current"]})
            if len(registered) < 2:
                continue
            keep = next((row for row in registered if row["recommended_current"]), registered[-1])
            removals = [row for row in registered if row["file_id"] != keep["file_id"] and not row["project_links"]]
            if removals:
                planned.append({"keep": keep, "remove": removals})
    receipt = {"apply": apply, "safe_group_count": len(safe_groups), "planned": planned, "source_files_deleted": False}
    if not apply or not planned:
        return receipt
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = root / f"library-before-word-consolidation-{stamp}.sqlite3"
    shutil.copy2(library_database_path(root), backup); receipt["backup"] = str(backup)
    with connect_library(root) as connection:
        touched = set()
        for plan in planned:
            touched.add(plan["keep"]["work_id"])
            for row in plan["remove"]:
                loser = row["work_id"]
                connection.execute("DELETE FROM file_versions WHERE file_id=?", (row["file_id"],))
                connection.execute("DELETE FROM library_files WHERE file_id=?", (row["file_id"],))
                if not connection.execute("SELECT 1 FROM library_files WHERE edition_id=?", (row["edition_id"],)).fetchone():
                    connection.execute("DELETE FROM editions WHERE edition_id=?", (row["edition_id"],))
                if connection.execute("SELECT 1 FROM library_files WHERE work_id=?", (loser,)).fetchone():
                    _refresh_search(connection, loser); _sync_work_graph(connection, loser); continue
                node = connection.execute("SELECT node_id FROM knowledge_nodes WHERE node_type='work' AND normalized_label=?", (loser.casefold(),)).fetchone()
                if node:
                    connection.execute("DELETE FROM knowledge_edges WHERE source_node_id=? OR target_node_id=?", (node["node_id"], node["node_id"]))
                    connection.execute("DELETE FROM knowledge_nodes WHERE node_id=?", (node["node_id"],))
                connection.execute("DELETE FROM knowledge_edges WHERE work_id=?", (loser,))
                connection.execute("DELETE FROM work_tags WHERE work_id=?", (loser,))
                connection.execute("DELETE FROM library_project_links WHERE work_id=?", (loser,))
                connection.execute("DELETE FROM work_search WHERE work_id=?", (loser,))
                connection.execute("DELETE FROM editions WHERE work_id=?", (loser,))
                connection.execute("DELETE FROM works WHERE work_id=?", (loser,))
        for work_id in touched:
            _refresh_search(connection, work_id); _sync_work_graph(connection, work_id)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Keep one current file from high-confidence DOCX version groups.")
    parser.add_argument("library_root", type=Path); parser.add_argument("audit_json", type=Path)
    parser.add_argument("--apply", action="store_true"); args = parser.parse_args()
    print(json.dumps(consolidate(args.library_root.resolve(), args.audit_json.resolve(), args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
