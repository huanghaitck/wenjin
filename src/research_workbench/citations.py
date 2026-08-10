from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .authoring import ensure_journal_templates
from .db import append_audit, connect, utc_now


MODES = {"VERIFY_AND_INSERT", "METADATA_FIRST_PAGE_LATER", "REFORMAT_EXISTING"}
VERIFICATION_STATES = {
    "PAGE_VERIFIED_INSERTED", "PAGE_VERIFIED_REFORMATTED", "METADATA_VERIFIED_PAGE_PENDING",
    "FORMAT_ONLY_USER_SUPPLIED", "UNRESOLVED",
}


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def render_citation(data: dict[str, Any], mode: str) -> tuple[str, str]:
    if mode not in MODES:
        raise ValueError(f"unsupported citation mode: {mode}")
    if mode == "REFORMAT_EXISTING":
        text = str(data.get("user_supplied_text", "")).strip()
        if not text:
            raise ValueError("existing note text is required")
        return text, "FORMAT_ONLY_USER_SUPPLIED"

    title = str(data.get("title", "")).strip()
    if not title:
        raise ValueError("source title is required")
    author = str(data.get("author", "")).strip()
    source_type = str(data.get("source_type", "book"))
    original_page = str(data.get("original_page", "")).strip()
    if mode == "VERIFY_AND_INSERT" and not original_page:
        raise ValueError("page-verified notes require an original page or stable source locator")
    page = original_page or "〔页码待作者填写〕"

    if source_type == "article":
        journal = str(data.get("journal", "")).strip()
        year_issue = str(data.get("year_issue", "")).strip()
        text = f"{author + '：' if author else ''}《{title}》，《{journal}》{year_issue}，第{page}页。"
    elif source_type == "archive":
        archive = str(data.get("archive", "")).strip()
        file_number = str(data.get("file_number", "")).strip()
        parts = [value for value in (author, f"《{title}》", archive, file_number, page) if value]
        text = "，".join(parts) + "。"
    elif source_type == "classic":
        volume = str(data.get("volume", "")).strip()
        edition = str(data.get("edition", "")).strip()
        parts = [author, f"《{title}》{volume}", edition, f"第{page}页"]
        text = "，".join(value for value in parts if value) + "。"
    else:
        translator = str(data.get("translator", "")).strip()
        place = str(data.get("place", "")).strip()
        publisher = str(data.get("publisher", "")).strip()
        year = str(data.get("year", "")).strip()
        responsibility = f"，{translator}译" if translator else ""
        publication = "：".join(value for value in (place, publisher) if value)
        if publication and year:
            publication += f"，{year}年"
        elif year:
            publication = f"{year}年"
        text = f"{author + '：' if author else ''}《{title}》{responsibility}"
        if publication:
            text += f"，{publication}"
        text += f"，第{page}页。"
    state = "PAGE_VERIFIED_INSERTED" if mode == "VERIFY_AND_INSERT" else "METADATA_VERIFIED_PAGE_PENDING"
    return text, state


def create_note(project_root: Path, manuscript_id: str, anchor_node_id: str, anchor_offset: int,
                anchor_text: str, template_id: str, mode: str, citation_data: dict[str, Any],
                evidence_id: str = "") -> dict[str, Any]:
    templates = {item["template_id"] for item in ensure_journal_templates(project_root)}
    if template_id not in templates:
        raise KeyError(f"unknown journal template: {template_id}")
    rendered, verification_state = render_citation(citation_data, mode)
    source_refs: list[dict[str, Any]] = []
    with connect(project_root) as connection:
        if connection.execute("SELECT 1 FROM manuscripts WHERE manuscript_id = ?", (manuscript_id,)).fetchone() is None:
            raise KeyError(f"unknown manuscript: {manuscript_id}")
        if mode == "VERIFY_AND_INSERT":
            if not evidence_id:
                raise ValueError("page-verified notes require an evidence item")
            evidence = connection.execute(
                """SELECT e.*, s.title AS source_title FROM evidence_items e
                   JOIN sources s ON s.source_id = e.source_id WHERE e.evidence_id = ?""", (evidence_id,)
            ).fetchone()
            if evidence is None:
                raise KeyError(f"unknown evidence item: {evidence_id}")
            source_refs.append({
                "evidence_id": evidence_id, "source_id": evidence["source_id"],
                "source_version_id": evidence["source_version_id"], "page_id": evidence["page_id"],
                "block_id": evidence["block_id"], "physical_page": evidence["physical_page"],
                "source_title": evidence["source_title"],
            })
        note_id, version_id, now = _id("NOTE"), _id("NVER"), utc_now()
        connection.execute(
            """INSERT INTO manuscript_notes(note_id, manuscript_id, anchor_node_id, anchor_offset,
               anchor_text, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (note_id, manuscript_id, anchor_node_id, int(anchor_offset), anchor_text, now, now),
        )
        connection.execute(
            """INSERT INTO manuscript_note_versions(note_version_id, note_id, base_version_id, mode,
               citation_data_json, rendered_text, source_refs_json, verification_state, template_id,
               status, created_at) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (version_id, note_id, mode, _json(citation_data), rendered, _json(source_refs),
             verification_state, template_id, now),
        )
        append_audit(connection, "manuscript_note_proposed", "manuscript_note", note_id,
                     {"note_version_id": version_id, "verification_state": verification_state})
    return note_detail(project_root, note_id)


def revise_note(project_root: Path, note_id: str, mode: str, citation_data: dict[str, Any]) -> dict[str, Any]:
    note = note_detail(project_root, note_id)
    if any(item["status"] == "pending" for item in note["versions"]):
        raise ValueError("this note already has a pending revision")
    rendered, verification_state = render_citation(citation_data, mode)
    current = note.get("current")
    if mode == "REFORMAT_EXISTING" and current:
        if current["verification_state"] in {"PAGE_VERIFIED_INSERTED", "PAGE_VERIFIED_REFORMATTED"}:
            verification_state = "PAGE_VERIFIED_REFORMATTED"
        elif current["verification_state"] == "METADATA_VERIFIED_PAGE_PENDING":
            verification_state = "METADATA_VERIFIED_PAGE_PENDING"
    version_id, now = _id("NVER"), utc_now()
    with connect(project_root) as connection:
        connection.execute(
            """INSERT INTO manuscript_note_versions(note_version_id, note_id, base_version_id, mode,
               citation_data_json, rendered_text, source_refs_json, verification_state, template_id,
               status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (version_id, note_id, note.get("current_version_id"), mode, _json(citation_data), rendered,
             _json(note.get("source_refs", [])), verification_state, note["template_id"], now),
        )
        connection.execute("UPDATE manuscript_notes SET status = 'active', updated_at = ? WHERE note_id = ?",
                           (now, note_id))
    return note_detail(project_root, note_id)


def decide_note(project_root: Path, note_version_id: str, approved: bool, reviewer: str) -> dict[str, Any]:
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("reviewer is required")
    now = utc_now()
    with connect(project_root) as connection:
        version = connection.execute(
            "SELECT * FROM manuscript_note_versions WHERE note_version_id = ?", (note_version_id,)
        ).fetchone()
        if version is None:
            raise KeyError(f"unknown note version: {note_version_id}")
        if version["status"] != "pending":
            raise ValueError(f"note version is already {version['status']}")
        status = "approved" if approved else "rejected"
        connection.execute(
            "UPDATE manuscript_note_versions SET status = ?, decided_at = ?, reviewer = ? WHERE note_version_id = ?",
            (status, now, reviewer, note_version_id),
        )
        if approved:
            connection.execute(
                "UPDATE manuscript_notes SET current_version_id = ?, status = 'active', updated_at = ? WHERE note_id = ?",
                (note_version_id, now, version["note_id"]),
            )
        else:
            current = connection.execute(
                "SELECT current_version_id FROM manuscript_notes WHERE note_id = ?", (version["note_id"],)
            ).fetchone()[0]
            connection.execute(
                "UPDATE manuscript_notes SET status = ?, updated_at = ? WHERE note_id = ?",
                ("active" if current else "rejected", now, version["note_id"]),
            )
        append_audit(connection, "manuscript_note_decided", "manuscript_note", version["note_id"],
                     {"note_version_id": note_version_id, "approved": approved})
    return note_detail(project_root, str(version["note_id"]))


def note_detail(project_root: Path, note_id: str) -> dict[str, Any]:
    with connect(project_root) as connection:
        note = connection.execute("SELECT * FROM manuscript_notes WHERE note_id = ?", (note_id,)).fetchone()
        if note is None:
            raise KeyError(f"unknown manuscript note: {note_id}")
        versions = [dict(row) for row in connection.execute(
            "SELECT * FROM manuscript_note_versions WHERE note_id = ? ORDER BY created_at DESC",
            (note_id,),
        )]
    for version in versions:
        version["citation_data"] = json.loads(version.pop("citation_data_json"))
        version["source_refs"] = json.loads(version.pop("source_refs_json"))
    result = dict(note)
    result["versions"] = versions
    current = next((item for item in versions if item["note_version_id"] == result["current_version_id"]), None)
    display = next((item for item in versions if item["status"] == "pending"), None) or current or versions[0]
    result.update({key: display[key] for key in (
        "note_version_id", "mode", "rendered_text", "verification_state", "template_id", "source_refs"
    )})
    result["pending"] = next((item for item in versions if item["status"] == "pending"), None)
    result["current"] = current
    return result


def list_notes(project_root: Path, manuscript_id: str, approved_only: bool = False) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        query = "SELECT note_id FROM manuscript_notes WHERE manuscript_id = ?"
        params: tuple[Any, ...] = (manuscript_id,)
        if approved_only:
            query += " AND status = 'active' AND current_version_id IS NOT NULL"
        ids = [row[0] for row in connection.execute(query + " ORDER BY created_at", params)]
    notes = [note_detail(project_root, note_id) for note_id in ids]
    if approved_only:
        for note in notes:
            current = note["current"]
            note.update({key: current[key] for key in (
                "note_version_id", "mode", "rendered_text", "verification_state", "template_id", "source_refs"
            )})
    return notes


def check_note_anchors(project_root: Path, manuscript_id: str, tree: dict[str, Any]) -> None:
    texts = {
        str(node.get("node_id")): str(node.get("text", ""))
        for section in tree.get("children", []) for node in section.get("children", [])
    }
    with connect(project_root) as connection:
        for note in connection.execute(
            "SELECT * FROM manuscript_notes WHERE manuscript_id = ? AND status IN ('active', 'pending', 'pending_revision')",
            (manuscript_id,),
        ):
            text = texts.get(str(note["anchor_node_id"]))
            offset, anchor = int(note["anchor_offset"]), str(note["anchor_text"])
            valid = text is not None and 0 <= offset <= len(text)
            if valid and anchor:
                valid = text[max(0, offset - len(anchor)):offset] == anchor
            if not valid:
                connection.execute(
                    "UPDATE manuscript_notes SET status = 'anchor_needs_review', updated_at = ? WHERE note_id = ?",
                    (utc_now(), note["note_id"]),
                )
