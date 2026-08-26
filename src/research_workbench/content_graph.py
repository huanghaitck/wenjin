from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .db import connect


def _id(kind: str, value: str) -> str:
    return "CGN_" + hashlib.sha256(f"{kind}\0{value}".encode("utf-8")).hexdigest()[:24]


def _edge(source: str, relation: str, target: str) -> dict[str, str]:
    return {
        "edge_id": "CGE_" + hashlib.sha256(f"{source}\0{relation}\0{target}".encode("utf-8")).hexdigest()[:24],
        "source_node_id": source, "relation": relation, "target_node_id": target,
        "origin": "project_content",
    }


def _decode(value: str | None) -> list[Any]:
    try:
        result = json.loads(value or "[]")
        return result if isinstance(result, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def project_content_graph(project_root: Path, query: str = "", limit: int = 160) -> dict[str, Any]:
    """Build a bounded graph from current page blocks and approved research objects.

    Page/block nodes are search/navigation aids. Event relations require approved event rows;
    evidence relations retain their existing qualification and claim status.
    """
    query = str(query).strip()
    limit = max(20, min(int(limit), 500))
    contains = f"%{query}%"
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, str]] = {}

    def add_node(kind: str, key: str, label: str, **metadata: Any) -> str:
        node_id = _id(kind, key)
        nodes[node_id] = {
            "node_id": node_id, "node_type": kind, "label": label,
            "origin": "project_content", **metadata,
        }
        return node_id

    def add_edge(source: str, relation: str, target: str) -> None:
        item = _edge(source, relation, target)
        edges[item["edge_id"]] = item

    with connect(project_root) as connection:
        source_rows = connection.execute(
            """SELECT s.source_id, s.title, s.processing_state, s.use_state,
                      l.library_work_id
               FROM sources s LEFT JOIN source_library_links l ON l.source_id = s.source_id
               WHERE (? = '' OR s.title LIKE ?) ORDER BY s.created_at LIMIT ?""",
            (query, contains, limit),
        ).fetchall()
        source_nodes: dict[str, str] = {}
        for row in source_rows:
            source_nodes[row["source_id"]] = add_node(
                "source", row["source_id"], row["title"], source_id=row["source_id"],
                status=row["use_state"], processing_state=row["processing_state"],
                library_work_id=row["library_work_id"] or "",
            )

        block_clause = "AND (b.block_type IN ('title','heading','subheading') OR b.block_order <= 2)"
        parameters: list[Any] = []
        if query:
            block_clause = "AND COALESCE(b.human_text, b.machine_text) LIKE ?"
            parameters.append(contains)
        block_rows = connection.execute(
            f"""SELECT s.source_id, s.title, p.page_id, p.physical_page, p.printed_page,
                       p.verification_state AS page_verification, p.use_state AS page_use_state,
                       b.block_id, b.block_type, b.block_order,
                       COALESCE(b.human_text, b.machine_text) AS text,
                       b.verification_state, b.use_state
                FROM blocks b JOIN pages p ON p.page_id = b.page_id
                JOIN sources s ON s.source_id = p.source_id
                WHERE b.use_state = 'research_usable' {block_clause}
                ORDER BY s.created_at, p.physical_page, b.block_order LIMIT ?""",
            (*parameters, limit),
        ).fetchall()
        page_nodes: dict[str, str] = {}
        for row in block_rows:
            source_node = source_nodes.get(row["source_id"])
            if source_node is None:
                source_node = add_node("source", row["source_id"], row["title"], source_id=row["source_id"], status="project_source")
                source_nodes[row["source_id"]] = source_node
            source_title = " ".join(str(row["title"] or "").split())
            if len(source_title) > 28:
                source_title = source_title[:28] + "…"
            page_reference = str(row["printed_page"] or f"PDF第{row['physical_page']}页")
            page_label = f"{source_title} · {page_reference}"
            page_node = page_nodes.get(row["page_id"])
            if page_node is None:
                page_node = add_node(
                    "page", row["page_id"], page_label, source_id=row["source_id"], page_id=row["page_id"],
                    physical_page=row["physical_page"], printed_page=row["printed_page"] or "",
                    status=row["page_verification"], use_state=row["page_use_state"],
                )
                page_nodes[row["page_id"]] = page_node
                add_edge(source_node, "contains_page", page_node)
            text = " ".join(str(row["text"] or "").split())
            if not text:
                continue
            label = text[:70] + ("…" if len(text) > 70 else "")
            block_node = add_node(
                "content", row["block_id"], label, source_id=row["source_id"], page_id=row["page_id"],
                block_id=row["block_id"], physical_page=row["physical_page"],
                printed_page=row["printed_page"] or "", excerpt=text[:700],
                block_type=row["block_type"], status=row["verification_state"], use_state=row["use_state"],
            )
            add_edge(page_node, "contains_content", block_node)

        event_rows = connection.execute(
            """SELECT * FROM research_event_rows WHERE status = 'approved'
               AND (? = '' OR event_date LIKE ? OR start_place LIKE ? OR end_place LIKE ?
                    OR route LIKE ? OR investigation_object LIKE ? OR chinese_participants LIKE ?
                    OR original_text LIKE ? OR translation LIKE ? OR notes LIKE ?)
               ORDER BY event_date, created_at LIMIT ?""",
            (query, *([contains] * 9), limit),
        ).fetchall()
        for row in event_rows:
            summary = "；".join(value for value in (
                row["route"], row["investigation_object"], row["chinese_participants"], row["notes"],
            ) if str(value).strip())
            event_node = add_node(
                "event", row["event_id"], row["event_date"] or row["case_id"], source_id=row["source_id"],
                event_id=row["event_id"], status="approved", excerpt=summary[:700],
                printed_pages=_decode(row["printed_pages_json"]), physical_pages=_decode(row["physical_pages_json"]),
            )
            source_node = source_nodes.get(row["source_id"])
            if source_node:
                add_edge(source_node, "records_event", event_node)
            entity_values = (
                ("case", row["case_id"], "belongs_to_case"),
                ("date", row["event_date"], "dated"),
                ("place", row["start_place"], "starts_at"),
                ("place", row["end_place"], "ends_at"),
                ("topic", row["investigation_object"], "investigates"),
            )
            for entity_type, raw_label, relation in entity_values:
                label = " ".join(str(raw_label or "").split())
                if not label:
                    continue
                entity_node = add_node(
                    "entity", f"{entity_type}:{label.casefold()}", label,
                    entity_type=entity_type, status="approved_event_field", excerpt=label,
                )
                add_edge(event_node, relation, entity_node)
            for page_id in _decode(row["page_ids_json"]):
                page_node = page_nodes.get(str(page_id))
                if page_node:
                    add_edge(event_node, "anchored_in", page_node)

        evidence_rows = connection.execute(
            """SELECT e.*, c.claim_id, c.text AS claim_text, c.status AS claim_status, ce.relation,
                      p.printed_page
               FROM evidence_items e
               LEFT JOIN claim_evidence ce ON ce.evidence_id = e.evidence_id
               LEFT JOIN claims c ON c.claim_id = ce.claim_id
               JOIN pages p ON p.page_id = e.page_id
               WHERE e.status = 'verified'
                 AND (? = '' OR e.quote LIKE ? OR e.note LIKE ? OR c.text LIKE ?)
               ORDER BY e.created_at LIMIT ?""",
            (query, contains, contains, contains, limit),
        ).fetchall()
        claim_nodes: dict[str, str] = {}
        for row in evidence_rows:
            evidence_node = add_node(
                "evidence", row["evidence_id"], str(row["quote"])[:70], source_id=row["source_id"],
                evidence_id=row["evidence_id"], page_id=row["page_id"], block_id=row["block_id"],
                physical_page=row["physical_page"], printed_page=row["printed_page"] or "",
                status=row["qualification"], excerpt=str(row["quote"])[:700], note=row["note"],
            )
            source_node = source_nodes.get(row["source_id"])
            if source_node:
                add_edge(source_node, "has_evidence", evidence_node)
            page_node = page_nodes.get(row["page_id"])
            if page_node:
                add_edge(evidence_node, "anchored_in", page_node)
            if row["claim_id"]:
                claim_node = claim_nodes.get(row["claim_id"])
                if claim_node is None:
                    claim_node = add_node(
                        "claim", row["claim_id"], row["claim_text"], claim_id=row["claim_id"],
                        status=row["claim_status"], excerpt=row["claim_text"],
                    )
                    claim_nodes[row["claim_id"]] = claim_node
                add_edge(claim_node, row["relation"] or "linked_to", evidence_node)

    type_counts: dict[str, int] = {}
    for node in nodes.values():
        type_counts[node["node_type"]] = type_counts.get(node["node_type"], 0) + 1
    return {
        "nodes": list(nodes.values()), "edges": list(edges.values()),
        "node_count": len(nodes), "edge_count": len(edges), "type_counts": type_counts,
        "query": query, "boundary": "current_markdown_blocks_plus_approved_events_and_verified_evidence",
    }
