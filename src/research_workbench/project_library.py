from __future__ import annotations

from pathlib import Path
from typing import Any

from .db import connect, utc_now
from .library import library_file_path, link_work_to_project, work_detail
from .pdf_ingestion import ingest_pdf
from .service import register_source


def add_library_file_to_project(project_root: Path, library_root: Path, work_id: str,
                                file_id: str) -> dict[str, Any]:
    detail = work_detail(project_root, work_id, library_root)
    file = next((item for item in detail["files"] if item["file_id"] == file_id), None)
    if file is None:
        raise KeyError(f"file {file_id} does not belong to work {work_id}")
    current = next((version for version in file["versions"] if version["is_current"]), None)
    if current is None or not current["bytes_available"]:
        raise ValueError("selected library version is not available at its registered path")
    source_path = library_file_path(project_root, file_id, library_root)
    if source_path.suffix.lower() != ".pdf":
        raise ValueError("the D1 project bridge currently accepts PDF files")
    source = register_source(project_root, source_path, detail["canonical_title"])
    with connect(project_root) as connection:
        connection.execute(
            """INSERT OR REPLACE INTO source_library_links(source_id, library_work_id, library_file_id,
               library_version_id, library_sha256, linked_at) VALUES (?, ?, ?, ?, ?, ?)""",
            (source["source_id"], work_id, file_id, current["version_id"], current["sha256"], utc_now()),
        )
        existing_pages = connection.execute(
            "SELECT COUNT(*) FROM pages WHERE source_id = ?", (source["source_id"],)
        ).fetchone()[0]
    link_work_to_project(project_root, work_id, library_root)
    intake = (
        {"source_id": source["source_id"], "page_count": existing_pages, "status": "already_ingested"}
        if existing_pages else ingest_pdf(project_root, source["source_id"])
    )
    return {"source": source, "intake": intake, "library_version": current}
