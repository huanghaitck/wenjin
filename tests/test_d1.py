from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

import pymupdf

from research_workbench.db import connect
from research_workbench.library import approve_candidates, scan_directory, work_detail
from research_workbench.project_library import add_library_file_to_project
from research_workbench.research import search
from research_workbench.scholarship import (
    approve_freeze,
    create_browser_session,
    create_claim,
    create_evidence,
    create_freeze,
    create_memory_candidate,
    decide_memory_candidate,
    draft_from_freeze,
    export_artifact,
    review_artifact,
)
from research_workbench.service import import_structure, initialize_project, register_source
from research_workbench.workspace import (
    create_workspace_project,
    initialize_workspace,
    select_workspace_project,
    workspace_view,
)
from research_workbench.translation import translate_evidence
from research_workbench.web import build_server


FIXTURES = Path(__file__).parent / "fixtures"


class D1EndToEndDemoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        initialize_project(self.project, "D1 demo")
        source_file = self.root / "source.pdf"
        source_file.write_bytes(b"%PDF-1.4\nD1 fixture\n%%EOF\n")
        self.source = register_source(self.project, source_file, "Expedition source")
        import_structure(self.project, self.source["source_id"], FIXTURES / "m1_structure.json")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_workspace_creates_and_switches_projects(self) -> None:
        workspace = self.root / "workspace"
        initialize_workspace(workspace, self.project)
        created = create_workspace_project(workspace, "蒙古知识史")
        view = workspace_view(workspace)
        self.assertEqual(len(view["projects"]), 2)
        self.assertEqual(view["current_project"], created["project_root"])
        selected = select_workspace_project(workspace, self.source_project_id())
        self.assertEqual(selected, self.project.resolve())

    def source_project_id(self) -> str:
        with connect(self.project) as connection:
            return connection.execute("SELECT project_id FROM projects").fetchone()[0]

    def test_retrieval_is_reproducible_and_stays_discovered(self) -> None:
        payload = {"message": {"items": [{
            "DOI": "10.1000/example", "title": ["Imperial Expedition"],
            "author": [{"family": "Smith", "given": "A"}],
            "published": {"date-parts": [[1908]]}, "container-title": ["History Review"],
            "URL": "https://doi.org/10.1000/example",
        }]}}
        result = search(self.project, "crossref", "imperial expedition", 5, lambda url, headers: payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["results"][0]["qualification"], "DISCOVERED")
        self.assertIn("query.bibliographic=imperial+expedition", result["request_url"])
        self.assertEqual(len(result["response_hash"]), 64)

    def test_library_version_is_copied_into_project_without_changing_original(self) -> None:
        materials, library = self.root / "materials", self.root / "library"
        materials.mkdir()
        pdf = materials / "archive.pdf"
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((72, 72), "Historical archive expedition record with verified page text.")
        document.save(pdf)
        document.close()
        before = pdf.read_bytes()
        session = scan_directory(self.project, materials, library)
        approved = approve_candidates(
            self.project, session["session_id"], [session["candidates"][0]["candidate_id"]], library
        )
        work_id = approved["approved"][0]["work_id"]
        file_id = work_detail(self.project, work_id, library)["files"][0]["file_id"]
        result = add_library_file_to_project(self.project, library, work_id, file_id)
        self.assertEqual(result["library_version"]["sha256"], result["source"]["sha256"])
        self.assertEqual(pdf.read_bytes(), before)
        with connect(self.project) as connection:
            linked = connection.execute(
                "SELECT library_version_id FROM source_library_links WHERE source_id = ?",
                (result["source"]["source_id"],),
            ).fetchone()
        self.assertEqual(linked["library_version_id"], result["library_version"]["version_id"])

    def test_blocked_text_cannot_be_evidence_and_freeze_requires_approval(self) -> None:
        claim = create_claim(self.project, "考察活动依赖页面所记载的地方知识。")
        blocked = f"{self.source['source_id']}:B1"
        with self.assertRaisesRegex(ValueError, "cannot be submitted"):
            create_evidence(self.project, claim["claim_id"], blocked,
                            "The expedition left the station in spring.", "待核")

        usable = f"{self.source['source_id']}:B2"
        claim = create_evidence(
            self.project, claim["claim_id"], usable,
            "The sentence continues toward the page boundary", "页面关系需保留", "supports",
        )
        freeze = create_freeze(self.project, "小型冻结包", [claim["claim_id"]])
        self.assertEqual(freeze["status"], "pending")
        with self.assertRaisesRegex(ValueError, "approved"):
            draft_from_freeze(self.project, freeze["freeze_id"], "试写")

        approved = approve_freeze(self.project, freeze["freeze_id"], "Professor")
        artifact = draft_from_freeze(self.project, approved["freeze_id"], "试写")
        version = artifact["versions"][0]
        self.assertIn("物理页 1", version["content"])
        self.assertEqual(len(version["source_refs"]), 1)
        review = review_artifact(self.project, version["version_id"])
        self.assertEqual(review["status"], "passed")
        exported = export_artifact(self.project, artifact["artifact_id"])
        self.assertTrue((self.project / exported["project_path"]).is_file())
        translation = translate_evidence(
            self.project, claim["evidence"][0]["evidence_id"], "Chinese",
            lambda text, language: "该句延伸至页面边界。",
        )
        self.assertEqual(translation["artifact_type"], "evidence_translation")
        self.assertIn("该句延伸至页面边界", translation["versions"][0]["content"])

    def test_browser_receipt_rejects_secrets_and_memory_stays_local_candidate(self) -> None:
        session = create_browser_session(self.project, "https://example.org/search?q=archive", "example.org")
        self.assertEqual(session["status"], "user_controlled")
        with self.assertRaisesRegex(ValueError, "credential"):
            create_browser_session(self.project, "https://example.org/?token=secret", "example.org")
        candidate = create_memory_candidate(
            self.project, "negative_result", "限定检索未找到直接研究。", [self.source["source_id"]]
        )
        decided = decide_memory_candidate(self.project, candidate["candidate_id"], True)
        self.assertEqual(decided["status"], "approved_local")

    def test_schema_four_tables_are_created(self) -> None:
        with connect(self.project) as connection:
            version = connection.execute("SELECT MAX(version) FROM schema_meta").fetchone()[0]
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(version, 6)
        self.assertTrue({"claims", "evidence_items", "evidence_freezes", "browser_sessions"} <= tables)

    def test_loopback_api_exposes_conversation_workspace_and_research_objects(self) -> None:
        server = build_server(
            self.project, port=0, library_root=self.root / "library",
            workspace_root=self.root / "workspace-api",
        )
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{server.server_port}"

        def post(path: str, payload: dict[str, object]) -> dict[str, object]:
            request = Request(
                base + path, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            return json.loads(urlopen(request, timeout=5).read())

        try:
            snapshot = json.loads(urlopen(base + "/api/snapshot", timeout=5).read())
            self.assertEqual(snapshot["workspace"]["projects"][0]["title"], "D1 demo")
            claim = post("/api/claim/create", {"text": "API claim"})
            session = post("/api/browser/session", {
                "start_url": "https://example.org/search", "allowed_domain": "example.org",
            })
            self.assertEqual(claim["status"], "candidate")
            self.assertEqual(session["status"], "user_controlled")
            html = urlopen(base + "/", timeout=5).read().decode()
            self.assertIn("研究浏览器", html)
            self.assertIn("projectSelect", html)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
