from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 15
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

CREATE TABLE ocr_proposals (
    proposal_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    page_id TEXT NOT NULL REFERENCES pages(page_id),
    anomaly_id TEXT NOT NULL REFERENCES anomalies(anomaly_id),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    image_sha256 TEXT NOT NULL,
    raw_response_json TEXT NOT NULL,
    normalized_payload_json TEXT NOT NULL,
    raw_response_hash TEXT NOT NULL,
    normalized_response_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    reviewer TEXT,
    decision_reason TEXT,
    repair_id TEXT REFERENCES repair_records(repair_id)
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

CREATE TABLE threads (
    thread_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE messages (
    message_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads(thread_id),
    role TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE goals (
    goal_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads(thread_id),
    objective TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads(thread_id),
    goal_id TEXT NOT NULL REFERENCES goals(goal_id),
    status TEXT NOT NULL,
    model_snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    error TEXT
);

CREATE TABLE run_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, sequence)
);

CREATE TABLE tool_calls (
    tool_call_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    tool_name TEXT NOT NULL,
    input_json TEXT NOT NULL,
    status TEXT NOT NULL,
    output_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE approvals (
    approval_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    tool_call_id TEXT NOT NULL REFERENCES tool_calls(tool_call_id),
    status TEXT NOT NULL,
    request_json TEXT NOT NULL,
    decision_json TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    UNIQUE(tool_call_id)
);

CREATE TABLE model_profiles (
    profile_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    capabilities_json TEXT NOT NULL,
    credential_ref TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE model_assignments (
    role TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES model_profiles(profile_id),
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_pages_source ON pages(source_id);
CREATE INDEX idx_blocks_page ON blocks(page_id);
CREATE INDEX idx_anomalies_source_status ON anomalies(source_id, status);
CREATE INDEX idx_ocr_proposals_page_status ON ocr_proposals(page_id, status);
CREATE INDEX idx_audit_project ON audit_events(project_id, event_id);
CREATE INDEX idx_messages_thread ON messages(thread_id, created_at);
CREATE INDEX idx_runs_thread ON runs(thread_id, created_at);
CREATE INDEX idx_run_events_run ON run_events(run_id, sequence);
CREATE INDEX idx_approvals_run_status ON approvals(run_id, status);
"""


MIGRATION_2 = """
CREATE TABLE IF NOT EXISTS ocr_proposals (
    proposal_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    page_id TEXT NOT NULL REFERENCES pages(page_id),
    anomaly_id TEXT NOT NULL REFERENCES anomalies(anomaly_id),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    image_sha256 TEXT NOT NULL,
    raw_response_json TEXT NOT NULL,
    normalized_payload_json TEXT NOT NULL,
    raw_response_hash TEXT NOT NULL,
    normalized_response_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    reviewer TEXT,
    decision_reason TEXT,
    repair_id TEXT REFERENCES repair_records(repair_id)
);
CREATE INDEX IF NOT EXISTS idx_ocr_proposals_page_status ON ocr_proposals(page_id, status);
"""


MIGRATION_3 = """
CREATE TABLE IF NOT EXISTS threads (
    thread_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads(thread_id),
    role TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS goals (
    goal_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads(thread_id),
    objective TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads(thread_id),
    goal_id TEXT NOT NULL REFERENCES goals(goal_id),
    status TEXT NOT NULL,
    model_snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS run_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, sequence)
);
CREATE TABLE IF NOT EXISTS tool_calls (
    tool_call_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    tool_name TEXT NOT NULL,
    input_json TEXT NOT NULL,
    status TEXT NOT NULL,
    output_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    tool_call_id TEXT NOT NULL REFERENCES tool_calls(tool_call_id),
    status TEXT NOT NULL,
    request_json TEXT NOT NULL,
    decision_json TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    UNIQUE(tool_call_id)
);
CREATE TABLE IF NOT EXISTS model_profiles (
    profile_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    capabilities_json TEXT NOT NULL,
    credential_ref TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_assignments (
    role TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES model_profiles(profile_id),
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_runs_thread ON runs(thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events(run_id, sequence);
CREATE INDEX IF NOT EXISTS idx_approvals_run_status ON approvals(run_id, status);
"""


MIGRATION_4 = """
CREATE TABLE IF NOT EXISTS source_library_links (
    source_id TEXT PRIMARY KEY REFERENCES sources(source_id),
    library_work_id TEXT NOT NULL,
    library_file_id TEXT NOT NULL,
    library_version_id TEXT NOT NULL,
    library_sha256 TEXT NOT NULL,
    linked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS retrieval_records (
    record_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    query TEXT NOT NULL,
    filters_json TEXT NOT NULL,
    status TEXT NOT NULL,
    result_count INTEGER NOT NULL,
    request_url TEXT NOT NULL,
    response_hash TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS retrieval_results (
    result_id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES retrieval_records(record_id),
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    authors TEXT NOT NULL,
    publication_year TEXT NOT NULL,
    container_title TEXT NOT NULL,
    doi TEXT NOT NULL,
    url TEXT NOT NULL,
    open_access_url TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    qualification TEXT NOT NULL,
    UNIQUE(record_id, external_id)
);
CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence_items (
    evidence_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    source_version_id TEXT NOT NULL REFERENCES source_versions(source_version_id),
    page_id TEXT NOT NULL REFERENCES pages(page_id),
    block_id TEXT NOT NULL REFERENCES blocks(block_id),
    physical_page INTEGER NOT NULL,
    quote TEXT NOT NULL,
    note TEXT NOT NULL,
    qualification TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claim_evidence (
    link_id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    evidence_id TEXT NOT NULL REFERENCES evidence_items(evidence_id),
    relation TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(claim_id, evidence_id, relation)
);
CREATE TABLE IF NOT EXISTS evidence_freezes (
    freeze_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    artifact_type TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifact_versions (
    version_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
    content TEXT NOT NULL,
    source_refs_json TEXT NOT NULL,
    model_snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    review_id TEXT PRIMARY KEY,
    artifact_version_id TEXT NOT NULL REFERENCES artifact_versions(version_id),
    reviewer_role TEXT NOT NULL,
    report TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS browser_sessions (
    session_id TEXT PRIMARY KEY,
    start_url TEXT NOT NULL,
    allowed_domain TEXT NOT NULL,
    status TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_candidates (
    candidate_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    source_refs_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_retrieval_results_record ON retrieval_results(record_id);
CREATE INDEX IF NOT EXISTS idx_evidence_source_page ON evidence_items(source_id, page_id);
CREATE INDEX IF NOT EXISTS idx_claim_evidence_claim ON claim_evidence(claim_id);
CREATE INDEX IF NOT EXISTS idx_artifact_versions_artifact ON artifact_versions(artifact_id, created_at);
"""


MIGRATION_5 = """
CREATE TABLE IF NOT EXISTS manuscripts (
    manuscript_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_format TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS manuscript_sections (
    section_id TEXT PRIMARY KEY,
    manuscript_id TEXT NOT NULL REFERENCES manuscripts(manuscript_id),
    section_order INTEGER NOT NULL,
    heading TEXT NOT NULL,
    current_version_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(manuscript_id, section_order)
);
CREATE TABLE IF NOT EXISTS section_versions (
    version_id TEXT PRIMARY KEY,
    section_id TEXT NOT NULL REFERENCES manuscript_sections(section_id),
    base_version_id TEXT,
    operation TEXT NOT NULL,
    content TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    model_snapshot_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    approved_at TEXT
);
CREATE TABLE IF NOT EXISTS writing_proposals (
    proposal_id TEXT PRIMARY KEY,
    section_id TEXT NOT NULL REFERENCES manuscript_sections(section_id),
    base_version_id TEXT NOT NULL REFERENCES section_versions(version_id),
    operation TEXT NOT NULL,
    instruction TEXT NOT NULL,
    proposed_content TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    model_snapshot_json TEXT NOT NULL,
    protected_markers_json TEXT NOT NULL,
    validation_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    reviewer TEXT
);
CREATE TABLE IF NOT EXISTS reading_jobs (
    job_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    question TEXT NOT NULL,
    mode TEXT NOT NULL,
    source_ids_json TEXT NOT NULL,
    stop_condition TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS reading_notes (
    note_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES reading_jobs(job_id),
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    page_refs_json TEXT NOT NULL,
    content TEXT NOT NULL,
    qualification TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS historiography_entries (
    entry_id TEXT PRIMARY KEY,
    work_title TEXT NOT NULL,
    position TEXT NOT NULL,
    contribution TEXT NOT NULL,
    limitation TEXT NOT NULL,
    relevance TEXT NOT NULL,
    source_refs_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS journal_templates (
    template_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    citation_style TEXT NOT NULL,
    section_rules_json TEXT NOT NULL,
    format_rules_json TEXT NOT NULL,
    origin TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sections_manuscript ON manuscript_sections(manuscript_id, section_order);
CREATE INDEX IF NOT EXISTS idx_section_versions_section ON section_versions(section_id, created_at);
CREATE INDEX IF NOT EXISTS idx_writing_proposals_section ON writing_proposals(section_id, created_at);
CREATE INDEX IF NOT EXISTS idx_reading_notes_job ON reading_notes(job_id, source_id);
"""


MIGRATION_6 = """
CREATE TABLE IF NOT EXISTS manuscript_documents (
    document_id TEXT PRIMARY KEY,
    manuscript_id TEXT NOT NULL UNIQUE REFERENCES manuscripts(manuscript_id),
    current_revision_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_revisions (
    revision_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES manuscript_documents(document_id),
    base_revision_id TEXT,
    document_json TEXT NOT NULL,
    plain_text_hash TEXT NOT NULL,
    source_format TEXT NOT NULL,
    status TEXT NOT NULL,
    fidelity_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS thread_context_bindings (
    binding_id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL UNIQUE REFERENCES messages(message_id),
    thread_id TEXT NOT NULL REFERENCES threads(thread_id),
    manuscript_id TEXT,
    revision_id TEXT,
    section_id TEXT,
    node_id TEXT,
    selection_hash TEXT NOT NULL,
    selection_text TEXT NOT NULL,
    attached_refs_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_io_receipts (
    receipt_id TEXT PRIMARY KEY,
    manuscript_id TEXT NOT NULL REFERENCES manuscripts(manuscript_id),
    revision_id TEXT,
    direction TEXT NOT NULL,
    format TEXT NOT NULL,
    project_path TEXT,
    fidelity_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_document_revisions_document ON document_revisions(document_id, created_at);
CREATE INDEX IF NOT EXISTS idx_context_bindings_thread ON thread_context_bindings(thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_document_io_manuscript ON document_io_receipts(manuscript_id, created_at);
"""


MIGRATION_7 = """
CREATE TABLE IF NOT EXISTS journal_template_revisions (
    template_revision_id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL REFERENCES journal_templates(template_id),
    version_label TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    source_url TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    requirements_json TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(template_id, version_label)
);
CREATE TABLE IF NOT EXISTS manuscript_notes (
    note_id TEXT PRIMARY KEY,
    manuscript_id TEXT NOT NULL REFERENCES manuscripts(manuscript_id),
    anchor_node_id TEXT NOT NULL,
    anchor_offset INTEGER NOT NULL,
    anchor_text TEXT NOT NULL,
    current_version_id TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS manuscript_note_versions (
    note_version_id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL REFERENCES manuscript_notes(note_id),
    base_version_id TEXT,
    mode TEXT NOT NULL,
    citation_data_json TEXT NOT NULL,
    rendered_text TEXT NOT NULL,
    source_refs_json TEXT NOT NULL,
    verification_state TEXT NOT NULL,
    template_id TEXT NOT NULL REFERENCES journal_templates(template_id),
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    reviewer TEXT
);
CREATE INDEX IF NOT EXISTS idx_template_revisions_template ON journal_template_revisions(template_id, created_at);
CREATE INDEX IF NOT EXISTS idx_manuscript_notes_manuscript ON manuscript_notes(manuscript_id, anchor_node_id);
CREATE INDEX IF NOT EXISTS idx_note_versions_note ON manuscript_note_versions(note_id, created_at);
"""


MIGRATION_8 = """
CREATE TABLE IF NOT EXISTS evidence_anchors (
    evidence_id TEXT NOT NULL REFERENCES evidence_items(evidence_id) ON DELETE CASCADE,
    block_id TEXT NOT NULL REFERENCES blocks(block_id),
    anchor_order INTEGER NOT NULL,
    PRIMARY KEY(evidence_id, block_id),
    UNIQUE(evidence_id, anchor_order)
);
CREATE INDEX IF NOT EXISTS idx_evidence_anchors_block ON evidence_anchors(block_id, evidence_id);
INSERT OR IGNORE INTO evidence_anchors(evidence_id, block_id, anchor_order)
SELECT evidence_id, block_id, 0 FROM evidence_items;
"""


MIGRATION_9 = """
CREATE TABLE IF NOT EXISTS manuscript_reviews (
    review_id TEXT PRIMARY KEY,
    review_group_id TEXT NOT NULL,
    manuscript_id TEXT NOT NULL REFERENCES manuscripts(manuscript_id),
    reviewer_role TEXT NOT NULL,
    model_role TEXT NOT NULL,
    model_snapshot_json TEXT NOT NULL,
    section_versions_json TEXT NOT NULL,
    template_id TEXT NOT NULL,
    report TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_manuscript_reviews_manuscript
ON manuscript_reviews(manuscript_id, created_at);
CREATE INDEX IF NOT EXISTS idx_manuscript_reviews_group
ON manuscript_reviews(review_group_id, reviewer_role);
"""

MIGRATION_10 = """
CREATE TABLE IF NOT EXISTS research_design_versions (
    design_id TEXT PRIMARY KEY,
    base_design_id TEXT REFERENCES research_design_versions(design_id),
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    change_summary TEXT NOT NULL,
    plan_role TEXT NOT NULL,
    origin TEXT NOT NULL,
    origin_ref TEXT NOT NULL,
    model_snapshot_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_by TEXT,
    decision_reason TEXT,
    decided_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_research_design_role_status
ON research_design_versions(plan_role, status, created_at);
"""

MIGRATION_11 = """
CREATE TABLE IF NOT EXISTS research_event_rows (
    event_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    event_date TEXT NOT NULL,
    start_place TEXT NOT NULL,
    end_place TEXT NOT NULL,
    route TEXT NOT NULL,
    movement_time TEXT NOT NULL,
    distance_original TEXT NOT NULL,
    distance_normalized TEXT NOT NULL,
    investigation_object TEXT NOT NULL,
    recording_technique TEXT NOT NULL,
    chinese_participants TEXT NOT NULL,
    institutional_task TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    source_version_id TEXT NOT NULL REFERENCES source_versions(source_version_id),
    page_ids_json TEXT NOT NULL,
    block_ids_json TEXT NOT NULL,
    physical_pages_json TEXT NOT NULL,
    printed_pages_json TEXT NOT NULL,
    original_text TEXT NOT NULL,
    translation TEXT NOT NULL,
    missing_reason TEXT NOT NULL,
    notes TEXT NOT NULL,
    qualification TEXT NOT NULL,
    origin TEXT NOT NULL,
    model_snapshot_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_by TEXT,
    decision_reason TEXT,
    decided_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_research_events_case_status
ON research_event_rows(case_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_research_events_source
ON research_event_rows(source_id, created_at);
CREATE TABLE IF NOT EXISTS research_event_field_anchors (
    event_id TEXT NOT NULL REFERENCES research_event_rows(event_id),
    field_name TEXT NOT NULL,
    block_id TEXT NOT NULL REFERENCES blocks(block_id),
    anchor_order INTEGER NOT NULL,
    PRIMARY KEY(event_id, field_name, block_id)
);
CREATE INDEX IF NOT EXISTS idx_research_event_field_anchors
ON research_event_field_anchors(event_id, field_name, anchor_order);
"""

MIGRATION_14 = """
CREATE TABLE IF NOT EXISTS style_profiles (
    profile_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_label TEXT NOT NULL,
    scope TEXT NOT NULL,
    manuscript_id TEXT NOT NULL REFERENCES manuscripts(manuscript_id),
    section_id TEXT NOT NULL REFERENCES manuscript_sections(section_id),
    source_version_id TEXT NOT NULL REFERENCES section_versions(version_id),
    sample_sha256 TEXT NOT NULL,
    features_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_by TEXT,
    decision_reason TEXT,
    decided_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_style_profiles_status
ON style_profiles(status, created_at);
CREATE TABLE IF NOT EXISTS style_profile_samples (
    sample_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES style_profiles(profile_id),
    manuscript_id TEXT NOT NULL REFERENCES manuscripts(manuscript_id),
    source_version_ids_json TEXT NOT NULL,
    sample_sha256 TEXT NOT NULL,
    character_count INTEGER NOT NULL,
    features_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(profile_id, sample_sha256)
);
CREATE INDEX IF NOT EXISTS idx_style_profile_samples_profile
ON style_profile_samples(profile_id, created_at);
"""

MIGRATION_15 = """
CREATE TABLE IF NOT EXISTS source_citation_metadata (
    source_id TEXT PRIMARY KEY REFERENCES sources(source_id),
    author TEXT NOT NULL,
    title TEXT NOT NULL,
    edition TEXT NOT NULL,
    place TEXT NOT NULL,
    publisher TEXT NOT NULL,
    year TEXT NOT NULL,
    type_code TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    verified_by TEXT NOT NULL,
    verified_at TEXT NOT NULL
);
"""

EVENT_COMPARISON_COLUMNS = (
    "movement_mode",
    "genre",
    "participant_visibility",
    "outcome_destination",
)


def _ensure_event_comparison_columns(connection: sqlite3.Connection) -> None:
    existing = {row[1] for row in connection.execute("PRAGMA table_info(research_event_rows)")}
    for column in EVENT_COMPARISON_COLUMNS:
        if column not in existing:
            connection.execute(
                f"ALTER TABLE research_event_rows ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
            )


def _restore_locally_repaired_blocks(connection: sqlite3.Connection) -> None:
    connection.execute(
        """UPDATE blocks
           SET use_state = 'research_usable'
           WHERE use_state != 'superseded'
             AND verification_state IN ('human_verified', 'human_repaired')
             AND page_id IN (SELECT page_id FROM pages WHERE page_type != 'docx_locator')
             AND NOT EXISTS (
                 SELECT 1 FROM anomalies a
                 WHERE a.status = 'open' AND a.scope_type = 'block'
                   AND a.target_id = blocks.block_id
             )
             AND NOT EXISTS (
                 SELECT 1 FROM anomalies a
                 JOIN page_relations r ON r.relation_id = a.target_id
                 WHERE a.status = 'open' AND a.scope_type = 'relation'
                   AND (r.from_block_id = blocks.block_id OR r.to_block_id = blocks.block_id)
             )"""
    )


def database_path(project_root: Path) -> Path:
    return project_root / DATABASE_NAME


def _migrate(connection: sqlite3.Connection) -> None:
    row = connection.execute("SELECT MAX(version) AS version FROM schema_meta").fetchone()
    version = int(row["version"] or 0)
    if version > SCHEMA_VERSION:
        raise RuntimeError(f"project schema {version} is newer than supported schema {SCHEMA_VERSION}")
    if version < 2:
        connection.executescript(MIGRATION_2)
        connection.execute(
            "INSERT INTO schema_meta(version, applied_at) VALUES (?, ?)",
            (2, utc_now()),
        )
        version = 2
    if version < 3:
        connection.executescript(MIGRATION_3)
        connection.execute(
            "INSERT INTO schema_meta(version, applied_at) VALUES (?, ?)",
            (3, utc_now()),
        )
        version = 3
    if version < 4:
        connection.executescript(MIGRATION_4)
        connection.execute(
            "INSERT INTO schema_meta(version, applied_at) VALUES (?, ?)",
            (4, utc_now()),
        )
        version = 4
    if version < 5:
        connection.executescript(MIGRATION_5)
        connection.execute(
            "INSERT INTO schema_meta(version, applied_at) VALUES (?, ?)",
            (5, utc_now()),
        )
        version = 5
    if version < 6:
        connection.executescript(MIGRATION_6)
        connection.execute(
            "INSERT INTO schema_meta(version, applied_at) VALUES (?, ?)",
            (6, utc_now()),
        )
        version = 6
    if version < 7:
        connection.executescript(MIGRATION_7)
        connection.execute(
            "INSERT INTO schema_meta(version, applied_at) VALUES (?, ?)",
            (7, utc_now()),
        )
        version = 7
    if version < 8:
        connection.executescript(MIGRATION_8)
        connection.execute(
            "INSERT INTO schema_meta(version, applied_at) VALUES (?, ?)",
            (8, utc_now()),
        )
        version = 8
    if version < 9:
        connection.executescript(MIGRATION_9)
        connection.execute(
            "INSERT INTO schema_meta(version, applied_at) VALUES (?, ?)",
            (9, utc_now()),
        )
        version = 9
    if version < 10:
        connection.executescript(MIGRATION_10)
        connection.execute(
            "INSERT INTO schema_meta(version, applied_at) VALUES (?, ?)",
            (10, utc_now()),
        )
        version = 10
    if version < 11:
        connection.executescript(MIGRATION_11)
        connection.execute(
            "INSERT INTO schema_meta(version, applied_at) VALUES (?, ?)",
            (11, utc_now()),
        )
        version = 11
    if version < 12:
        _ensure_event_comparison_columns(connection)
        connection.execute(
            "INSERT INTO schema_meta(version, applied_at) VALUES (?, ?)",
            (12, utc_now()),
        )
        version = 12
    if version < 13:
        _restore_locally_repaired_blocks(connection)
        connection.execute(
            "INSERT INTO schema_meta(version, applied_at) VALUES (?, ?)",
            (13, utc_now()),
        )
        version = 13
    if version < 14:
        connection.executescript(MIGRATION_14)
        connection.execute(
            "INSERT INTO schema_meta(version, applied_at) VALUES (?, ?)",
            (14, utc_now()),
        )
        version = 14
    if version < 15:
        connection.executescript(MIGRATION_15)
        connection.execute(
            "INSERT INTO schema_meta(version, applied_at) VALUES (?, ?)",
            (15, utc_now()),
        )
    # The scripts are idempotent and also repair an interrupted migration where
    # schema_meta was committed but one of its tables was not.
    connection.executescript(MIGRATION_2)
    connection.executescript(MIGRATION_3)
    connection.executescript(MIGRATION_4)
    connection.executescript(MIGRATION_5)
    connection.executescript(MIGRATION_6)
    connection.executescript(MIGRATION_7)
    anchors_table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'evidence_anchors'"
    ).fetchone()
    if anchors_table is None:
        connection.executescript(MIGRATION_8)
    else:
        orphan = connection.execute(
            """SELECT 1 FROM evidence_items e
               LEFT JOIN evidence_anchors ea ON ea.evidence_id = e.evidence_id
               WHERE ea.evidence_id IS NULL LIMIT 1"""
        ).fetchone()
        if orphan is not None:
            connection.execute(
                """INSERT OR IGNORE INTO evidence_anchors(evidence_id, block_id, anchor_order)
                   SELECT e.evidence_id, e.block_id, 0 FROM evidence_items e
                   LEFT JOIN evidence_anchors ea ON ea.evidence_id = e.evidence_id
                   WHERE ea.evidence_id IS NULL"""
            )
    connection.executescript(MIGRATION_9)
    connection.executescript(MIGRATION_10)
    connection.executescript(MIGRATION_11)
    connection.executescript(MIGRATION_14)
    connection.executescript(MIGRATION_15)
    _ensure_event_comparison_columns(connection)


@contextmanager
def connect(project_root: Path) -> Iterator[sqlite3.Connection]:
    path = database_path(project_root)
    if not path.is_file():
        raise FileNotFoundError(f"project database does not exist: {path}")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        _migrate(connection)
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
        connection.executescript(MIGRATION_4)
        connection.executescript(MIGRATION_5)
        connection.executescript(MIGRATION_6)
        connection.executescript(MIGRATION_7)
        connection.executescript(MIGRATION_8)
        connection.executescript(MIGRATION_9)
        connection.executescript(MIGRATION_10)
        connection.executescript(MIGRATION_11)
        connection.executescript(MIGRATION_14)
        connection.executescript(MIGRATION_15)
        _ensure_event_comparison_columns(connection)
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
