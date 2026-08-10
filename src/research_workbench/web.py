from __future__ import annotations

import json
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .agent_runtime import (
    assign_model,
    create_thread,
    decide_approval,
    list_threads,
    send_message,
    sync_model_profiles,
    thread_view,
)
from .authoring import (
    authoring_state,
    create_historiography_entry,
    create_journal_template,
    create_reading_job,
    create_writing_proposal,
    decide_writing_proposal,
    export_manuscript,
    import_manuscript,
)
from .document_model import document_detail, ensure_document, export_document, import_docx, save_document
from .pdf_ingestion import ingest_pdf
from .library import (
    approve_candidates,
    library_file_path,
    library_status,
    link_work_to_project,
    scan_directory,
    scan_session,
    search_library,
    update_work,
    work_detail,
)
from .library_store import resolve_library_root
from .project_library import add_library_file_to_project
from .research import connector_capabilities, list_retrievals, retrieval_record, search
from .scholarship import (
    approve_freeze,
    create_browser_session,
    create_claim,
    create_evidence,
    create_freeze,
    create_memory_candidate,
    decide_memory_candidate,
    draft_from_freeze,
    export_artifact,
    research_state,
    review_artifact,
)
from .service import (
    accept_ocr_proposal,
    create_ocr_proposal,
    list_sources,
    page_image_path,
    project_status,
    reject_ocr_proposal,
    register_source,
    source_view,
    submit_block_repair,
    submit_page_repair,
    submit_relation_repair,
)
from .vision import capability
from .translation import capability as translation_capability, translate_evidence
from .workspace import (
    create_workspace_project,
    initialize_workspace,
    select_workspace_project,
    workspace_view,
)


WEB_ROOT = Path(__file__).parent / "web_assets"


class WorkbenchServer(ThreadingHTTPServer):
    project_root: Path
    library_root: Path
    workspace_root: Path


class WorkbenchHandler(BaseHTTPRequestHandler):
    server: WorkbenchServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, value: Any, status: int = 200) -> None:
        self._send(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _body_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/snapshot":
                self._json({
                    "project": project_status(self.server.project_root),
                    "sources": list_sources(self.server.project_root),
                    "threads": list_threads(self.server.project_root),
                    "model_profiles": sync_model_profiles(self.server.project_root),
                    "library": library_status(self.server.project_root, self.server.library_root),
                    "library_works": search_library(self.server.project_root, library_root=self.server.library_root),
                    "workspace": workspace_view(self.server.workspace_root),
                    "retrievals": list_retrievals(self.server.project_root),
                    "research": research_state(self.server.project_root),
                    "authoring": authoring_state(self.server.project_root),
                })
                return
            if parsed.path == "/api/capabilities":
                self._json({
                    "vision_ocr": capability(), "translation": translation_capability(),
                    "research_connectors": connector_capabilities(),
                })
                return
            if parsed.path == "/api/research/record":
                record_id = parse_qs(parsed.query).get("id", [""])[0]
                self._json(retrieval_record(self.server.project_root, record_id))
                return
            if parsed.path == "/api/source":
                source_id = parse_qs(parsed.query).get("id", [""])[0]
                self._json(source_view(self.server.project_root, source_id))
                return
            if parsed.path == "/api/thread":
                thread_id = parse_qs(parsed.query).get("id", [""])[0]
                self._json(thread_view(self.server.project_root, thread_id))
                return
            if parsed.path == "/api/manuscript/document":
                manuscript_id = parse_qs(parsed.query).get("id", [""])[0]
                try:
                    self._json(document_detail(self.server.project_root, manuscript_id))
                except KeyError:
                    self._json(ensure_document(self.server.project_root, manuscript_id))
                return
            if parsed.path == "/api/library/search":
                query = parse_qs(parsed.query)
                self._json(search_library(
                    self.server.project_root,
                    query.get("q", [""])[0],
                    query.get("tag", []),
                    self.server.library_root,
                ))
                return
            if parsed.path == "/api/library/work":
                work_id = parse_qs(parsed.query).get("id", [""])[0]
                self._json(work_detail(self.server.project_root, work_id, self.server.library_root))
                return
            if parsed.path == "/api/library/scan":
                session_id = parse_qs(parsed.query).get("id", [""])[0]
                self._json(scan_session(self.server.project_root, session_id, self.server.library_root))
                return
            if parsed.path == "/api/library/file":
                file_id = parse_qs(parsed.query).get("id", [""])[0]
                source = library_file_path(self.server.project_root, file_id, self.server.library_root)
                content_type = {
                    ".pdf": "application/pdf", ".txt": "text/plain; charset=utf-8",
                    ".md": "text/markdown; charset=utf-8",
                }.get(source.suffix.lower(), "application/octet-stream")
                self._send(200, source.read_bytes(), content_type)
                return
            if parsed.path == "/api/page-image":
                page_id = parse_qs(parsed.query).get("id", [""])[0]
                image = page_image_path(self.server.project_root, page_id)
                self._send(200, image.read_bytes(), "image/png")
                return
            if parsed.path == "/api/export/file":
                relative = Path(parse_qs(parsed.query).get("path", [""])[0])
                export_root = (self.server.project_root / "exports").resolve()
                target = (self.server.project_root / relative).resolve()
                if export_root not in target.parents or not target.is_file():
                    raise FileNotFoundError("export file is unavailable")
                content_type = {
                    ".md": "text/markdown; charset=utf-8",
                    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                }.get(target.suffix.lower(), "application/octet-stream")
                self._send(200, target.read_bytes(), content_type)
                return
            name = "index.html" if parsed.path == "/" else parsed.path.lstrip("/")
            if name not in {"index.html", "app.js", "styles.css"}:
                self._json({"error": "not_found"}, 404)
                return
            content_type = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}[Path(name).suffix]
            self._send(200, (WEB_ROOT / name).read_bytes(), content_type)
        except (KeyError, ValueError, FileNotFoundError) as error:
            self._json({"error": str(error)}, 404)
        except Exception as error:
            self._json({"error": str(error)}, 500)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/import":
                query = parse_qs(parsed.query)
                filename = Path(query.get("filename", ["source.pdf"])[0]).name
                title = query.get("title", [Path(filename).stem])[0]
                if Path(filename).suffix.lower() != ".pdf":
                    raise ValueError("only PDF files can be imported into the workbench")
                length = int(self.headers.get("Content-Length", "0"))
                data = self.rfile.read(length)
                if not data.startswith(b"%PDF-"):
                    raise ValueError("uploaded file is not a PDF")
                temp_root = self.server.project_root / "tmp"
                temp_root.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(dir=temp_root) as directory:
                    upload = Path(directory) / filename
                    upload.write_bytes(data)
                    source = register_source(self.server.project_root, upload, title)
                    intake = ingest_pdf(self.server.project_root, source["source_id"])
                self._json({"source": source, "intake": intake}, 201)
                return
            if parsed.path == "/api/manuscript/import-docx":
                query = parse_qs(parsed.query)
                title = query.get("title", ["导入的 DOCX"])[0]
                length = int(self.headers.get("Content-Length", "0"))
                data = self.rfile.read(length)
                if not data.startswith(b"PK"):
                    raise ValueError("uploaded file is not a DOCX package")
                self._json(import_docx(self.server.project_root, title, data), 201)
                return
            payload = self._body_json()
            if parsed.path == "/api/repair/block":
                result = submit_block_repair(
                    self.server.project_root,
                    str(payload["anomaly_id"]),
                    str(payload["text"]),
                    str(payload["reviewer"]),
                    str(payload["reason"]),
                )
            elif parsed.path == "/api/repair/page":
                result = submit_page_repair(
                    self.server.project_root,
                    str(payload["anomaly_id"]),
                    {"blocks": payload["blocks"]},
                    str(payload["reviewer"]),
                    str(payload["reason"]),
                )
            elif parsed.path == "/api/repair/relation":
                result = submit_relation_repair(
                    self.server.project_root,
                    str(payload["anomaly_id"]),
                    bool(payload["continues"]),
                    str(payload["reviewer"]),
                    str(payload["reason"]),
                )
            elif parsed.path == "/api/ocr/propose":
                result = create_ocr_proposal(
                    self.server.project_root,
                    str(payload["page_id"]),
                )
            elif parsed.path == "/api/ocr/accept":
                result = accept_ocr_proposal(
                    self.server.project_root,
                    str(payload["proposal_id"]),
                    {"blocks": payload["blocks"]},
                    str(payload["reviewer"]),
                    str(payload["reason"]),
                )
            elif parsed.path == "/api/ocr/reject":
                result = reject_ocr_proposal(
                    self.server.project_root,
                    str(payload["proposal_id"]),
                    str(payload["reviewer"]),
                    str(payload["reason"]),
                )
            elif parsed.path == "/api/thread/create":
                result = create_thread(self.server.project_root, str(payload["title"]))
            elif parsed.path == "/api/model/assign":
                result = assign_model(
                    self.server.project_root,
                    str(payload["profile_id"]),
                    str(payload.get("role", "main_reasoning")),
                )
            elif parsed.path == "/api/agent/message":
                result = send_message(
                    self.server.project_root,
                    str(payload["thread_id"]),
                    str(payload["content"]),
                    payload.get("context") if isinstance(payload.get("context"), dict) else None,
                )
            elif parsed.path == "/api/approval/decide":
                edited = payload.get("edited_request")
                if not isinstance(payload.get("approved"), bool):
                    raise ValueError("approved must be a boolean")
                result = decide_approval(
                    self.server.project_root,
                    str(payload["approval_id"]),
                    bool(payload["approved"]),
                    str(payload["reviewer"]),
                    str(payload["reason"]),
                    edited if isinstance(edited, dict) else None,
                )
            elif parsed.path == "/api/library/scan":
                result = scan_directory(
                    self.server.project_root,
                    Path(str(payload["source_root"])),
                    self.server.library_root,
                    str(payload.get("skill_name", "historical-material-intake")),
                )
            elif parsed.path == "/api/library/approve":
                candidate_ids = payload.get("candidate_ids")
                result = approve_candidates(
                    self.server.project_root,
                    str(payload["session_id"]),
                    [str(item) for item in candidate_ids] if isinstance(candidate_ids, list) else None,
                    self.server.library_root,
                )
            elif parsed.path == "/api/library/work/update":
                result = update_work(
                    self.server.project_root,
                    str(payload["work_id"]),
                    payload.get("fields", {}) if isinstance(payload.get("fields"), dict) else {},
                    [str(item) for item in payload.get("tags", [])],
                    self.server.library_root,
                )
            elif parsed.path == "/api/library/link":
                result = link_work_to_project(
                    self.server.project_root,
                    str(payload["work_id"]),
                    self.server.library_root,
                )
            elif parsed.path == "/api/project/create":
                result = create_workspace_project(self.server.workspace_root, str(payload["title"]))
                self.server.project_root = Path(result["project_root"])
            elif parsed.path == "/api/project/select":
                self.server.project_root = select_workspace_project(
                    self.server.workspace_root, str(payload["project_id"])
                )
                result = {"project_root": str(self.server.project_root), "project": project_status(self.server.project_root)}
            elif parsed.path == "/api/library/add-to-project":
                result = add_library_file_to_project(
                    self.server.project_root, self.server.library_root,
                    str(payload["work_id"]), str(payload["file_id"]),
                )
            elif parsed.path == "/api/research/search":
                result = search(
                    self.server.project_root, str(payload["provider"]), str(payload["query"]),
                    int(payload.get("limit", 10)),
                )
            elif parsed.path == "/api/claim/create":
                result = create_claim(self.server.project_root, str(payload["text"]))
            elif parsed.path == "/api/evidence/create":
                result = create_evidence(
                    self.server.project_root, str(payload["claim_id"]), str(payload["block_id"]),
                    str(payload["quote"]), str(payload.get("note", "")), str(payload.get("relation", "supports")),
                )
            elif parsed.path == "/api/freeze/create":
                result = create_freeze(
                    self.server.project_root, str(payload["title"]), [str(value) for value in payload["claim_ids"]],
                )
            elif parsed.path == "/api/freeze/approve":
                result = approve_freeze(
                    self.server.project_root, str(payload["freeze_id"]), str(payload["reviewer"]),
                )
            elif parsed.path == "/api/draft/create":
                result = draft_from_freeze(
                    self.server.project_root, str(payload["freeze_id"]), str(payload.get("title", "")),
                )
            elif parsed.path == "/api/review/create":
                result = review_artifact(
                    self.server.project_root, str(payload["version_id"]), str(payload.get("reviewer_role", "source_critic")),
                )
            elif parsed.path == "/api/artifact/export":
                result = export_artifact(self.server.project_root, str(payload["artifact_id"]))
            elif parsed.path == "/api/browser/session":
                result = create_browser_session(
                    self.server.project_root, str(payload["start_url"]), str(payload["allowed_domain"]),
                )
            elif parsed.path == "/api/memory/create":
                result = create_memory_candidate(
                    self.server.project_root, str(payload["category"]), str(payload["content"]),
                    [str(value) for value in payload["source_refs"]],
                )
            elif parsed.path == "/api/translation/create":
                result = translate_evidence(
                    self.server.project_root, str(payload["evidence_id"]),
                    str(payload.get("target_language", "Chinese")),
                )
            elif parsed.path == "/api/manuscript/import":
                result = import_manuscript(
                    self.server.project_root, str(payload["title"]), str(payload["markdown"]),
                )
                result["structured_document"] = ensure_document(
                    self.server.project_root, str(result["manuscript_id"])
                )
            elif parsed.path == "/api/manuscript/document/save":
                if not isinstance(payload.get("document"), dict):
                    raise ValueError("document must be an object")
                result = save_document(
                    self.server.project_root, str(payload["manuscript_id"]), payload["document"],
                )
            elif parsed.path == "/api/manuscript/document/export":
                result = export_document(
                    self.server.project_root, str(payload["manuscript_id"]), str(payload["format"]),
                )
            elif parsed.path == "/api/writing/propose":
                result = create_writing_proposal(
                    self.server.project_root, str(payload["section_id"]), str(payload["operation"]),
                    str(payload.get("instruction", "")), str(payload.get("freeze_id", "")),
                )
            elif parsed.path == "/api/writing/decide":
                if not isinstance(payload.get("approved"), bool):
                    raise ValueError("approved must be a boolean")
                result = decide_writing_proposal(
                    self.server.project_root, str(payload["proposal_id"]), bool(payload["approved"]),
                    str(payload["reviewer"]), str(payload["edited_content"]) if "edited_content" in payload else None,
                )
            elif parsed.path == "/api/reading/create":
                result = create_reading_job(
                    self.server.project_root, str(payload["title"]), str(payload["question"]),
                    str(payload["mode"]), [str(value) for value in payload["source_ids"]],
                    str(payload["stop_condition"]),
                )
            elif parsed.path == "/api/historiography/create":
                result = create_historiography_entry(self.server.project_root, payload)
            elif parsed.path == "/api/journal/create":
                result = create_journal_template(
                    self.server.project_root, str(payload["name"]), str(payload["citation_style"]),
                    [str(value) for value in payload["section_rules"]],
                )
            elif parsed.path == "/api/manuscript/export":
                result = export_manuscript(
                    self.server.project_root, str(payload["manuscript_id"]), str(payload["template_id"]),
                )
            elif parsed.path == "/api/memory/decide":
                if not isinstance(payload.get("approved"), bool):
                    raise ValueError("approved must be a boolean")
                result = decide_memory_candidate(
                    self.server.project_root, str(payload["candidate_id"]), bool(payload["approved"]),
                )
            else:
                self._json({"error": "not_found"}, 404)
                return
            self._json(result)
        except (KeyError, ValueError, FileNotFoundError) as error:
            self._json({"error": str(error)}, 400)
        except Exception as error:
            self._json({"error": str(error)}, 500)


def build_server(
    project_root: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    library_root: Path | None = None,
    workspace_root: Path | None = None,
) -> WorkbenchServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("workbench may only bind to a loopback address")
    project_root = project_root.resolve()
    if not (project_root / "project.sqlite3").is_file():
        raise FileNotFoundError(f"project database does not exist: {project_root}")
    server = WorkbenchServer((host, port), WorkbenchHandler)
    server.library_root = resolve_library_root(project_root, library_root)
    server.workspace_root = (workspace_root or (project_root.parent / "historical-workbench-workspace")).resolve()
    registry = initialize_workspace(server.workspace_root, project_root)
    server.project_root = Path(registry["current_project"])
    return server


def serve(
    project_root: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    library_root: Path | None = None,
    workspace_root: Path | None = None,
) -> None:
    server = build_server(project_root, host, port, library_root, workspace_root)
    try:
        print(f"Historical Research Workbench: http://{host}:{server.server_port}")
        server.serve_forever()
    finally:
        server.server_close()
