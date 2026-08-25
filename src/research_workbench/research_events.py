from __future__ import annotations

import csv
import json
import re
import uuid
from pathlib import Path
from typing import Any

from .db import append_audit, connect, utc_now


PRE_SOURCE_FIELDS = (
    "case_id", "event_date", "start_place", "end_place", "route", "movement_time",
    "distance_original", "distance_normalized", "investigation_object", "recording_technique",
    "chinese_participants", "institutional_task", "movement_mode", "genre",
    "participant_visibility", "outcome_destination",
)
POST_SOURCE_FIELDS = ("original_text", "translation", "missing_reason", "notes")
TEXT_FIELDS = PRE_SOURCE_FIELDS + POST_SOURCE_FIELDS

EVENT_EXPORT_FIELDS = (
    "event_id", "case_id", "event_date", "start_place", "end_place", "route",
    "movement_time", "distance_original", "distance_normalized", "movement_mode",
    "investigation_object", "recording_technique", "genre", "chinese_participants",
    "participant_visibility", "institutional_task", "outcome_destination", "source_title",
    "source_id", "source_version_id", "physical_pages", "printed_pages", "block_ids",
    "original_text", "translation", "missing_reason", "notes", "qualification", "status",
    "decided_by", "decision_reason",
)

SOURCE_ANCHORED_FIELDS = {
    "event_date", "start_place", "end_place", "route", "movement_time",
    "distance_original", "investigation_object", "recording_technique",
    "chinese_participants", "institutional_task", "movement_mode", "genre",
    "participant_visibility", "outcome_destination", "original_text", "translation",
}

COVERAGE_FIELDS = (
    "route", "movement_time", "distance_original", "investigation_object",
    "recording_technique", "chinese_participants", "institutional_task",
    "movement_mode", "genre", "participant_visibility", "outcome_destination",
)

MISSING_CODE = re.compile(r"^(NR|UNC|PND)(?:$|[\s:：\-(（—])", re.IGNORECASE)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _decode(value: str | None, fallback: Any) -> Any:
    return json.loads(value) if value else fallback


def _qualified_block_id(source_id: str, value: Any) -> str:
    block_id = str(value).strip()
    if not block_id or block_id.startswith(f"{source_id}:"):
        return block_id
    if block_id.startswith("SRC_") and ":" in block_id:
        return block_id
    return f"{source_id}:{block_id}"


def _validate_missing_codes(values: dict[str, str]) -> None:
    for field_name in SOURCE_ANCHORED_FIELDS:
        match = MISSING_CODE.match(values[field_name])
        if match:
            code = match.group(1).upper()
            raise ValueError(
                f"source-derived event field {field_name} cannot contain missing code {code}; "
                f"leave {field_name} blank and record {code} in missing_reason"
            )


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


def event_state(
    project_root: Path,
    case_ids: list[str] | None = None,
    statuses: list[str] | None = None,
    detail: str = "full",
) -> dict[str, Any]:
    if detail not in {"full", "summary"}:
        raise ValueError("research event detail must be full or summary")
    selected_case_ids = {
        str(case_id).strip() for case_id in (case_ids or []) if str(case_id).strip()
    }
    selected_statuses = {
        str(status).strip() for status in (statuses or []) if str(status).strip()
    }
    unknown_statuses = selected_statuses - {"draft", "approved", "rejected"}
    if unknown_statuses:
        raise ValueError(f"unknown research event status: {', '.join(sorted(unknown_statuses))}")
    with connect(project_root) as connection:
        rows = connection.execute(
            "SELECT * FROM research_event_rows ORDER BY created_at DESC, event_id DESC"
        ).fetchall()
        anchors = _anchor_map(connection, [row["event_id"] for row in rows])
    events = [_public(row, anchors.get(row["event_id"], {})) for row in rows]
    if selected_case_ids:
        events = [item for item in events if item["case_id"] in selected_case_ids]
    if selected_statuses:
        events = [item for item in events if item["status"] in selected_statuses]
    if detail == "summary":
        for item in events:
            item.pop("original_text", None)
            item.pop("translation", None)
            item.pop("model_snapshot", None)
    return {
        "events": events,
        "counts": {
            status: sum(item["status"] == status for item in events)
            for status in ("draft", "approved", "rejected")
        },
        "filters": {
            "case_ids": sorted(selected_case_ids),
            "statuses": sorted(selected_statuses),
            "detail": detail,
        },
    }


def event_coverage(project_root: Path, case_ids: list[str] | None = None) -> dict[str, Any]:
    state = event_state(project_root)
    approved = [item for item in state["events"] if item["status"] == "approved"]
    selected_case_ids = list(dict.fromkeys(
        str(case_id).strip() for case_id in (case_ids or []) if str(case_id).strip()
    ))
    if not selected_case_ids:
        selected_case_ids = sorted({str(item["case_id"]) for item in approved})

    def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(events)
        fields: dict[str, Any] = {}
        for field_name in COVERAGE_FIELDS:
            nonempty = sum(bool(str(item[field_name]).strip()) for item in events)
            anchored = sum(
                bool(str(item[field_name]).strip())
                and bool(item["field_anchors"].get(field_name))
                for item in events
            )
            fields[field_name] = {
                "anchored": anchored,
                "nonempty": nonempty,
                "unanchored_nonempty": nonempty - anchored,
                "total": total,
                "percent": round(anchored * 100 / total, 1) if total else None,
            }
        movement_cost = sum(
            any(
                bool(str(item[field_name]).strip())
                and bool(item["field_anchors"].get(field_name))
                for field_name in ("movement_time", "distance_original")
            )
            for item in events
        )
        return {
            "approved_events": total,
            "fields": fields,
            "movement_cost_any": {
                "anchored": movement_cost,
                "total": total,
                "percent": round(movement_cost * 100 / total, 1) if total else None,
            },
        }

    selected = [item for item in approved if item["case_id"] in selected_case_ids]
    other_counts: dict[str, int] = {}
    for item in approved:
        if item["case_id"] not in selected_case_ids:
            other_counts[item["case_id"]] = other_counts.get(item["case_id"], 0) + 1
    return {
        "selected_case_ids": selected_case_ids,
        "selected_approved_total": len(selected),
        "cases": {
            case_id: summarize([item for item in selected if item["case_id"] == case_id])
            for case_id in selected_case_ids
        },
        "combined": summarize(selected),
        "other_approved_cases": [
            {"case_id": case_id, "approved_events": count}
            for case_id, count in sorted(other_counts.items())
        ],
        "global_counts": state["counts"],
        "coverage_rule": "non-empty source-derived field with at least one explicit field anchor",
    }


def _chronicle_summary(event: dict[str, Any]) -> str:
    parts = []
    for label, key in (
        ("路线", "route"), ("调查", "investigation_object"),
        ("记录", "recording_technique"), ("参与", "chinese_participants"),
        ("任务", "institutional_task"), ("去向", "outcome_destination"),
    ):
        value = str(event.get(key, "")).strip()
        if value:
            parts.append(f"{label}：{value}")
    return "；".join(parts) or str(event.get("notes", "")).strip()


def event_chronicle(
    project_root: Path,
    query: str = "",
    year: str = "",
    case_id: str = "",
    source_id: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    """Return a source-grounded chronological compilation from approved event rows."""
    query, year, case_id, source_id = (
        str(value).strip() for value in (query, year, case_id, source_id)
    )
    limit = max(1, min(int(limit), 5000))
    state = event_state(project_root, statuses=["approved"])
    with connect(project_root) as connection:
        source_titles = {
            row["source_id"]: row["title"]
            for row in connection.execute("SELECT source_id, title FROM sources")
        }
    rows = []
    for event in state["events"]:
        year_match = re.search(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)", str(event["event_date"]))
        event_year = year_match.group(1) if year_match else ""
        if year and event_year != year:
            continue
        if case_id and event["case_id"] != case_id:
            continue
        if source_id and event["source_id"] != source_id:
            continue
        source_title = source_titles.get(event["source_id"], event["source_id"])
        haystack = "\n".join(str(event.get(key, "")) for key in TEXT_FIELDS)
        haystack += f"\n{source_title}\n{event['case_id']}"
        if query and query.casefold() not in haystack.casefold():
            continue
        rows.append({
            "event_id": event["event_id"],
            "event_date": event["event_date"],
            "year": event_year,
            "case_id": event["case_id"],
            "source_id": event["source_id"],
            "source_title": source_title,
            "source_version_id": event["source_version_id"],
            "page_ids": event["page_ids"],
            "physical_pages": event["physical_pages"],
            "printed_pages": event["printed_pages"],
            "block_ids": event["block_ids"],
            "summary": _chronicle_summary(event),
            "original_text": event["original_text"],
            "translation": event["translation"],
            "qualification": event["qualification"],
        })
    rows.sort(key=lambda item: (item["event_date"] or "9999", item["case_id"], item["event_id"]))
    total_count = len(rows)
    available_years = sorted({row["year"] for row in rows if row["year"]})
    available_cases = sorted({row["case_id"] for row in rows})
    rows = rows[:limit]
    return {
        "entries": rows,
        "total_count": total_count,
        "returned_count": len(rows),
        "has_more": total_count > len(rows),
        "filters": {"query": query, "year": year, "case_id": case_id, "source_id": source_id},
        "available_years": available_years,
        "available_cases": available_cases,
        "boundary": (
            "Only human-approved, page-linked event rows are included. This is a saved source "
            "chronicle, not an automatic claim that every relevant passage has been found."
        ),
    }


def export_event_chronicle(
    project_root: Path, query: str = "", year: str = "", case_id: str = "",
    source_id: str = "", name: str = "史料长编",
) -> dict[str, Any]:
    chronicle = event_chronicle(project_root, query, year, case_id, source_id, limit=5000)
    name = name.strip() or "史料长编"
    lines = [f"# {name}", ""]
    for entry in chronicle["entries"]:
        pages = "、".join(str(value) for value in entry["printed_pages"] or entry["physical_pages"])
        lines.extend([
            f"## {entry['event_date'] or '日期待考'}　{entry['case_id']}", "",
            entry["summary"] or "（本条尚无内容提要）", "",
            f"> {entry['original_text']}" if entry["original_text"] else "> （原文待补）", "",
        ])
        if entry["translation"]:
            lines.extend([f"译文：{entry['translation']}", ""])
        lines.extend([
            f"来源：{entry['source_title']}，页码 {pages or '待核'}。",
            f"回链：{entry['source_id']} / {entry['source_version_id']} / {entry['event_id']}", "",
        ])
    safe_name = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", name).strip("-") or "史料长编"
    target = project_root / "exports" / f"{safe_name}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    receipt = {
        "project_path": target.relative_to(project_root).as_posix(),
        "row_count": chronicle["returned_count"],
        "filters": chronicle["filters"], "name": name,
    }
    with connect(project_root) as connection:
        append_audit(
            connection, "source_chronicle_exported", "project", "source_chronicle", receipt,
        )
    return receipt


def export_event_register(
    project_root: Path,
    case_ids: list[str] | None = None,
    statuses: list[str] | None = None,
) -> dict[str, Any]:
    selected_statuses = statuses or ["approved"]
    state = event_state(project_root, case_ids=case_ids, statuses=selected_statuses)
    with connect(project_root) as connection:
        source_titles = {
            row["source_id"]: row["title"]
            for row in connection.execute("SELECT source_id, title FROM sources")
        }
    export_root = project_root / "exports"
    export_root.mkdir(parents=True, exist_ok=True)
    target = export_root / "research-events-approved.csv"
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENT_EXPORT_FIELDS)
        writer.writeheader()
        for event in sorted(
            state["events"], key=lambda item: (item["case_id"], item["event_date"], item["event_id"])
        ):
            row = {field: event.get(field, "") for field in EVENT_EXPORT_FIELDS}
            row["source_title"] = source_titles.get(event["source_id"], "")
            for field in ("physical_pages", "printed_pages", "block_ids"):
                row[field] = " | ".join(str(value) for value in event.get(field, []))
            writer.writerow(row)
    append_payload = {
        "case_ids": state["filters"]["case_ids"],
        "statuses": state["filters"]["statuses"],
        "row_count": len(state["events"]),
        "project_path": str(target.relative_to(project_root)),
    }
    with connect(project_root) as connection:
        append_audit(
            connection, "research_event_register_exported", "project", "research_events",
            append_payload,
        )
    return append_payload


def event_anchor_text(project_root: Path, event_id: str) -> dict[str, Any]:
    with connect(project_root) as connection:
        row = connection.execute(
            "SELECT event_id, original_text FROM research_event_rows WHERE event_id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown research event: {event_id}")
        anchors = _anchor_map(connection, [event_id]).get(event_id, {}).get("original_text", [])
        if not anchors:
            raise ValueError("research event has no original_text anchors")
        placeholders = ",".join("?" for _ in anchors)
        blocks = connection.execute(
            """SELECT block_id, COALESCE(human_text, machine_text) AS text FROM blocks
               WHERE block_id IN (""" + placeholders + ")",
            anchors,
        ).fetchall()
        by_id = {block["block_id"]: block["text"] for block in blocks}
        if any(block_id not in by_id for block_id in anchors):
            raise KeyError("research event references an unavailable original_text block")
        original_text = "\n".join(by_id[block_id] for block_id in anchors)
    return {
        "event_id": event_id,
        "block_ids": anchors,
        "original_text": original_text,
        "changed": original_text != row["original_text"],
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
            _validate_missing_codes(values)
            source_id = str(payload.get("source_id", "")).strip()
            block_ids = list(dict.fromkeys(
                _qualified_block_id(source_id, value)
                for value in payload.get("block_ids", []) if str(value).strip()
            ))
            if not values["case_id"] or not source_id or not block_ids:
                raise ValueError("case_id, source_id and block_ids are required")
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
                normalized = list(dict.fromkeys(
                    _qualified_block_id(source_id, value) for value in anchors if str(value).strip()
                ))
                if any(block_id not in block_ids for block_id in normalized):
                    raise ValueError(f"field anchor for {field_name} must belong to the event blocks")
                if normalized:
                    field_anchors[field_name] = normalized
            original_text_copied = not values["original_text"]
            if original_text_copied:
                quote_anchors = field_anchors.get("original_text", [])
                if not quote_anchors:
                    quote_anchors = list(block_ids)
                    field_anchors["original_text"] = quote_anchors
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
            record = {
                "event_id": event_id,
                **values,
                "source_id": source_id,
                "source_version_id": version["source_version_id"],
                "page_ids_json": _json(page_ids),
                "block_ids_json": _json(block_ids),
                "physical_pages_json": _json(physical_pages),
                "printed_pages_json": _json(printed_pages),
                "qualification": "PAGE_LINKED_EVENT_NOT_FROZEN",
                "origin": origin,
                "model_snapshot_json": _json(model_snapshot or {}),
                "status": "draft",
                "created_by": created_by,
                "created_at": now,
            }
            columns = (
                "event_id", *PRE_SOURCE_FIELDS, "source_id", "source_version_id",
                "page_ids_json", "block_ids_json", "physical_pages_json", "printed_pages_json",
                *POST_SOURCE_FIELDS, "qualification", "origin", "model_snapshot_json",
                "status", "created_by", "created_at",
            )
            connection.execute(
                f"INSERT INTO research_event_rows({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                tuple(record[column] for column in columns),
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
    field_anchor_edits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reviewer, reason = reviewer.strip(), reason.strip()
    if not reviewer or not reason:
        raise ValueError("event decision requires reviewer and reason")
    edits = edits or {}
    field_anchor_edits = field_anchor_edits or {}
    now = utc_now()
    with connect(project_root) as connection:
        row = connection.execute(
            "SELECT * FROM research_event_rows WHERE event_id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown research event: {event_id}")
        current_status = str(row["status"])
        revising = current_status == "approved"
        if current_status not in {"draft", "approved"} or (revising and not approved):
            raise ValueError(f"research event is already {current_status}")
        values = {
            key: str(edits[key]).strip() if key in edits else str(row[key])
            for key in TEXT_FIELDS
        }
        field_anchors = _anchor_map(connection, [event_id]).get(event_id, {})
        previous_anchors = {key: list(value) for key, value in field_anchors.items()}
        page_snapshot = {
            "page_ids_json": row["page_ids_json"],
            "physical_pages_json": row["physical_pages_json"],
            "printed_pages_json": row["printed_pages_json"],
        }
        if approved:
            if not values["case_id"] or not values["original_text"]:
                raise ValueError("approved events require case_id and original_text")
            _validate_missing_codes(values)
            block_ids = _decode(row["block_ids_json"], [])
            unknown_anchor_fields = set(field_anchor_edits) - SOURCE_ANCHORED_FIELDS
            if unknown_anchor_fields:
                raise ValueError(
                    f"unsupported event field anchors: {', '.join(sorted(unknown_anchor_fields))}"
                )
            for field_name, raw_anchors in field_anchor_edits.items():
                if not isinstance(raw_anchors, list):
                    raise ValueError(f"field anchor for {field_name} must be a block list")
                anchors = list(dict.fromkeys(
                    _qualified_block_id(row["source_id"], value)
                    for value in raw_anchors if str(value).strip()
                ))
                if any(block_id not in block_ids for block_id in anchors):
                    raise ValueError(f"field anchor for {field_name} must belong to the event blocks")
                if anchors:
                    field_anchors[field_name] = anchors
                else:
                    field_anchors.pop(field_name, None)
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
                if block["block_use_state"] != "research_usable":
                    raise ValueError("blocked block content cannot approve a research event")
            unverified_blocks = [
                block["block_id"] for block in blocks
                if block["block_verification_state"] not in {"human_verified", "human_repaired"}
            ]
            if unverified_blocks:
                raise ValueError(
                    "event text blocks require human verification before approval: "
                    + ", ".join(unverified_blocks)
                )
            for block in blocks:
                if block["page_verification_state"] not in {"human_spot_checked", "human_verified", "human_repaired"}:
                    raise ValueError("event pages require human verification before approval")
            current_pages = connection.execute(
                """SELECT DISTINCT p.page_id, p.physical_page, p.printed_page
                   FROM pages p JOIN blocks b ON b.page_id = p.page_id
                   WHERE b.block_id IN (""" + placeholders + ") ORDER BY p.physical_page",
                block_ids,
            ).fetchall()
            page_snapshot = {
                "page_ids_json": _json([page["page_id"] for page in current_pages]),
                "physical_pages_json": _json([page["physical_page"] for page in current_pages]),
                "printed_pages_json": _json(list(dict.fromkeys(
                    str(page["printed_page"]) for page in current_pages if page["printed_page"]
                ))),
            }
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
        edited_fields = [key for key in TEXT_FIELDS if values[key] != str(row[key])]
        edited_anchors = [
            key for key in SOURCE_ANCHORED_FIELDS
            if previous_anchors.get(key, []) != field_anchors.get(key, [])
        ]
        assignments = ", ".join(f"{key} = ?" for key in TEXT_FIELDS)
        updated = connection.execute(
            f"""UPDATE research_event_rows SET {assignments}, page_ids_json = ?,
                       physical_pages_json = ?, printed_pages_json = ?, status = ?, decided_by = ?,
                       decision_reason = ?, decided_at = ? WHERE event_id = ? AND status = ?""",
            (*(values[key] for key in TEXT_FIELDS), page_snapshot["page_ids_json"],
             page_snapshot["physical_pages_json"], page_snapshot["printed_pages_json"],
             status, reviewer, reason, now, event_id, current_status),
        )
        if updated.rowcount != 1:
            raise RuntimeError("research event changed during the decision")
        for field_name in edited_anchors:
            connection.execute(
                "DELETE FROM research_event_field_anchors WHERE event_id = ? AND field_name = ?",
                (event_id, field_name),
            )
            connection.executemany(
                """INSERT INTO research_event_field_anchors(
                       event_id, field_name, block_id, anchor_order
                   ) VALUES (?, ?, ?, ?)""",
                [
                    (event_id, field_name, block_id, index)
                    for index, block_id in enumerate(field_anchors.get(field_name, []))
                ],
            )
        event_type = "research_event_revised" if revising else "research_event_decided"
        append_audit(
            connection,
            event_type,
            "research_event",
            event_id,
            {
                "approved": approved,
                "reviewer": reviewer,
                "reason": reason,
                "edited_fields": edited_fields,
                "edited_anchors": edited_anchors,
                "before": {key: str(row[key]) for key in edited_fields},
                "after": {key: values[key] for key in edited_fields},
                "page_snapshot_refreshed": approved,
            },
        )
        decided = connection.execute(
            "SELECT * FROM research_event_rows WHERE event_id = ?", (event_id,)
        ).fetchone()
    return _public(decided, field_anchors)
