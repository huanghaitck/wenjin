from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .db import append_audit, connect, utc_now


RELATIONS = {"supports", "weakens", "background", "counterevidence"}


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


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
    return {**dict(row), "evidence": evidence}


def list_claims(project_root: Path) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        ids = [row[0] for row in connection.execute("SELECT claim_id FROM claims ORDER BY created_at DESC")]
    return [get_claim(project_root, claim_id) for claim_id in ids]


def create_evidence(project_root: Path, claim_id: str, block_id: str, quote: str,
                    note: str, relation: str = "supports") -> dict[str, Any]:
    quote, note, relation = quote.strip(), note.strip(), relation.strip()
    if relation not in RELATIONS:
        raise ValueError(f"unsupported claim/evidence relation: {relation}")
    if not quote:
        raise ValueError("evidence quote is required")
    evidence_id, link_id, now = _id("EVI"), _id("CEL"), utc_now()
    with connect(project_root) as connection:
        if connection.execute("SELECT 1 FROM claims WHERE claim_id = ?", (claim_id,)).fetchone() is None:
            raise KeyError(f"unknown claim: {claim_id}")
        block = connection.execute(
            """SELECT b.block_id, b.use_state AS block_use_state,
                      COALESCE(b.human_text, b.machine_text) AS effective_text,
                      p.page_id, p.physical_page, p.use_state AS page_use_state, p.source_id
               FROM blocks b JOIN pages p ON p.page_id = b.page_id WHERE b.block_id = ?""", (block_id,)
        ).fetchone()
        if block is None:
            raise KeyError(f"unknown block: {block_id}")
        if block["block_use_state"] != "research_usable" or block["page_use_state"] != "research_usable":
            raise ValueError("blocked or unverified page content cannot be submitted as evidence")
        if quote not in block["effective_text"]:
            raise ValueError("evidence quote must exactly occur in the verified block text")
        version = connection.execute(
            "SELECT source_version_id FROM source_versions WHERE source_id = ? ORDER BY created_at DESC LIMIT 1",
            (block["source_id"],),
        ).fetchone()
        connection.execute(
            """INSERT INTO evidence_items(evidence_id, source_id, source_version_id, page_id, block_id,
               physical_page, quote, note, qualification, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PAGE_VERIFIED', 'verified', ?)""",
            (evidence_id, block["source_id"], version["source_version_id"], block["page_id"], block_id,
             block["physical_page"], quote, note, now),
        )
        connection.execute(
            "INSERT INTO claim_evidence(link_id, claim_id, evidence_id, relation, created_at) VALUES (?, ?, ?, ?, ?)",
            (link_id, claim_id, evidence_id, relation, now),
        )
        append_audit(connection, "evidence_submitted", "evidence", evidence_id,
                     {"claim_id": claim_id, "relation": relation})
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
        "boundary": "Only the frozen quotations and their recorded relations may support the draft; retrieval results are leads only.",
    }
    freeze_id, now = _id("FRZ"), utc_now()
    with connect(project_root) as connection:
        connection.execute(
            "INSERT INTO evidence_freezes(freeze_id, title, status, payload_json, created_at) VALUES (?, ?, 'pending', ?, ?)",
            (freeze_id, title, json.dumps(payload, ensure_ascii=False, sort_keys=True), now),
        )
        append_audit(connection, "evidence_freeze_proposed", "freeze", freeze_id)
    return freeze_detail(project_root, freeze_id)


def approve_freeze(project_root: Path, freeze_id: str, reviewer: str) -> dict[str, Any]:
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("freeze reviewer is required")
    now = utc_now()
    with connect(project_root) as connection:
        row = connection.execute("SELECT status FROM evidence_freezes WHERE freeze_id = ?", (freeze_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown freeze: {freeze_id}")
        if row["status"] != "pending":
            raise ValueError(f"freeze is already {row['status']}")
        connection.execute(
            "UPDATE evidence_freezes SET status = 'approved', approved_by = ?, approved_at = ? WHERE freeze_id = ?",
            (reviewer, now, freeze_id),
        )
        append_audit(connection, "evidence_freeze_approved", "freeze", freeze_id, {"reviewer": reviewer})
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
                f"[^{note_number}]: {evidence['source_id']}，物理页 {evidence['physical_page']}；"
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
        missing = [ref for ref in refs if connection.execute(
            "SELECT 1 FROM evidence_items WHERE evidence_id = ?", (ref["evidence_id"],)
        ).fetchone() is None]
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
    session_id, now = _id("BRS"), utc_now()
    receipt = {"start_url": start_url, "allowed_domain": allowed_domain,
               "boundary": "User handles login, CAPTCHA, payment, download and submission."}
    with connect(project_root) as connection:
        connection.execute(
            "INSERT INTO browser_sessions(session_id, start_url, allowed_domain, status, receipt_json, created_at) VALUES (?, ?, ?, 'user_controlled', ?, ?)",
            (session_id, start_url, allowed_domain, json.dumps(receipt, ensure_ascii=False), now),
        )
    return {"session_id": session_id, "status": "user_controlled", **receipt, "created_at": now}


def list_browser_sessions(project_root: Path) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        return [dict(row) for row in connection.execute(
            "SELECT session_id, start_url, allowed_domain, status, created_at FROM browser_sessions ORDER BY created_at DESC"
        )]


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
