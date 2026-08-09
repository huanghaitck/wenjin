from __future__ import annotations

import json
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .pdf_ingestion import ingest_pdf
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


WEB_ROOT = Path(__file__).parent / "web_assets"


class WorkbenchServer(ThreadingHTTPServer):
    project_root: Path


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
                self._json({"project": project_status(self.server.project_root), "sources": list_sources(self.server.project_root)})
                return
            if parsed.path == "/api/capabilities":
                self._json({"vision_ocr": capability()})
                return
            if parsed.path == "/api/source":
                source_id = parse_qs(parsed.query).get("id", [""])[0]
                self._json(source_view(self.server.project_root, source_id))
                return
            if parsed.path == "/api/page-image":
                page_id = parse_qs(parsed.query).get("id", [""])[0]
                image = page_image_path(self.server.project_root, page_id)
                self._send(200, image.read_bytes(), "image/png")
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
            else:
                self._json({"error": "not_found"}, 404)
                return
            self._json(result)
        except (KeyError, ValueError, FileNotFoundError) as error:
            self._json({"error": str(error)}, 400)
        except Exception as error:
            self._json({"error": str(error)}, 500)


def build_server(project_root: Path, host: str = "127.0.0.1", port: int = 8765) -> WorkbenchServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("workbench may only bind to a loopback address")
    project_root = project_root.resolve()
    if not (project_root / "project.sqlite3").is_file():
        raise FileNotFoundError(f"project database does not exist: {project_root}")
    server = WorkbenchServer((host, port), WorkbenchHandler)
    server.project_root = project_root
    return server


def serve(project_root: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = build_server(project_root, host, port)
    try:
        print(f"Historical Research Workbench: http://{host}:{server.server_port}")
        server.serve_forever()
    finally:
        server.server_close()
