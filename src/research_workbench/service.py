from __future__ import annotations

import csv
import hashlib
import json
import shutil
import uuid
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pymupdf

from . import __version__
from .db import SCHEMA_VERSION, append_audit, connect, initialize_database, utc_now
from .vision import (
    PAGE_OCR_PROMPT,
    PROMPT_VERSION,
    OcrSettings,
    normalize_ocr_content,
    page_ocr_prompt,
    request_page_ocr,
)


BLOCKING_CATEGORIES = {"content", "location"}


def _source_research_context(project_root: Path) -> dict[str, dict[str, Any]]:
    manifest = project_root / "research" / "source_manifest.csv"
    if not manifest.is_file():
        return {}
    fields = (
        "author", "title", "version", "date", "language", "source_type", "carrier",
        "text_layer", "witness_relation", "rights_scope", "reading_status",
        "verification_status", "notes",
    )
    contexts: dict[str, dict[str, Any]] = {}
    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            source_id = str(row.get("source_id", "")).strip()
            if not source_id:
                continue
            context = {field: str(row.get(field, "")).strip() for field in fields if str(row.get(field, "")).strip()}
            context["citable"] = str(row.get("citable", "")).strip().lower() == "true"
            contexts[source_id] = context
    return contexts


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


def _replace_machine_structure(connection: Any, source_id: str) -> bool:
    if connection.execute("SELECT 1 FROM pages WHERE source_id = ? LIMIT 1", (source_id,)).fetchone() is None:
        return False
    protected_checks = (
        ("human page review", """SELECT 1 FROM pages WHERE source_id = ? AND
            (verification_state != 'machine_parsed' OR human_payload_json IS NOT NULL) LIMIT 1"""),
        ("human block review", """SELECT 1 FROM blocks WHERE page_id IN
            (SELECT page_id FROM pages WHERE source_id = ?) AND
            (verification_state != 'machine_parsed' OR human_text IS NOT NULL) LIMIT 1"""),
        ("human relation review", """SELECT 1 FROM page_relations WHERE source_id = ? AND
            (verification_state != 'machine_parsed' OR human_value IS NOT NULL) LIMIT 1"""),
        ("repair records", "SELECT 1 FROM repair_records WHERE source_id = ? LIMIT 1"),
        ("OCR proposals", "SELECT 1 FROM ocr_proposals WHERE source_id = ? LIMIT 1"),
        ("reading notes", "SELECT 1 FROM reading_notes WHERE source_id = ? LIMIT 1"),
        ("evidence", "SELECT 1 FROM evidence_items WHERE source_id = ? LIMIT 1"),
        ("research events", "SELECT 1 FROM research_event_rows WHERE source_id = ? LIMIT 1"),
        ("historiography", """SELECT 1 FROM historiography_entries
            WHERE instr(source_refs_json, ?) > 0 LIMIT 1"""),
    )
    protected = [label for label, sql in protected_checks if connection.execute(sql, (source_id,)).fetchone()]
    if protected:
        raise ValueError(
            "machine structure cannot be replaced after downstream or human work: " + ", ".join(protected)
        )
    connection.execute("DELETE FROM anomalies WHERE source_id = ?", (source_id,))
    connection.execute("DELETE FROM page_relations WHERE source_id = ?", (source_id,))
    connection.execute(
        "DELETE FROM blocks WHERE page_id IN (SELECT page_id FROM pages WHERE source_id = ?)",
        (source_id,),
    )
    connection.execute("DELETE FROM pages WHERE source_id = ?", (source_id,))
    return True


def import_structure(
    project_root: Path,
    source_id: str,
    packet_path: Path,
    replace_machine_structure: bool = False,
) -> dict[str, Any]:
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

        has_structure = connection.execute(
            "SELECT 1 FROM pages WHERE source_id = ? LIMIT 1", (source_id,)
        ).fetchone() is not None
        replaced = False
        if has_structure:
            if not replace_machine_structure:
                raise ValueError("source already has a structure; use explicit machine reprocessing")
            replaced = _replace_machine_structure(connection, source_id)

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
            "structure_reprocessed" if replaced else "structure_imported",
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


def correct_block(project_root: Path, block_id: str, corrected_text: str,
                  reviewer: str, reason: str, block_type: str | None = None) -> dict[str, Any]:
    corrected_text, reviewer, reason = corrected_text.strip(), reviewer.strip(), reason.strip()
    if not corrected_text or not reviewer or not reason:
        raise ValueError("manual block correction requires text, reviewer and reason")
    with connect(project_root) as connection:
        block = connection.execute(
            """SELECT b.*, p.source_id FROM blocks b
               JOIN pages p ON p.page_id = b.page_id WHERE b.block_id = ?""",
            (block_id,),
        ).fetchone()
        if block is None:
            raise KeyError(f"unknown block: {block_id}")
        before_text = block["human_text"] if block["human_text"] is not None else block["machine_text"]
        corrected_type = (block_type or block["block_type"]).strip()
        if corrected_type not in {"paragraph", "heading", "footnote", "header", "footer", "page_number"}:
            raise ValueError("unsupported block type")
        if corrected_text == before_text and corrected_type == block["block_type"]:
            raise ValueError("manual correction did not change the block")
        repair_id = f"REP_{uuid.uuid4().hex}"
        target = {"source_id": block["source_id"], "scope_type": "block", "target_id": block_id}
        _insert_repair(
            connection, repair_id, target, {"text": corrected_text, "block_type": corrected_type},
            [block["page_id"]], reviewer, reason,
            _json_hash({"text": before_text, "block_type": block["block_type"]}),
        )
        connection.execute(
            """UPDATE blocks SET human_text = ?, block_type = ?, verification_state = 'human_repaired',
                      use_state = 'research_usable' WHERE block_id = ?""",
            (corrected_text, corrected_type, block_id),
        )
        connection.execute(
            """UPDATE pages SET verification_state = 'human_spot_checked'
               WHERE page_id = ? AND verification_state NOT IN ('human_verified', 'human_repaired')""",
            (block["page_id"],),
        )
        _recalculate_source_state(connection, block["source_id"])
        append_audit(connection, "block_corrected", "block", block_id, {"repair_id": repair_id})
    return {"repair_id": repair_id, "scope_type": "block", "target_id": block_id,
            "block_type": corrected_type}


def correct_printed_page(project_root: Path, page_id: str, printed_page: str,
                         reviewer: str, reason: str) -> dict[str, Any]:
    printed_page, reviewer, reason = printed_page.strip(), reviewer.strip(), reason.strip()
    if not printed_page or not reviewer or not reason:
        raise ValueError("printed page correction requires a label, reviewer and reason")
    with connect(project_root) as connection:
        page = connection.execute(
            "SELECT page_id, source_id, printed_page FROM pages WHERE page_id = ?", (page_id,)
        ).fetchone()
        if page is None:
            raise KeyError(f"unknown page: {page_id}")
        if printed_page == (page["printed_page"] or ""):
            raise ValueError("printed page label did not change")
        repair_id = f"REP_{uuid.uuid4().hex}"
        target = {"source_id": page["source_id"], "scope_type": "page", "target_id": page_id}
        _insert_repair(
            connection, repair_id, target, {"printed_page": printed_page}, [page_id],
            reviewer, reason, _json_hash({"printed_page": page["printed_page"]}),
        )
        connection.execute(
            """UPDATE pages SET printed_page = ?, verification_state =
                       CASE WHEN verification_state = 'human_verified' THEN verification_state
                            ELSE 'human_spot_checked' END
               WHERE page_id = ?""",
            (printed_page, page_id),
        )
        append_audit(
            connection, "printed_page_corrected", "page", page_id,
            {"repair_id": repair_id, "before": page["printed_page"], "after": printed_page},
        )
    return {"repair_id": repair_id, "page_id": page_id, "printed_page": printed_page}


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
        relation_snapshots = _page_relation_snapshots(connection, page["page_id"])
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
        relation_changes = _remap_page_relation_endpoints(
            connection, page["page_id"], anomaly["source_id"], relation_snapshots,
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
        append_audit(
            connection,
            "page_repaired",
            "page",
            page["page_id"],
            {"repair_id": repair_id, "relation_endpoint_changes": relation_changes},
        )
        return {"repair_id": repair_id, "scope_type": "page", "target_id": page["page_id"]}


def _page_relation_snapshots(connection: Any, page_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT r.*,
                  fb.page_id AS from_page_id, fb.block_type AS from_block_type,
                  COALESCE(fb.human_text, fb.machine_text) AS from_text,
                  tb.page_id AS to_page_id, tb.block_type AS to_block_type,
                  COALESCE(tb.human_text, tb.machine_text) AS to_text
           FROM page_relations r
           LEFT JOIN blocks fb ON fb.block_id = r.from_block_id
           LEFT JOIN blocks tb ON tb.block_id = r.to_block_id
           WHERE fb.page_id = ? OR tb.page_id = ?""",
        (page_id, page_id),
    ).fetchall()
    return [dict(row) for row in rows]


def _remap_page_relation_endpoints(
    connection: Any,
    page_id: str,
    source_id: str,
    snapshots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    active = [dict(row) for row in connection.execute(
        """SELECT block_id, block_order, block_type,
                  COALESCE(human_text, machine_text) AS effective_text
           FROM blocks WHERE page_id = ? AND use_state != 'superseded'
           ORDER BY block_order""",
        (page_id,),
    ).fetchall()]
    eligible = [block for block in active if block["block_type"] in {"paragraph", "footnote"}]
    changes: list[dict[str, Any]] = []

    def normalized(value: str | None) -> str:
        return " ".join((value or "").split())

    for relation in snapshots:
        endpoints = {
            "from": relation["from_block_id"],
            "to": relation["to_block_id"],
        }
        invalidated = False
        for side in ("from", "to"):
            if relation[f"{side}_page_id"] != page_id:
                continue
            old_text = normalized(relation[f"{side}_text"])
            old_type = relation[f"{side}_block_type"]
            same_type = [block for block in eligible if block["block_type"] == old_type]
            matches = [
                (
                    SequenceMatcher(None, old_text, normalized(block["effective_text"])).ratio(),
                    block,
                )
                for block in same_type
            ]
            best_ratio, best = max(matches, key=lambda item: item[0]) if matches else (0.0, None)
            if best is not None and best_ratio >= 0.8:
                endpoints[side] = best["block_id"]
                continue

            candidates = same_type or [block for block in eligible if block["block_type"] == "paragraph"] or eligible
            endpoints[side] = (candidates[-1] if side == "from" else candidates[0])["block_id"] if candidates else None
            invalidated = True

        endpoint_changed = (
            endpoints["from"] != relation["from_block_id"]
            or endpoints["to"] != relation["to_block_id"]
        )
        if endpoint_changed:
            connection.execute(
                """UPDATE page_relations SET from_block_id = ?, to_block_id = ?
                   WHERE relation_id = ?""",
                (endpoints["from"], endpoints["to"], relation["relation_id"]),
            )
        if invalidated:
            machine_value = {
                "continues": None,
                "confidence": "requires_human",
                "reason": "page structure changed after repair",
            }
            connection.execute(
                """UPDATE page_relations
                   SET machine_value = ?, human_value = NULL, verification_state = 'needs_review'
                   WHERE relation_id = ?""",
                (json.dumps(machine_value, ensure_ascii=False, sort_keys=True), relation["relation_id"]),
            )
            anomaly_id = f"{relation['relation_id']}:A_ENDPOINT_REVIEW"
            connection.execute(
                """INSERT INTO anomalies(
                       anomaly_id, source_id, scope_type, target_id, severity, category,
                       message, status, created_at, resolved_at, repair_id
                   ) VALUES (?, ?, 'relation', ?, 'local', 'location', ?, 'open', ?, NULL, NULL)
                   ON CONFLICT(anomaly_id) DO UPDATE SET
                       message = excluded.message, status = 'open', created_at = excluded.created_at,
                       resolved_at = NULL, repair_id = NULL""",
                (
                    anomaly_id,
                    source_id,
                    relation["relation_id"],
                    "Page structure changed this relation endpoint; compare both original pages again.",
                    utc_now(),
                ),
            )
        if endpoint_changed or invalidated:
            change = {
                "relation_id": relation["relation_id"],
                "before": {
                    "from_block_id": relation["from_block_id"],
                    "to_block_id": relation["to_block_id"],
                },
                "after": endpoints,
                "human_decision_preserved": not invalidated,
            }
            changes.append(change)
            append_audit(
                connection,
                "relation_endpoint_remapped",
                "relation",
                relation["relation_id"],
                change,
            )
    return changes


def revise_page(
    project_root: Path,
    page_id: str,
    corrected_page: dict[str, Any],
    reviewer: str,
    reason: str,
) -> dict[str, Any]:
    with connect(project_root) as connection:
        page = connection.execute(
            "SELECT page_id, source_id, page_type FROM pages WHERE page_id = ?",
            (page_id,),
        ).fetchone()
        if page is None:
            raise KeyError(f"unknown page: {page_id}")
        if page["page_type"] == "docx_locator":
            raise ValueError("page revisions require an original PDF page")
        anomaly = connection.execute(
            """SELECT anomaly_id FROM anomalies
               WHERE scope_type = 'page' AND target_id = ? AND status = 'open'
               ORDER BY created_at, anomaly_id LIMIT 1""",
            (page_id,),
        ).fetchone()
        if anomaly is None:
            anomaly_id = f"ANO_{uuid.uuid4().hex}"
            connection.execute(
                """INSERT INTO anomalies(
                       anomaly_id, source_id, scope_type, target_id, severity, category,
                       message, status, created_at, resolved_at, repair_id
                   ) VALUES (?, ?, 'page', ?, 'local', 'content', ?, 'open', ?, NULL, NULL)""",
                (
                    anomaly_id,
                    page["source_id"],
                    page_id,
                    "Researcher requested another full-page structural correction.",
                    utc_now(),
                ),
            )
            append_audit(
                connection,
                "page_revision_requested",
                "page",
                page_id,
                {"anomaly_id": anomaly_id},
            )
        else:
            anomaly_id = str(anomaly["anomaly_id"])
    return submit_page_repair(project_root, anomaly_id, corrected_page, reviewer, reason)


def verify_page(project_root: Path, page_id: str, reviewer: str, reason: str) -> dict[str, Any]:
    reviewer, reason = reviewer.strip(), reason.strip()
    if not reviewer or not reason:
        raise ValueError("page verification requires reviewer and reason")
    with connect(project_root) as connection:
        page = connection.execute(
            "SELECT page_id, source_id, use_state FROM pages WHERE page_id = ?", (page_id,)
        ).fetchone()
        if page is None:
            raise KeyError(f"unknown page: {page_id}")
        block_ids = [row[0] for row in connection.execute(
            "SELECT block_id FROM blocks WHERE page_id = ? AND use_state != 'superseded'", (page_id,)
        )]
        targets = [page_id, *block_ids]
        placeholders = ",".join("?" for _ in targets)
        blocking = connection.execute(
            f"""SELECT COUNT(*) FROM anomalies
                WHERE status = 'open' AND severity != 'advisory'
                  AND scope_type IN ('page', 'block') AND target_id IN ({placeholders})""",
            targets,
        ).fetchone()[0]
        if blocking:
            raise ValueError("resolve page or block anomalies before verifying this page")
        unusable = connection.execute(
            """SELECT COUNT(*) FROM blocks
               WHERE page_id = ? AND use_state NOT IN ('research_usable', 'superseded')""",
            (page_id,),
        ).fetchone()[0]
        if page["use_state"] != "research_usable" or unusable:
            raise ValueError("blocked page content cannot be verified")
        connection.execute(
            "UPDATE pages SET verification_state = 'human_verified' WHERE page_id = ?", (page_id,)
        )
        connection.execute(
            """UPDATE blocks SET verification_state = 'human_verified'
               WHERE page_id = ? AND use_state != 'superseded'""",
            (page_id,),
        )
        append_audit(connection, "page_verified", "page", page_id, {"reviewer": reviewer, "reason": reason})
    return {"page_id": page_id, "verification_state": "human_verified", "reviewer": reviewer}


def reject_source_identity(project_root: Path, source_id: str, reviewer: str, reason: str) -> dict[str, Any]:
    reviewer, reason = reviewer.strip(), reason.strip()
    if not reviewer or not reason:
        raise ValueError("source rejection requires reviewer and reason")
    with connect(project_root) as connection:
        source = connection.execute(
            "SELECT source_id, title FROM sources WHERE source_id = ?", (source_id,)
        ).fetchone()
        if source is None:
            raise KeyError(f"unknown source: {source_id}")
        anomaly_id = f"{source_id}:A_IDENTITY"
        connection.execute(
            "UPDATE sources SET processing_state = 'error', use_state = 'blocked' WHERE source_id = ?",
            (source_id,),
        )
        connection.execute("UPDATE pages SET use_state = 'blocked' WHERE source_id = ?", (source_id,))
        connection.execute(
            """UPDATE blocks SET use_state = 'blocked' WHERE page_id IN (
                   SELECT page_id FROM pages WHERE source_id = ?
               ) AND use_state != 'superseded'""", (source_id,),
        )
        connection.execute(
            """INSERT INTO anomalies(
                   anomaly_id, source_id, scope_type, target_id, severity, category,
                   message, status, created_at, resolved_at, repair_id
               ) VALUES (?, ?, 'source', ?, 'systemic', 'identity', ?, 'open', ?, NULL, NULL)
               ON CONFLICT(anomaly_id) DO UPDATE SET message=excluded.message, status='open', resolved_at=NULL""",
            (anomaly_id, source_id, source_id, reason, utc_now()),
        )
        append_audit(connection, "source_identity_rejected", "source", source_id, {
            "reviewer": reviewer, "reason": reason, "previous_title": source["title"],
        })
    return {"source_id": source_id, "processing_state": "error", "use_state": "blocked",
            "anomaly_id": anomaly_id, "reviewer": reviewer, "reason": reason}


def verify_block(project_root: Path, block_id: str, reviewer: str, reason: str) -> dict[str, Any]:
    reviewer, reason = reviewer.strip(), reason.strip()
    if not reviewer or not reason:
        raise ValueError("block verification requires reviewer and reason")
    with connect(project_root) as connection:
        block = connection.execute(
            """SELECT b.block_id, b.page_id, b.use_state AS block_use_state,
                      p.source_id, p.use_state AS page_use_state
               FROM blocks b JOIN pages p ON p.page_id = b.page_id WHERE b.block_id = ?""",
            (block_id,),
        ).fetchone()
        if block is None:
            raise KeyError(f"unknown block: {block_id}")
        blocking = connection.execute(
            """SELECT COUNT(*) FROM anomalies
               WHERE status = 'open' AND severity != 'advisory'
                 AND ((scope_type = 'block' AND target_id = ?)
                   OR (scope_type = 'page' AND target_id = ?)
                   OR (scope_type = 'relation' AND target_id IN (
                       SELECT relation_id FROM page_relations
                       WHERE from_block_id = ? OR to_block_id = ?)))""",
            (block_id, block["page_id"], block_id, block_id),
        ).fetchone()[0]
        if blocking:
            raise ValueError("resolve this block or page anomaly before verification")
        systemic = connection.execute(
            """SELECT 1 FROM anomalies WHERE source_id = ? AND status = 'open'
               AND scope_type = 'source' AND severity = 'systemic' LIMIT 1""",
            (block["source_id"],),
        ).fetchone()
        if ((block["block_use_state"] != "research_usable" or block["page_use_state"] != "research_usable")
                and systemic is None):
            raise ValueError("blocked page content cannot be verified")
        connection.execute(
            """UPDATE blocks SET verification_state = 'human_verified', use_state = 'research_usable'
               WHERE block_id = ?""",
            (block_id,),
        )
        connection.execute(
            """UPDATE pages SET verification_state = 'human_spot_checked', use_state = 'research_usable'
               WHERE page_id = ? AND verification_state NOT IN ('human_verified', 'human_repaired')""",
            (block["page_id"],),
        )
        _recalculate_source_state(connection, block["source_id"])
        append_audit(connection, "block_verified", "block", block_id, {"reviewer": reviewer, "reason": reason})
    return {"block_id": block_id, "page_id": block["page_id"], "verification_state": "human_verified"}


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
        project["app_version"] = __version__
        project["schema_version"] = SCHEMA_VERSION
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
    contexts = _source_research_context(project_root)
    with connect(project_root) as connection:
        rows = [dict(row) for row in connection.execute(
            """SELECT s.source_id, s.title, s.original_name, s.processing_state, s.use_state,
                      s.created_at, (SELECT COUNT(*) FROM pages p WHERE p.source_id = s.source_id) AS page_count,
                      COALESCE((SELECT sv.byte_count FROM source_versions sv WHERE sv.source_id = s.source_id
                                ORDER BY sv.created_at DESC LIMIT 1), 0) AS byte_count,
                      COALESCE(cm.verification_status, 'UNVERIFIED') AS citation_verification_status
               FROM sources s LEFT JOIN source_citation_metadata cm ON cm.source_id = s.source_id
               ORDER BY s.created_at, s.source_id"""
        ).fetchall()]
    for row in rows:
        if row["source_id"] in contexts:
            row["research_context"] = contexts[row["source_id"]]
    return rows


def source_view(project_root: Path, source_id: str) -> dict[str, Any]:
    contexts = _source_research_context(project_root)
    with connect(project_root) as connection:
        source = connection.execute(
            """SELECT source_id, title, original_name, processing_state, use_state
               FROM sources WHERE source_id = ?""",
            (source_id,),
        ).fetchone()
        if source is None:
            raise KeyError(f"unknown source: {source_id}")
        source = dict(source)
        if source_id in contexts:
            source["research_context"] = contexts[source_id]
        citation_row = connection.execute(
            "SELECT * FROM source_citation_metadata WHERE source_id = ?", (source_id,)
        ).fetchone()
        source["citation_metadata"] = dict(citation_row) if citation_row else {
            "source_id": source_id, "author": "", "title": source["title"], "edition": "",
            "place": "", "publisher": "", "year": "", "type_code": "",
            "translator": "", "journal": "", "volume": "", "issue": "", "page_range": "",
            "verification_status": "UNVERIFIED",
            "verified_by": "", "verified_at": "",
        }
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
            "source": source,
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


def ocr_page_image_path(project_root: Path, page_id: str, render_scale: float = 4.0) -> Path:
    with connect(project_root) as connection:
        row = connection.execute(
            """SELECT p.source_id, p.physical_page, sv.project_path
               FROM pages p JOIN source_versions sv ON sv.source_id = p.source_id
               WHERE p.page_id = ? ORDER BY sv.created_at DESC LIMIT 1""",
            (page_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"unknown page: {page_id}")
    source_path = (project_root.resolve() / Path(str(row["project_path"]))).resolve()
    if project_root.resolve() not in source_path.parents or not source_path.is_file():
        raise FileNotFoundError(f"source PDF is missing: {source_path}")
    image_path = (
        project_root / "sources" / str(row["source_id"]) / "derived" / "ocr-pages"
        / f"page-{int(row['physical_page']):04d}@{render_scale:g}x.png"
    )
    if image_path.is_file():
        return image_path
    image_path.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(source_path) as document:
        pixmap = document[int(row["physical_page"]) - 1].get_pixmap(
            matrix=pymupdf.Matrix(render_scale, render_scale), alpha=False
        )
        pixmap.save(image_path)
    return image_path


def create_ocr_proposal(
    project_root: Path,
    page_id: str,
    settings: OcrSettings | None = None,
    reopen_verified: bool = False,
) -> dict[str, Any]:
    settings = settings or OcrSettings.from_environment()
    with connect(project_root) as connection:
        page = connection.execute(
            """SELECT page_id, source_id, page_type, verification_state, machine_payload_json
               FROM pages WHERE page_id = ?""",
            (page_id,),
        ).fetchone()
        if page is None:
            raise KeyError(f"unknown page: {page_id}")
        if page["page_type"] == "docx_locator":
            raise ValueError("OCR proposals require an original PDF page")
        if page["verification_state"] in {"human_verified", "human_repaired"} and not reopen_verified:
            raise ValueError("OCR proposals cannot reopen a human-verified page without explicit review")
        eligible = connection.execute(
            """SELECT anomaly_id FROM anomalies
               WHERE scope_type = 'page' AND target_id = ? AND status = 'open'
               ORDER BY created_at, anomaly_id LIMIT 1""",
            (page_id,),
        ).fetchone()
        if eligible is None:
            anomaly_id = _stable_id("ANO", page_id, "model-assisted-review")
            now = utc_now()
            connection.execute(
                """INSERT INTO anomalies(
                       anomaly_id, source_id, scope_type, target_id, severity, category,
                       message, status, created_at, resolved_at, repair_id
                   ) VALUES (?, ?, 'page', ?, 'local', 'content', ?, 'open', ?, NULL, NULL)""",
                (
                    anomaly_id,
                    page["source_id"],
                    page_id,
                    ("Researcher explicitly reopened a human-verified page for model-assisted comparison."
                     if reopen_verified else
                     "Researcher requested model-assisted retranscription of this unverified page."),
                    now,
                ),
            )
            _recalculate_source_state(connection, page["source_id"])
            append_audit(
                connection,
                "page_review_requested",
                "page",
                page_id,
                {"anomaly_id": anomaly_id, "reason": ("reopen_verified_page" if reopen_verified else
                                                        "model_assisted_retranscription")},
            )
    machine_payload = json.loads(page["machine_payload_json"])
    candidate_payload = {
        "printed_page": machine_payload.get("printed_page"),
        "blocks": [
            {"order": index, "type": block.get("type", "paragraph"), "text": block.get("text", "")}
            for index, block in enumerate(machine_payload.get("blocks", []), start=1)
            if str(block.get("text", "")).strip()
        ],
    }
    prompt = page_ocr_prompt(candidate_payload)
    image_path = ocr_page_image_path(project_root, page_id)
    raw_response, normalized_payload = request_page_ocr(image_path, settings, candidate_payload)
    return record_ocr_proposal(
        project_root,
        page_id,
        settings,
        raw_response,
        normalized_payload,
        image_path,
        prompt,
    )


def record_ocr_proposal(
    project_root: Path,
    page_id: str,
    settings: OcrSettings,
    raw_response: dict[str, Any],
    normalized_payload: dict[str, Any],
    proposal_image_path: Path | None = None,
    proposal_prompt: str = PAGE_OCR_PROMPT,
) -> dict[str, Any]:
    normalized_payload = normalize_ocr_content(
        json.dumps(normalized_payload, ensure_ascii=False)
    )
    image_path = proposal_image_path or page_image_path(project_root, page_id)
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
                _json_hash(proposal_prompt),
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


def correct_relation(
    project_root: Path,
    relation_id: str,
    from_block_id: str,
    to_block_id: str,
    continues: bool,
    reviewer: str,
    reason: str,
) -> dict[str, Any]:
    reviewer, reason = reviewer.strip(), reason.strip()
    if not reviewer or not reason:
        raise ValueError("relation correction requires reviewer and reason")
    with connect(project_root) as connection:
        relation = connection.execute(
            "SELECT * FROM page_relations WHERE relation_id = ?", (relation_id,)
        ).fetchone()
        if relation is None:
            raise KeyError(f"unknown relation: {relation_id}")
        blocks = connection.execute(
            """SELECT b.block_id, b.block_type, p.page_id, p.source_id, p.physical_page
               FROM blocks b JOIN pages p ON p.page_id = b.page_id
               WHERE b.block_id IN (?, ?)""",
            (from_block_id, to_block_id),
        ).fetchall()
        by_id = {row["block_id"]: row for row in blocks}
        if from_block_id not in by_id or to_block_id not in by_id:
            raise ValueError("relation correction references an unknown block")
        left, right = by_id[from_block_id], by_id[to_block_id]
        if left["source_id"] != relation["source_id"] or right["source_id"] != relation["source_id"]:
            raise ValueError("relation endpoints must belong to the same source")
        if right["physical_page"] != left["physical_page"] + 1:
            raise ValueError("relation endpoints must be on adjacent pages in reading order")
        allowed_types = {"paragraph", "footnote"}
        if left["block_type"] not in allowed_types or right["block_type"] not in allowed_types:
            raise ValueError("relation endpoints must be paragraph or footnote blocks")
        human_value = {"continues": continues}
        previous_human = json.loads(relation["human_value"]) if relation["human_value"] else None
        if (relation["from_block_id"], relation["to_block_id"], previous_human) == (
            from_block_id, to_block_id, human_value,
        ):
            raise ValueError("relation correction did not change the relation")
        repair_id = f"REP_{uuid.uuid4().hex}"
        target = {"source_id": relation["source_id"], "scope_type": "relation", "target_id": relation_id}
        before = {
            "from_block_id": relation["from_block_id"],
            "to_block_id": relation["to_block_id"],
            "human_value": previous_human,
        }

        corrected = {
            "from_block_id": from_block_id,
            "to_block_id": to_block_id,
            "continues": continues,
        }
        _insert_repair(
            connection, repair_id, target, corrected, [left["page_id"], right["page_id"]],
            reviewer, reason, _json_hash(before),
        )
        connection.execute(
            """UPDATE page_relations
               SET from_block_id = ?, to_block_id = ?, human_value = ?, verification_state = 'human_repaired'
               WHERE relation_id = ?""",
            (from_block_id, to_block_id, json.dumps(human_value, ensure_ascii=False, sort_keys=True), relation_id),
        )
        connection.execute(
            """UPDATE anomalies SET status = 'resolved', resolved_at = ?, repair_id = ?
               WHERE source_id = ? AND scope_type = 'relation' AND target_id = ? AND status = 'open'""",
            (utc_now(), repair_id, relation["source_id"], relation_id),
        )
        _recalculate_source_state(connection, relation["source_id"])
        append_audit(
            connection, "relation_corrected", "relation", relation_id,
            {"repair_id": repair_id, "before": before, "after": corrected},
        )
    return {
        "repair_id": repair_id,
        "relation_id": relation_id,
        "from_block_id": from_block_id,
        "to_block_id": to_block_id,
        "continues": continues,
    }


def save_source_citation_metadata(project_root: Path, source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    author = str(payload.get("author", "")).strip()
    title = str(payload.get("title", "")).strip()
    year = str(payload.get("year", "")).strip()
    verified_by = str(payload.get("verified_by", "")).strip()
    if not author or not title or not year or not verified_by:
        raise ValueError("引文元数据至少需要作者、题名、年份和核验人")
    now = utc_now()
    values = {
        "source_id": source_id,
        "author": author,
        "title": title,
        "edition": str(payload.get("edition", "")).strip(),
        "place": str(payload.get("place", "")).strip(),
        "publisher": str(payload.get("publisher", "")).strip(),
        "year": year,
        "type_code": str(payload.get("type_code", "")).strip().upper(),
        "translator": str(payload.get("translator", "")).strip(),
        "journal": str(payload.get("journal", "")).strip(),
        "volume": str(payload.get("volume", "")).strip(),
        "issue": str(payload.get("issue", "")).strip(),
        "page_range": str(payload.get("page_range", "")).strip(),
        "verification_status": "HUMAN_VERIFIED",
        "verified_by": verified_by,
        "verified_at": now,
    }
    with connect(project_root) as connection:
        if connection.execute("SELECT 1 FROM sources WHERE source_id = ?", (source_id,)).fetchone() is None:
            raise KeyError(f"unknown source: {source_id}")
        connection.execute(
            """INSERT OR REPLACE INTO source_citation_metadata(
                   source_id, author, title, edition, place, publisher, year, type_code,
                   verification_status, verified_by, verified_at, translator, journal, volume, issue, page_range
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            tuple(values[key] for key in (
                "source_id", "author", "title", "edition", "place", "publisher", "year", "type_code",
                "verification_status", "verified_by", "verified_at", "translator", "journal", "volume",
                "issue", "page_range",
            )),
        )
        append_audit(connection, "source_citation_metadata_verified", "source", source_id, {
            "author": author, "title": title, "year": year, "verified_by": verified_by,
        })
    return values


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
    page_types = connection.execute(
        "SELECT page_type, COUNT(*) AS count FROM pages WHERE source_id = ? GROUP BY page_type",
        (source_id,),
    ).fetchall()
    if page_types and all(row["page_type"] == "docx_locator" for row in page_types):
        connection.execute("UPDATE pages SET use_state = 'locator_only' WHERE source_id = ?", (source_id,))
        connection.execute(
            """UPDATE blocks SET use_state = 'locator_only'
               WHERE page_id IN (SELECT page_id FROM pages WHERE source_id = ?)""",
            (source_id,),
        )
        connection.execute(
            "UPDATE sources SET processing_state = 'accepted', use_state = 'locator_only' WHERE source_id = ?",
            (source_id,),
        )
        return
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
        connection.execute(
            """UPDATE pages SET use_state = 'blocked'
               WHERE source_id = ? AND verification_state NOT IN
                     ('human_spot_checked', 'human_verified', 'human_repaired')""",
            (source_id,),
        )
        connection.execute(
            """UPDATE blocks SET use_state = 'blocked'
               WHERE verification_state NOT IN ('human_verified', 'human_repaired')
                 AND page_id IN (SELECT page_id FROM pages WHERE source_id = ?)""",
            (source_id,),
        )
        usable_body_blocks = connection.execute(
            """SELECT COUNT(*) FROM blocks b JOIN pages p ON p.page_id = b.page_id
               WHERE p.source_id = ? AND b.use_state = 'research_usable'
                 AND b.block_type NOT IN ('header', 'footer', 'page_number')""",
            (source_id,),
        ).fetchone()[0]
        processing_state = "needs_review"
        use_state = "partial" if usable_body_blocks else "blocked"
    else:
        for anomaly in blocking:
            if anomaly["scope_type"] == "block":
                connection.execute("UPDATE blocks SET use_state = 'blocked' WHERE block_id = ?",
                                   (anomaly["target_id"],))
            elif anomaly["scope_type"] == "page":
                connection.execute("UPDATE pages SET use_state = 'blocked' WHERE page_id = ?",
                                   (anomaly["target_id"],))
                connection.execute(
                    """UPDATE blocks SET use_state = 'blocked'
                       WHERE page_id = ? AND verification_state NOT IN
                             ('human_verified', 'human_repaired')""",
                    (anomaly["target_id"],),
                )
            elif anomaly["scope_type"] == "relation":
                relation = connection.execute(
                    "SELECT from_block_id, to_block_id FROM page_relations WHERE relation_id = ?",
                    (anomaly["target_id"],),
                ).fetchone()
                if relation:
                    for block_id in (relation["from_block_id"], relation["to_block_id"]):
                        if block_id:
                            connection.execute(
                                """UPDATE blocks SET use_state = 'blocked'
                                   WHERE block_id = ? AND verification_state NOT IN
                                         ('human_verified', 'human_repaired')""",
                                (block_id,),
                            )
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
