from __future__ import annotations

import shutil
import tempfile
import json
import threading
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

import fitz

from research_workbench.library import (
    _material_type,
    _pdf_bibliography,
    approve_candidates,
    decide_literature_relation,
    link_work_to_project,
    library_graph,
    move_work_to_shelf,
    scan_directory,
    search_library,
    update_work,
    work_detail,
)
from research_workbench.library_store import connect_library
from research_workbench.db import connect
from research_workbench.project_library import add_library_file_to_project
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
        changed = work_detail(self.project, work_id, self.library)
        self.assertEqual(changed["files"][0]["file_state"], "changed_since_last_scan")
        self.assertFalse(changed["files"][0]["versions"][0]["bytes_available"])
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
        self.assertEqual(search_library(self.project, "知识", library_root=self.library)[0]["work_id"], work_id)
        self.assertEqual(search_library(self.project, tags=["知识史"], library_root=self.library)[0]["work_id"], work_id)
        moved = move_work_to_shelf(self.project, work_id, "monographs", self.library)
        self.assertEqual(moved["shelf"], "monographs")
        self.assertEqual(moved["shelf_label"], "学术专著")
        graph = library_graph(self.project, library_root=self.library)
        labels = {node["label"] for node in graph["nodes"]}
        relations = {edge["relation"] for edge in graph["edges"]}
        self.assertIn("Imperial Archive Revised", labels)
        self.assertIn("Professor A", labels)
        self.assertIn("1908", labels)
        self.assertIn("authored_by", relations)
        self.assertIn("shelved_as", relations)
        self.assertEqual(len(graph["work_cards"]), 1)
        self.assertIn("Historical archive empire chronicle page 8", graph["work_cards"][0]["content_excerpt"])
        self.assertEqual(graph["work_cards"][0]["preview_pages"], 10)
        self.assertIsNone(graph["work_cards"][0]["project_source"])
        content_graph = library_graph(self.project, "chronicle page 8", library_root=self.library)
        self.assertEqual(content_graph["work_cards"][0]["work_id"], work_id)
        with connect_library(self.library) as connection:
            work_node = connection.execute(
                "SELECT node_id FROM knowledge_nodes WHERE node_type = 'work' AND normalized_label = ?",
                (work_id.casefold(),),
            ).fetchone()["node_id"]
            connection.execute(
                "DELETE FROM knowledge_edges WHERE source_node_id = ? OR target_node_id = ?",
                (work_node, work_node),
            )
            connection.execute("DELETE FROM knowledge_nodes WHERE node_id = ?", (work_node,))
        repaired_graph = library_graph(self.project, library_root=self.library)
        self.assertEqual(repaired_graph["backfilled_work_count"], 1)
        self.assertIn("Imperial Archive Revised", {node["label"] for node in repaired_graph["nodes"]})
        focused_graph = library_graph(self.project, limit=1, library_root=self.library)
        self.assertEqual(sum(node["node_type"] == "work" for node in focused_graph["nodes"]), 1)
        linked = link_work_to_project(self.project, work_id, self.library)
        self.assertEqual(len(linked["project_links"]), 1)
        added = add_library_file_to_project(
            self.project, self.library, work_id, linked["files"][0]["file_id"]
        )
        with connect(self.project) as connection:
            connection.execute(
                "UPDATE pages SET verification_state='human_verified', use_state='research_usable' WHERE source_id=?",
                (added["source"]["source_id"],),
            )
            connection.execute(
                """UPDATE blocks SET verification_state='human_verified', use_state='research_usable'
                   WHERE page_id IN (SELECT page_id FROM pages WHERE source_id=?)""",
                (added["source"]["source_id"],),
            )
        linked_graph = library_graph(self.project, "Imperial Archive", library_root=self.library)
        self.assertEqual(linked_graph["work_cards"][0]["project_source"]["source_id"], added["source"]["source_id"])
        content_graph = library_graph(self.project, library_root=self.library)["content_graph"]
        content_types = {node["node_type"] for node in content_graph["nodes"]}
        self.assertIn("source", content_types)
        self.assertIn("page", content_types)
        self.assertIn("content", content_types)
        self.assertTrue(any("Historical archive" in node.get("excerpt", "") for node in content_graph["nodes"]))
        self.assertIn("contains_content", {edge["relation"] for edge in content_graph["edges"]})
        version = linked["files"][0]["versions"][0]
        self.assertEqual(version["skill_name"], "historical-material-intake")
        self.assertEqual(len(version["skill_sha256"]), 64)

    def test_skill_discovery_and_unsupported_candidate_remain_visible(self) -> None:
        skill = next(item for item in discover_skills() if item["name"] == "historical-material-intake")
        self.assertEqual(skill["execution"], "instructions_only")
        self.assertEqual(skill["placement"], "user_action")
        self.assertIn("library_intake", skill["compatible_actions"])
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

    def test_title_page_suggestions_remain_human_editable_metadata(self) -> None:
        sample = "书 名廿二史考异\n(清)钱大昕撰\n凤凰出版社\n版次 2008年1月第1版"
        self.assertEqual(
            _pdf_bibliography(sample, "qdx", "", "", ""),
            ("廿二史考异", "(清)钱大昕撰", "凤凰出版社", "2008"),
        )

    def test_note_title_match_requires_human_decision_before_formal_literature_relation(self) -> None:
        target = self.materials / "target.md"
        target.write_text("# Referenced Monograph\n\nHistorical methods and archives." * 10, encoding="utf-8")
        target_work, _ = self._approve_one(target)
        update_work(self.project, target_work, {"canonical_title": "Referenced Monograph"}, [], self.library)
        source = self.materials / "source-study.pdf"
        document = fitz.open()
        document.new_page().insert_text((72, 72), "Source Study main argument and evidence.")
        document.new_page().insert_text((72, 72), "References: Referenced Monograph. University Press.")
        document.set_metadata({"title": "Source Study", "author": "Scholar B"})
        document.save(source)
        document.close()
        source_work, _ = self._approve_one(source)
        detail = update_work(self.project, source_work, {"canonical_title": "Source Study"}, [], self.library)
        add_library_file_to_project(self.project, self.library, source_work, detail["files"][0]["file_id"])
        graph = library_graph(self.project, library_root=self.library)
        candidate = next(item for item in graph["literature_relations"] if item["target_work_id"] == target_work)
        self.assertEqual(candidate["status"], "candidate")
        decided = decide_literature_relation(
            self.project, candidate["relation_key"], True, "cites", "researcher", "checked reference page",
            self.library,
        )
        self.assertEqual(decided["status"], "approved")
        refreshed = library_graph(self.project, library_root=self.library)
        approved = next(item for item in refreshed["literature_relations"] if item["relation_key"] == candidate["relation_key"])
        self.assertEqual(approved["relation_type"], "cites")
        self.assertEqual(approved["status"], "approved")

    def test_scan_suggests_all_six_shelves_and_bulk_approval_keeps_files_in_place(self) -> None:
        samples = {
            "source.md": ("# 地方志史料\n\n地方志日记与档案。", "primary_sources"),
            "article.md": ("# 区域史研究论文\n\n某大学学报期刊论文。", "academic_articles"),
            "book.md": ("# 区域史专著\n\n某某出版社 ISBN 978-7。", "monographs"),
            "draft.md": ("# 我的返修稿\n\n尚未刊行的论文稿。", "personal_manuscripts"),
            "catalog.md": ("# 地方文献目录索引\n\n工具书与目录。", "reference_works"),
            "unknown.md": ("# 普通材料\n\n内容尚待研究者判断。", "unclassified"),
        }
        original = {}
        for name, (content, _) in samples.items():
            path = self.materials / name
            path.write_text(content * 20, encoding="utf-8")
            original[path] = path.read_bytes()
        session = scan_directory(self.project, self.materials, self.library)
        shelves = {Path(item["path"]).name: item["suggested_shelf"] for item in session["candidates"]}
        self.assertEqual(shelves, {name: expected for name, (_, expected) in samples.items()})
        self.assertEqual(session["eligible_remaining_count"], len(samples))
        result = approve_candidates(self.project, session["session_id"], None, self.library)
        self.assertEqual(len(result["approved"]), len(samples))
        self.assertTrue(all(path.read_bytes() == value for path, value in original.items()))
        works = search_library(self.project, library_root=self.library)
        self.assertEqual({work["shelf"] for work in works}, set(shelves.values()))

    def test_material_type_uses_project_location_only_as_a_classification_hint(self) -> None:
        self.assertEqual(_material_type("未定名", "内容", r"D:\\研究\\个人论文与稿件\\草稿.docx"), "personal_manuscript")
        self.assertEqual(_material_type("某书", "CIP 某出版社"), "monograph")

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
            deadline = time.monotonic() + 5
            while session["status"] == "scanning" and time.monotonic() < deadline:
                time.sleep(0.02)
                session = json.loads(urlopen(
                    base + f"/api/library/scan?id={session['session_id']}", timeout=5
                ).read())
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
