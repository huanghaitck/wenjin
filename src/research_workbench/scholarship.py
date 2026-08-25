from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .db import append_audit, connect, utc_now
from .research_events import event_state


RELATIONS = {"supports", "weakens", "background", "counterevidence"}
CLAIM_MAP_COLUMNS = (
    "claim_id", "claim_text", "claim_strength", "evidence_id", "source_id", "source_role",
    "original_page", "digital_page", "locator_verified", "witness_independence", "supports",
    "does_not_support", "citation_full", "citation_short", "status", "notes",
)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _write_event_claim_map(project_root: Path, freeze_id: str, payload: dict[str, Any],
                           status: str) -> str:
    if payload.get("freeze_kind") != "approved_research_events":
        return ""
    source_ids = {
        evidence["source_id"]
        for claim in payload["claims"] for evidence in claim["evidence"]
    }
    with connect(project_root) as connection:
        sources = {
            row["source_id"]: dict(row)
            for row in connection.execute(
                "SELECT source_id, title, source_type FROM sources WHERE source_id IN ("
                + ",".join("?" for _ in source_ids) + ")",
                list(source_ids),
            )
        }
    target = project_root / "research" / "freezes" / freeze_id / "claim_citation_map.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CLAIM_MAP_COLUMNS)
        writer.writeheader()
        for claim in payload["claims"]:
            case_ids = {evidence["case_id"] for evidence in claim["evidence"]}
            strength = "COMPARATIVE" if len(case_ids) > 1 else "INTERPRETIVE"
            boundary = claim.get("does_not_support") or "不得超出所列原文、字段锚点与人工决定。"
            for evidence in claim["evidence"]:
                source = sources.get(evidence["source_id"], {})
                physical = "–".join(str(page) for page in evidence.get("physical_pages", []))
                printed = "–".join(str(page) for page in evidence.get("printed_pages", []) if str(page))
                title = source.get("title", evidence["source_id"])
                citation = (
                    f"{title}，物理页 {physical}（{evidence['source_id']}，"
                    f"{evidence['source_version_id']}）"
                )
                relation = evidence["relation"]
                support_text = (
                    claim["text"] if relation == "supports"
                    else f"{relation}：{claim['text']}"
                )
                writer.writerow({
                    "claim_id": claim["claim_id"],
                    "claim_text": claim["text"],
                    "claim_strength": strength,
                    "evidence_id": evidence["evidence_id"],
                    "source_id": evidence["source_id"],
                    "source_role": source.get("source_type", "historical_source"),
                    "original_page": printed,
                    "digital_page": physical,
                    "locator_verified": "true",
                    "witness_independence": evidence["source_id"],
                    "supports": support_text,
                    "does_not_support": boundary,
                    "citation_full": citation,
                    "citation_short": f"{title}，物理页 {physical}",
                    "status": status,
                    "notes": (
                        f"event={evidence['event_id']}; relation={relation}; "
                        f"classification={evidence['classification']}; {evidence.get('missing_reason', '')}"
                    ).strip(),
                })
    return target.relative_to(project_root).as_posix()


def create_claim(project_root: Path, text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise ValueError("claim text is required")
    claim_id, now = _id("CLM"), utc_now()
    with connect(project_root) as connection:
        connection.execute(
            "INSERT INTO claims(claim_id, text, status, created_at, updated_at) VALUES (?, ?, 'candidate', ?, ?)",
            (claim_id, text, now, now),
        )
        append_audit(connection, "claim_created", "claim", claim_id)
    return get_claim(project_root, claim_id)


def get_claim(project_root: Path, claim_id: str) -> dict[str, Any]:
    with connect(project_root) as connection:
        row = connection.execute("SELECT * FROM claims WHERE claim_id = ?", (claim_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown claim: {claim_id}")
        evidence = [dict(item) for item in connection.execute(
            """SELECT ce.relation, e.* FROM claim_evidence ce
               JOIN evidence_items e ON e.evidence_id = ce.evidence_id
               WHERE ce.claim_id = ? ORDER BY ce.created_at""", (claim_id,)
        )]
        for item in evidence:
            anchors = [dict(anchor) for anchor in connection.execute(
                """SELECT ea.block_id, p.page_id, p.physical_page
                   FROM evidence_anchors ea
                   JOIN blocks b ON b.block_id = ea.block_id
                   JOIN pages p ON p.page_id = b.page_id
                   WHERE ea.evidence_id = ? ORDER BY ea.anchor_order""",
                (item["evidence_id"],),
            )]
            item["block_ids"] = [anchor["block_id"] for anchor in anchors] or [item["block_id"]]
            item["page_ids"] = list(dict.fromkeys(anchor["page_id"] for anchor in anchors)) or [item["page_id"]]
            item["physical_pages"] = list(dict.fromkeys(anchor["physical_page"] for anchor in anchors)) or [item["physical_page"]]
    return {**dict(row), "evidence": evidence}


def list_claims(project_root: Path) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        ids = [row[0] for row in connection.execute("SELECT claim_id FROM claims ORDER BY created_at DESC")]
    return [get_claim(project_root, claim_id) for claim_id in ids]


def create_evidence(project_root: Path, claim_id: str, block_id: str, quote: str,
                    note: str, relation: str = "supports",
                    block_ids: list[str] | None = None) -> dict[str, Any]:
    quote, note, relation = quote.strip(), note.strip(), relation.strip()
    if relation not in RELATIONS:
        raise ValueError(f"unsupported claim/evidence relation: {relation}")
    if not quote:
        raise ValueError("evidence quote is required")
    anchor_ids = list(dict.fromkeys(str(item).strip() for item in (block_ids or [block_id]) if str(item).strip()))
    if not anchor_ids:
        raise ValueError("at least one evidence block is required")
    if len(anchor_ids) > 12:
        raise ValueError("an evidence span may contain at most 12 blocks")
    block_id = anchor_ids[0]
    evidence_id, link_id, now = _id("EVI"), _id("CEL"), utc_now()
    with connect(project_root) as connection:
        if connection.execute("SELECT 1 FROM claims WHERE claim_id = ?", (claim_id,)).fetchone() is None:
            raise KeyError(f"unknown claim: {claim_id}")
        placeholders = ",".join("?" for _ in anchor_ids)
        blocks = [dict(item) for item in connection.execute(
            """SELECT b.block_id, b.use_state AS block_use_state,
                      b.verification_state AS block_verification_state,
                      COALESCE(b.human_text, b.machine_text) AS effective_text,
                      b.block_order, b.block_type,
                      p.page_id, p.physical_page, p.use_state AS page_use_state,
                      p.verification_state AS page_verification_state, p.source_id
               FROM blocks b JOIN pages p ON p.page_id = b.page_id
               WHERE b.block_id IN (""" + placeholders + ")", anchor_ids
        )]
        by_id = {item["block_id"]: item for item in blocks}
        missing = [item for item in anchor_ids if item not in by_id]
        if missing:
            raise KeyError(f"unknown block: {missing[0]}")
        blocks = [by_id[item] for item in anchor_ids]
        if anchor_ids != [item["block_id"] for item in sorted(
            blocks, key=lambda item: (item["physical_page"], item["block_order"])
        )]:
            raise ValueError("evidence blocks must be ordered by physical page and block order")
        if len({item["source_id"] for item in blocks}) != 1:
            raise ValueError("all evidence blocks must belong to one source")
        block_verified_states = {"human_verified", "human_repaired"}
        page_verified_states = {"human_spot_checked", "human_verified", "human_repaired"}
        for block in blocks:
            if block["block_use_state"] != "research_usable" or block["page_use_state"] != "research_usable":
                raise ValueError("blocked or unverified page content cannot be submitted as evidence")
            if (block["block_verification_state"] not in block_verified_states
                    or block["page_verification_state"] not in page_verified_states):
                raise ValueError("human page verification is required before evidence submission")
        ignored_types = ("header", "footer", "page_number")
        for previous, current in zip(blocks, blocks[1:]):
            if current["physical_page"] == previous["physical_page"]:
                skipped = connection.execute(
                    """SELECT 1 FROM blocks
                       WHERE page_id = ? AND block_order > ? AND block_order < ?
                         AND block_type NOT IN (?, ?, ?) LIMIT 1""",
                    (previous["page_id"], previous["block_order"], current["block_order"], *ignored_types),
                ).fetchone()
                if skipped is not None:
                    raise ValueError("evidence blocks must form a contiguous text span")
                continue
            if current["physical_page"] != previous["physical_page"] + 1:
                raise ValueError("cross-page evidence blocks must use adjacent physical pages")
            trailing = connection.execute(
                """SELECT 1 FROM blocks WHERE page_id = ? AND block_order > ?
                   AND block_type NOT IN (?, ?, ?) LIMIT 1""",
                (previous["page_id"], previous["block_order"], *ignored_types),
            ).fetchone()
            leading = connection.execute(
                """SELECT 1 FROM blocks WHERE page_id = ? AND block_order < ?
                   AND block_type NOT IN (?, ?, ?) LIMIT 1""",
                (current["page_id"], current["block_order"], *ignored_types),
            ).fetchone()
            if trailing is not None or leading is not None:
                raise ValueError("cross-page evidence must continue at the page boundary")
            page_relation = connection.execute(
                """SELECT human_value, verification_state FROM page_relations
                   WHERE from_block_id = ? AND to_block_id = ?
                     AND relation_type IN ('continues_to', 'continues_on_next_page')
                   LIMIT 1""",
                (previous["block_id"], current["block_id"]),
            ).fetchone()
            human_value = json.loads(page_relation["human_value"]) if page_relation and page_relation["human_value"] else None
            continuation_confirmed = human_value is True or (
                isinstance(human_value, dict)
                and (human_value.get("continues") is True or human_value.get("value") is True)
            )
            if (page_relation is None or page_relation["verification_state"] not in block_verified_states
                    or not continuation_confirmed):
                raise ValueError("cross-page evidence requires a human-confirmed continuation relation")
        effective_text = "\n".join(item["effective_text"] for item in blocks)
        normalized_quote = re.sub(r"\s+", " ", quote).strip()
        normalized_text = re.sub(r"\s+", " ", effective_text).strip()
        if normalized_quote not in normalized_text:
            raise ValueError("evidence quote must exactly occur in the verified block text")
        duplicates = connection.execute(
            """SELECT e.evidence_id FROM claim_evidence ce
               JOIN evidence_items e ON e.evidence_id = ce.evidence_id
               WHERE ce.claim_id = ? AND e.block_id = ? AND e.quote = ? AND ce.relation = ?
               ORDER BY ce.created_at""",
            (claim_id, block_id, quote, relation),
        ).fetchall()
        duplicate_evidence_id = None
        for duplicate in duplicates:
            existing_anchors = [row[0] for row in connection.execute(
                """SELECT block_id FROM evidence_anchors
                   WHERE evidence_id = ? ORDER BY anchor_order""",
                (duplicate["evidence_id"],),
            )]
            if existing_anchors == anchor_ids:
                duplicate_evidence_id = duplicate["evidence_id"]
                append_audit(
                    connection, "evidence_submission_deduplicated", "evidence", duplicate["evidence_id"],
                    {"claim_id": claim_id, "relation": relation, "block_ids": anchor_ids},
                )
                break
        if duplicate_evidence_id is None:
            version = connection.execute(
                "SELECT source_version_id FROM source_versions WHERE source_id = ? ORDER BY created_at DESC LIMIT 1",
                (blocks[0]["source_id"],),
            ).fetchone()
            connection.execute(
                """INSERT INTO evidence_items(evidence_id, source_id, source_version_id, page_id, block_id,
                   physical_page, quote, note, qualification, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PAGE_VERIFIED', 'verified', ?)""",
                (evidence_id, blocks[0]["source_id"], version["source_version_id"], blocks[0]["page_id"], block_id,
                 blocks[0]["physical_page"], quote, note, now),
            )
            connection.executemany(
                "INSERT INTO evidence_anchors(evidence_id, block_id, anchor_order) VALUES (?, ?, ?)",
                [(evidence_id, anchor, order) for order, anchor in enumerate(anchor_ids)],
            )
            connection.execute(
                "INSERT INTO claim_evidence(link_id, claim_id, evidence_id, relation, created_at) VALUES (?, ?, ?, ?, ?)",
                (link_id, claim_id, evidence_id, relation, now),
            )
            append_audit(connection, "evidence_submitted", "evidence", evidence_id,
                         {"claim_id": claim_id, "relation": relation, "block_ids": anchor_ids})
    return get_claim(project_root, claim_id)


def create_freeze(project_root: Path, title: str, claim_ids: list[str]) -> dict[str, Any]:
    title = title.strip()
    if not title or not claim_ids:
        raise ValueError("freeze title and at least one claim are required")
    claims = [get_claim(project_root, claim_id) for claim_id in dict.fromkeys(claim_ids)]
    if any(not claim["evidence"] for claim in claims):
        raise ValueError("every frozen claim must have at least one verified evidence item")
    with connect(project_root) as connection:
        for claim in claims:
            for evidence in claim["evidence"]:
                version = connection.execute(
                    "SELECT sha256, project_path FROM source_versions WHERE source_version_id = ?",
                    (evidence["source_version_id"],),
                ).fetchone()
                evidence["source_version"] = dict(version)
    payload = {
        "claims": claims,
        "boundary": (
            "Only the frozen quotations and their recorded relations may support the draft; "
            "counterevidence and weakens relations remain binding. Missing evidence cannot be recast as proof, "
            "and retrieval results remain leads only."
        ),
    }
    freeze_id, now = _id("FRZ"), utc_now()
    with connect(project_root) as connection:
        connection.execute(
            "INSERT INTO evidence_freezes(freeze_id, title, status, payload_json, created_at) VALUES (?, ?, 'pending', ?, ?)",
            (freeze_id, title, json.dumps(payload, ensure_ascii=False, sort_keys=True), now),
        )
        append_audit(connection, "evidence_freeze_proposed", "freeze", freeze_id)
    return freeze_detail(project_root, freeze_id)


def create_event_freeze(project_root: Path, title: str, claim_specs: list[dict[str, Any]],
                        unresolved: list[str] | None = None,
                        prohibited_claims: list[str] | None = None) -> dict[str, Any]:
    """Create a pending freeze directly from human-approved research events.

    Research events already carry the original-page anchors and the source-version
    identity needed by the writing harness.  This bridge snapshots those approved
    rows without silently promoting draft or rejected events to evidence.
    """
    title = title.strip()
    if not title or not claim_specs:
        raise ValueError("freeze title and at least one event-backed claim are required")

    requested_ids = list(dict.fromkeys(
        str(item.get("event_id", "")).strip()
        for claim in claim_specs for item in claim.get("evidence", [])
        if str(item.get("event_id", "")).strip()
    ))
    if not requested_ids:
        raise ValueError("every event-backed claim must select at least one event")
    events = {
        item["event_id"]: item
        for item in event_state(project_root, statuses=["approved"], detail="full")["events"]
        if item["event_id"] in requested_ids
    }
    missing = [event_id for event_id in requested_ids if event_id not in events]
    if missing:
        raise ValueError(f"event is not approved and cannot be frozen: {missing[0]}")

    with connect(project_root) as connection:
        versions = {
            version_id: dict(row)
            for version_id in {events[event_id]["source_version_id"] for event_id in requested_ids}
            for row in [connection.execute(
                "SELECT source_version_id, sha256, project_path FROM source_versions WHERE source_version_id = ?",
                (version_id,),
            ).fetchone()]
            if row is not None
        }

    claims: list[dict[str, Any]] = []
    classifications = {
        "FROZEN_WRITABLE": [],
        "CONTEXT_ONLY": [],
        "COUNTEREVIDENCE": [],
        "UNRESOLVED": [str(value).strip() for value in (unresolved or []) if str(value).strip()],
        "PROHIBITED_CLAIM": [
            str(value).strip() for value in (prohibited_claims or []) if str(value).strip()
        ],
    }
    for spec in claim_specs:
        text = str(spec.get("text", "")).strip()
        evidence_specs = spec.get("evidence", [])
        if not text or not evidence_specs:
            raise ValueError("every event-backed claim requires text and evidence")
        frozen_evidence = []
        for evidence_spec in evidence_specs:
            event_id = str(evidence_spec.get("event_id", "")).strip()
            relation = str(evidence_spec.get("relation", "supports")).strip()
            if relation not in RELATIONS:
                raise ValueError(f"unsupported claim/evidence relation: {relation}")
            event = events[event_id]
            if not event["block_ids"] or not event["page_ids"] or not event["original_text"].strip():
                raise ValueError(f"approved event lacks page-linked original text: {event_id}")
            classification = (
                "FROZEN_WRITABLE" if relation == "supports"
                else "CONTEXT_ONLY" if relation == "background"
                else "COUNTEREVIDENCE"
            )
            classifications[classification].append(event_id)
            frozen_evidence.append({
                **event,
                "evidence_id": event_id,
                "event_id": event_id,
                "page_id": event["page_ids"][0],
                "block_id": event["block_ids"][0],
                "physical_page": event["physical_pages"][0],
                "quote": event["original_text"],
                "note": str(evidence_spec.get("note", "")).strip() or event["notes"],
                "relation": relation,
                "classification": classification,
                "qualification_before_freeze": event["qualification"],
                "qualification": classification,
                "source_version": versions.get(event["source_version_id"], {}),
                "status": "frozen",
            })
        claims.append({
            "claim_id": _id("FCL"),
            "text": text,
            "status": "frozen",
            "does_not_support": str(spec.get("does_not_support", "")).strip(),
            "evidence": frozen_evidence,
        })

    for key in ("FROZEN_WRITABLE", "CONTEXT_ONLY", "COUNTEREVIDENCE"):
        classifications[key] = list(dict.fromkeys(classifications[key]))
    payload = {
        "freeze_kind": "approved_research_events",
        "claims": claims,
        "classifications": classifications,
        "boundary": (
            "Only FROZEN_WRITABLE event quotations and their recorded field anchors may support the draft. "
            "CONTEXT_ONLY material cannot carry a factual claim; COUNTEREVIDENCE remains binding. "
            "UNRESOLVED items and PROHIBITED_CLAIM statements must not be converted into facts. "
            "Missing evidence cannot be recast as proof, and retrieval results remain leads only."
        ),
    }
    freeze_id, now = _id("FRZ"), utc_now()
    payload["claim_map_project_path"] = _write_event_claim_map(
        project_root, freeze_id, payload, "VERIFIED"
    )
    with connect(project_root) as connection:
        connection.execute(
            "INSERT INTO evidence_freezes(freeze_id, title, status, payload_json, created_at) "
            "VALUES (?, ?, 'pending', ?, ?)",
            (freeze_id, title, json.dumps(payload, ensure_ascii=False, sort_keys=True), now),
        )
        append_audit(
            connection, "event_evidence_freeze_proposed", "freeze", freeze_id,
            {"event_ids": requested_ids, "claim_count": len(claims)},
        )
    return freeze_detail(project_root, freeze_id)


def approve_freeze(project_root: Path, freeze_id: str, reviewer: str, reason: str) -> dict[str, Any]:
    reviewer, reason = reviewer.strip(), reason.strip()
    if not reviewer or not reason:
        raise ValueError("freeze approval requires reviewer and reason")
    now = utc_now()
    with connect(project_root) as connection:
        row = connection.execute(
            "SELECT status, payload_json FROM evidence_freezes WHERE freeze_id = ?", (freeze_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown freeze: {freeze_id}")
        if row["status"] != "pending":
            raise ValueError(f"freeze is already {row['status']}")
        payload = json.loads(row["payload_json"])
        payload["approval"] = {"reviewer": reviewer, "reason": reason, "approved_at": now}
        claim_map_path = _write_event_claim_map(project_root, freeze_id, payload, "FROZEN")
        if claim_map_path:
            payload["claim_map_project_path"] = claim_map_path
        connection.execute(
            """UPDATE evidence_freezes SET status = 'approved', approved_by = ?, approved_at = ?,
                       payload_json = ? WHERE freeze_id = ?""",
            (reviewer, now, json.dumps(payload, ensure_ascii=False, sort_keys=True), freeze_id),
        )
        append_audit(
            connection, "evidence_freeze_approved", "freeze", freeze_id,
            {"reviewer": reviewer, "reason": reason},
        )
    return freeze_detail(project_root, freeze_id)


def freeze_detail(project_root: Path, freeze_id: str) -> dict[str, Any]:
    with connect(project_root) as connection:
        row = connection.execute("SELECT * FROM evidence_freezes WHERE freeze_id = ?", (freeze_id,)).fetchone()
    if row is None:
        raise KeyError(f"unknown freeze: {freeze_id}")
    return {**dict(row), "payload": json.loads(row["payload_json"])}


def list_freezes(project_root: Path) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        ids = [row[0] for row in connection.execute(
            "SELECT freeze_id FROM evidence_freezes ORDER BY created_at DESC"
        )]
    return [freeze_detail(project_root, freeze_id) for freeze_id in ids]


def draft_from_freeze(project_root: Path, freeze_id: str, title: str) -> dict[str, Any]:
    freeze = freeze_detail(project_root, freeze_id)
    if freeze["status"] != "approved":
        raise ValueError("only an approved evidence freeze can drive drafting")
    lines = [f"# {title.strip() or freeze['title']}", ""]
    refs: list[dict[str, str]] = []
    note_number = 0
    footnotes = []
    for claim in freeze["payload"]["claims"]:
        lines.extend([f"## {claim['text']}", ""])
        for evidence in claim["evidence"]:
            note_number += 1
            relation = {"supports": "支持", "weakens": "削弱", "background": "提供背景", "counterevidence": "构成反证"}[evidence["relation"]]
            lines.append(f"材料表明：“{evidence['quote']}”[^${note_number}]（该材料在冻结包中被标记为：{relation}）。".replace("^$", "^"))
            refs.append({"claim_id": claim["claim_id"], "evidence_id": evidence["evidence_id"],
                         "page_id": evidence["page_id"], "source_version_id": evidence["source_version_id"]})
            footnotes.append(
                f"[^{note_number}]: {evidence['source_id']}，物理页 "
                f"{'–'.join(str(page) for page in evidence.get('physical_pages', [evidence['physical_page']]))}；"
                f"Evidence {evidence['evidence_id']}；Source Version {evidence['source_version_id']}。"
            )
        lines.append("")
    lines.extend(["## 注释", "", *footnotes])
    content = "\n".join(lines).rstrip() + "\n"
    artifact_id, version_id, now = _id("ART"), _id("ARV"), utc_now()
    with connect(project_root) as connection:
        connection.execute(
            "INSERT INTO artifacts(artifact_id, artifact_type, title, status, created_at, updated_at) VALUES (?, 'frozen_draft', ?, 'draft', ?, ?)",
            (artifact_id, title.strip() or freeze["title"], now, now),
        )
        connection.execute(
            """INSERT INTO artifact_versions(version_id, artifact_id, content, source_refs_json,
               model_snapshot_json, created_at) VALUES (?, ?, ?, ?, ?, ?)""",
            (version_id, artifact_id, content, json.dumps(refs, ensure_ascii=False),
             json.dumps({"provider": "deterministic_demo", "freeze_id": freeze_id}), now),
        )
        append_audit(connection, "frozen_draft_created", "artifact", artifact_id,
                     {"version_id": version_id, "freeze_id": freeze_id})
    return artifact_detail(project_root, artifact_id)


def review_artifact(project_root: Path, version_id: str, reviewer_role: str = "source_critic") -> dict[str, Any]:
    with connect(project_root) as connection:
        version = connection.execute("SELECT * FROM artifact_versions WHERE version_id = ?", (version_id,)).fetchone()
        if version is None:
            raise KeyError(f"unknown artifact version: {version_id}")
        refs = json.loads(version["source_refs_json"])
        missing = [
            ref for ref in refs
            if connection.execute(
                "SELECT 1 FROM evidence_items WHERE evidence_id = ?", (ref["evidence_id"],)
            ).fetchone() is None
            and connection.execute(
                "SELECT 1 FROM research_event_rows WHERE event_id = ? AND status = 'approved'",
                (ref["evidence_id"],),
            ).fetchone() is None
        ]
        report = (
            "通过：所有段落引用均可回到冻结证据、物理页和来源版本；仍需作者判断解释是否充分。"
            if not missing else f"阻断：发现 {len(missing)} 个失效证据引用。"
        )
        review_id = _id("REV")
        connection.execute(
            "INSERT INTO reviews(review_id, artifact_version_id, reviewer_role, report, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (review_id, version_id, reviewer_role, report, "passed" if not missing else "blocked", utc_now()),
        )
    return {"review_id": review_id, "version_id": version_id, "reviewer_role": reviewer_role,
            "status": "passed" if not missing else "blocked", "report": report}


def artifact_detail(project_root: Path, artifact_id: str) -> dict[str, Any]:
    with connect(project_root) as connection:
        row = connection.execute("SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown artifact: {artifact_id}")
        versions = [dict(item) for item in connection.execute(
            "SELECT * FROM artifact_versions WHERE artifact_id = ? ORDER BY created_at DESC", (artifact_id,)
        )]
        for version in versions:
            version["source_refs"] = json.loads(version["source_refs_json"])
            version["reviews"] = [dict(item) for item in connection.execute(
                "SELECT * FROM reviews WHERE artifact_version_id = ? ORDER BY created_at", (version["version_id"],)
            )]
    return {**dict(row), "versions": versions}


def list_artifacts(project_root: Path) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        ids = [row[0] for row in connection.execute("SELECT artifact_id FROM artifacts ORDER BY created_at DESC")]
    return [artifact_detail(project_root, artifact_id) for artifact_id in ids]


def export_artifact(project_root: Path, artifact_id: str) -> dict[str, Any]:
    artifact = artifact_detail(project_root, artifact_id)
    version = artifact["versions"][0]
    path = project_root / "exports" / f"{artifact_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".md.tmp")
    temporary.write_text(version["content"], encoding="utf-8")
    temporary.replace(path)
    return {"artifact_id": artifact_id, "version_id": version["version_id"],
            "project_path": path.relative_to(project_root).as_posix()}


def create_browser_session(project_root: Path, start_url: str, allowed_domain: str) -> dict[str, Any]:
    parsed, allowed_domain = urlparse(start_url.strip()), allowed_domain.strip().lower()
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("browser start URL must use http or https")
    if parsed.username or parsed.password:
        raise ValueError("browser session URLs must not contain credentials")
    sensitive = {"token", "access_token", "password", "key", "api_key"}
    if sensitive.intersection(key.lower() for key in parse_qs(parsed.query)):
        raise ValueError("browser session URLs must not contain credential query parameters")
    if parsed.hostname.lower() != allowed_domain and not parsed.hostname.lower().endswith("." + allowed_domain):
        raise ValueError("start URL must be inside the allowed domain")
    with connect(project_root) as connection:
        existing = connection.execute(
            """SELECT session_id, start_url, allowed_domain, status, receipt_json, created_at
               FROM browser_sessions WHERE allowed_domain = ? ORDER BY created_at DESC LIMIT 1""",
            (allowed_domain,),
        ).fetchone()
    if existing is not None:
        receipt = json.loads(existing["receipt_json"])
        return {**dict(existing), **receipt, "reused": True}
    session_id, now = _id("BRS"), utc_now()
    receipt = {"start_url": start_url, "allowed_domain": allowed_domain,
               "boundary": "User handles login, CAPTCHA, payment, download and submission."}
    with connect(project_root) as connection:
        connection.execute(
            "INSERT INTO browser_sessions(session_id, start_url, allowed_domain, status, receipt_json, created_at) VALUES (?, ?, ?, 'user_controlled', ?, ?)",
            (session_id, start_url, allowed_domain, json.dumps(receipt, ensure_ascii=False), now),
        )
    return {"session_id": session_id, "status": "user_controlled", **receipt, "created_at": now,
            "reused": False}


def _agent_browser_executable() -> tuple[str, str]:
    configured = os.getenv("WENJIN_AGENT_BROWSER", "").strip()
    candidates = []
    if configured:
        candidates.append((Path(configured), "configured"))
    candidates.append((Path(sys.executable).resolve().parent / "tools" / "agent-browser.exe", "bundled"))
    candidates.append((Path(__file__).resolve().parents[2] / "node_modules" / "agent-browser" / "bin" / "agent-browser-win32-x64.exe", "project"))
    located = shutil.which("agent-browser")
    if located:
        candidates.append((Path(located), "system"))
    for path, origin in candidates:
        if path.is_file() and path.suffix.casefold() in {".exe", ""}:
            return str(path.resolve()), origin
    return "", "missing"


def _chromium_browser_executable() -> tuple[str, str]:
    configured = os.getenv("WENJIN_BROWSER_EXECUTABLE", "").strip()
    candidates = []
    if configured:
        candidates.append((Path(configured), "configured"))
    for variable, relative, label in (
        ("ProgramFiles(x86)", "Microsoft/Edge/Application/msedge.exe", "system_edge"),
        ("ProgramFiles", "Microsoft/Edge/Application/msedge.exe", "system_edge"),
        ("ProgramFiles", "Google/Chrome/Application/chrome.exe", "system_chrome"),
        ("LOCALAPPDATA", "Google/Chrome/Application/chrome.exe", "user_chrome"),
    ):
        root = os.getenv(variable, "").strip()
        if root:
            candidates.append((Path(root) / relative, label))
    for command, label in (("msedge", "system_edge"), ("chrome", "system_chrome")):
        located = shutil.which(command)
        if located:
            candidates.append((Path(located), label))
    for path, origin in candidates:
        if path.is_file():
            return str(path.resolve()), origin
    return "", "missing"


def computer_use_capability() -> dict[str, Any]:
    executable, runtime_origin = _agent_browser_executable()
    browser_executable, browser_origin = _chromium_browser_executable()
    version = ""
    if executable:
        try:
            completed = subprocess.run(
                [executable, "--version"], capture_output=True, text=True, timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            version = (completed.stdout or completed.stderr).strip().splitlines()[0]
        except (OSError, subprocess.SubprocessError, IndexError):
            version = ""
    return {
        "installed": bool(executable),
        "executable": executable or "",
        "version": version,
        "runtime_origin": runtime_origin,
        "browser_executable": browser_executable,
        "browser_origin": browser_origin,
        "browser_available": bool(browser_executable),
        "visible_browser_launch": bool(executable and browser_executable),
        "agent_actuated": bool(executable and browser_executable),
        "agent_actions": ["observe", "read", "same_domain_navigate"] if executable and browser_executable else [],
        "mode": "bounded_research_browser" if executable and browser_executable else "runtime_only" if executable else "unavailable",
        "boundary": (
            "The agent may inspect, read and navigate inside the session's approved domain. "
            "Clicking controls, filling forms, login, CAPTCHA, payment, download and submission "
            "remain user actions in the visible browser window."
        ),
    }


def launch_controlled_browser(project_root: Path, session_id: str) -> dict[str, Any]:
    with connect(project_root) as connection:
        row = connection.execute(
            "SELECT session_id, start_url, allowed_domain FROM browser_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"unknown browser session: {session_id}")
    executable, _runtime_origin = _agent_browser_executable()
    if not executable:
        raise RuntimeError("受控浏览器组件 agent-browser 不可用，请在 Skills 页面检查程序集成。")
    browser_executable, _browser_origin = _chromium_browser_executable()
    if not browser_executable:
        raise RuntimeError("没有找到可供受控会话使用的 Microsoft Edge 或 Google Chrome。")
    browser_session = f"hrw-{row['session_id'][-12:]}"
    subprocess.Popen(
        [executable, "--executable-path", browser_executable,
         "--session", browser_session, "--restore", "--headed", "open", row["start_url"]],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    with connect(project_root) as connection:
        connection.execute(
            "UPDATE browser_sessions SET status = 'controlled_browser_open' WHERE session_id = ?",
            (session_id,),
        )
    return {
        "session_id": session_id,
        "browser_session": browser_session,
        "status": "controlled_browser_open",
        "start_url": row["start_url"],
        "allowed_domain": row["allowed_domain"],
        "boundary": "User handles login, CAPTCHA, payment, download and submission.",
    }


def list_browser_sessions(project_root: Path) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        return [dict(row) for row in connection.execute(
            "SELECT session_id, start_url, allowed_domain, status, created_at FROM browser_sessions ORDER BY created_at DESC"
        )]


def _browser_session(project_root: Path, session_id: str) -> dict[str, Any]:
    with connect(project_root) as connection:
        row = connection.execute(
            "SELECT session_id, start_url, allowed_domain, status, created_at "
            "FROM browser_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"unknown browser session: {session_id}")
    if row["status"] != "controlled_browser_open":
        raise ValueError("browser session must be opened visibly before the agent can inspect it")
    return dict(row)


def _browser_session_name(session_id: str) -> str:
    return f"hrw-{session_id[-12:]}"


def _run_browser_command(arguments: list[str], timeout: int = 30) -> str:
    executable, _origin = _agent_browser_executable()
    if not executable:
        raise RuntimeError("受控浏览器组件 agent-browser 不可用。")
    completed = subprocess.run(
        [executable, *arguments], capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"controlled browser command failed: {message[:500]}")
    return (completed.stdout or "").strip()


def inspect_controlled_browser(project_root: Path, session_id: str) -> dict[str, Any]:
    session = _browser_session(project_root, session_id)
    raw = _run_browser_command([
        "--session", _browser_session_name(session_id), "snapshot", "-i", "-u", "--json",
    ])
    payload = json.loads(raw)
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    return {
        "session_id": session_id,
        "allowed_domain": session["allowed_domain"],
        "origin": data.get("origin", ""),
        "snapshot": str(data.get("snapshot", ""))[:16000],
        "refs": data.get("refs", {}),
        "boundary": (
            "Rendered browser state is a discovery lead, not evidence. The agent may follow only "
            "same-domain URLs; form controls and external side effects remain user actions."
        ),
    }


def read_controlled_browser(project_root: Path, session_id: str) -> dict[str, Any]:
    session = _browser_session(project_root, session_id)
    browser_session = _browser_session_name(session_id)
    text = _run_browser_command(["--session", browser_session, "read"])
    url = _run_browser_command(["--session", browser_session, "get", "url"])
    title = _run_browser_command(["--session", browser_session, "get", "title"])
    return {
        "session_id": session_id,
        "allowed_domain": session["allowed_domain"],
        "url": url,
        "title": title,
        "text": text[:20000],
        "truncated": len(text) > 20000,
        "boundary": "Rendered page text is a research lead and must be acquired as a project source before evidentiary use.",
    }


def navigate_controlled_browser(project_root: Path, session_id: str, url: str) -> dict[str, Any]:
    session = _browser_session(project_root, session_id)
    parsed = urlparse(url.strip())
    allowed_domain = str(session["allowed_domain"]).lower()
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("browser navigation URL must use http or https")
    hostname = parsed.hostname.lower()
    if hostname != allowed_domain and not hostname.endswith("." + allowed_domain):
        raise ValueError("agent browser navigation must stay inside the approved domain")
    if parsed.username or parsed.password:
        raise ValueError("browser navigation URLs must not contain credentials")
    sensitive = {"token", "access_token", "password", "key", "api_key"}
    if sensitive.intersection(key.lower() for key in parse_qs(parsed.query)):
        raise ValueError("browser navigation URLs must not contain credential query parameters")
    browser_session = _browser_session_name(session_id)
    _run_browser_command(["--session", browser_session, "open", url.strip()])
    current_url = _run_browser_command(["--session", browser_session, "get", "url"])
    current_title = _run_browser_command(["--session", browser_session, "get", "title"])
    return {
        "session_id": session_id,
        "url": current_url,
        "title": current_title,
        "allowed_domain": allowed_domain,
        "boundary": "Same-domain navigation only; clicking, forms, login, download and submission remain user actions.",
    }


def create_memory_candidate(project_root: Path, category: str, content: str,
                            source_refs: list[str]) -> dict[str, Any]:
    category, content = category.strip(), content.strip()
    if not category or not content or not source_refs:
        raise ValueError("memory candidate requires category, content and source references")
    candidate_id, now = _id("MEM"), utc_now()
    with connect(project_root) as connection:
        connection.execute(
            "INSERT INTO memory_candidates(candidate_id, category, content, source_refs_json, status, created_at) VALUES (?, ?, ?, ?, 'candidate', ?)",
            (candidate_id, category, content, json.dumps(source_refs, ensure_ascii=False), now),
        )
    return {"candidate_id": candidate_id, "category": category, "content": content,
            "source_refs": source_refs, "status": "candidate", "created_at": now}


def decide_memory_candidate(project_root: Path, candidate_id: str, approved: bool) -> dict[str, Any]:
    with connect(project_root) as connection:
        row = connection.execute("SELECT * FROM memory_candidates WHERE candidate_id = ?", (candidate_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown memory candidate: {candidate_id}")
        if row["status"] != "candidate":
            raise ValueError(f"memory candidate is already {row['status']}")
        status = "approved_local" if approved else "rejected"
        connection.execute(
            "UPDATE memory_candidates SET status = ?, decided_at = ? WHERE candidate_id = ?",
            (status, utc_now(), candidate_id),
        )
    return {**dict(row), "source_refs": json.loads(row["source_refs_json"]), "status": status}


def list_memory_candidates(project_root: Path) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        rows = [dict(row) for row in connection.execute(
            "SELECT * FROM memory_candidates ORDER BY created_at DESC"
        )]
    for row in rows:
        row["source_refs"] = json.loads(row["source_refs_json"])
    return rows


def research_state(project_root: Path) -> dict[str, Any]:
    return {
        "claims": list_claims(project_root), "freezes": list_freezes(project_root),
        "artifacts": list_artifacts(project_root), "browser_sessions": list_browser_sessions(project_root),
        "memory_candidates": list_memory_candidates(project_root),
    }
