from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .db import append_audit, connect, utc_now


ROLES = {"researcher_baseline", "shared_design"}
ORIGINS = {"imported", "manual", "conversation", "model"}


def _decode(value: str | None) -> dict[str, Any]:
    return json.loads(value or "{}")


def _public(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["model_snapshot"] = _decode(item.pop("model_snapshot_json"))
    return item


def design_state(project_root: Path) -> dict[str, Any]:
    with connect(project_root) as connection:
        rows = connection.execute(
            """SELECT * FROM research_design_versions
               ORDER BY created_at DESC, design_id DESC"""
        ).fetchall()
    versions = [_public(row) for row in rows]
    return {
        "researcher_baseline": next(
            (item for item in versions if item["plan_role"] == "researcher_baseline" and item["status"] == "approved"),
            None,
        ),
        "shared_design": next(
            (item for item in versions if item["plan_role"] == "shared_design" and item["status"] == "approved"),
            None,
        ),
        "versions": versions,
    }


def current_shared_design(project_root: Path) -> dict[str, Any] | None:
    return design_state(project_root)["shared_design"]


def create_design_draft(
    project_root: Path,
    title: str,
    content: str,
    plan_role: str,
    origin: str,
    created_by: str,
    change_summary: str = "",
    base_design_id: str = "",
    origin_ref: str = "",
    model_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    title, content, created_by = title.strip(), content.strip(), created_by.strip()
    if not title or not content or not created_by:
        raise ValueError("title, content and created_by are required")
    if plan_role not in ROLES:
        raise ValueError(f"unknown research design role: {plan_role}")
    if origin not in ORIGINS:
        raise ValueError(f"unknown research design origin: {origin}")
    design_id, now = f"RDP_{uuid.uuid4().hex}", utc_now()
    with connect(project_root) as connection:
        if base_design_id and connection.execute(
            "SELECT 1 FROM research_design_versions WHERE design_id = ?", (base_design_id,)
        ).fetchone() is None:
            raise KeyError(f"unknown base research design: {base_design_id}")
        connection.execute(
            """INSERT INTO research_design_versions(
                   design_id, base_design_id, title, content, change_summary, plan_role,
                   origin, origin_ref, model_snapshot_json, status, created_by, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)""",
            (design_id, base_design_id or None, title, content, change_summary.strip(), plan_role,
             origin, origin_ref.strip(), json.dumps(model_snapshot or {}, ensure_ascii=False, sort_keys=True),
             created_by, now),
        )
        append_audit(connection, "research_design_draft_created", "research_design", design_id,
                     {"plan_role": plan_role, "origin": origin})
        row = connection.execute(
            "SELECT * FROM research_design_versions WHERE design_id = ?", (design_id,)
        ).fetchone()
    return _public(row)


def decide_design(
    project_root: Path,
    design_id: str,
    approved: bool,
    reviewer: str,
    reason: str,
    edited_title: str | None = None,
    edited_content: str | None = None,
) -> dict[str, Any]:
    reviewer, reason = reviewer.strip(), reason.strip()
    if not reviewer or not reason:
        raise ValueError("reviewer and reason are required")
    now = utc_now()
    with connect(project_root) as connection:
        row = connection.execute(
            "SELECT * FROM research_design_versions WHERE design_id = ?", (design_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown research design: {design_id}")
        if row["status"] != "draft":
            raise ValueError(f"research design is already {row['status']}")
        title = (edited_title if edited_title is not None else row["title"]).strip()
        content = (edited_content if edited_content is not None else row["content"]).strip()
        if approved and (not title or not content):
            raise ValueError("approved research design requires title and content")
        if approved:
            connection.execute(
                """UPDATE research_design_versions
                   SET status = 'superseded', decided_at = ?
                   WHERE plan_role = ? AND status = 'approved'""",
                (now, row["plan_role"]),
            )
        status = "approved" if approved else "rejected"
        connection.execute(
            """UPDATE research_design_versions
               SET title = ?, content = ?, status = ?, decided_by = ?, decision_reason = ?, decided_at = ?
               WHERE design_id = ? AND status = 'draft'""",
            (title, content, status, reviewer, reason, now, design_id),
        )
        append_audit(connection, "research_design_decided", "research_design", design_id,
                     {"approved": approved, "reviewer": reviewer, "reason": reason})
        decided = connection.execute(
            "SELECT * FROM research_design_versions WHERE design_id = ?", (design_id,)
        ).fetchone()
    return _public(decided)
