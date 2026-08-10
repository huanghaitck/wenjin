from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from .db import append_audit, connect, utc_now


TEXT_FIELDS = (
    "case_id", "event_date", "start_place", "end_place", "route", "movement_time",
    "distance_original", "distance_normalized", "investigation_object", "recording_technique",
    "chinese_participants", "institutional_task", "original_text", "translation",
    "missing_reason", "notes",
)

SOURCE_ANCHORED_FIELDS = {
    "event_date", "start_place", "end_place", "route", "movement_time",
    "distance_original", "investigation_object", "recording_technique",
    "chinese_participants", "institutional_task", "original_text", "translation",
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _decode(value: str | None, fallback: Any) -> Any:
    return json.loads(value) if value else fallback


def _public(row: Any, field_anchors: dict[str, list[str]] | None = None) -> dict[str, Any]:
    item = dict(row)
    for key in ("page_ids", "block_ids", "physical_pages", "printed_pages"):
        item[key] = _decode(item.pop(f"{key}_json"), [])
    item["model_snapshot"] = _decode(item.pop("model_snapshot_json"), {})
    item["field_anchors"] = field_anchors or {}
    return item


def _anchor_map(connection: Any, event_ids: list[str]) -> dict[str, dict[str, list[str]]]:
    if not event_ids:
        return {}
    placeholders = ",".join("?" for _ in event_ids)
    rows = connection.execute(
        """SELECT event_id, field_name, block_id FROM research_event_field_anchors
           WHERE event_id IN (""" + placeholders + ") ORDER BY event_id, field_name, anchor_order",
        event_ids,
    ).fetchall()
    result: dict[str, dict[str, list[str]]] = {}
    for row in rows:
        result.setdefault(row["event_id"], {}).setdefault(row["field_name"], []).append(row["block_id"])
    return result


def event_state(project_root: Path) -> dict[str, Any]:
    with connect(project_root) as connection:
        rows = connection.execute(
            "SELECT * FROM research_event_rows ORDER BY created_at DESC, event_id DESC"
        ).fetchall()
        anchors = _anchor_map(connection, [row["event_id"] for row in rows])
    events = [_public(row, anchors.get(row["event_id"], {})) for row in rows]
    return {
        "events": events,
        "counts": {
            status: sum(item["status"] == status for item in events)
            for status in ("draft", "approved", "rejected")
        },
    }


def create_event_candidates(
    project_root: Path,
    events: list[dict[str, Any]],
    created_by: str,
    origin: str = "model",
    model_snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    created_by = created_by.strip()
    if not created_by:
        raise ValueError("event candidate creator is required")
    if not events or len(events) > 20:
        raise ValueError("an event proposal batch must contain 1 to 20 rows")
    created = []
    with connect(project_root) as connection:
        for payload in events:
            values = {key: str(payload.get(key, "")).strip() for key in TEXT_FIELDS}
            source_id = str(payload.get("source_id", "")).strip()
            block_ids = list(dict.fromkeys(
                str(value).strip() for value in payload.get("block_ids", []) if str(value).strip()
            ))
            if not values["case_id"] or not source_id or not block_ids:
                raise ValueError("case_id, source_id and block_ids are required")
            if len(block_ids) > 12:
                raise ValueError("an event row may reference at most 12 blocks")
            placeholders = ",".join("?" for _ in block_ids)
            rows = [dict(row) for row in connection.execute(
                """SELECT b.block_id, b.block_order, p.page_id, p.physical_page, p.printed_page,
                          p.source_id, COALESCE(b.human_text, b.machine_text) AS text
                   FROM blocks b JOIN pages p ON p.page_id = b.page_id
                   WHERE b.block_id IN (""" + placeholders + ")", block_ids
            )]
            by_id = {row["block_id"]: row for row in rows}
            if any(block_id not in by_id for block_id in block_ids):
                raise KeyError("event candidate references an unknown block")
            ordered = sorted((by_id[value] for value in block_ids),
                             key=lambda row: (row["physical_page"], row["block_order"]))
            if [row["block_id"] for row in ordered] != block_ids:
                raise ValueError("event blocks must be ordered by physical page and block order")
            if {row["source_id"] for row in ordered} != {source_id}:
                raise ValueError("event blocks must belong to the selected source")
            supplied_anchors = payload.get("field_anchors", {})
            if not isinstance(supplied_anchors, dict):
                raise ValueError("field_anchors must map source-derived fields to block lists")
            unknown_fields = set(supplied_anchors) - SOURCE_ANCHORED_FIELDS
            if unknown_fields:
                raise ValueError(f"unsupported event field anchors: {', '.join(sorted(unknown_fields))}")
            field_anchors: dict[str, list[str]] = {}
            for field_name in SOURCE_ANCHORED_FIELDS:
                anchors = supplied_anchors.get(field_name, [])
                if not isinstance(anchors, list):
                    raise ValueError(f"field anchor for {field_name} must be a block list")
                normalized = list(dict.fromkeys(str(value).strip() for value in anchors if str(value).strip()))
                if any(block_id not in block_ids for block_id in normalized):
                    raise ValueError(f"field anchor for {field_name} must belong to the event blocks")
                if normalized:
                    field_anchors[field_name] = normalized
            original_text_copied = not values["original_text"]
            if original_text_copied:
                quote_anchors = field_anchors.get("original_text", [])
                if not quote_anchors:
                    raise ValueError("original_text or its explicit block anchors are required")
                values["original_text"] = "\n".join(by_id[block_id]["text"] for block_id in quote_anchors)
            for field_name in SOURCE_ANCHORED_FIELDS:
                if values[field_name] and not field_anchors.get(field_name):
                    raise ValueError(f"source-derived event field {field_name} requires explicit block anchors")
            version = connection.execute(
                "SELECT source_version_id FROM source_versions WHERE source_id = ? ORDER BY created_at DESC LIMIT 1",
                (source_id,),
            ).fetchone()
            if version is None:
                raise ValueError("event source has no registered version")
            page_ids = list(dict.fromkeys(row["page_id"] for row in ordered))
            physical_pages = list(dict.fromkeys(row["physical_page"] for row in ordered))
            printed_pages = list(dict.fromkeys(
                str(row["printed_page"]) for row in ordered if row["printed_page"] not in (None, "")
            ))
            event_id, now = f"EVT_{uuid.uuid4().hex}", utc_now()
            connection.execute(
                """INSERT INTO research_event_rows(
                       event_id, case_id, event_date, start_place, end_place, route, movement_time,
                       distance_original, distance_normalized, investigation_object, recording_technique,
                       chinese_participants, institutional_task, source_id, source_version_id,
                       page_ids_json, block_ids_json, physical_pages_json, printed_pages_json,
                       original_text, translation, missing_reason, notes, qualification, origin,
                       model_snapshot_json, status, created_by, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                             'PAGE_LINKED_EVENT_NOT_FROZEN', ?, ?, 'draft', ?, ?)""",
                (event_id, *(values[key] for key in TEXT_FIELDS[:12]), source_id,
                 version["source_version_id"], _json(page_ids), _json(block_ids), _json(physical_pages),
                 _json(printed_pages), *(values[key] for key in TEXT_FIELDS[12:]), origin,
                 _json(model_snapshot or {}), created_by, now),
            )
            append_audit(connection, "research_event_candidate_created", "research_event", event_id,
                         {"case_id": values["case_id"], "source_id": source_id, "block_ids": block_ids,
                          "original_text_mode": "anchor_copy" if original_text_copied else "submitted_exact_text"})
            for field_name, anchors in field_anchors.items():
                connection.executemany(
                    """INSERT INTO research_event_field_anchors(
                           event_id, field_name, block_id, anchor_order
                       ) VALUES (?, ?, ?, ?)""",
                    [(event_id, field_name, block_id, index) for index, block_id in enumerate(anchors)],
                )
            row = connection.execute(
                "SELECT * FROM research_event_rows WHERE event_id = ?", (event_id,)
            ).fetchone()
            created.append(_public(row, field_anchors))
    return created


def decide_event(
    project_root: Path,
    event_id: str,
    approved: bool,
    reviewer: str,
    reason: str,
    edits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reviewer, reason = reviewer.strip(), reason.strip()
    if not reviewer or not reason:
        raise ValueError("event decision requires reviewer and reason")
    edits = edits or {}
    now = utc_now()
    with connect(project_root) as connection:
        row = connection.execute(
            "SELECT * FROM research_event_rows WHERE event_id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown research event: {event_id}")
        if row["status"] != "draft":
            raise ValueError(f"research event is already {row['status']}")
        values = {
            key: str(edits[key]).strip() if key in edits else str(row[key])
            for key in TEXT_FIELDS
        }
        field_anchors = _anchor_map(connection, [event_id]).get(event_id, {})
        if approved:
            if not values["case_id"] or not values["original_text"]:
                raise ValueError("approved events require case_id and original_text")
            block_ids = _decode(row["block_ids_json"], [])
            placeholders = ",".join("?" for _ in block_ids)
            blocks = [dict(block) for block in connection.execute(
                """SELECT b.block_id, b.block_order, b.use_state AS block_use_state,
                          b.verification_state AS block_verification_state,
                          COALESCE(b.human_text, b.machine_text) AS text,
                          p.physical_page, p.use_state AS page_use_state,
                          p.verification_state AS page_verification_state
                   FROM blocks b JOIN pages p ON p.page_id = b.page_id
                   WHERE b.block_id IN (""" + placeholders + ")", block_ids
            )]
            by_id = {block["block_id"]: block for block in blocks}
            blocks = [by_id[value] for value in block_ids]
            for block in blocks:
                if block["block_use_state"] != "research_usable" or block["page_use_state"] != "research_usable":
                    raise ValueError("blocked page content cannot approve a research event")
                if block["block_verification_state"] not in {"human_verified", "human_repaired"}:
                    raise ValueError("every event text block requires human verification before approval")
                if block["page_verification_state"] not in {"human_spot_checked", "human_verified", "human_repaired"}:
                    raise ValueError("event pages require human verification before approval")
            for field_name in SOURCE_ANCHORED_FIELDS:
                if values[field_name] and not field_anchors.get(field_name):
                    raise ValueError(f"source-derived event field {field_name} requires explicit block anchors")
            quote_block_ids = field_anchors["original_text"]
            normalized_source = re.sub(
                r"\s+", " ", "\n".join(by_id[block_id]["text"] for block_id in quote_block_ids)
            ).strip()
            normalized_quote = re.sub(r"\s+", " ", values["original_text"]).strip()
            if normalized_quote not in normalized_source:
                raise ValueError("event original text must occur in the verified source blocks")
        status = "approved" if approved else "rejected"
        assignments = ", ".join(f"{key} = ?" for key in TEXT_FIELDS)
        connection.execute(
            f"""UPDATE research_event_rows SET {assignments}, status = ?, decided_by = ?,
                       decision_reason = ?, decided_at = ? WHERE event_id = ? AND status = 'draft'""",
            (*(values[key] for key in TEXT_FIELDS), status, reviewer, reason, now, event_id),
        )
        append_audit(connection, "research_event_decided", "research_event", event_id,
                     {"approved": approved, "reviewer": reviewer, "reason": reason})
        decided = connection.execute(
            "SELECT * FROM research_event_rows WHERE event_id = ?", (event_id,)
        ).fetchone()
    return _public(decided, field_anchors)
