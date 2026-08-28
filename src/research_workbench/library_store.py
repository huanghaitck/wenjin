from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .db import utc_now


LIBRARY_SCHEMA_VERSION = 4
LIBRARY_DATABASE_NAME = "library.sqlite3"
_INITIALIZE_LOCK = threading.Lock()
_INITIALIZED_PATHS: set[Path] = set()

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE library_meta (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE works (
    work_id TEXT PRIMARY KEY,
    canonical_title TEXT NOT NULL,
    author TEXT NOT NULL,
    language TEXT NOT NULL,
    material_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE editions (
    edition_id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES works(work_id),
    edition_label TEXT NOT NULL,
    publisher TEXT NOT NULL,
    publication_year TEXT NOT NULL,
    isbn TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE library_files (
    file_id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES works(work_id),
    edition_id TEXT NOT NULL REFERENCES editions(edition_id),
    path TEXT NOT NULL UNIQUE,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE file_versions (
    version_id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL REFERENCES library_files(file_id),
    sha256 TEXT NOT NULL,
    byte_count INTEGER NOT NULL,
    modified_ns INTEGER NOT NULL,
    format TEXT NOT NULL,
    page_count INTEGER,
    text_layer TEXT NOT NULL,
    triage_state TEXT NOT NULL,
    triage_reason TEXT NOT NULL,
    inspected_pages INTEGER NOT NULL,
    sample_text TEXT NOT NULL,
    qualification TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    skill_sha256 TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    is_current INTEGER NOT NULL
);

CREATE TABLE scan_sessions (
    session_id TEXT PRIMARY KEY,
    root_path TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    skill_sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    approved_at TEXT,
    processed_count INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    completed_at TEXT
);

CREATE TABLE scan_candidates (
    candidate_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES scan_sessions(session_id),
    path TEXT NOT NULL,
    format TEXT NOT NULL,
    byte_count INTEGER NOT NULL,
    modified_ns INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    suggested_title TEXT NOT NULL,
    suggested_author TEXT NOT NULL,
    suggested_year TEXT NOT NULL,
    suggested_publisher TEXT NOT NULL,
    suggested_language TEXT NOT NULL,
    suggested_material_type TEXT NOT NULL,
    page_count INTEGER,
    text_layer TEXT NOT NULL,
    triage_state TEXT NOT NULL,
    triage_reason TEXT NOT NULL,
    inspected_pages INTEGER NOT NULL,
    sample_text TEXT NOT NULL,
    proposed_action TEXT NOT NULL,
    existing_work_id TEXT,
    existing_edition_id TEXT,
    existing_file_id TEXT,
    status TEXT NOT NULL,
    error TEXT NOT NULL
);

CREATE TABLE tags (
    tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE work_tags (
    work_id TEXT NOT NULL REFERENCES works(work_id),
    tag_id INTEGER NOT NULL REFERENCES tags(tag_id),
    origin TEXT NOT NULL,
    PRIMARY KEY(work_id, tag_id)
);

CREATE TABLE author_aliases (
    alias_normalized TEXT PRIMARY KEY,
    alias TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    orcid TEXT NOT NULL,
    decided_by TEXT NOT NULL,
    decision_reason TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE library_project_links (
    work_id TEXT NOT NULL REFERENCES works(work_id),
    project_id TEXT NOT NULL,
    project_root TEXT NOT NULL,
    linked_at TEXT NOT NULL,
    PRIMARY KEY(work_id, project_id)
);

CREATE TABLE knowledge_nodes (
    node_id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL,
    label TEXT NOT NULL,
    normalized_label TEXT NOT NULL,
    origin TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(node_type, normalized_label)
);

CREATE TABLE knowledge_edges (
    edge_id TEXT PRIMARY KEY,
    source_node_id TEXT NOT NULL REFERENCES knowledge_nodes(node_id),
    relation TEXT NOT NULL,
    target_node_id TEXT NOT NULL REFERENCES knowledge_nodes(node_id),
    work_id TEXT REFERENCES works(work_id),
    origin TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_node_id, relation, target_node_id, work_id)
);

CREATE VIRTUAL TABLE work_search USING fts5(
    work_id UNINDEXED,
    title,
    author,
    publisher,
    tags,
    sample_text,
    tokenize='unicode61'
);

CREATE INDEX idx_editions_work ON editions(work_id);
CREATE INDEX idx_library_files_work ON library_files(work_id);
CREATE INDEX idx_file_versions_file ON file_versions(file_id, discovered_at);
CREATE INDEX idx_file_versions_sha ON file_versions(sha256);
CREATE INDEX idx_scan_candidates_session ON scan_candidates(session_id, status);
CREATE INDEX idx_knowledge_edges_work ON knowledge_edges(work_id);
CREATE INDEX idx_knowledge_edges_source ON knowledge_edges(source_node_id);
CREATE INDEX idx_knowledge_edges_target ON knowledge_edges(target_node_id);
"""


def resolve_library_root(project_root: Path, library_root: Path | None = None) -> Path:
    if library_root is not None:
        return library_root.expanduser().resolve()
    configured = os.getenv("HRW_LIBRARY_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return (project_root.resolve() / "library").resolve()


def library_database_path(library_root: Path) -> Path:
    return library_root / LIBRARY_DATABASE_NAME


def initialize_library(library_root: Path) -> None:
    library_root.mkdir(parents=True, exist_ok=True)
    path = library_database_path(library_root).resolve()
    with _INITIALIZE_LOCK:
        if path in _INITIALIZED_PATHS:
            return
        connection = sqlite3.connect(path, timeout=10)
        try:
            connection.execute("PRAGMA busy_timeout = 10000")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA foreign_keys = ON")
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'library_meta'"
            ).fetchone()
            if exists is None:
                connection.executescript(SCHEMA)
                connection.execute(
                    "INSERT INTO library_meta(version, applied_at) VALUES (?, ?)",
                    (LIBRARY_SCHEMA_VERSION, utc_now()),
                )
            else:
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(scan_sessions)").fetchall()
                }
                if "processed_count" not in columns:
                    connection.execute(
                        "ALTER TABLE scan_sessions ADD COLUMN processed_count INTEGER NOT NULL DEFAULT 0"
                    )
                if "error" not in columns:
                    connection.execute(
                        "ALTER TABLE scan_sessions ADD COLUMN error TEXT NOT NULL DEFAULT ''"
                    )
                if "completed_at" not in columns:
                    connection.execute("ALTER TABLE scan_sessions ADD COLUMN completed_at TEXT")
                connection.executescript("""
                    CREATE TABLE IF NOT EXISTS knowledge_nodes (
                        node_id TEXT PRIMARY KEY, node_type TEXT NOT NULL, label TEXT NOT NULL,
                        normalized_label TEXT NOT NULL, origin TEXT NOT NULL, created_at TEXT NOT NULL,
                        UNIQUE(node_type, normalized_label)
                    );
                    CREATE TABLE IF NOT EXISTS knowledge_edges (
                        edge_id TEXT PRIMARY KEY,
                        source_node_id TEXT NOT NULL REFERENCES knowledge_nodes(node_id),
                        relation TEXT NOT NULL,
                        target_node_id TEXT NOT NULL REFERENCES knowledge_nodes(node_id),
                        work_id TEXT REFERENCES works(work_id), origin TEXT NOT NULL, created_at TEXT NOT NULL,
                        UNIQUE(source_node_id, relation, target_node_id, work_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_knowledge_edges_work ON knowledge_edges(work_id);
                    CREATE INDEX IF NOT EXISTS idx_knowledge_edges_source ON knowledge_edges(source_node_id);
                    CREATE INDEX IF NOT EXISTS idx_knowledge_edges_target ON knowledge_edges(target_node_id);
                    CREATE TABLE IF NOT EXISTS author_aliases (
                        alias_normalized TEXT PRIMARY KEY, alias TEXT NOT NULL,
                        canonical_name TEXT NOT NULL, orcid TEXT NOT NULL,
                        decided_by TEXT NOT NULL, decision_reason TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                """)
                current_version = connection.execute(
                    "SELECT version FROM library_meta LIMIT 1"
                ).fetchone()
                if current_version is None:
                    connection.execute(
                        "INSERT INTO library_meta(version, applied_at) VALUES (?, ?)",
                        (LIBRARY_SCHEMA_VERSION, utc_now()),
                    )
                elif current_version[0] != LIBRARY_SCHEMA_VERSION:
                    connection.execute(
                        "UPDATE library_meta SET version = ?, applied_at = ?",
                        (LIBRARY_SCHEMA_VERSION, utc_now()),
                    )
            connection.commit()
            _INITIALIZED_PATHS.add(path)
        finally:
            connection.close()


@contextmanager
def connect_library(library_root: Path) -> Iterator[sqlite3.Connection]:
    initialize_library(library_root)
    connection = sqlite3.connect(library_database_path(library_root), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
