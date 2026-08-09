from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .pdf_ingestion import ingest_pdf
from .service import (
    import_structure,
    initialize_project,
    list_anomalies,
    list_blocks,
    project_status,
    register_source,
    submit_block_repair,
    submit_page_repair,
    submit_relation_repair,
)
from .web import serve


def _emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hrw", description="Historical Research Workbench M2")
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

    web = commands.add_parser("serve", help="open the local PDF repair workbench")
    web.add_argument("project_root", type=Path)
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: list[str] | None = None) -> int:
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
    elif args.command == "serve":
        serve(args.project_root, args.host, args.port)
        return 0
    else:
        raise AssertionError(args.command)
    _emit(result)
    return 0
