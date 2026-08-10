from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import certifi

from .agent_runtime import (
    assign_model,
    create_thread,
    decide_approval,
    list_threads,
    send_message,
    sync_model_profiles,
    thread_view,
)
from .pdf_ingestion import ingest_pdf
from .library import (
    approve_candidates,
    library_status,
    link_work_to_project,
    scan_directory,
    scan_session,
    search_library,
    update_work,
    work_detail,
)
from .skill_registry import discover_skills
from .service import (
    accept_ocr_proposal,
    create_ocr_proposal,
    import_structure,
    initialize_project,
    list_anomalies,
    list_blocks,
    project_status,
    register_source,
    reject_ocr_proposal,
    submit_block_repair,
    submit_page_repair,
    submit_relation_repair,
)
from .vision import capability
from .web import serve
from .desktop_runtime import serve_desktop


def _emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hrw", description="Historical Research Workbench D1")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="initialize a research project")
    init.add_argument("project_root", type=Path)
    init.add_argument("--title", required=True)

    add_source = commands.add_parser("add-source", help="register a local source file")
    add_source.add_argument("project_root", type=Path)
    add_source.add_argument("source_file", type=Path)
    add_source.add_argument("--title")

    structure = commands.add_parser("import-structure", help="apply a deterministic structure packet")
    structure.add_argument("project_root", type=Path)
    structure.add_argument("source_id")
    structure.add_argument("packet", type=Path)

    ingest = commands.add_parser("ingest-pdf", help="render and extract a registered PDF")
    ingest.add_argument("project_root", type=Path)
    ingest.add_argument("source_id")
    ingest.add_argument("--render-scale", type=float, default=1.5)

    anomalies = commands.add_parser("anomalies", help="list anomalies")
    anomalies.add_argument("project_root", type=Path)
    anomalies.add_argument("--source-id")

    block_repair = commands.add_parser("repair-block", help="submit a local block repair")
    block_repair.add_argument("project_root", type=Path)
    block_repair.add_argument("anomaly_id")
    block_repair.add_argument("--text-file", type=Path, required=True)
    block_repair.add_argument("--reviewer", required=True)
    block_repair.add_argument("--reason", required=True)

    page_repair = commands.add_parser("repair-page", help="submit a full-page repair")
    page_repair.add_argument("project_root", type=Path)
    page_repair.add_argument("anomaly_id")
    page_repair.add_argument("--payload", type=Path, required=True)
    page_repair.add_argument("--reviewer", required=True)
    page_repair.add_argument("--reason", required=True)

    relation_repair = commands.add_parser("repair-relation", help="confirm a cross-page relation")
    relation_repair.add_argument("project_root", type=Path)
    relation_repair.add_argument("anomaly_id")
    relation_repair.add_argument("--continues", choices=("yes", "no"), required=True)
    relation_repair.add_argument("--reviewer", required=True)
    relation_repair.add_argument("--reason", required=True)

    status = commands.add_parser("status", help="show project status")
    status.add_argument("project_root", type=Path)

    blocks = commands.add_parser("blocks", help="show effective source blocks")
    blocks.add_argument("project_root", type=Path)
    blocks.add_argument("source_id")

    commands.add_parser("ocr-capability", help="show the configured visual OCR role without secrets")

    ocr_propose = commands.add_parser("ocr-propose", help="create a pending OCR proposal for a blocked page")
    ocr_propose.add_argument("project_root", type=Path)
    ocr_propose.add_argument("page_id")

    ocr_accept = commands.add_parser("ocr-accept", help="accept an edited OCR proposal as a human page repair")
    ocr_accept.add_argument("project_root", type=Path)
    ocr_accept.add_argument("proposal_id")
    ocr_accept.add_argument("--payload", type=Path, required=True)
    ocr_accept.add_argument("--reviewer", required=True)
    ocr_accept.add_argument("--reason", required=True)

    ocr_reject = commands.add_parser("ocr-reject", help="reject an OCR proposal without changing source text")
    ocr_reject.add_argument("project_root", type=Path)
    ocr_reject.add_argument("proposal_id")
    ocr_reject.add_argument("--reviewer", required=True)
    ocr_reject.add_argument("--reason", required=True)

    thread_create = commands.add_parser("thread-create", help="create a persistent research thread")
    thread_create.add_argument("project_root", type=Path)
    thread_create.add_argument("--title", required=True)

    threads = commands.add_parser("threads", help="list research threads")
    threads.add_argument("project_root", type=Path)

    thread_show = commands.add_parser("thread-show", help="show messages, runs, tools and approvals")
    thread_show.add_argument("project_root", type=Path)
    thread_show.add_argument("thread_id")

    agent_send = commands.add_parser("agent-send", help="send a message and start a research run")
    agent_send.add_argument("project_root", type=Path)
    agent_send.add_argument("thread_id")
    agent_send.add_argument("--message", required=True)

    models = commands.add_parser("models", help="show model profiles without secrets")
    models.add_argument("project_root", type=Path)

    model_assign = commands.add_parser("model-assign", help="assign the main reasoning model")
    model_assign.add_argument("project_root", type=Path)
    model_assign.add_argument("profile_id")

    approve = commands.add_parser("approval-decide", help="approve or reject a pending tool call")
    approve.add_argument("project_root", type=Path)
    approve.add_argument("approval_id")
    approve.add_argument("--decision", choices=("approve", "reject"), required=True)
    approve.add_argument("--reviewer", required=True)
    approve.add_argument("--reason", required=True)
    approve.add_argument("--payload", type=Path)

    commands.add_parser("skills", help="list discovered instruction-only SKILL.md packages")

    library_status_command = commands.add_parser("library-status", help="show the research library")
    library_status_command.add_argument("project_root", type=Path)
    library_status_command.add_argument("--library-root", type=Path)

    library_scan = commands.add_parser("library-scan", help="create a read-only folder inventory preview")
    library_scan.add_argument("project_root", type=Path)
    library_scan.add_argument("source_root", type=Path)
    library_scan.add_argument("--library-root", type=Path)
    library_scan.add_argument("--skill", default="historical-material-intake")

    library_session = commands.add_parser("library-session", help="show one inventory preview")
    library_session.add_argument("project_root", type=Path)
    library_session.add_argument("session_id")
    library_session.add_argument("--library-root", type=Path)

    library_approve = commands.add_parser("library-approve", help="approve selected candidates in place")
    library_approve.add_argument("project_root", type=Path)
    library_approve.add_argument("session_id")
    library_approve.add_argument("candidate_ids", nargs="*")
    library_approve.add_argument("--library-root", type=Path)

    library_search = commands.add_parser("library-search", help="search titles, authors, text and tags")
    library_search.add_argument("project_root", type=Path)
    library_search.add_argument("--query", default="")
    library_search.add_argument("--tag", action="append", default=[])
    library_search.add_argument("--library-root", type=Path)

    library_work = commands.add_parser("library-work", help="show complete edition and file version details")
    library_work.add_argument("project_root", type=Path)
    library_work.add_argument("work_id")
    library_work.add_argument("--library-root", type=Path)

    library_update = commands.add_parser("library-update", help="update approved bibliography and user tags")
    library_update.add_argument("project_root", type=Path)
    library_update.add_argument("work_id")
    library_update.add_argument("--payload", type=Path, required=True)
    library_update.add_argument("--library-root", type=Path)

    library_link = commands.add_parser("library-link", help="link an approved work to the current project")
    library_link.add_argument("project_root", type=Path)
    library_link.add_argument("work_id")
    library_link.add_argument("--library-root", type=Path)

    web = commands.add_parser("serve", help="open the local PDF repair workbench")
    web.add_argument("project_root", type=Path)
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--library-root", type=Path)
    web.add_argument("--workspace-root", type=Path)
    web.add_argument("--config-root", type=Path)

    desktop = commands.add_parser("desktop-serve", help="start a first-run desktop workspace")
    desktop.add_argument("--data-root", type=Path, required=True)
    desktop.add_argument("--host", default="127.0.0.1")
    desktop.add_argument("--port", type=int, required=True)
    desktop.add_argument("--desktop-build", default="development")
    return parser


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    args = build_parser().parse_args(argv)
    if args.command == "init":
        result = initialize_project(args.project_root, args.title)
    elif args.command == "add-source":
        result = register_source(args.project_root, args.source_file, args.title)
    elif args.command == "import-structure":
        result = import_structure(args.project_root, args.source_id, args.packet)
    elif args.command == "ingest-pdf":
        result = ingest_pdf(args.project_root, args.source_id, args.render_scale)
    elif args.command == "anomalies":
        result = list_anomalies(args.project_root, args.source_id)
    elif args.command == "repair-block":
        result = submit_block_repair(
            args.project_root,
            args.anomaly_id,
            args.text_file.read_text(encoding="utf-8"),
            args.reviewer,
            args.reason,
        )
    elif args.command == "repair-page":
        result = submit_page_repair(
            args.project_root,
            args.anomaly_id,
            json.loads(args.payload.read_text(encoding="utf-8")),
            args.reviewer,
            args.reason,
        )
    elif args.command == "repair-relation":
        result = submit_relation_repair(
            args.project_root,
            args.anomaly_id,
            args.continues == "yes",
            args.reviewer,
            args.reason,
        )
    elif args.command == "status":
        result = project_status(args.project_root)
    elif args.command == "blocks":
        result = list_blocks(args.project_root, args.source_id)
    elif args.command == "ocr-capability":
        result = capability()
    elif args.command == "ocr-propose":
        result = create_ocr_proposal(args.project_root, args.page_id)
    elif args.command == "ocr-accept":
        result = accept_ocr_proposal(
            args.project_root,
            args.proposal_id,
            json.loads(args.payload.read_text(encoding="utf-8")),
            args.reviewer,
            args.reason,
        )
    elif args.command == "ocr-reject":
        result = reject_ocr_proposal(
            args.project_root,
            args.proposal_id,
            args.reviewer,
            args.reason,
        )
    elif args.command == "thread-create":
        result = create_thread(args.project_root, args.title)
    elif args.command == "threads":
        result = list_threads(args.project_root)
    elif args.command == "thread-show":
        result = thread_view(args.project_root, args.thread_id)
    elif args.command == "agent-send":
        result = send_message(args.project_root, args.thread_id, args.message)
    elif args.command == "models":
        result = sync_model_profiles(args.project_root)
    elif args.command == "model-assign":
        result = assign_model(args.project_root, args.profile_id)
    elif args.command == "approval-decide":
        edited = json.loads(args.payload.read_text(encoding="utf-8")) if args.payload else None
        result = decide_approval(
            args.project_root,
            args.approval_id,
            args.decision == "approve",
            args.reviewer,
            args.reason,
            edited,
        )
    elif args.command == "skills":
        result = discover_skills()
    elif args.command == "library-status":
        result = library_status(args.project_root, args.library_root)
    elif args.command == "library-scan":
        result = scan_directory(args.project_root, args.source_root, args.library_root, args.skill)
    elif args.command == "library-session":
        result = scan_session(args.project_root, args.session_id, args.library_root)
    elif args.command == "library-approve":
        result = approve_candidates(
            args.project_root, args.session_id, args.candidate_ids or None, args.library_root
        )
    elif args.command == "library-search":
        result = search_library(args.project_root, args.query, args.tag, args.library_root)
    elif args.command == "library-work":
        result = work_detail(args.project_root, args.work_id, args.library_root)
    elif args.command == "library-update":
        payload = json.loads(args.payload.read_text(encoding="utf-8"))
        result = update_work(
            args.project_root, args.work_id, payload.get("fields", {}), payload.get("tags", []), args.library_root
        )
    elif args.command == "library-link":
        result = link_work_to_project(args.project_root, args.work_id, args.library_root)
    elif args.command == "serve":
        serve(args.project_root, args.host, args.port, args.library_root, args.workspace_root, args.config_root)
        return 0
    elif args.command == "desktop-serve":
        serve_desktop(args.data_root, args.host, args.port, args.desktop_build)
        return 0
    else:
        raise AssertionError(args.command)
    _emit(result)
    return 0
