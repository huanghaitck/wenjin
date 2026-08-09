from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
DATABASE_NAME = "project.sqlite3"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE schema_meta (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    current_stage TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,
    original_name TEXT NOT NULL,
    acquisition_state TEXT NOT NULL,
    processing_state TEXT NOT NULL,
    use_state TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE source_versions (
    source_version_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    project_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_id, sha256)
);

CREATE TABLE pages (
    page_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    physical_page INTEGER NOT NULL,
    printed_page TEXT,
    page_type TEXT NOT NULL,
    verification_state TEXT NOT NULL,
    use_state TEXT NOT NULL,
    machine_payload_json TEXT NOT NULL,
    human_payload_json TEXT,
    UNIQUE(source_id, physical_page)
);

CREATE TABLE blocks (
    block_id TEXT PRIMARY KEY,
    page_id TEXT NOT NULL REFERENCES pages(page_id),
    block_order INTEGER NOT NULL,
    block_type TEXT NOT NULL,
    machine_text TEXT NOT NULL,
    human_text TEXT,
    verification_state TEXT NOT NULL,
    use_state TEXT NOT NULL,
    source_region_json TEXT,
    UNIQUE(page_id, block_order)
);

CREATE TABLE page_relations (
    relation_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    from_block_id TEXT REFERENCES blocks(block_id),
    to_block_id TEXT REFERENCES blocks(block_id),
    relation_type TEXT NOT NULL,
    machine_value TEXT NOT NULL,
    human_value TEXT,
    verification_state TEXT NOT NULL
);

CREATE TABLE anomalies (
    anomaly_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    scope_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    repair_id TEXT
);

CREATE TABLE repair_records (
    repair_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    scope_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    base_version TEXT NOT NULL,
    before_hash TEXT NOT NULL,
    corrected_payload_json TEXT NOT NULL,
    source_page_refs_json TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    reason TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    validation_status TEXT NOT NULL
);

CREATE TABLE staging_receipts (
    receipt_id TEXT PRIMARY KEY,
    receipt_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    input_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    applied_at TEXT
);

CREATE TABLE audit_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_pages_source ON pages(source_id);
CREATE INDEX idx_blocks_page ON blocks(page_id);
CREATE INDEX idx_anomalies_source_status ON anomalies(source_id, status);
CREATE INDEX idx_audit_project ON audit_events(project_id, event_id);
"""


def database_path(project_root: Path) -> Path:
    return project_root / DATABASE_NAME


@contextmanager
def connect(project_root: Path) -> Iterator[sqlite3.Connection]:
    path = database_path(project_root)
    if not path.is_file():
        raise FileNotFoundError(f"project database does not exist: {path}")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(project_root: Path, project_id: str, title: str) -> None:
    path = database_path(project_root)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        now = utc_now()
        connection.execute(
            "INSERT INTO schema_meta(version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, now),
        )
        connection.execute(
            "INSERT INTO projects(project_id, title, current_stage, created_at) VALUES (?, ?, ?, ?)",
            (project_id, title, "M1_DOCUMENT_REPAIR", now),
        )
        connection.execute(
            """INSERT INTO audit_events(
                   project_id, event_type, entity_type, entity_id, payload_json, created_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (project_id, "project_initialized", "project", project_id, "{}", now),
        )
        connection.commit()
    finally:
        connection.close()


def project_id(connection: sqlite3.Connection) -> str:
    row = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()
    if row is None:
        raise RuntimeError("project row is missing")
    return str(row["project_id"])


def append_audit(
    connection: sqlite3.Connection,
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any] | None = None,
) -> None:
    connection.execute(
        """INSERT INTO audit_events(
               project_id, event_type, entity_type, entity_id, payload_json, created_at
           ) VALUES (?, ?, ?, ?, ?, ?)""",
        (
            project_id(connection),
            event_type,
            entity_type,
            entity_id,
            json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
            utc_now(),
        ),
    )
