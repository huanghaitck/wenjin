from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docx import Document

from .db import append_audit, connect
from .service import import_structure


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _source_path(project_root: Path, source_id: str) -> Path:
    with connect(project_root) as connection:
        row = connection.execute(
            """SELECT sv.project_path FROM source_versions sv
               WHERE sv.source_id = ? ORDER BY sv.created_at DESC LIMIT 1""",
            (source_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"unknown source: {source_id}")
    path = (project_root.resolve() / str(row["project_path"])).resolve()
    if project_root.resolve() not in path.parents or not path.is_file():
        raise FileNotFoundError("source file is unavailable")
    return path


def _paragraphs(path: Path) -> list[dict[str, str]]:
    document = Document(path)
    result: list[dict[str, str]] = []
    for paragraph in document.paragraphs:
        text = " ".join(paragraph.text.split()).strip()
        if not text:
            continue
        style = (paragraph.style.name if paragraph.style else "").lower()
        result.append({"type": "heading" if style.startswith("heading") else "paragraph", "text": text})
    return result


def _segments(paragraphs: list[dict[str, str]], max_blocks: int = 24,
              max_characters: int = 8000) -> list[list[dict[str, str]]]:
    segments: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    characters = 0
    for paragraph in paragraphs:
        length = len(paragraph["text"])
        if current and (len(current) >= max_blocks or characters + length > max_characters):
            segments.append(current)
            current, characters = [], 0
        current.append(paragraph)
        characters += length
    if current:
        segments.append(current)
    return segments


def ingest_docx_locator(project_root: Path, source_id: str) -> dict[str, Any]:
    """Index a DOCX as a locator aid without granting page-level evidence status."""
    project_root = project_root.resolve()
    source_path = _source_path(project_root, source_id)
    if source_path.suffix.lower() != ".docx":
        raise ValueError("locator ingestion currently accepts DOCX files")
    paragraphs = _paragraphs(source_path)
    if not paragraphs:
        raise ValueError("DOCX does not contain readable paragraphs")

    pages: list[dict[str, Any]] = []
    artifact_root = project_root / "sources" / source_id / "derived" / "locator"
    for segment_number, segment in enumerate(_segments(paragraphs), start=1):
        local_page_id = f"L{segment_number:04d}"
        blocks = [
            {
                "id": f"{local_page_id}_B{index:03d}",
                "order": index,
                "type": paragraph["type"],
                "text": paragraph["text"],
                "region": None,
            }
            for index, paragraph in enumerate(segment, start=1)
        ]
        markdown_path = artifact_root / f"segment-{segment_number:04d}.md"
        _write_text(
            markdown_path,
            f"<!-- logical_segment: {segment_number}; evidence_status: locator_only -->\n\n"
            + "\n\n".join(block["text"] for block in blocks)
            + "\n",
        )
        pages.append({
            "id": local_page_id,
            "physical_page": segment_number,
            "printed_page": None,
            "page_type": "docx_locator",
            "markdown_path": markdown_path.relative_to(project_root).as_posix(),
            "blocks": blocks,
        })

    packet = {
        "schema_version": 1,
        "processor": {"name": "hrw-docx-locator", "version": "1"},
        "source_id": source_id,
        "pages": pages,
        "relations": [],
        "anomalies": [],
    }
    structure_path = artifact_root / "structure.json"
    _write_text(structure_path, json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    receipt = import_structure(project_root, source_id, structure_path)
    with connect(project_root) as connection:
        connection.execute("UPDATE pages SET use_state = 'locator_only' WHERE source_id = ?", (source_id,))
        connection.execute(
            """UPDATE blocks SET use_state = 'locator_only'
               WHERE page_id IN (SELECT page_id FROM pages WHERE source_id = ?)""",
            (source_id,),
        )
        connection.execute(
            "UPDATE sources SET processing_state = 'accepted', use_state = 'locator_only' WHERE source_id = ?",
            (source_id,),
        )
        append_audit(connection, "docx_locator_ingested", "source", source_id, {
            "segments": len(pages), "paragraphs": len(paragraphs),
        })
    return {
        "source_id": source_id,
        "status": "locator_only",
        "segment_count": len(pages),
        "paragraph_count": len(paragraphs),
        "receipt": receipt,
        "structure_path": structure_path.relative_to(project_root).as_posix(),
    }
