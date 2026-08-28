from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

from research_workbench.library import _refresh_search, _sync_work_graph
from research_workbench.library_store import connect_library, library_database_path


def prune(root: Path, session_id: str, apply: bool = False) -> dict:
    with connect_library(root) as connection:
        rows = connection.execute(
            """SELECT sc.path,f.file_id,f.edition_id,f.work_id,w.canonical_title,
                      (SELECT COUNT(*) FROM library_project_links l WHERE l.work_id=f.work_id) AS project_links
               FROM scan_candidates sc
               LEFT JOIN library_files f ON f.path=sc.path
               LEFT JOIN works w ON w.work_id=f.work_id
               WHERE sc.session_id=? AND sc.status='ignored' ORDER BY sc.path""",
            (session_id,),
        ).fetchall()
    removable = [dict(row) for row in rows if row["file_id"] and not row["project_links"]]
    skipped = [dict(row) for row in rows if row["file_id"] and row["project_links"]]
    receipt = {
        "session_id": session_id, "apply": apply,
        "removable": [{"path": row["path"], "work_id": row["work_id"], "title": row["canonical_title"]} for row in removable],
        "skipped_project_linked": [{"path": row["path"], "work_id": row["work_id"]} for row in skipped],
        "source_files_deleted": False,
    }
    if not apply or not removable:
        return receipt
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = root / f"library-before-word-prune-{stamp}.sqlite3"
    shutil.copy2(library_database_path(root), backup)
    receipt["backup"] = str(backup)
    with connect_library(root) as connection:
        touched: set[str] = set()
        for row in removable:
            touched.add(row["work_id"])
            connection.execute("DELETE FROM file_versions WHERE file_id=?", (row["file_id"],))
            connection.execute("DELETE FROM library_files WHERE file_id=?", (row["file_id"],))
            if not connection.execute("SELECT 1 FROM library_files WHERE edition_id=?", (row["edition_id"],)).fetchone():
                connection.execute("DELETE FROM editions WHERE edition_id=?", (row["edition_id"],))
        for work_id in touched:
            if connection.execute("SELECT 1 FROM library_files WHERE work_id=?", (work_id,)).fetchone():
                _refresh_search(connection, work_id); _sync_work_graph(connection, work_id)
                continue
            node = connection.execute(
                "SELECT node_id FROM knowledge_nodes WHERE node_type='work' AND normalized_label=?",
                (work_id.casefold(),),
            ).fetchone()
            if node:
                connection.execute("DELETE FROM knowledge_edges WHERE source_node_id=? OR target_node_id=?", (node["node_id"], node["node_id"]))
                connection.execute("DELETE FROM knowledge_nodes WHERE node_id=?", (node["node_id"],))
            connection.execute("DELETE FROM knowledge_edges WHERE work_id=?", (work_id,))
            connection.execute("DELETE FROM work_tags WHERE work_id=?", (work_id,))
            connection.execute("DELETE FROM library_project_links WHERE work_id=?", (work_id,))
            connection.execute("DELETE FROM work_search WHERE work_id=?", (work_id,))
            connection.execute("DELETE FROM editions WHERE work_id=?", (work_id,))
            connection.execute("DELETE FROM works WHERE work_id=?", (work_id,))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove bulk-ignored Word records from the library without deleting source files.")
    parser.add_argument("library_root", type=Path)
    parser.add_argument("session_id")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prune(args.library_root.resolve(), args.session_id, args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
