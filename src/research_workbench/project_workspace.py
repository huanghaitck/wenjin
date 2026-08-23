from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db import connect
from .readiness import formal_research_readiness


def _count(connection: Any, query: str, parameters: tuple[Any, ...] = ()) -> int:
    return int(connection.execute(query, parameters).fetchone()[0])


def project_workspace_state(project_root: Path) -> dict[str, Any]:
    readiness = formal_research_readiness(project_root)
    with connect(project_root) as connection:
        project = dict(connection.execute("SELECT * FROM projects LIMIT 1").fetchone())
        sources = [dict(row) for row in connection.execute(
            """SELECT s.source_id, s.title, s.processing_state, s.use_state,
                      COUNT(DISTINCT p.page_id) AS page_count,
                      SUM(CASE WHEN p.verification_state IN ('human_verified','human_repaired') THEN 1 ELSE 0 END) AS verified_pages,
                      (SELECT COUNT(*) FROM anomalies a WHERE a.source_id=s.source_id AND a.status='open') AS open_anomalies
               FROM sources s LEFT JOIN pages p ON p.source_id=s.source_id
               GROUP BY s.source_id ORDER BY s.created_at"""
        ).fetchall()]
        counts = {
            "sources": len(sources),
            "research_usable_sources": sum(item["use_state"] == "accepted" or item["use_state"] == "research_usable" for item in sources),
            "open_anomalies": _count(connection, "SELECT COUNT(*) FROM anomalies WHERE status='open'"),
            "threads": _count(connection, "SELECT COUNT(*) FROM threads"),
            "runs": _count(connection, "SELECT COUNT(*) FROM runs"),
            "waiting_approvals": _count(connection, "SELECT COUNT(*) FROM approvals WHERE status='pending'"),
            "approved_events": _count(connection, "SELECT COUNT(*) FROM research_event_rows WHERE status='approved'"),
            "candidate_events": _count(connection, "SELECT COUNT(*) FROM research_event_rows WHERE status='draft'"),
            "claims": _count(connection, "SELECT COUNT(*) FROM claims"),
            "verified_evidence": _count(connection, "SELECT COUNT(*) FROM evidence_items WHERE status='verified'"),
            "approved_freezes": _count(connection, "SELECT COUNT(*) FROM evidence_freezes WHERE status='approved'"),
            "reading_jobs": _count(connection, "SELECT COUNT(*) FROM reading_jobs"),
            "completed_reading_jobs": _count(connection, "SELECT COUNT(*) FROM reading_jobs WHERE status='completed'"),
            "approved_historiography": _count(connection, "SELECT COUNT(*) FROM historiography_entries WHERE status='approved'"),
            "manuscripts": _count(connection, "SELECT COUNT(*) FROM manuscripts"),
            "sections": _count(connection, "SELECT COUNT(*) FROM manuscript_sections"),
            "pending_writing_proposals": _count(connection, "SELECT COUNT(*) FROM writing_proposals WHERE status='pending'"),
            "reviews": _count(connection, "SELECT COUNT(*) FROM manuscript_reviews"),
            "exports": _count(connection, "SELECT COUNT(*) FROM document_io_receipts WHERE direction='export'"),
        }
        baseline = connection.execute(
            """SELECT design_id, title, status FROM research_design_versions
               WHERE plan_role='researcher_baseline' AND status='approved'
               ORDER BY created_at DESC LIMIT 1"""
        ).fetchone()
        shared = connection.execute(
            """SELECT design_id, title, status FROM research_design_versions
               WHERE plan_role='shared_design' AND status='approved'
               ORDER BY created_at DESC LIMIT 1"""
        ).fetchone()
        manuscripts = [dict(row) for row in connection.execute(
            """SELECT m.manuscript_id, m.title, m.status, m.updated_at,
                      COUNT(DISTINCT ms.section_id) AS section_count,
                      SUM(CASE WHEN wp.status='pending' THEN 1 ELSE 0 END) AS pending_proposals
               FROM manuscripts m LEFT JOIN manuscript_sections ms ON ms.manuscript_id=m.manuscript_id
               LEFT JOIN writing_proposals wp ON wp.section_id=ms.section_id
               GROUP BY m.manuscript_id ORDER BY m.updated_at DESC"""
        ).fetchall()]
        recent_activity = []
        for row in connection.execute(
            """SELECT event_type, entity_type, entity_id, payload_json, created_at
               FROM audit_events ORDER BY event_id DESC LIMIT 24"""
        ).fetchall():
            item = dict(row)
            try:
                payload = json.loads(item.pop("payload_json") or "{}")
            except json.JSONDecodeError:
                payload = {}
            item["summary"] = ", ".join(
                f"{key}={value}" for key, value in list(payload.items())[:3]
                if isinstance(value, (str, int, float, bool))
            )
            recent_activity.append(item)

    if counts["sources"] == 0:
        phase = "setup"
    elif counts["open_anomalies"] or not all(item["page_count"] for item in sources):
        phase = "materials"
    elif shared is None:
        phase = "design"
    elif counts["verified_evidence"] == 0 and counts["approved_events"] == 0:
        phase = "research"
    elif counts["approved_freezes"] == 0:
        phase = "evidence"
    elif counts["manuscripts"] == 0:
        phase = "writing"
    elif counts["pending_writing_proposals"]:
        phase = "revision"
    else:
        phase = "review"

    next_actions = []
    if counts["sources"] == 0:
        next_actions.append({"action": "library_intake", "priority": 1})
    if counts["open_anomalies"]:
        next_actions.append({"action": "repair_sources", "priority": 1, "count": counts["open_anomalies"]})
    if baseline is None or shared is None:
        next_actions.append({"action": "research_design", "priority": 2})
    if counts["sources"] and counts["approved_events"] == 0 and counts["verified_evidence"] == 0:
        next_actions.append({"action": "events_or_evidence", "priority": 3})
    if counts["verified_evidence"] and counts["approved_freezes"] == 0:
        next_actions.append({"action": "approve_freeze", "priority": 4})
    if counts["approved_freezes"] and counts["manuscripts"] == 0:
        next_actions.append({"action": "create_manuscript", "priority": 5})
    if counts["pending_writing_proposals"]:
        next_actions.append({"action": "decide_writing", "priority": 1, "count": counts["pending_writing_proposals"]})
    if counts["manuscripts"] and not counts["pending_writing_proposals"]:
        next_actions.append({"action": "review_export", "priority": 6})
    next_actions.sort(key=lambda item: item["priority"])
    return {
        "project": {**project, "project_root": str(project_root.resolve())},
        "phase": phase, "counts": counts, "sources": sources,
        "research_design": {"baseline": dict(baseline) if baseline else None, "shared": dict(shared) if shared else None},
        "readiness": readiness, "manuscripts": manuscripts,
        "next_actions": next_actions, "recent_activity": recent_activity,
    }
