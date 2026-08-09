from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from .db import append_audit, connect, initialize_database, utc_now
from .vision import (
    PAGE_OCR_PROMPT,
    PROMPT_VERSION,
    OcrSettings,
    normalize_ocr_content,
    request_page_ocr,
)


BLOCKING_CATEGORIES = {"content", "location"}


def _json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _canonical(source_id: str, local_id: str) -> str:
    return f"{source_id}:{local_id}"


def _atomic_write(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def initialize_project(project_root: Path, title: str) -> dict[str, Any]:
    project_root = project_root.resolve()
    if (project_root / "project.sqlite3").exists():
        raise FileExistsError(f"project already exists: {project_root}")
    project_root.mkdir(parents=True, exist_ok=True)
    for name in ("sources", "research/evidence", "research/claims", "research/freezes",
                 "manuscripts", "reviews", "exports", "logs"):
        (project_root / name).mkdir(parents=True, exist_ok=True)
    project_id = f"PRJ_{uuid.uuid4().hex}"
    initialize_database(project_root, project_id, title)
    _atomic_write(
        project_root / "project.yaml",
        "\n".join(
            [
                "schema_version: 1",
                f'project_id: "{project_id}"',
                f"title: {json.dumps(title, ensure_ascii=False)}",
                "project_type: historical_research_workbench",
                "current_stage: M1_DOCUMENT_REPAIR",
                "memory_backend: none",
                "",
            ]
        ),
    )
    return {"project_id": project_id, "project_root": str(project_root), "title": title}


def register_source(project_root: Path, source_file: Path, title: str | None = None) -> dict[str, Any]:
    source_file = source_file.resolve()
    if not source_file.is_file():
        raise FileNotFoundError(f"source file does not exist: {source_file}")
    sha256 = _file_hash(source_file)
    source_id = f"SRC_{sha256[:20]}"
    version_id = _stable_id("VER", source_id, sha256)
    relative_path = Path("sources") / source_id / "original" / source_file.name
    destination = project_root.resolve() / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if _file_hash(destination) != sha256:
            raise FileExistsError(f"source destination collision: {destination}")
    else:
        shutil.copy2(source_file, destination)

    with connect(project_root) as connection:
        project = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()
        if project is None:
            raise RuntimeError("project row is missing")
        now = utc_now()
        connection.execute(
            """INSERT OR IGNORE INTO sources(
                   source_id, project_id, title, source_type, original_name,
                   acquisition_state, processing_state, use_state, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source_id,
                project["project_id"],
                title or source_file.stem,
                "local_file",
                source_file.name,
                "acquired",
                "pending",
                "blocked",
                now,
            ),
        )
        connection.execute(
            """INSERT OR IGNORE INTO source_versions(
                   source_version_id, source_id, project_path, sha256, byte_count, created_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (version_id, source_id, relative_path.as_posix(), sha256, source_file.stat().st_size, now),
        )
        append_audit(connection, "source_registered", "source", source_id, {"sha256": sha256})
    return {
        "source_id": source_id,
        "source_version_id": version_id,
        "sha256": sha256,
        "project_path": relative_path.as_posix(),
    }


def import_structure(project_root: Path, source_id: str, packet_path: Path) -> dict[str, Any]:
    packet_path = packet_path.resolve()
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    if not isinstance(packet.get("pages"), list):
        raise ValueError("structure packet must contain a pages list")
    input_hash = _json_hash(packet)
    idempotency_key = f"structure:{source_id}:{input_hash}"

    with connect(project_root) as connection:
        source = connection.execute("SELECT source_id FROM sources WHERE source_id = ?", (source_id,)).fetchone()
        if source is None:
            raise KeyError(f"unknown source: {source_id}")
        existing = connection.execute(
            "SELECT receipt_id, status FROM staging_receipts WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            return {"receipt_id": existing["receipt_id"], "status": "already_applied"}

        receipt_id = f"RCP_{uuid.uuid4().hex}"
        now = utc_now()
        connection.execute(
            """INSERT INTO staging_receipts(
                   receipt_id, receipt_type, idempotency_key, input_hash, payload_json,
                   status, created_at, applied_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)""",
            (receipt_id, "document_structure", idempotency_key, input_hash,
             json.dumps(packet, ensure_ascii=False, sort_keys=True), "pending", now),
        )

        block_ids: dict[str, str] = {}
        page_ids: dict[str, str] = {}
        for page in packet["pages"]:
            local_page_id = str(page["id"])
            page_id = _canonical(source_id, local_page_id)
            page_ids[local_page_id] = page_id
            connection.execute(
                """INSERT INTO pages(
                       page_id, source_id, physical_page, printed_page, page_type,
                       verification_state, use_state, machine_payload_json, human_payload_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
                (
                    page_id,
                    source_id,
                    int(page["physical_page"]),
                    page.get("printed_page"),
                    str(page.get("page_type", "unknown")),
                    "machine_parsed",
                    "research_usable",
                    json.dumps(page, ensure_ascii=False, sort_keys=True),
                ),
            )
            for block in page.get("blocks", []):
                local_block_id = str(block["id"])
                block_id = _canonical(source_id, local_block_id)
                block_ids[local_block_id] = block_id
                connection.execute(
                    """INSERT INTO blocks(
                           block_id, page_id, block_order, block_type, machine_text, human_text,
                           verification_state, use_state, source_region_json
                       ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?)""",
                    (
                        block_id,
                        page_id,
                        int(block["order"]),
                        str(block.get("type", "unknown")),
                        str(block.get("text", "")),
                        "machine_parsed",
                        "research_usable",
                        json.dumps(block.get("region"), ensure_ascii=False),
                    ),
                )

        relation_ids: dict[str, str] = {}
        for relation in packet.get("relations", []):
            local_relation_id = str(relation["id"])
            relation_id = _canonical(source_id, local_relation_id)
            relation_ids[local_relation_id] = relation_id
            connection.execute(
                """INSERT INTO page_relations(
                       relation_id, source_id, from_block_id, to_block_id, relation_type,
                       machine_value, human_value, verification_state
                   ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?)""",
                (
                    relation_id,
                    source_id,
                    block_ids.get(str(relation.get("from_block"))),
                    block_ids.get(str(relation.get("to_block"))),
                    str(relation["type"]),
                    json.dumps(relation.get("value"), ensure_ascii=False, sort_keys=True),
                    "machine_parsed",
                ),
            )

        anomaly_count = 0
        for anomaly in packet.get("anomalies", []):
            scope_type = str(anomaly["scope_type"])
            target_local = str(anomaly["target_id"])
            target_map = {"block": block_ids, "page": page_ids, "relation": relation_ids}
            if scope_type == "source":
                target_id = source_id
            else:
                target_id = target_map[scope_type][target_local]
            anomaly_id = _canonical(source_id, str(anomaly["id"]))
            connection.execute(
                """INSERT INTO anomalies(
                       anomaly_id, source_id, scope_type, target_id, severity, category,
                       message, status, created_at, resolved_at, repair_id
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)""",
                (
                    anomaly_id,
                    source_id,
                    scope_type,
                    target_id,
                    str(anomaly.get("severity", "local")),
                    str(anomaly.get("category", "content")),
                    str(anomaly["message"]),
                    "open",
                    now,
                ),
            )
            anomaly_count += 1

        _recalculate_source_state(connection, source_id)
        connection.execute(
            "UPDATE staging_receipts SET status = ?, applied_at = ? WHERE receipt_id = ?",
            ("applied", utc_now(), receipt_id),
        )
        append_audit(
            connection,
            "structure_imported",
            "source",
            source_id,
            {"receipt_id": receipt_id, "pages": len(packet["pages"]), "anomalies": anomaly_count},
        )
        return {"receipt_id": receipt_id, "status": "applied", "anomalies": anomaly_count}


def list_anomalies(project_root: Path, source_id: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM anomalies"
    parameters: tuple[Any, ...] = ()
    if source_id:
        query += " WHERE source_id = ?"
        parameters = (source_id,)
    query += " ORDER BY created_at, anomaly_id"
    with connect(project_root) as connection:
        return [dict(row) for row in connection.execute(query, parameters).fetchall()]


def submit_block_repair(
    project_root: Path,
    anomaly_id: str,
    corrected_text: str,
    reviewer: str,
    reason: str,
) -> dict[str, Any]:
    if not corrected_text.strip():
        raise ValueError("corrected text must not be empty")
    with connect(project_root) as connection:
        anomaly = _open_anomaly(connection, anomaly_id, "block")
        block = connection.execute("SELECT * FROM blocks WHERE block_id = ?", (anomaly["target_id"],)).fetchone()
        if block is None:
            raise RuntimeError("anomaly target block is missing")
        before_text = block["human_text"] if block["human_text"] is not None else block["machine_text"]
        repair_id = f"REP_{uuid.uuid4().hex}"
        payload = {"text": corrected_text}
        _insert_repair(connection, repair_id, anomaly, payload, [block["page_id"]], reviewer, reason,
                       _json_hash({"text": before_text}))
        connection.execute(
            """UPDATE blocks
               SET human_text = ?, verification_state = ?, use_state = ?
               WHERE block_id = ?""",
            (corrected_text, "human_repaired", "research_usable", block["block_id"]),
        )
        _resolve_anomaly(connection, anomaly_id, repair_id)
        _recalculate_source_state(connection, anomaly["source_id"])
        append_audit(connection, "block_repaired", "block", block["block_id"], {"repair_id": repair_id})
        return {"repair_id": repair_id, "scope_type": "block", "target_id": block["block_id"]}


def submit_page_repair(
    project_root: Path,
    anomaly_id: str,
    corrected_page: dict[str, Any],
    reviewer: str,
    reason: str,
) -> dict[str, Any]:
    if not isinstance(corrected_page.get("blocks"), list):
        raise ValueError("page repair must contain a blocks list")
    if not corrected_page["blocks"] or any(not str(block.get("text", "")).strip() for block in corrected_page["blocks"]):
        raise ValueError("page repair must contain at least one non-empty block")
    with connect(project_root) as connection:
        anomaly = _open_anomaly(connection, anomaly_id, "page")
        page = connection.execute("SELECT * FROM pages WHERE page_id = ?", (anomaly["target_id"],)).fetchone()
        if page is None:
            raise RuntimeError("anomaly target page is missing")
        current_blocks = [dict(row) for row in connection.execute(
            "SELECT * FROM blocks WHERE page_id = ? ORDER BY block_order", (page["page_id"],)
        ).fetchall()]
        current = {"page": dict(page), "blocks": current_blocks}
        repair_id = f"REP_{uuid.uuid4().hex}"
        _insert_repair(connection, repair_id, anomaly, corrected_page, [page["page_id"]], reviewer, reason,
                       _json_hash(current))

        connection.execute(
            """UPDATE pages
               SET human_payload_json = ?, verification_state = ?, use_state = ?
               WHERE page_id = ?""",
            (json.dumps(corrected_page, ensure_ascii=False, sort_keys=True), "human_repaired",
             "research_usable", page["page_id"]),
        )
        connection.execute(
            "UPDATE blocks SET use_state = 'superseded' WHERE page_id = ?",
            (page["page_id"],),
        )
        for block_update in corrected_page["blocks"]:
            block_order = int(block_update["order"])
            block = connection.execute(
                "SELECT block_id FROM blocks WHERE page_id = ? AND block_order = ?",
                (page["page_id"], block_order),
            ).fetchone()
            if block is None:
                block_id = f"{page['page_id']}:H{block_order:03d}"
                connection.execute(
                    """INSERT INTO blocks(
                           block_id, page_id, block_order, block_type, machine_text, human_text,
                           verification_state, use_state, source_region_json
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        block_id,
                        page["page_id"],
                        block_order,
                        str(block_update.get("type", "paragraph")),
                        "",
                        str(block_update["text"]),
                        "human_repaired",
                        "research_usable",
                        json.dumps(block_update.get("region"), ensure_ascii=False),
                    ),
                )
            else:
                connection.execute(
                    """UPDATE blocks
                       SET human_text = ?, block_type = ?, verification_state = ?, use_state = ?,
                           source_region_json = COALESCE(?, source_region_json)
                       WHERE block_id = ?""",
                    (
                        str(block_update["text"]),
                        str(block_update.get("type", "paragraph")),
                        "human_repaired",
                        "research_usable",
                        json.dumps(block_update.get("region"), ensure_ascii=False)
                        if "region" in block_update else None,
                        block["block_id"],
                    ),
                )
        for relation_update in corrected_page.get("relation_updates", []):
            relation_id = str(relation_update["relation_id"])
            relation = connection.execute(
                "SELECT relation_id FROM page_relations WHERE relation_id = ? AND source_id = ?",
                (relation_id, anomaly["source_id"]),
            ).fetchone()
            if relation is None:
                raise ValueError(f"page repair references unknown relation: {relation_id}")
            connection.execute(
                """UPDATE page_relations
                   SET human_value = ?, verification_state = ?
                   WHERE relation_id = ?""",
                (
                    json.dumps(relation_update.get("value"), ensure_ascii=False, sort_keys=True),
                    "human_repaired",
                    relation_id,
                ),
            )
            connection.execute(
                """UPDATE anomalies SET status = ?, resolved_at = ?, repair_id = ?
                   WHERE source_id = ? AND scope_type = 'relation' AND target_id = ? AND status = 'open'""",
                ("resolved", utc_now(), repair_id, anomaly["source_id"], relation_id),
            )

        page_block_ids = [row[0] for row in connection.execute(
            "SELECT block_id FROM blocks WHERE page_id = ?",
            (page["page_id"],),
        ).fetchall()]
        placeholders = ",".join("?" for _ in page_block_ids)
        connection.execute(
            """UPDATE anomalies SET status = ?, resolved_at = ?, repair_id = ?
               WHERE source_id = ? AND status = 'open' AND
                     (target_id = ? OR (scope_type = 'block' AND target_id IN (""" + placeholders + ")))",
            ("resolved", utc_now(), repair_id, anomaly["source_id"], page["page_id"], *page_block_ids),
        )
        remaining_page_content = connection.execute(
            """SELECT COUNT(*) FROM anomalies
               WHERE source_id = ? AND status = 'open' AND category = 'content'
                 AND scope_type IN ('page', 'block')""",
            (anomaly["source_id"],),
        ).fetchone()[0]
        if remaining_page_content == 0:
            connection.execute(
                """UPDATE anomalies SET status = ?, resolved_at = ?, repair_id = ?
                   WHERE source_id = ? AND status = 'open' AND scope_type = 'source'
                     AND anomaly_id LIKE '%:A_SOURCE_TEXT_LAYER_SYSTEMIC'""",
                ("resolved", utc_now(), repair_id, anomaly["source_id"]),
            )
        _recalculate_source_state(connection, anomaly["source_id"])
        append_audit(connection, "page_repaired", "page", page["page_id"], {"repair_id": repair_id})
        return {"repair_id": repair_id, "scope_type": "page", "target_id": page["page_id"]}


def project_status(project_root: Path) -> dict[str, Any]:
    with connect(project_root) as connection:
        project = dict(connection.execute("SELECT * FROM projects LIMIT 1").fetchone())
        project["source_count"] = connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        project["open_anomaly_count"] = connection.execute(
            "SELECT COUNT(*) FROM anomalies WHERE status = 'open'"
        ).fetchone()[0]
        project["repair_count"] = connection.execute("SELECT COUNT(*) FROM repair_records").fetchone()[0]
        project["ocr_proposal_count"] = connection.execute("SELECT COUNT(*) FROM ocr_proposals").fetchone()[0]
        project["pending_ocr_proposal_count"] = connection.execute(
            "SELECT COUNT(*) FROM ocr_proposals WHERE status = 'pending'"
        ).fetchone()[0]
        project["audit_event_count"] = connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        project["sources"] = [dict(row) for row in connection.execute(
            "SELECT source_id, title, processing_state, use_state FROM sources ORDER BY created_at"
        ).fetchall()]
        return project


def list_blocks(project_root: Path, source_id: str) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        rows = connection.execute(
            """SELECT b.*, p.physical_page,
                      COALESCE(b.human_text, b.machine_text) AS effective_text
               FROM blocks b JOIN pages p ON p.page_id = b.page_id
               WHERE p.source_id = ? AND b.use_state != 'superseded'
               ORDER BY p.physical_page, b.block_order""",
            (source_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_sources(project_root: Path) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        return [dict(row) for row in connection.execute(
            """SELECT source_id, title, original_name, processing_state, use_state, created_at
               FROM sources ORDER BY created_at, source_id"""
        ).fetchall()]


def source_view(project_root: Path, source_id: str) -> dict[str, Any]:
    with connect(project_root) as connection:
        source = connection.execute(
            """SELECT source_id, title, original_name, processing_state, use_state
               FROM sources WHERE source_id = ?""",
            (source_id,),
        ).fetchone()
        if source is None:
            raise KeyError(f"unknown source: {source_id}")
        page_rows = connection.execute(
            "SELECT * FROM pages WHERE source_id = ? ORDER BY physical_page",
            (source_id,),
        ).fetchall()
        pages: list[dict[str, Any]] = []
        for page_row in page_rows:
            page = dict(page_row)
            payload = json.loads(page.pop("machine_payload_json"))
            page["machine_payload"] = payload
            if page.get("human_payload_json"):
                page["human_payload"] = json.loads(page["human_payload_json"])
            block_rows = connection.execute(
                """SELECT *, COALESCE(human_text, machine_text) AS effective_text
                   FROM blocks WHERE page_id = ? AND use_state != 'superseded' ORDER BY block_order""",
                (page["page_id"],),
            ).fetchall()
            page["blocks"] = []
            for block_row in block_rows:
                block = dict(block_row)
                block["source_region"] = json.loads(block.pop("source_region_json") or "null")
                page["blocks"].append(block)
            pages.append(page)
        relations = []
        for row in connection.execute(
            "SELECT * FROM page_relations WHERE source_id = ? ORDER BY relation_id",
            (source_id,),
        ).fetchall():
            relation = dict(row)
            relation["machine_value"] = json.loads(relation["machine_value"])
            relation["human_value"] = json.loads(relation["human_value"]) if relation["human_value"] else None
            relation["effective_value"] = relation["human_value"] if relation["human_value"] is not None else relation["machine_value"]
            relations.append(relation)
        anomalies = [dict(row) for row in connection.execute(
            "SELECT * FROM anomalies WHERE source_id = ? ORDER BY status, created_at, anomaly_id",
            (source_id,),
        ).fetchall()]
        proposals = []
        for row in connection.execute(
            """SELECT proposal_id, source_id, page_id, anomaly_id, provider, model,
                      prompt_version, source_sha256, image_sha256, normalized_payload_json,
                      normalized_response_hash, status, created_at, decided_at, reviewer,
                      decision_reason, repair_id
               FROM ocr_proposals WHERE source_id = ? ORDER BY created_at DESC, proposal_id""",
            (source_id,),
        ).fetchall():
            proposal = dict(row)
            proposal["normalized_payload"] = json.loads(proposal.pop("normalized_payload_json"))
            proposals.append(proposal)
        return {
            "source": dict(source),
            "pages": pages,
            "relations": relations,
            "anomalies": anomalies,
            "ocr_proposals": proposals,
        }


def page_image_path(project_root: Path, page_id: str) -> Path:
    with connect(project_root) as connection:
        row = connection.execute("SELECT machine_payload_json FROM pages WHERE page_id = ?", (page_id,)).fetchone()
    if row is None:
        raise KeyError(f"unknown page: {page_id}")
    payload = json.loads(row["machine_payload_json"])
    relative = Path(str(payload["image_path"]))
    candidate = (project_root.resolve() / relative).resolve()
    if project_root.resolve() not in candidate.parents:
        raise ValueError("page image path escapes project root")
    if not candidate.is_file():
        raise FileNotFoundError(f"page image is missing: {candidate}")
    return candidate


def create_ocr_proposal(
    project_root: Path,
    page_id: str,
    settings: OcrSettings | None = None,
) -> dict[str, Any]:
    settings = settings or OcrSettings.from_environment()
    with connect(project_root) as connection:
        eligible = connection.execute(
            """SELECT 1 FROM anomalies
               WHERE scope_type = 'page' AND target_id = ? AND status = 'open' LIMIT 1""",
            (page_id,),
        ).fetchone()
        if eligible is None:
            raise ValueError("OCR proposals require an open page anomaly")
    image_path = page_image_path(project_root, page_id)
    raw_response, normalized_payload = request_page_ocr(image_path, settings)
    return record_ocr_proposal(
        project_root,
        page_id,
        settings,
        raw_response,
        normalized_payload,
    )


def record_ocr_proposal(
    project_root: Path,
    page_id: str,
    settings: OcrSettings,
    raw_response: dict[str, Any],
    normalized_payload: dict[str, Any],
) -> dict[str, Any]:
    normalized_payload = normalize_ocr_content(
        json.dumps(normalized_payload, ensure_ascii=False)
    )
    image_path = page_image_path(project_root, page_id)
    proposal_id = f"OCR_{uuid.uuid4().hex}"
    with connect(project_root) as connection:
        page = connection.execute(
            """SELECT p.page_id, p.source_id, sv.sha256 AS source_sha256
               FROM pages p JOIN source_versions sv ON sv.source_id = p.source_id
               WHERE p.page_id = ? ORDER BY sv.created_at DESC LIMIT 1""",
            (page_id,),
        ).fetchone()
        if page is None:
            raise KeyError(f"unknown page: {page_id}")
        anomaly = connection.execute(
            """SELECT anomaly_id FROM anomalies
               WHERE source_id = ? AND scope_type = 'page' AND target_id = ? AND status = 'open'
               ORDER BY created_at, anomaly_id LIMIT 1""",
            (page["source_id"], page_id),
        ).fetchone()
        if anomaly is None:
            raise ValueError("OCR proposals require an open page anomaly")
        now = utc_now()
        connection.execute(
            """INSERT INTO ocr_proposals(
                   proposal_id, source_id, page_id, anomaly_id, provider, model,
                   prompt_version, prompt_hash, source_sha256, image_sha256,
                   raw_response_json, normalized_payload_json, raw_response_hash,
                   normalized_response_hash, status, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (
                proposal_id,
                page["source_id"],
                page_id,
                anomaly["anomaly_id"],
                settings.provider,
                settings.model,
                PROMPT_VERSION,
                _json_hash(PAGE_OCR_PROMPT),
                page["source_sha256"],
                _file_hash(image_path),
                json.dumps(raw_response, ensure_ascii=False, sort_keys=True),
                json.dumps(normalized_payload, ensure_ascii=False, sort_keys=True),
                _json_hash(raw_response),
                _json_hash(normalized_payload),
                now,
            ),
        )
        append_audit(
            connection,
            "ocr_proposal_created",
            "ocr_proposal",
            proposal_id,
            {"page_id": page_id, "provider": settings.provider, "model": settings.model},
        )
    return {
        "proposal_id": proposal_id,
        "page_id": page_id,
        "provider": settings.provider,
        "model": settings.model,
        "prompt_version": PROMPT_VERSION,
        "status": "pending",
        "normalized_payload": normalized_payload,
    }


def accept_ocr_proposal(
    project_root: Path,
    proposal_id: str,
    corrected_payload: dict[str, Any],
    reviewer: str,
    reason: str,
) -> dict[str, Any]:
    if not reviewer.strip() or not reason.strip():
        raise ValueError("reviewer and reason are required")
    normalized = normalize_ocr_content(json.dumps(corrected_payload, ensure_ascii=False))
    with connect(project_root) as connection:
        proposal = connection.execute(
            "SELECT * FROM ocr_proposals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        if proposal is None:
            raise KeyError(f"unknown OCR proposal: {proposal_id}")
        if proposal["status"] != "pending":
            raise ValueError(f"OCR proposal is already {proposal['status']}")
        anomaly_id = str(proposal["anomaly_id"])
        page_id = str(proposal["page_id"])
    repair = submit_page_repair(project_root, anomaly_id, normalized, reviewer, reason)
    with connect(project_root) as connection:
        updated = connection.execute(
            """UPDATE ocr_proposals
               SET status = 'accepted', decided_at = ?, reviewer = ?, decision_reason = ?, repair_id = ?
               WHERE proposal_id = ? AND status = 'pending'""",
            (utc_now(), reviewer, reason, repair["repair_id"], proposal_id),
        )
        if updated.rowcount != 1:
            raise RuntimeError("OCR proposal state changed during acceptance")
        superseded = connection.execute(
            """UPDATE ocr_proposals
               SET status = 'superseded', decided_at = ?, reviewer = ?,
                   decision_reason = ?, repair_id = ?
               WHERE page_id = ? AND proposal_id != ? AND status = 'pending'""",
            (
                utc_now(),
                reviewer,
                f"Superseded by accepted proposal {proposal_id}",
                repair["repair_id"],
                page_id,
                proposal_id,
            ),
        )
        append_audit(
            connection,
            "ocr_proposal_accepted",
            "ocr_proposal",
            proposal_id,
            {"repair_id": repair["repair_id"], "superseded_proposals": superseded.rowcount},
        )
    return {
        "proposal_id": proposal_id,
        "status": "accepted",
        "superseded_proposals": superseded.rowcount,
        **repair,
    }


def reject_ocr_proposal(
    project_root: Path,
    proposal_id: str,
    reviewer: str,
    reason: str,
) -> dict[str, Any]:
    if not reviewer.strip() or not reason.strip():
        raise ValueError("reviewer and reason are required")
    with connect(project_root) as connection:
        updated = connection.execute(
            """UPDATE ocr_proposals
               SET status = 'rejected', decided_at = ?, reviewer = ?, decision_reason = ?
               WHERE proposal_id = ? AND status = 'pending'""",
            (utc_now(), reviewer, reason, proposal_id),
        )
        if updated.rowcount != 1:
            existing = connection.execute(
                "SELECT status FROM ocr_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            if existing is None:
                raise KeyError(f"unknown OCR proposal: {proposal_id}")
            raise ValueError(f"OCR proposal is already {existing['status']}")
        append_audit(
            connection,
            "ocr_proposal_rejected",
            "ocr_proposal",
            proposal_id,
            {},
        )
    return {"proposal_id": proposal_id, "status": "rejected"}


def submit_relation_repair(
    project_root: Path,
    anomaly_id: str,
    continues: bool,
    reviewer: str,
    reason: str,
) -> dict[str, Any]:
    with connect(project_root) as connection:
        anomaly = _open_anomaly(connection, anomaly_id, "relation")
        relation = connection.execute(
            "SELECT * FROM page_relations WHERE relation_id = ?",
            (anomaly["target_id"],),
        ).fetchone()
        if relation is None:
            raise RuntimeError("anomaly target relation is missing")
        repair_id = f"REP_{uuid.uuid4().hex}"
        payload = {"continues": continues}
        page_refs = [row[0] for row in connection.execute(
            """SELECT DISTINCT page_id FROM blocks
               WHERE block_id IN (?, ?) ORDER BY page_id""",
            (relation["from_block_id"], relation["to_block_id"]),
        ).fetchall()]
        _insert_repair(
            connection,
            repair_id,
            anomaly,
            payload,
            page_refs,
            reviewer,
            reason,
            _json_hash({"machine_value": relation["machine_value"], "human_value": relation["human_value"]}),
        )
        connection.execute(
            """UPDATE page_relations SET human_value = ?, verification_state = ?
               WHERE relation_id = ?""",
            (json.dumps(payload, ensure_ascii=False, sort_keys=True), "human_repaired", relation["relation_id"]),
        )
        _resolve_anomaly(connection, anomaly_id, repair_id)
        _recalculate_source_state(connection, anomaly["source_id"])
        append_audit(connection, "relation_repaired", "relation", relation["relation_id"], {"repair_id": repair_id})
        return {"repair_id": repair_id, "scope_type": "relation", "target_id": relation["relation_id"]}


def _open_anomaly(connection: Any, anomaly_id: str, expected_scope: str) -> Any:
    anomaly = connection.execute("SELECT * FROM anomalies WHERE anomaly_id = ?", (anomaly_id,)).fetchone()
    if anomaly is None:
        raise KeyError(f"unknown anomaly: {anomaly_id}")
    if anomaly["status"] != "open":
        raise ValueError(f"anomaly is not open: {anomaly_id}")
    if anomaly["scope_type"] != expected_scope:
        raise ValueError(f"anomaly scope is {anomaly['scope_type']}, expected {expected_scope}")
    return anomaly


def _insert_repair(
    connection: Any,
    repair_id: str,
    anomaly: Any,
    corrected_payload: dict[str, Any],
    source_page_refs: list[str],
    reviewer: str,
    reason: str,
    before_hash: str,
) -> None:
    connection.execute(
        """INSERT INTO repair_records(
               repair_id, source_id, scope_type, target_id, base_version, before_hash,
               corrected_payload_json, source_page_refs_json, reviewer, reason,
               submitted_at, validation_status
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            repair_id,
            anomaly["source_id"],
            anomaly["scope_type"],
            anomaly["target_id"],
            "structure-v1",
            before_hash,
            json.dumps(corrected_payload, ensure_ascii=False, sort_keys=True),
            json.dumps(source_page_refs, ensure_ascii=False),
            reviewer,
            reason,
            utc_now(),
            "accepted",
        ),
    )


def _resolve_anomaly(connection: Any, anomaly_id: str, repair_id: str) -> None:
    connection.execute(
        "UPDATE anomalies SET status = ?, resolved_at = ?, repair_id = ? WHERE anomaly_id = ?",
        ("resolved", utc_now(), repair_id, anomaly_id),
    )


def _recalculate_source_state(connection: Any, source_id: str) -> None:
    connection.execute(
        "UPDATE pages SET use_state = 'research_usable' WHERE source_id = ?",
        (source_id,),
    )
    connection.execute(
        """UPDATE blocks SET use_state = 'research_usable'
           WHERE use_state != 'superseded'
             AND page_id IN (SELECT page_id FROM pages WHERE source_id = ?)""",
        (source_id,),
    )
    open_anomalies = connection.execute(
        "SELECT * FROM anomalies WHERE source_id = ? AND status = 'open'",
        (source_id,),
    ).fetchall()
    systemic = any(row["severity"] == "systemic" for row in open_anomalies)
    blocking = [
        row for row in open_anomalies
        if row["severity"] == "systemic" or row["category"] in BLOCKING_CATEGORIES
    ]
    if systemic:
        connection.execute("UPDATE pages SET use_state = 'blocked' WHERE source_id = ?", (source_id,))
        connection.execute(
            """UPDATE blocks SET use_state = 'blocked'
               WHERE page_id IN (SELECT page_id FROM pages WHERE source_id = ?)""",
            (source_id,),
        )
        processing_state, use_state = "needs_review", "blocked"
    else:
        for anomaly in blocking:
            if anomaly["scope_type"] == "block":
                connection.execute("UPDATE blocks SET use_state = 'blocked' WHERE block_id = ?",
                                   (anomaly["target_id"],))
            elif anomaly["scope_type"] == "page":
                connection.execute("UPDATE pages SET use_state = 'blocked' WHERE page_id = ?",
                                   (anomaly["target_id"],))
                connection.execute("UPDATE blocks SET use_state = 'blocked' WHERE page_id = ?",
                                   (anomaly["target_id"],))
            elif anomaly["scope_type"] == "relation":
                relation = connection.execute(
                    "SELECT from_block_id, to_block_id FROM page_relations WHERE relation_id = ?",
                    (anomaly["target_id"],),
                ).fetchone()
                if relation:
                    for block_id in (relation["from_block_id"], relation["to_block_id"]):
                        if block_id:
                            connection.execute("UPDATE blocks SET use_state = 'blocked' WHERE block_id = ?",
                                               (block_id,))
        processing_state = "needs_review" if blocking else "accepted"
        usable_body_blocks = connection.execute(
            """SELECT COUNT(*) FROM blocks b JOIN pages p ON p.page_id = b.page_id
               WHERE p.source_id = ? AND b.use_state = 'research_usable'
                 AND b.block_type NOT IN ('header', 'footer', 'page_number')""",
            (source_id,),
        ).fetchone()[0]
        use_state = "blocked" if blocking and usable_body_blocks == 0 else ("partial" if blocking else "research_usable")
    connection.execute(
        "UPDATE sources SET processing_state = ?, use_state = ? WHERE source_id = ?",
        (processing_state, use_state, source_id),
    )
