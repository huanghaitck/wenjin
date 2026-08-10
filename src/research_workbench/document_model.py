from __future__ import annotations

import hashlib
import io
import json
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from docx.shared import RGBColor

from .authoring import ensure_journal_templates
from .citations import check_note_anchors, list_notes
from .db import append_audit, connect, utc_now
from .docx_notes import add_footnote_reference, attach_footnotes


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
    result["notes"] = list_notes(project_root, manuscript_id)
    return result


def save_document(project_root: Path, manuscript_id: str, tree: dict[str, Any],
                  source_format: str = "structured_editor",
                  fidelity: dict[str, Any] | None = None) -> dict[str, Any]:
    _validate_tree(tree)
    current = ensure_document(project_root, manuscript_id)
    revision_id, now = _id("DREV"), utc_now()
    fidelity = fidelity or {"level": "native", "warnings": [], "source": "structured_editor"}
    with connect(project_root) as connection:
        existing = {row["section_id"]: dict(row) for row in connection.execute(
            """SELECT s.*, v.content AS current_content,
                      v.evidence_refs_json AS current_evidence_refs_json
               FROM manuscript_sections s
               LEFT JOIN section_versions v ON v.version_id = s.current_version_id
               WHERE s.manuscript_id = ?""", (manuscript_id,)
        )}
        for section in tree["children"]:
            if str(section.get("section_id", "")) not in existing:
                section["section_id"] = _id("SEC")
        digest = hashlib.sha256(_plain_text(tree).encode("utf-8")).hexdigest()
        connection.execute(
            """INSERT INTO document_revisions(revision_id, document_id, base_revision_id, document_json,
               plain_text_hash, source_format, status, fidelity_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'approved', ?, ?)""",
            (revision_id, current["document_id"], current["current_revision_id"], _json(tree), digest,
             source_format, _json(fidelity), now),
        )
        for order, section in enumerate(tree["children"], start=1):
            section_id = str(section.get("section_id", ""))
            if section_id not in existing:
                connection.execute(
                    "INSERT INTO manuscript_sections(section_id, manuscript_id, section_order, heading, created_at) VALUES (?, ?, ?, ?, ?)",
                    (section_id, manuscript_id, order, str(section["heading"]).strip(), now),
                )
            content = "\n\n".join(str(node.get("text", "")).strip() for node in section["children"]).strip()
            prior = existing.get(section_id, {})
            base = prior.get("current_version_id")
            version_id = base
            if not prior or content != str(prior.get("current_content") or ""):
                version_id = _id("SEV")
                evidence_refs = str(prior.get("current_evidence_refs_json") or "[]")
                connection.execute(
                    """INSERT INTO section_versions(version_id, section_id, base_version_id, operation, content,
                       evidence_refs_json, model_snapshot_json, status, created_at, approved_at)
                       VALUES (?, ?, ?, 'manual_structured_edit', ?, ?, '{"provider":"human_editor"}', 'approved', ?, ?)""",
                    (version_id, section_id, base, content, evidence_refs, now, now),
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
    check_note_anchors(project_root, manuscript_id, tree)
    return document_detail(project_root, manuscript_id)


def sync_approved_section(project_root: Path, manuscript_id: str, section_id: str,
                          content: str, section_version_id: str) -> dict[str, Any]:
    """Make an approved section version the current structured-document revision."""
    current = ensure_document(project_root, manuscript_id)
    tree = deepcopy(current["document"])
    section = next((item for item in tree["children"] if item.get("section_id") == section_id), None)
    if section is None:
        raise KeyError(f"structured document is missing section: {section_id}")
    old_children = section.get("children", [])
    new_children = _paragraphs(content)
    for index, node in enumerate(new_children):
        if index < len(old_children):
            node["node_id"] = old_children[index]["node_id"]
    if [node.get("text", "") for node in old_children] == [node["text"] for node in new_children]:
        return current
    section["children"] = new_children
    revision_id, now = _id("DREV"), utc_now()
    digest = hashlib.sha256(_plain_text(tree).encode("utf-8")).hexdigest()
    fidelity = {
        "level": "evidence_reviewed", "warnings": [],
        "source": "approved_section_version", "section_version_id": section_version_id,
    }
    with connect(project_root) as connection:
        connection.execute(
            """INSERT INTO document_revisions(revision_id, document_id, base_revision_id, document_json,
               plain_text_hash, source_format, status, fidelity_json, created_at)
               VALUES (?, ?, ?, ?, ?, 'approved_section_version', 'approved', ?, ?)""",
            (revision_id, current["document_id"], current["current_revision_id"], _json(tree), digest,
             _json(fidelity), now),
        )
        connection.execute(
            "UPDATE manuscript_documents SET current_revision_id = ?, updated_at = ? WHERE document_id = ?",
            (revision_id, now, current["document_id"]),
        )
        append_audit(connection, "approved_section_synced", "manuscript", manuscript_id, {
            "section_id": section_id, "section_version_id": section_version_id,
            "revision_id": revision_id, "base_revision_id": current["current_revision_id"],
        })
    check_note_anchors(project_root, manuscript_id, tree)
    return document_detail(project_root, manuscript_id)


def _numbered_notes(notes: list[dict[str, Any]], tree: dict[str, Any]) -> tuple[dict[str, list[tuple[int, dict[str, Any]]]], list[dict[str, Any]]]:
    by_node: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    node_order = {
        str(node.get("node_id")): position
        for position, node in enumerate(
            node for section in tree.get("children", []) for node in section.get("children", [])
        )
    }
    ordered = sorted(notes, key=lambda item: (
        node_order.get(str(item["anchor_node_id"]), 10**9), int(item["anchor_offset"]), item["created_at"]
    ))
    for number, note in enumerate(ordered, start=1):
        by_node.setdefault(str(note["anchor_node_id"]), []).append((number, note))
    return by_node, ordered


def _markdown_text(text: str, placements: list[tuple[int, dict[str, Any]]]) -> str:
    for number, note in sorted(placements, key=lambda item: int(item[1]["anchor_offset"]), reverse=True):
        offset = min(max(0, int(note["anchor_offset"])), len(text))
        text = text[:offset] + f"[^note{number}]" + text[offset:]
    return text


def markdown_from_tree(tree: dict[str, Any], notes: list[dict[str, Any]] | None = None) -> str:
    by_node, ordered = _numbered_notes(notes or [], tree)
    lines = [f"# {tree.get('title', '未命名稿件')}", ""]
    for section in tree.get("children", []):
        lines.extend([f"## {section.get('heading', '正文')}", ""])
        for node in section.get("children", []):
            prefix = "> " if node.get("type") == "quote" else ""
            text = _markdown_text(str(node.get("text", "")), by_node.get(str(node.get("node_id")), []))
            lines.extend([prefix + text, ""])
    if ordered:
        lines.append("---")
        lines.append("")
        for number, note in enumerate(ordered, start=1):
            lines.append(f"[^note{number}]: {note['rendered_text']}")
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


def reimport_docx(project_root: Path, manuscript_id: str, data: bytes) -> dict[str, Any]:
    current = ensure_document(project_root, manuscript_id)
    document = Document(io.BytesIO(data))
    old_sections = current["document"].get("children", [])
    sections: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style = paragraph.style.name if paragraph.style else ""
        if style.startswith("Heading"):
            active = {
                "type": "section", "node_id": _id("NOD"), "section_id": "",
                "heading": text, "children": [],
            }
            sections.append(active)
            continue
        if active is None:
            active = {
                "type": "section", "node_id": _id("NOD"), "section_id": "",
                "heading": "正文", "children": [],
            }
            sections.append(active)
        node_type = "quote" if style == "Quote" else ("list_item" if style.startswith("List") else "paragraph")
        active["children"].append({"type": node_type, "node_id": _id("NOD"), "text": text})
    if not sections:
        raise ValueError("DOCX does not contain readable paragraphs")
    for index, section in enumerate(sections):
        if index < len(old_sections):
            section["section_id"] = str(old_sections[index].get("section_id", ""))
        if not section["children"]:
            section["children"].append({"type": "paragraph", "node_id": _id("NOD"), "text": ""})
    warnings = ["Word 修改稿已作为新修订导回，原导出与旧修订保持不变",
                "批注、修订、域代码、脚注与嵌入对象未做无损往返保证",
                "原结构化注释锚点因 Word 段落身份变化而需要重新核对"]
    if document.tables:
        warnings.append(f"{len(document.tables)} 个表格未导入")
    tree = {
        "type": "document", "node_id": _id("NOD"),
        "title": str(current["document"].get("title", "未命名稿件")), "children": sections,
    }
    result = save_document(
        project_root, manuscript_id, tree, "docx_reimport",
        {"level": "limited", "warnings": warnings, "source": "microsoft_word_roundtrip"},
    )
    _record_receipt(project_root, manuscript_id, result["current_revision_id"], "import", "docx", "",
                    {"level": "limited", "warnings": warnings})
    result = document_detail(project_root, manuscript_id)
    result["import_fidelity"] = {"level": "limited", "warnings": warnings}
    return result


def export_document(project_root: Path, manuscript_id: str, format_name: str,
                    template_id: str = "builtin-history-research") -> dict[str, Any]:
    detail = ensure_document(project_root, manuscript_id)
    tree = detail["document"]
    templates = {item["template_id"]: item for item in ensure_journal_templates(project_root)}
    if template_id not in templates:
        raise KeyError(f"unknown journal template: {template_id}")
    template = templates[template_id]
    notes = list_notes(project_root, manuscript_id, approved_only=True)
    by_node, ordered_notes = _numbered_notes(notes, tree)
    export_root = project_root / "exports"
    export_root.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    if format_name == "markdown":
        path = export_root / f"{manuscript_id}-{detail['current_revision_id']}.md"
        path.write_text(markdown_from_tree(tree, notes), encoding="utf-8")
        level = "native_text"
    elif format_name == "docx":
        path = export_root / f"{manuscript_id}-{detail['current_revision_id']}.docx"
        document = Document()
        requirements = template.get("requirements", {})
        section_properties = document.sections[0]
        section_properties.page_width, section_properties.page_height = Cm(21), Cm(29.7)
        normal = document.styles["Normal"]
        normal.font.name = "SimSun"
        normal._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        normal.font.size = Pt(float(requirements.get("body_size_pt", 12)))
        for style_name, size in (("Heading 1", 14),):
            style = document.styles[style_name]
            style.font.name = "SimSun"
            style._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
            style.font.size = Pt(size)
            style.font.color.rgb = RGBColor(0, 0, 0)
        title = document.add_paragraph()
        title_run = title.add_run(str(tree.get("title", "未命名稿件")))
        title_run.bold = True
        title_run.font.name = "SimSun"
        title_run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        title_run.font.size = Pt(18)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for section in tree.get("children", []):
            document.add_heading(str(section.get("heading", "正文")), level=1)
            for node in section.get("children", []):
                style = "Quote" if node.get("type") == "quote" else None
                paragraph = document.add_paragraph(style=style)
                text = str(node.get("text", ""))
                cursor = 0
                for number, note in sorted(by_node.get(str(node.get("node_id")), []), key=lambda item: int(item[1]["anchor_offset"])):
                    offset = min(max(cursor, int(note["anchor_offset"])), len(text))
                    paragraph.add_run(text[cursor:offset])
                    add_footnote_reference(paragraph, number)
                    cursor = offset
                paragraph.add_run(text[cursor:])
        document.save(path)
        attach_footnotes(path, [note["rendered_text"] for note in ordered_notes],
                         requirements.get("number_restart") == "each_page")
        level = "structured_with_true_footnotes"
        warnings.append("已写入真实 Word 脚注；圈码外观、每页重编号及最终分页仍须在目标 Word 版本中复核")
        warnings.append("LibreOffice 无界面转换在中文标点后紧接脚注时可能失败；Microsoft Word 渲染已通过")
    else:
        raise ValueError("format must be markdown or docx")
    fidelity = {
        "level": level, "warnings": warnings, "approved_note_count": len(ordered_notes),
        "template_id": template_id, "template_revision_id": template.get("template_revision_id"),
        "template_verification_status": template.get("verification_status"),
    }
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
