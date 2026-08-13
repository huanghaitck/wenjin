from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .db import connect
from .research_design import current_shared_design


def _event_minimum(design_text: str) -> int | None:
    patterns = (
        r"每组[^。；\n]{0,30}?(\d+)\s*[—–-]\s*(\d+)\s*条",
        r"每个?[^。；\n]{0,24}?至少\s*(\d+)\s*条",
    )
    for pattern in patterns:
        match = re.search(pattern, design_text)
        if match:
            return int(match.group(1))
    return None


def _stage_fields(formal_draft_ready: bool) -> dict[str, Any]:
    """Expose the project gate without claiming manuscript submission readiness."""
    return {
        "stage": "FORMAL_DRAFT_READY" if formal_draft_ready else "CONTINUE_RESEARCH",
        "continue_research": not formal_draft_ready,
        "formal_draft_ready": formal_draft_ready,
        # Submission is manuscript-, template- and export-specific.  This project-level
        # function cannot truthfully promote an individual manuscript to that state.
        "submission_ready": False,
        "submission_status": (
            "REQUIRES_MANUSCRIPT_EXPORT_CHECK" if formal_draft_ready else "RESEARCH_NOT_READY"
        ),
        "next_action": "CHECK_MANUSCRIPT_EXPORT" if formal_draft_ready else "CONTINUE_RESEARCH",
    }


def _freeze_has_writable_evidence(payload: dict[str, Any]) -> bool:
    claims = payload.get("claims", [])
    return isinstance(claims, list) and any(
        isinstance(claim, dict)
        and bool(str(claim.get("claim_id", "")).strip())
        and isinstance(claim.get("evidence"), list)
        and any(
            isinstance(evidence, dict)
            and bool(str(evidence.get("evidence_id", "")).strip())
            for evidence in claim["evidence"]
        )
        for claim in claims
    )


def formal_research_readiness(project_root: Path) -> dict[str, Any]:
    """Translate explicit, approved research-plan requirements into visible gates.

    Plan-specific requirements come only from the approved plan.  Formal drafting
    additionally requires a non-empty approved evidence freeze; no universal source
    or bibliography-count threshold is invented.
    """
    design = current_shared_design(project_root)
    blockers: list[str] = []
    warnings: list[str] = []
    if design is None:
        return {
            "status": "BLOCKED", "design_id": "", "blockers": ["尚无人工批准的共同研究设计"],
            "warnings": [], "event_requirement": None, "case_coverage": [],
            "historiography_entries": 0, "approved_historiography_entries": 0,
            "candidate_historiography_entries": 0,
            "reading_jobs": 0, "completed_reading_jobs": 0,
            "approved_freeze_count": 0, "approved_nonempty_freeze_count": 0,
            "latest_approved_freeze_id": "", "frozen_source_count": 0,
            **_stage_fields(False),
        }

    text = design["content"]
    minimum = _event_minimum(text)
    with connect(project_root) as connection:
        case_rows = connection.execute(
            """SELECT case_id, COUNT(*) AS approved_events
               FROM research_event_rows WHERE status = 'approved'
               GROUP BY case_id ORDER BY case_id"""
        ).fetchall()
        historiography_entries = connection.execute(
            "SELECT COUNT(*) FROM historiography_entries"
        ).fetchone()[0]
        approved_historiography_entries = connection.execute(
            "SELECT COUNT(*) FROM historiography_entries WHERE status = 'approved'"
        ).fetchone()[0]
        candidate_historiography_entries = connection.execute(
            "SELECT COUNT(*) FROM historiography_entries WHERE status = 'candidate'"
        ).fetchone()[0]
        reading_jobs = connection.execute("SELECT COUNT(*) FROM reading_jobs").fetchone()[0]
        completed_reading_jobs = connection.execute(
            "SELECT COUNT(*) FROM reading_jobs WHERE status = 'completed'"
        ).fetchone()[0]
        project_source_count = connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        frozen_sources: set[str] = set()
        approved_freezes = connection.execute(
            """SELECT freeze_id, payload_json FROM evidence_freezes WHERE status = 'approved'
               ORDER BY created_at DESC"""
        ).fetchall()
        approved_nonempty_freeze_count = 0
        latest_approved_freeze_id = ""
        for row in approved_freezes:
            payload = json.loads(row["payload_json"])
            if not _freeze_has_writable_evidence(payload):
                continue
            approved_nonempty_freeze_count += 1
            if latest_approved_freeze_id:
                continue
            latest_approved_freeze_id = str(row["freeze_id"])
            for claim in payload.get("claims", []):
                for evidence in claim.get("evidence", []):
                    source_id = str(evidence.get("source_id", "")).strip()
                    if source_id:
                        frozen_sources.add(source_id)

    coverage = [dict(row) for row in case_rows]
    if minimum is not None:
        if not coverage:
            blockers.append(f"研究设计要求每组至少约 {minimum} 条有效事件，目前尚无获批事件")
        for item in coverage:
            item["required_minimum"] = minimum
            item["ready"] = item["approved_events"] >= minimum
            if not item["ready"]:
                blockers.append(
                    f"{item['case_id']} 仅有 {item['approved_events']} 条获批事件，"
                    f"未达到研究设计约 {minimum} 条的最低口径"
                )
    if "学术史" in text and approved_historiography_entries == 0:
        blockers.append("研究设计要求建立学术史，但项目尚无人工批准的学术史条目")
    if approved_nonempty_freeze_count == 0:
        blockers.append("尚无包含主张与证据的人工批准冻结包；候选主张或待审冻结不能进入正式写作")
    if reading_jobs == 0:
        warnings.append("项目尚无登记的定向或全文阅读任务；图书馆中的材料不能自动视为已读")
    elif completed_reading_jobs == 0:
        warnings.append(f"项目已有 {reading_jobs} 项阅读任务，但尚无一项满足完成条件")
    if len(frozen_sources) < project_source_count:
        warnings.append(
            f"项目登记 {project_source_count} 种来源，最新批准冻结仅覆盖 {len(frozen_sources)} 种；"
            "其余材料尚未自动进入论证"
        )
    formal_draft_ready = not blockers
    return {
        "status": "READY" if formal_draft_ready else "BLOCKED",
        "design_id": design["design_id"], "design_title": design["title"],
        "blockers": blockers, "warnings": warnings,
        "event_requirement": minimum, "case_coverage": coverage,
        "historiography_entries": historiography_entries,
        "approved_historiography_entries": approved_historiography_entries,
        "candidate_historiography_entries": candidate_historiography_entries,
        "reading_jobs": reading_jobs,
        "completed_reading_jobs": completed_reading_jobs,
        "approved_freeze_count": len(approved_freezes),
        "approved_nonempty_freeze_count": approved_nonempty_freeze_count,
        "latest_approved_freeze_id": latest_approved_freeze_id,
        "project_source_count": project_source_count, "frozen_source_count": len(frozen_sources),
        **_stage_fields(formal_draft_ready),
    }
