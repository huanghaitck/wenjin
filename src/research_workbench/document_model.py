from __future__ import annotations

import hashlib
import io
import json
import uuid
from pathlib import Path
from typing import Any

from docx import Document

from .db import append_audit, connect, utc_now


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _paragraphs(text: str) -> list[dict[str, str]]:
    parts = [part.strip() for part in text.replace("\r\n", "\n").split("\n\n") if part.strip()]
    return [{"type": "paragraph", "node_id": _id("NOD"), "text": part} for part in parts] or [
        {"type": "paragraph", "node_id": _id("NOD"), "text": ""}
    ]


def _tree_from_sections(title: str, sections: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "document",
        "node_id": _id("NOD"),
        "title": title,
        "children": [
            {
                "type": "section",
                "node_id": _id("NOD"),
                "section_id": section["section_id"],
                "heading": section["heading"],
                "children": _paragraphs(section["content"]),
            }
            for section in sections
        ],
    }


def _plain_text(tree: dict[str, Any]) -> str:
    lines = [str(tree.get("title", ""))]
    for section in tree.get("children", []):
        lines.append(str(section.get("heading", "")))
        lines.extend(str(node.get("text", "")) for node in section.get("children", []))
    return "\n".join(lines)


def _validate_tree(tree: dict[str, Any]) -> None:
    if tree.get("type") != "document" or not isinstance(tree.get("children"), list):
        raise ValueError("document must be a structured document tree")
    seen: set[str] = set()
    for section in tree["children"]:
        if section.get("type") != "section" or not str(section.get("heading", "")).strip():
            raise ValueError("each document section requires a heading")
        if not isinstance(section.get("children"), list):
            raise ValueError("each document section requires paragraph nodes")
        for node in [section, *section["children"]]:
            node_id = str(node.get("node_id", ""))
            if not node_id or node_id in seen:
                raise ValueError("document node IDs must be present and unique")
            seen.add(node_id)
        if any(node.get("type") not in {"paragraph", "quote", "list_item"} for node in section["children"]):
            raise ValueError("unsupported document node type")


def ensure_document(project_root: Path, manuscript_id: str) -> dict[str, Any]:
    with connect(project_root) as connection:
        manuscript = connection.execute(
            "SELECT * FROM manuscripts WHERE manuscript_id = ?", (manuscript_id,)
        ).fetchone()
        if manuscript is None:
            raise KeyError(f"unknown manuscript: {manuscript_id}")
        existing = connection.execute(
            "SELECT document_id FROM manuscript_documents WHERE manuscript_id = ?", (manuscript_id,)
        ).fetchone()
        if existing is None:
            sections = [dict(row) for row in connection.execute(
                """SELECT s.section_id, s.heading, v.content
                   FROM manuscript_sections s JOIN section_versions v ON v.version_id = s.current_version_id
                   WHERE s.manuscript_id = ? ORDER BY s.section_order""", (manuscript_id,)
            )]
            tree = _tree_from_sections(str(manuscript["title"]), sections)
            document_id, revision_id, now = _id("DOC"), _id("DREV"), utc_now()
            digest = hashlib.sha256(_plain_text(tree).encode("utf-8")).hexdigest()
            fidelity = {"level": "exact_text", "warnings": [], "source": "legacy_sections"}
            connection.execute(
                "INSERT INTO manuscript_documents(document_id, manuscript_id, current_revision_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (document_id, manuscript_id, revision_id, now, now),
            )
            connection.execute(
                """INSERT INTO document_revisions(revision_id, document_id, base_revision_id, document_json,
                   plain_text_hash, source_format, status, fidelity_json, created_at)
                   VALUES (?, ?, NULL, ?, ?, 'legacy_sections', 'approved', ?, ?)""",
                (revision_id, document_id, _json(tree), digest, _json(fidelity), now),
            )
    return document_detail(project_root, manuscript_id)


def document_detail(project_root: Path, manuscript_id: str) -> dict[str, Any]:
    with connect(project_root) as connection:
        row = connection.execute(
            """SELECT d.*, r.document_json, r.plain_text_hash, r.source_format, r.status,
                      r.fidelity_json, r.created_at AS revision_created_at
               FROM manuscript_documents d JOIN document_revisions r ON r.revision_id = d.current_revision_id
               WHERE d.manuscript_id = ?""", (manuscript_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"structured document is not initialized: {manuscript_id}")
        revisions = [dict(item) for item in connection.execute(
            """SELECT revision_id, base_revision_id, plain_text_hash, source_format, status,
                      fidelity_json, created_at FROM document_revisions
               WHERE document_id = ? ORDER BY created_at DESC, revision_id DESC""", (row["document_id"],)
        )]
        receipts = [dict(item) for item in connection.execute(
            "SELECT * FROM document_io_receipts WHERE manuscript_id = ? ORDER BY created_at DESC",
            (manuscript_id,),
        )]
    result = dict(row)
    result["document"] = json.loads(result.pop("document_json"))
    result["fidelity"] = json.loads(result.pop("fidelity_json"))
    for item in revisions:
        item["fidelity"] = json.loads(item.pop("fidelity_json"))
    for item in receipts:
        item["fidelity"] = json.loads(item.pop("fidelity_json"))
    result["revisions"], result["io_receipts"] = revisions, receipts
    return result


def save_document(project_root: Path, manuscript_id: str, tree: dict[str, Any]) -> dict[str, Any]:
    _validate_tree(tree)
    current = ensure_document(project_root, manuscript_id)
    revision_id, now = _id("DREV"), utc_now()
    fidelity = {"level": "native", "warnings": [], "source": "structured_editor"}
    with connect(project_root) as connection:
        existing = {row["section_id"]: dict(row) for row in connection.execute(
            "SELECT * FROM manuscript_sections WHERE manuscript_id = ?", (manuscript_id,)
        )}
        for section in tree["children"]:
            if str(section.get("section_id", "")) not in existing:
                section["section_id"] = _id("SEC")
        digest = hashlib.sha256(_plain_text(tree).encode("utf-8")).hexdigest()
        connection.execute(
            """INSERT INTO document_revisions(revision_id, document_id, base_revision_id, document_json,
               plain_text_hash, source_format, status, fidelity_json, created_at)
               VALUES (?, ?, ?, ?, ?, 'structured_editor', 'approved', ?, ?)""",
            (revision_id, current["document_id"], current["current_revision_id"], _json(tree), digest,
             _json(fidelity), now),
        )
        for order, section in enumerate(tree["children"], start=1):
            section_id = str(section.get("section_id", ""))
            if section_id not in existing:
                connection.execute(
                    "INSERT INTO manuscript_sections(section_id, manuscript_id, section_order, heading, created_at) VALUES (?, ?, ?, ?, ?)",
                    (section_id, manuscript_id, order, str(section["heading"]).strip(), now),
                )
            content = "\n\n".join(str(node.get("text", "")).strip() for node in section["children"]).strip()
            version_id = _id("SEV")
            base = existing.get(section_id, {}).get("current_version_id")
            connection.execute(
                """INSERT INTO section_versions(version_id, section_id, base_version_id, operation, content,
                   evidence_refs_json, model_snapshot_json, status, created_at, approved_at)
                   VALUES (?, ?, ?, 'manual_structured_edit', ?, '[]', '{"provider":"human_editor"}', 'approved', ?, ?)""",
                (version_id, section_id, base, content, now, now),
            )
            connection.execute(
                "UPDATE manuscript_sections SET section_order = ?, heading = ?, current_version_id = ? WHERE section_id = ?",
                (order, str(section["heading"]).strip(), version_id, section_id),
            )
        connection.execute(
            "UPDATE manuscript_documents SET current_revision_id = ?, updated_at = ? WHERE document_id = ?",
            (revision_id, now, current["document_id"]),
        )
        connection.execute("UPDATE manuscripts SET title = ?, updated_at = ? WHERE manuscript_id = ?",
                           (str(tree.get("title", "")).strip() or "未命名稿件", now, manuscript_id))
        append_audit(connection, "document_revision_saved", "manuscript", manuscript_id,
                     {"revision_id": revision_id, "base_revision_id": current["current_revision_id"]})
    return document_detail(project_root, manuscript_id)


def markdown_from_tree(tree: dict[str, Any]) -> str:
    lines = [f"# {tree.get('title', '未命名稿件')}", ""]
    for section in tree.get("children", []):
        lines.extend([f"## {section.get('heading', '正文')}", ""])
        for node in section.get("children", []):
            prefix = "> " if node.get("type") == "quote" else ""
            lines.extend([prefix + str(node.get("text", "")), ""])
    return "\n".join(lines).rstrip() + "\n"


def import_docx(project_root: Path, title: str, data: bytes) -> dict[str, Any]:
    from .authoring import import_manuscript

    document = Document(io.BytesIO(data))
    lines: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style = paragraph.style.name if paragraph.style else ""
        if style.startswith("Heading"):
            level = style.removeprefix("Heading").strip() or "1"
            lines.append("#" * min(6, max(1, int(level))) + " " + text)
        else:
            lines.extend([text, ""])
    if not lines:
        raise ValueError("DOCX does not contain readable paragraphs")
    manuscript = import_manuscript(project_root, title.strip() or "导入的 DOCX", "\n".join(lines))
    detail = ensure_document(project_root, manuscript["manuscript_id"])
    warnings = []
    if document.tables:
        warnings.append(f"{len(document.tables)} 个表格未导入")
    warnings.append("批注、修订、域代码、脚注与嵌入对象未做无损往返保证")
    _record_receipt(project_root, manuscript["manuscript_id"], detail["current_revision_id"],
                    "import", "docx", "", {"level": "limited", "warnings": warnings})
    result = document_detail(project_root, manuscript["manuscript_id"])
    result["import_fidelity"] = {"level": "limited", "warnings": warnings}
    return result


def export_document(project_root: Path, manuscript_id: str, format_name: str) -> dict[str, Any]:
    detail = ensure_document(project_root, manuscript_id)
    tree = detail["document"]
    export_root = project_root / "exports"
    export_root.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    if format_name == "markdown":
        path = export_root / f"{manuscript_id}-{detail['current_revision_id']}.md"
        path.write_text(markdown_from_tree(tree), encoding="utf-8")
        level = "native_text"
    elif format_name == "docx":
        path = export_root / f"{manuscript_id}-{detail['current_revision_id']}.docx"
        document = Document()
        document.add_heading(str(tree.get("title", "未命名稿件")), level=0)
        for section in tree.get("children", []):
            document.add_heading(str(section.get("heading", "正文")), level=1)
            for node in section.get("children", []):
                style = "Quote" if node.get("type") == "quote" else None
                document.add_paragraph(str(node.get("text", "")), style=style)
        document.save(path)
        level = "limited"
        warnings.append("导出保留标题与段落；批注、修订、域代码和复杂脚注需在 Word 中人工复核")
    else:
        raise ValueError("format must be markdown or docx")
    fidelity = {"level": level, "warnings": warnings}
    receipt = _record_receipt(project_root, manuscript_id, detail["current_revision_id"],
                              "export", format_name, path.relative_to(project_root).as_posix(), fidelity)
    return {**receipt, "download_url": "/api/export/file?path=" + path.relative_to(project_root).as_posix()}


def _record_receipt(project_root: Path, manuscript_id: str, revision_id: str, direction: str,
                    format_name: str, project_path: str, fidelity: dict[str, Any]) -> dict[str, Any]:
    receipt_id, now = _id("IOR"), utc_now()
    with connect(project_root) as connection:
        connection.execute(
            """INSERT INTO document_io_receipts(receipt_id, manuscript_id, revision_id, direction,
               format, project_path, fidelity_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (receipt_id, manuscript_id, revision_id, direction, format_name, project_path, _json(fidelity), now),
        )
    return {"receipt_id": receipt_id, "manuscript_id": manuscript_id, "revision_id": revision_id,
            "direction": direction, "format": format_name, "project_path": project_path,
            "fidelity": fidelity, "created_at": now}
