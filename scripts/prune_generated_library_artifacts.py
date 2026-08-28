from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

from research_workbench.library import _refresh_search, _sync_work_graph
from research_workbench.library_store import connect_library, library_database_path


def prune(root: Path, apply: bool = False) -> dict:
    with connect_library(root) as connection:
        rows = connection.execute(
            """SELECT f.file_id,f.edition_id,f.work_id,f.path,v.format,w.canonical_title,
                      (SELECT COUNT(*) FROM library_project_links l WHERE l.work_id=f.work_id) AS project_links
               FROM library_files f JOIN works w ON w.work_id=f.work_id
               JOIN file_versions v ON v.file_id=f.file_id AND v.is_current=1"""
        ).fetchall()
    generated = []
    for row in rows:
        item = dict(row); stem = Path(item["path"]).stem.casefold()
        if item["format"] in {"md", "txt"} or any(term in stem for term in ("histra-bench", "benchmark", "mcqtask", "final_three_questions")) or "bench" in stem:
            generated.append(item)
    removable = [item for item in generated if not item["project_links"]]
    skipped = [item for item in generated if item["project_links"]]
    receipt = {
        "apply": apply,
        "removable": [{"path": item["path"], "work_id": item["work_id"], "title": item["canonical_title"]} for item in removable],
        "skipped_project_linked": [{"path": item["path"], "work_id": item["work_id"]} for item in skipped],
        "source_files_deleted": False,
    }
    if not apply or not removable:
        return receipt
    backup = root / f"library-before-generated-prune-{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
    shutil.copy2(library_database_path(root), backup); receipt["backup"] = str(backup)
    with connect_library(root) as connection:
        touched: set[str] = set()
        for item in removable:
            touched.add(item["work_id"])
            connection.execute("DELETE FROM file_versions WHERE file_id=?", (item["file_id"],))
            connection.execute("DELETE FROM library_files WHERE file_id=?", (item["file_id"],))
            if not connection.execute("SELECT 1 FROM library_files WHERE edition_id=?", (item["edition_id"],)).fetchone():
                connection.execute("DELETE FROM editions WHERE edition_id=?", (item["edition_id"],))
        for work_id in touched:
            if connection.execute("SELECT 1 FROM library_files WHERE work_id=?", (work_id,)).fetchone():
                _refresh_search(connection, work_id); _sync_work_graph(connection, work_id); continue
            node = connection.execute(
                "SELECT node_id FROM knowledge_nodes WHERE node_type='work' AND normalized_label=?",
                (work_id.casefold(),),
            ).fetchone()
            if node:
                connection.execute("DELETE FROM knowledge_edges WHERE source_node_id=? OR target_node_id=?", (node["node_id"], node["node_id"]))
                connection.execute("DELETE FROM knowledge_nodes WHERE node_id=?", (node["node_id"],))
            for table in ("knowledge_edges", "work_tags", "library_project_links", "editions"):
                connection.execute(f"DELETE FROM {table} WHERE work_id=?", (work_id,))
            connection.execute("DELETE FROM work_search WHERE work_id=?", (work_id,))
            connection.execute("DELETE FROM works WHERE work_id=?", (work_id,))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove generated Bench/Markdown/text records without deleting source files.")
    parser.add_argument("library_root", type=Path); parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prune(args.library_root.resolve(), args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
