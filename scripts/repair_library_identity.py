from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from research_workbench.library import (
    _bibliographic_identifiers,
    _refresh_search,
    _sync_work_graph,
)
from research_workbench.library_store import connect_library, library_database_path


def identity_groups(root: Path) -> list[set[str]]:
    by_key: dict[str, set[str]] = defaultdict(set)
    with connect_library(root) as connection:
        rows = connection.execute(
            """SELECT f.work_id,v.sha256,v.sample_text FROM library_files f
               JOIN file_versions v ON v.file_id=f.file_id AND v.is_current=1"""
        ).fetchall()
    for row in rows:
        by_key[f"sha256:{row['sha256']}"].add(row["work_id"])
        for key in _bibliographic_identifiers(row["sample_text"]):
            by_key[key].add(row["work_id"])
    groups: list[set[str]] = []
    for work_ids in (value for value in by_key.values() if len(value) > 1):
        overlapping = [group for group in groups if group & work_ids]
        merged = set(work_ids)
        for group in overlapping:
            merged.update(group)
            groups.remove(group)
        groups.append(merged)
    return groups


def _score(connection, work_id: str) -> tuple[int, str]:
    row = connection.execute(
        """SELECT w.canonical_title,w.author,w.updated_at,
                  COUNT(DISTINCT f.file_id) AS files,
                  MAX(CASE WHEN e.publisher<>'' THEN 1 ELSE 0 END) AS publisher,
                  MAX(CASE WHEN e.publication_year<>'' THEN 1 ELSE 0 END) AS year
           FROM works w LEFT JOIN editions e ON e.work_id=w.work_id
           LEFT JOIN library_files f ON f.work_id=w.work_id WHERE w.work_id=? GROUP BY w.work_id""",
        (work_id,),
    ).fetchone()
    clean_title = not str(row["canonical_title"]).startswith("(NEW)")
    score = int(row["files"] or 0) * 10 + bool(row["author"]) * 4 + int(row["publisher"] or 0) * 2 + int(row["year"] or 0) + clean_title
    return score, str(row["updated_at"])


def repair(root: Path, apply: bool = False) -> dict:
    groups = identity_groups(root)
    receipt = {"apply": apply, "groups": [], "removed_duplicate_locations": []}
    if not groups:
        return receipt
    if apply:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = root / f"library-before-identity-repair-{stamp}.sqlite3"
        shutil.copy2(library_database_path(root), backup)
        receipt["backup"] = str(backup)
    with connect_library(root) as connection:
        for work_ids in groups:
            ordered = sorted(work_ids, key=lambda work_id: _score(connection, work_id), reverse=True)
            winner, losers = ordered[0], ordered[1:]
            receipt["groups"].append({"winner": winner, "merged": losers})
            if not apply:
                continue
            winner_row = connection.execute("SELECT * FROM works WHERE work_id=?", (winner,)).fetchone()
            for loser in losers:
                loser_row = connection.execute("SELECT * FROM works WHERE work_id=?", (loser,)).fetchone()
                if not winner_row["author"] and loser_row["author"]:
                    connection.execute("UPDATE works SET author=? WHERE work_id=?", (loser_row["author"], winner))
                connection.execute("UPDATE editions SET work_id=? WHERE work_id=?", (winner, loser))
                connection.execute("UPDATE library_files SET work_id=? WHERE work_id=?", (winner, loser))
                connection.execute(
                    "INSERT OR IGNORE INTO work_tags(work_id,tag_id,origin) SELECT ?,tag_id,origin FROM work_tags WHERE work_id=?",
                    (winner, loser),
                )
                connection.execute("DELETE FROM work_tags WHERE work_id=?", (loser,))
                connection.execute(
                    "INSERT OR IGNORE INTO library_project_links(work_id,project_id,project_root,linked_at) SELECT ?,project_id,project_root,linked_at FROM library_project_links WHERE work_id=?",
                    (winner, loser),
                )
                connection.execute("DELETE FROM library_project_links WHERE work_id=?", (loser,))
                connection.execute("UPDATE scan_candidates SET existing_work_id=? WHERE existing_work_id=?", (winner, loser))
                node = connection.execute(
                    "SELECT node_id FROM knowledge_nodes WHERE node_type='work' AND normalized_label=?", (loser.casefold(),)
                ).fetchone()
                if node:
                    connection.execute("DELETE FROM knowledge_edges WHERE source_node_id=? OR target_node_id=?", (node["node_id"], node["node_id"]))
                    connection.execute("DELETE FROM knowledge_nodes WHERE node_id=?", (node["node_id"],))
                connection.execute("DELETE FROM knowledge_edges WHERE work_id=?", (loser,))
                connection.execute("DELETE FROM work_search WHERE work_id=?", (loser,))
                connection.execute("DELETE FROM works WHERE work_id=?", (loser,))
            duplicates = connection.execute(
                """SELECT v.sha256,COUNT(*) AS n FROM library_files f
                   JOIN file_versions v ON v.file_id=f.file_id AND v.is_current=1
                   WHERE f.work_id=? GROUP BY v.sha256 HAVING COUNT(*)>1""",
                (winner,),
            ).fetchall()
            for duplicate in duplicates:
                files = connection.execute(
                    """SELECT f.file_id,f.edition_id,f.path,v.modified_ns FROM library_files f
                       JOIN file_versions v ON v.file_id=f.file_id AND v.is_current=1
                       WHERE f.work_id=? AND v.sha256=? ORDER BY v.modified_ns DESC,f.path""",
                    (winner, duplicate["sha256"]),
                ).fetchall()
                keep = files[0]
                for old in files[1:]:
                    connection.execute("DELETE FROM file_versions WHERE file_id=?", (old["file_id"],))
                    connection.execute("DELETE FROM library_files WHERE file_id=?", (old["file_id"],))
                    if not connection.execute("SELECT 1 FROM library_files WHERE edition_id=?", (old["edition_id"],)).fetchone():
                        connection.execute("DELETE FROM editions WHERE edition_id=?", (old["edition_id"],))
                    receipt["removed_duplicate_locations"].append({"work_id": winner, "removed": old["path"], "kept": keep["path"]})
            _refresh_search(connection, winner)
            _sync_work_graph(connection, winner)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit or merge library works sharing SHA-256, DOI, or ISBN.")
    parser.add_argument("library_root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = repair(args.library_root.resolve(), args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
