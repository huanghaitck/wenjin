from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import uuid
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .db import connect, utc_now


ALLOWED_SUFFIXES = {
    ".pdf", ".docx", ".xlsx", ".xlsm", ".csv", ".tsv", ".txt", ".md",
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".geojson", ".gpkg", ".kml", ".kmz", ".mbtiles",
}
MAX_ATTACHMENT_BYTES = 100 * 1024 * 1024


def archive_bytes_in_library(
    project_root: Path,
    filename: str,
    data: bytes,
    library_root: Path,
) -> dict[str, Any]:
    name = Path(filename).name
    suffix = Path(name).suffix.casefold()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"unsupported attachment type: {suffix or 'none'}")
    if not data or len(data) > MAX_ATTACHMENT_BYTES:
        raise ValueError("attachment must be between 1 byte and 100 MB")
    digest = hashlib.sha256(data).hexdigest()
    managed = library_root.resolve() / "uploads" / digest[:2] / f"{digest}{suffix}"
    managed.parent.mkdir(parents=True, exist_ok=True)
    if not managed.is_file():
        temporary = managed.with_suffix(managed.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(managed)
    from .library import archive_uploaded_file

    archived = archive_uploaded_file(project_root, managed, library_root, display_name=name)
    return {
        "managed_path": str(managed), "sha256": digest, "byte_count": len(data),
        "original_name": name, "library_action": archived["action"],
        "library_work_id": archived.get("work_id", ""),
        "library_version_id": archived.get("version_id", ""),
    }


def _xlsx_preview(path: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(item.itertext()) for item in root.findall("{*}si")]
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {item.attrib["Id"]: item.attrib["Target"] for item in relationships}
        sheets = []
        for item in workbook.findall(".//{*}sheet")[:3]:
            relation_id = next(value for key, value in item.attrib.items() if key.endswith("}id"))
            target = targets[relation_id].lstrip("/")
            sheet_path = target if target.startswith("xl/") else "xl/" + target
            root = ElementTree.fromstring(archive.read(sheet_path))
            rows = []
            for row in root.findall(".//{*}sheetData/{*}row")[:20]:
                values = []
                for cell in row.findall("{*}c"):
                    reference = cell.attrib.get("r", "A1")
                    letters = re.match(r"[A-Z]+", reference)
                    column = 0
                    for letter in (letters.group(0) if letters else "A"):
                        column = column * 26 + ord(letter) - 64
                    while len(values) < column:
                        values.append("")
                    value = cell.find("{*}v")
                    text = "" if value is None else value.text or ""
                    if cell.attrib.get("t") == "s" and text.isdigit():
                        text = shared[int(text)]
                    elif cell.attrib.get("t") == "inlineStr":
                        text = "".join(cell.itertext())
                    values[column - 1] = text[:300]
                while values and values[-1] == "":
                    values.pop()
                rows.append(values)
            sheets.append({"sheet": item.attrib.get("name", "Sheet"), "rows": rows})
        return sheets


def save_attachment(
    project_root: Path,
    thread_id: str,
    filename: str,
    data: bytes,
    library_root: Path | None = None,
) -> dict[str, Any]:
    name = Path(filename).name
    suffix = Path(name).suffix.casefold()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"unsupported attachment type: {suffix or 'none'}")
    if not data or len(data) > MAX_ATTACHMENT_BYTES:
        raise ValueError("attachment must be between 1 byte and 100 MB")
    with connect(project_root) as connection:
        if connection.execute("SELECT 1 FROM threads WHERE thread_id=?", (thread_id,)).fetchone() is None:
            raise KeyError(f"unknown thread: {thread_id}")
    digest = hashlib.sha256(data).hexdigest()
    managed: Path | None = None
    library_record: dict[str, Any] = {}
    if library_root is not None:
        library_record = archive_bytes_in_library(project_root, name, data, library_root)
        managed = Path(library_record["managed_path"])
    with connect(project_root) as connection:
        existing = connection.execute(
            "SELECT project_path FROM thread_attachments WHERE sha256=? ORDER BY created_at LIMIT 1",
            (digest,),
        ).fetchone()
    attachment_id = f"ATT_{uuid.uuid4().hex}"
    if existing is not None and (project_root / existing["project_path"]).is_file():
        relative = Path(existing["project_path"])
    else:
        relative = Path("attachments") / attachment_id / name
        target = project_root / relative
        target.parent.mkdir(parents=True, exist_ok=False)
        if managed is not None:
            try:
                os.link(managed, target)
            except OSError:
                target.write_bytes(data)
        else:
            target.write_bytes(data)
    record = {
        "attachment_id": attachment_id, "thread_id": thread_id, "original_name": name,
        "project_path": str(relative).replace("\\", "/"),
        "media_type": mimetypes.guess_type(name)[0] or "application/octet-stream",
        "sha256": digest, "byte_count": len(data),
        "created_at": utc_now(),
    }
    with connect(project_root) as connection:
        connection.execute(
            """INSERT INTO thread_attachments(
                   attachment_id,thread_id,original_name,project_path,media_type,sha256,byte_count,created_at
               ) VALUES (?,?,?,?,?,?,?,?)""",
            tuple(record[key] for key in (
                "attachment_id", "thread_id", "original_name", "project_path", "media_type",
                "sha256", "byte_count", "created_at",
            )),
        )
    if library_record:
        record.update({key: value for key, value in library_record.items() if key != "managed_path"})
    return record


def get_attachment(project_root: Path, attachment_id: str) -> dict[str, Any]:
    with connect(project_root) as connection:
        row = connection.execute(
            "SELECT * FROM thread_attachments WHERE attachment_id=?", (attachment_id,)
        ).fetchone()
    if row is None:
        raise KeyError(f"unknown attachment: {attachment_id}")
    record = dict(row)
    path = (project_root / record["project_path"]).resolve()
    if project_root.resolve() not in path.parents or not path.is_file():
        raise FileNotFoundError("attachment file is unavailable")
    record["absolute_path"] = str(path)
    return record


def inspect_attachment(project_root: Path, attachment_id: str) -> dict[str, Any]:
    record = get_attachment(project_root, attachment_id)
    path = Path(record["absolute_path"])
    suffix = path.suffix.casefold()
    result: dict[str, Any] = {**record, "kind": "binary", "preview": ""}
    if suffix in {".txt", ".md", ".csv", ".tsv"}:
        result.update(kind="text", preview=path.read_text(encoding="utf-8-sig", errors="replace")[:100000])
    elif suffix == ".docx":
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
        text = "".join(root.itertext())
        result.update(kind="text", preview=text[:100000])
    elif suffix in {".xlsx", ".xlsm"}:
        result.update(kind="spreadsheet", sheets=_xlsx_preview(path))
    elif suffix == ".pdf":
        import pymupdf

        document = pymupdf.open(path)
        try:
            preview = "\n\n".join(document[index].get_text() for index in range(min(3, len(document))))
        finally:
            document.close()
        result.update(kind="pdf", preview=preview[:100000])
    elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        result.update(kind="image")
    return result
