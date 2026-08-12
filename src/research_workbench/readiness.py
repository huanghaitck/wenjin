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


def formal_research_readiness(project_root: Path) -> dict[str, Any]:
    """Translate explicit, approved research-plan requirements into visible gates.

    This deliberately reads only requirements stated in the approved plan. It does
    not invent universal source-count or bibliography thresholds for every field.
    """
    design = current_shared_design(project_root)
    blockers: list[str] = []
    warnings: list[str] = []
    if design is None:
        return {
            "status": "BLOCKED", "design_id": "", "blockers": ["尚无人工批准的共同研究设计"],
            "warnings": [], "event_requirement": None, "case_coverage": [],
            "historiography_entries": 0, "reading_jobs": 0, "completed_reading_jobs": 0,
            "frozen_source_count": 0,
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
        reading_jobs = connection.execute("SELECT COUNT(*) FROM reading_jobs").fetchone()[0]
        completed_reading_jobs = connection.execute(
            "SELECT COUNT(*) FROM reading_jobs WHERE status = 'completed'"
        ).fetchone()[0]
        project_source_count = connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        frozen_sources: set[str] = set()
        for row in connection.execute(
            """SELECT payload_json FROM evidence_freezes WHERE status = 'approved'
               ORDER BY created_at DESC LIMIT 1"""
        ):
            payload = json.loads(row["payload_json"])
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
    if "学术史" in text and historiography_entries == 0:
        blockers.append("研究设计要求建立学术史，但项目尚无学术史条目")
    if reading_jobs == 0:
        warnings.append("项目尚无登记的定向或全文阅读任务；图书馆中的材料不能自动视为已读")
    elif completed_reading_jobs == 0:
        warnings.append(f"项目已有 {reading_jobs} 项阅读任务，但尚无一项满足完成条件")
    if len(frozen_sources) < project_source_count:
        warnings.append(
            f"项目登记 {project_source_count} 种来源，最新批准冻结仅覆盖 {len(frozen_sources)} 种；"
            "其余材料尚未自动进入论证"
        )
    return {
        "status": "READY" if not blockers else "BLOCKED",
        "design_id": design["design_id"], "design_title": design["title"],
        "blockers": blockers, "warnings": warnings,
        "event_requirement": minimum, "case_coverage": coverage,
        "historiography_entries": historiography_entries, "reading_jobs": reading_jobs,
        "completed_reading_jobs": completed_reading_jobs,
        "project_source_count": project_source_count, "frozen_source_count": len(frozen_sources),
    }
