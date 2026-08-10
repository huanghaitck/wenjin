from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz

from research_workbench.db import database_path
from research_workbench.pdf_ingestion import ingest_pdf
from research_workbench.service import (
    accept_ocr_proposal,
    create_ocr_proposal,
    initialize_project,
    list_blocks,
    project_status,
    record_ocr_proposal,
    register_source,
    reject_ocr_proposal,
    source_view,
    submit_page_repair,
)
from research_workbench.vision import OcrSettings, capability, normalize_ocr_content, request_page_ocr


def make_image_only_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=360, height=480)
    page.draw_rect(fitz.Rect(35, 50, 325, 430), color=(0, 0, 0), fill=(0.94, 0.92, 0.86))
    page.draw_line(fitz.Point(80, 100), fitz.Point(280, 100), color=(0, 0, 0), width=2)
    document.save(path)
    document.close()


class FakeResponse:
    def __init__(self, value: dict) -> None:
        self.value = value

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.value).encode("utf-8")


class M3OcrProposalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        initialize_project(self.project, "M3 test project")
        source_file = self.root / "scan.pdf"
        make_image_only_pdf(source_file)
        self.source = register_source(self.project, source_file, "Scan")
        ingest_pdf(self.project, self.source["source_id"])
        self.page = source_view(self.project, self.source["source_id"])["pages"][0]
        self.settings = OcrSettings(provider="mock", model="mock-vision", mock_text="Machine text")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def proposal(self) -> dict:
        return record_ocr_proposal(
            self.project,
            self.page["page_id"],
            self.settings,
            {"id": "mock-response", "content": "Machine text"},
            {
                "printed_page": None,
                "blocks": [{"order": 1, "type": "paragraph", "text": "Machine text", "region": None}],
                "uncertain_characters": [],
                "warnings": [],
            },
        )

    def test_schema_v1_project_migrates_on_open(self) -> None:
        connection = sqlite3.connect(database_path(self.project))
        try:
            connection.execute("DROP TABLE ocr_proposals")
            connection.execute("DELETE FROM schema_meta WHERE version >= 2")
            connection.commit()
        finally:
            connection.close()
        project_status(self.project)
        connection = sqlite3.connect(database_path(self.project))
        try:
            version = connection.execute("SELECT MAX(version) FROM schema_meta").fetchone()[0]
            table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'ocr_proposals'"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(version, 5)
        self.assertIsNotNone(table)

    def test_pending_proposal_preserves_blocked_source_and_provenance(self) -> None:
        proposal = self.proposal()
        status = project_status(self.project)
        self.assertEqual(status["pending_ocr_proposal_count"], 1)
        self.assertEqual(status["sources"][0]["use_state"], "blocked")
        self.assertEqual(list_blocks(self.project, self.source["source_id"]), [])
        saved = source_view(self.project, self.source["source_id"])["ocr_proposals"][0]
        self.assertEqual(saved["proposal_id"], proposal["proposal_id"])
        self.assertEqual(saved["status"], "pending")
        self.assertEqual(len(saved["source_sha256"]), 64)
        self.assertEqual(len(saved["image_sha256"]), 64)

    def test_human_acceptance_uses_edited_text_and_existing_repair_gate(self) -> None:
        proposal = self.proposal()
        result = accept_ocr_proposal(
            self.project,
            proposal["proposal_id"],
            {"blocks": [{"order": 1, "type": "paragraph", "text": "Human-corrected transcription."}]},
            "reviewer",
            "Compared every line with the rendered source page.",
        )
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(project_status(self.project)["sources"][0]["use_state"], "research_usable")
        self.assertEqual(
            list_blocks(self.project, self.source["source_id"])[0]["effective_text"],
            "Human-corrected transcription.",
        )
        saved = source_view(self.project, self.source["source_id"])["ocr_proposals"][0]
        self.assertEqual(saved["status"], "accepted")
        self.assertEqual(saved["repair_id"], result["repair_id"])
        with self.assertRaises(ValueError):
            accept_ocr_proposal(
                self.project,
                proposal["proposal_id"],
                {"blocks": [{"order": 1, "type": "paragraph", "text": "Second acceptance"}]},
                "reviewer",
                "Should be rejected.",
            )

    def test_rejection_keeps_page_anomaly_open(self) -> None:
        proposal = self.proposal()
        reject_ocr_proposal(self.project, proposal["proposal_id"], "reviewer", "The text was inaccurate.")
        view = source_view(self.project, self.source["source_id"])
        self.assertEqual(view["ocr_proposals"][0]["status"], "rejected")
        self.assertTrue(any(item["status"] == "open" and item["scope_type"] == "page" for item in view["anomalies"]))
        self.assertEqual(view["source"]["use_state"], "blocked")

    def test_capability_never_returns_api_key(self) -> None:
        state = capability(OcrSettings(
            provider="openai_compatible",
            model="glm-4.6v-flash",
            base_url="https://example.invalid/v1",
            api_key="not-for-output",
        ))
        self.assertTrue(state["available"])
        self.assertNotIn("not-for-output", json.dumps(state))
        self.assertNotIn("api_key", state)

    def test_boolean_printed_page_is_quarantined(self) -> None:
        normalized = normalize_ocr_content(json.dumps({
            "printed_page": True,
            "blocks": [{"text": "Visible text"}],
        }))
        self.assertIsNone(normalized["printed_page"])
        self.assertIn("invalid_printed_page", normalized["warnings"])
        self.assertIn("block_regions_missing", normalized["warnings"])

    def test_clean_page_is_rejected_before_a_model_call(self) -> None:
        anomaly = next(
            item for item in source_view(self.project, self.source["source_id"])["anomalies"]
            if item["scope_type"] == "page"
        )
        submit_page_repair(
            self.project,
            anomaly["anomaly_id"],
            {"blocks": [{"order": 1, "type": "paragraph", "text": "Human transcription"}]},
            "reviewer",
            "Verified against the page.",
        )
        with patch("research_workbench.service.request_page_ocr") as mocked:
            with self.assertRaises(ValueError):
                create_ocr_proposal(self.project, self.page["page_id"], self.settings)
        mocked.assert_not_called()

    def test_accepting_one_comparator_supersedes_other_pending_proposals(self) -> None:
        accepted = self.proposal()
        other = self.proposal()
        result = accept_ocr_proposal(
            self.project,
            accepted["proposal_id"],
            {"blocks": [{"order": 1, "type": "paragraph", "text": "Verified text"}]},
            "reviewer",
            "Compared with the rendered page.",
        )
        self.assertEqual(result["superseded_proposals"], 1)
        proposals = {
            item["proposal_id"]: item
            for item in source_view(self.project, self.source["source_id"])["ocr_proposals"]
        }
        self.assertEqual(proposals[accepted["proposal_id"]]["status"], "accepted")
        self.assertEqual(proposals[other["proposal_id"]]["status"], "superseded")

    def test_openai_and_ollama_requests_are_explicit_and_normalized(self) -> None:
        image = self.root / "page.png"
        image.write_bytes(b"fake-png")
        content = json.dumps({"blocks": [{"order": 9, "type": "paragraph", "text": "Visible text"}]})
        openai_raw = {"choices": [{"message": {"content": content}}]}
        openai = OcrSettings(
            provider="openai_compatible",
            model="glm-4.6v-flash",
            base_url="https://example.invalid/v1",
            api_key="secret",
        )
        with patch("research_workbench.vision.urlopen", return_value=FakeResponse(openai_raw)) as mocked:
            _, normalized = request_page_ocr(image, openai)
            request = mocked.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.invalid/v1/chat/completions")
        self.assertEqual(json.loads(request.data)["model"], "glm-4.6v-flash")
        self.assertEqual(normalized["blocks"][0]["order"], 1)

        ollama_raw = {"message": {"content": content}}
        ollama = OcrSettings(
            provider="ollama",
            model="qwen3-vl:4b-instruct-q4_K_M",
            base_url="http://127.0.0.1:11434",
        )
        with patch("research_workbench.vision.urlopen", return_value=FakeResponse(ollama_raw)) as mocked:
            request_page_ocr(image, ollama)
            request = mocked.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(payload["model"], "qwen3-vl:4b-instruct-q4_K_M")
        self.assertFalse(payload["stream"])


if __name__ == "__main__":
    unittest.main()
