from __future__ import annotations

import shutil
import tempfile
import json
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

import fitz

from research_workbench.library import (
    approve_candidates,
    link_work_to_project,
    scan_directory,
    search_library,
    update_work,
    work_detail,
)
from research_workbench.service import initialize_project
from research_workbench.skill_registry import discover_skills
from research_workbench.web import build_server


class M5ResearchLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.project = root / "project"
        self.library = root / "library"
        self.materials = root / "materials"
        self.materials.mkdir()
        initialize_project(self.project, "M5 test project")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _approve_one(self, path: Path) -> tuple[str, dict[str, object]]:
        session = scan_directory(self.project, path.parent, self.library)
        candidate = next(item for item in session["candidates"] if item["path"] == str(path.resolve()))
        approved = approve_candidates(self.project, session["session_id"], [candidate["candidate_id"]], self.library)
        return approved["approved"][0]["work_id"], candidate

    def test_one_character_change_creates_linked_version_not_new_work(self) -> None:
        source = self.materials / "chronicle.txt"
        original_text = "地方历史档案与帝国考察记录。" * 20
        source.write_text(original_text, encoding="utf-8")
        work_id, first = self._approve_one(source)

        source.write_text(source.read_text(encoding="utf-8") + "字", encoding="utf-8")
        session = scan_directory(self.project, self.materials, self.library)
        candidate = next(item for item in session["candidates"] if item["path"] == str(source.resolve()))
        self.assertEqual(candidate["proposed_action"], "new_version")
        self.assertEqual(candidate["existing_work_id"], work_id)
        approve_candidates(self.project, session["session_id"], [candidate["candidate_id"]], self.library)

        detail = work_detail(self.project, work_id, self.library)
        self.assertEqual(detail["file_count"], 1)
        self.assertEqual(detail["version_count"], 2)
        versions = detail["files"][0]["versions"]
        self.assertEqual(sum(item["is_current"] for item in versions), 1)
        self.assertNotEqual(first["sha256"], versions[0]["sha256"])

        source.write_text(original_text, encoding="utf-8")
        reverted = scan_directory(self.project, self.materials, self.library)
        candidate = reverted["candidates"][0]
        self.assertEqual(candidate["proposed_action"], "new_version")
        approve_candidates(self.project, reverted["session_id"], [candidate["candidate_id"]], self.library)
        self.assertEqual(work_detail(self.project, work_id, self.library)["version_count"], 3)

    def test_exact_duplicate_keeps_both_locations_and_original_bytes(self) -> None:
        original = self.materials / "source.md"
        original.write_text("# 蒙古考察史\n\n历史档案与帝国知识。" * 20, encoding="utf-8")
        before = original.read_bytes()
        work_id, _ = self._approve_one(original)
        duplicate = self.materials / "copy.md"
        shutil.copy2(original, duplicate)

        session = scan_directory(self.project, self.materials, self.library)
        candidate = next(item for item in session["candidates"] if item["path"] == str(duplicate.resolve()))
        self.assertEqual(candidate["proposed_action"], "exact_duplicate")
        approve_candidates(self.project, session["session_id"], [candidate["candidate_id"]], self.library)

        detail = work_detail(self.project, work_id, self.library)
        self.assertEqual(detail["file_count"], 2)
        self.assertEqual({item["path"] for item in detail["files"]}, {str(original.resolve()), str(duplicate.resolve())})
        self.assertEqual(original.read_bytes(), before)

    def test_pdf_triage_stops_at_ten_pages_and_library_is_searchable(self) -> None:
        pdf = self.materials / "history.pdf"
        document = fitz.open()
        for index in range(12):
            page = document.new_page()
            page.insert_text((72, 72), f"Historical archive empire chronicle page {index + 1}")
        document.set_metadata({"title": "Imperial Archive", "author": "A Historian"})
        document.save(pdf)
        document.close()

        work_id, candidate = self._approve_one(pdf)
        self.assertEqual(candidate["inspected_pages"], 10)
        self.assertEqual(candidate["page_count"], 12)
        self.assertEqual(candidate["triage_state"], "likely_historical")
        self.assertEqual(candidate["format"], "pdf")

        updated = update_work(
            self.project,
            work_id,
            {
                "canonical_title": "Imperial Archive Revised", "author": "Professor A",
                "edition_label": "Second edition", "publication_year": "1908",
            },
            ["蒙古", "知识史"],
            self.library,
        )
        self.assertEqual(updated["canonical_title"], "Imperial Archive Revised")
        self.assertEqual(updated["editions"][0]["publication_year"], "1908")
        self.assertEqual(search_library(self.project, "Professor A", library_root=self.library)[0]["work_id"], work_id)
        self.assertEqual(search_library(self.project, tags=["知识史"], library_root=self.library)[0]["work_id"], work_id)
        linked = link_work_to_project(self.project, work_id, self.library)
        self.assertEqual(len(linked["project_links"]), 1)
        version = linked["files"][0]["versions"][0]
        self.assertEqual(version["skill_name"], "historical-material-intake")
        self.assertEqual(len(version["skill_sha256"]), 64)

    def test_skill_discovery_and_unsupported_candidate_remain_visible(self) -> None:
        skill = next(item for item in discover_skills() if item["name"] == "historical-material-intake")
        self.assertEqual(skill["execution"], "instructions_only")
        self.assertEqual(len(skill["sha256"]), 64)
        unsupported = self.materials / "scan.jpg"
        unsupported.write_bytes(b"not-a-real-image")
        session = scan_directory(self.project, self.materials, self.library)
        candidate = session["candidates"][0]
        self.assertEqual(candidate["triage_state"], "unsupported")
        approved = approve_candidates(
            self.project, session["session_id"], [candidate["candidate_id"]], self.library
        )
        self.assertEqual(approved["approved"], [])

    def test_loopback_library_api_scans_approves_and_shows_versions(self) -> None:
        source = self.materials / "api-history.txt"
        source.write_text("历史档案与地方志研究。" * 30, encoding="utf-8")
        server = build_server(self.project, port=0, library_root=self.library)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{server.server_port}"

        def post(path: str, payload: dict[str, object]) -> dict[str, object]:
            request = Request(
                base + path,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            return json.loads(urlopen(request, timeout=5).read())

        try:
            snapshot = json.loads(urlopen(base + "/api/snapshot", timeout=5).read())
            self.assertEqual(snapshot["library"]["library_root"], str(self.library.resolve()))
            session = post("/api/library/scan", {"source_root": str(self.materials)})
            candidate = session["candidates"][0]
            result = post(
                "/api/library/approve",
                {"session_id": session["session_id"], "candidate_ids": [candidate["candidate_id"]]},
            )
            work_id = result["approved"][0]["work_id"]
            detail = json.loads(urlopen(base + f"/api/library/work?id={work_id}", timeout=5).read())
            self.assertEqual(detail["version_count"], 1)
            self.assertEqual(len(detail["files"][0]["versions"][0]["sha256"]), 64)
            original = urlopen(
                base + f"/api/library/file?id={detail['files'][0]['file_id']}", timeout=5
            ).read()
            self.assertEqual(original, source.read_bytes())
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
