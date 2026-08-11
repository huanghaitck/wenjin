from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen

import pymupdf as fitz

from research_workbench.pdf_ingestion import ingest_pdf
from research_workbench.service import (
    correct_relation,
    initialize_project,
    list_anomalies,
    list_blocks,
    project_status,
    register_source,
    source_view,
    submit_page_repair,
    submit_relation_repair,
)
from research_workbench.web import build_server


def make_text_pdf(path: Path, unfinished_boundary: bool = True) -> None:
    document = fitz.open()
    first = document.new_page(width=612, height=792)
    first.insert_text((300, 38), "1", fontsize=10)
    first.insert_text((72, 120), "Expedition field notes", fontsize=18)
    ending = "The party crossed the frozen river and continued toward" if unfinished_boundary else "The party stopped for the night."
    first.insert_textbox((72, 170, 540, 700), ending, fontsize=12)
    second = document.new_page(width=612, height=792)
    second.insert_text((300, 38), "2", fontsize=10)
    second.insert_textbox((72, 120, 540, 700), "the northern station, where the guide recorded the route.", fontsize=12)
    document.save(path)
    document.close()


def make_image_only_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=300, height=400)
    page.draw_rect(fitz.Rect(40, 50, 260, 350), color=(0, 0, 0), fill=(0.92, 0.9, 0.84))
    document.save(path)
    document.close()


def make_pdf_with_bottom_note(path: Path) -> None:
    document = fitz.open()
    first = document.new_page(width=612, height=792)
    first.insert_textbox((72, 500, 540, 570), "The main account continues across the page toward", fontsize=12)
    first.insert_textbox((72, 610, 540, 650), "VOYAGE EN CRISE - J5", fontsize=8)
    second = document.new_page(width=612, height=792)
    second.insert_textbox((72, 120, 540, 200), "the next settlement and records its local name.", fontsize=12)
    document.save(path)
    document.close()


def make_overlapping_text_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_textbox((72, 120, 540, 300), "First paragraph with enough text to form a block. " * 4, fontsize=12)
    page.insert_textbox((250, 140, 540, 260), "Overlapping OCR fragment that should not be trusted. " * 2, fontsize=12)
    document.save(path)
    document.close()


class M2PdfIntakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        initialize_project(self.project, "M2 test project")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def register_text_pdf(self, unfinished_boundary: bool = True) -> dict:
        source_file = self.root / "text-source.pdf"
        make_text_pdf(source_file, unfinished_boundary)
        return register_source(self.project, source_file, "Text source")

    def test_real_pdf_creates_page_images_markdown_and_normalized_regions(self) -> None:
        source = self.register_text_pdf()
        result = ingest_pdf(self.project, source["source_id"])
        self.assertEqual(result["page_count"], 2)
        artifact_root = self.project / "sources" / source["source_id"] / "derived" / "m2"
        self.assertTrue((artifact_root / "pages" / "page-0001.png").is_file())
        self.assertTrue((artifact_root / "markdown" / "page-0001.md").is_file())
        packet = json.loads((artifact_root / "structure.json").read_text(encoding="utf-8"))
        self.assertEqual([page["physical_page"] for page in packet["pages"]], [1, 2])
        self.assertEqual(packet["pages"][0]["printed_page"], "1")
        regions = [block["region"] for page in packet["pages"] for block in page["blocks"]]
        self.assertTrue(regions)
        self.assertTrue(all(0 <= value <= 1 for region in regions for value in region.values()))
        markdown = (artifact_root / "markdown" / "page-0001.md").read_text(encoding="utf-8")
        self.assertIn("physical_page: 1", markdown)
        self.assertIn("page-0001.png", markdown)

    def test_possible_cross_page_continuation_is_blocked_until_human_decision(self) -> None:
        source = self.register_text_pdf()
        ingest_pdf(self.project, source["source_id"])
        anomaly = next(item for item in list_anomalies(self.project) if item["scope_type"] == "relation")
        self.assertEqual(project_status(self.project)["sources"][0]["use_state"], "partial")
        result = submit_relation_repair(
            self.project,
            anomaly["anomaly_id"],
            True,
            "human-reviewer",
            "Compared the last and first lines against both page images.",
        )
        self.assertEqual(result["scope_type"], "relation")
        self.assertEqual(project_status(self.project)["sources"][0]["use_state"], "research_usable")
        relation = source_view(self.project, source["source_id"])["relations"][0]
        self.assertEqual(relation["effective_value"], {"continues": True})

    def test_cross_page_candidate_uses_paragraph_instead_of_bottom_note(self) -> None:
        source_file = self.root / "bottom-note.pdf"
        make_pdf_with_bottom_note(source_file)
        source = register_source(self.project, source_file, "Bottom note source")
        ingest_pdf(self.project, source["source_id"])
        view = source_view(self.project, source["source_id"])
        relation = view["relations"][0]
        blocks = {block["block_id"]: block for page in view["pages"] for block in page["blocks"]}
        self.assertEqual(blocks[relation["from_block_id"]]["block_type"], "paragraph")
        self.assertIn("main account continues", blocks[relation["from_block_id"]]["effective_text"])

    def test_human_can_correct_existing_relation_endpoints(self) -> None:
        source_file = self.root / "relation-correction.pdf"
        make_pdf_with_bottom_note(source_file)
        source = register_source(self.project, source_file, "Relation correction source")
        ingest_pdf(self.project, source["source_id"])
        view = source_view(self.project, source["source_id"])
        relation = view["relations"][0]
        first_page = view["pages"][0]
        paragraph = relation["from_block_id"]
        bottom_note = next(block["block_id"] for block in first_page["blocks"] if block["block_type"] == "footnote")
        correct_relation(
            self.project, relation["relation_id"], bottom_note, relation["to_block_id"], True,
            "human-reviewer", "Recorded a mistaken endpoint for the correction regression test.",
        )
        result = correct_relation(
            self.project, relation["relation_id"], paragraph, relation["to_block_id"], True,
            "human-reviewer", "Corrected both endpoints against adjacent rendered pages.",
        )
        self.assertEqual(result["from_block_id"], paragraph)
        corrected = source_view(self.project, source["source_id"])["relations"][0]
        self.assertEqual(corrected["from_block_id"], paragraph)
        self.assertEqual(corrected["effective_value"], {"continues": True})
        self.assertEqual(corrected["verification_state"], "human_repaired")

    def test_clean_page_boundary_does_not_create_relation_anomaly(self) -> None:
        source = self.register_text_pdf(unfinished_boundary=False)
        ingest_pdf(self.project, source["source_id"])
        self.assertFalse(any(item["scope_type"] == "relation" for item in list_anomalies(self.project)))
        self.assertEqual(project_status(self.project)["sources"][0]["use_state"], "research_usable")

    def test_image_only_pdf_is_visible_but_blocked_until_page_transcription(self) -> None:
        source_file = self.root / "scan.pdf"
        make_image_only_pdf(source_file)
        source = register_source(self.project, source_file, "Scan")
        ingest_pdf(self.project, source["source_id"])
        view = source_view(self.project, source["source_id"])
        self.assertEqual(view["source"]["use_state"], "blocked")
        self.assertTrue((self.project / view["pages"][0]["machine_payload"]["image_path"]).is_file())
        page_anomaly = next(item for item in view["anomalies"] if item["scope_type"] == "page")
        submit_page_repair(
            self.project,
            page_anomaly["anomaly_id"],
            {"blocks": [{"order": 1, "type": "paragraph", "text": "Human transcription of the scanned page."}]},
            "human-reviewer",
            "Transcribed the complete rendered page.",
        )
        self.assertEqual(project_status(self.project)["sources"][0]["use_state"], "research_usable")
        blocks = list_blocks(self.project, source["source_id"])
        self.assertEqual(blocks[0]["effective_text"], "Human transcription of the scanned page.")

    def test_overlapping_text_layer_is_not_marked_research_usable(self) -> None:
        source_file = self.root / "overlap.pdf"
        make_overlapping_text_pdf(source_file)
        source = register_source(self.project, source_file, "Overlapping text")
        ingest_pdf(self.project, source["source_id"])
        view = source_view(self.project, source["source_id"])
        self.assertEqual(view["source"]["use_state"], "blocked")
        anomaly = next(item for item in view["anomalies"] if item["anomaly_id"].endswith("FRAGMENTED_LAYOUT"))
        self.assertEqual(anomaly["scope_type"], "page")
        self.assertTrue((self.project / view["pages"][0]["machine_payload"]["image_path"]).is_file())

    def test_loopback_workbench_serves_project_state_and_page_image(self) -> None:
        source = self.register_text_pdf(unfinished_boundary=False)
        ingest_pdf(self.project, source["source_id"])
        server = build_server(self.project, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            html = urlopen(base + "/", timeout=5).read().decode("utf-8")
            self.assertIn("史学研究工作台", html)
            snapshot = json.loads(urlopen(base + "/api/snapshot", timeout=5).read())
            self.assertEqual(snapshot["sources"][0]["source_id"], source["source_id"])
            page_id = source_view(self.project, source["source_id"])["pages"][0]["page_id"]
            image = urlopen(base + f"/api/page-image?id={page_id}", timeout=5).read()
            self.assertTrue(image.startswith(b"\x89PNG"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
