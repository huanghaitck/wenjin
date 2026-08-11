from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

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
    revise_page,
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
    def test_vision_capability_declares_single_concurrency(self) -> None:
        state = capability(OcrSettings(provider="mock", model="mock-vision"))
        self.assertEqual(state["max_concurrency"], 1)

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
        self.assertEqual(version, 13)
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

    def test_collapsed_page_text_is_split_into_reviewable_paragraphs(self) -> None:
        normalized = normalize_ocr_content(json.dumps({
            "printed_page": True,
            "blocks": [{"type": "paragraph", "text": "651\nFirst paragraph.\n\nSecond paragraph."}],
        }))
        self.assertEqual(normalized["printed_page"], "651")
        self.assertEqual(
            [block["text"] for block in normalized["blocks"]],
            ["First paragraph.", "Second paragraph."],
        )
        self.assertIn("printed_page_recovered_from_leading_line", normalized["warnings"])
        self.assertIn("single_block_split_on_blank_lines", normalized["warnings"])

    def test_truncated_json_is_not_downgraded_to_a_text_proposal(self) -> None:
        with self.assertRaisesRegex(ValueError, "incomplete or invalid JSON"):
            normalize_ocr_content('{"printed_page": 659, "blocks": [{"text": "truncated"}')

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

    def test_unverified_page_without_anomaly_can_request_model_assisted_review(self) -> None:
        connection = sqlite3.connect(database_path(self.project))
        try:
            connection.execute("UPDATE anomalies SET status = 'resolved', resolved_at = 'test'")
            connection.execute(
                "UPDATE pages SET verification_state = 'machine_parsed', use_state = 'research_usable'"
            )
            connection.commit()
        finally:
            connection.close()
        response = ({"id": "mock-response"}, {
            "printed_page": None,
            "blocks": [{"order": 1, "type": "paragraph", "text": "Proposed text", "region": None}],
            "uncertain_characters": [],
            "warnings": [],
        })
        with patch("research_workbench.service.request_page_ocr", return_value=response) as requested:
            proposal = create_ocr_proposal(self.project, self.page["page_id"], self.settings)
        requested.assert_called_once()
        proposal_image = requested.call_args.args[0]
        pixmap = fitz.Pixmap(proposal_image)
        self.assertEqual((pixmap.width, pixmap.height), (1440, 1920))
        self.assertEqual(proposal["status"], "pending")
        view = source_view(self.project, self.source["source_id"])
        generated = [
            item for item in view["anomalies"]
            if item["scope_type"] == "page" and item["status"] == "open"
        ]
        self.assertEqual(len(generated), 1)
        self.assertEqual(generated[0]["target_id"], self.page["page_id"])
        self.assertEqual(generated[0]["category"], "content")

    def test_pending_proposal_editor_can_add_and_remove_blocks(self) -> None:
        script = (
            Path(__file__).parents[1] / "src" / "research_workbench" / "web_assets" / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn("remove.textContent = '删除此块'", script)
        self.assertIn("addBlock.textContent = '新增一块'", script)
        self.assertIn("order: index + 1", script)

    def test_page_anomaly_keeps_local_block_repair_entry(self) -> None:
        script = (
            Path(__file__).parents[1] / "src" / "research_workbench" / "web_assets" / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn("correct.textContent = pageAnomaly ? '保存这一小段修正' : '保存这段修正'", script)
        self.assertIn("if (!pageAnomaly) actions.append(button)", script)

    def test_human_repaired_page_can_be_structurally_revised_again(self) -> None:
        anomaly = next(
            item for item in source_view(self.project, self.source["source_id"])["anomalies"]
            if item["scope_type"] == "page"
        )
        submit_page_repair(
            self.project,
            anomaly["anomaly_id"],
            {"blocks": [{"order": 1, "type": "paragraph", "text": "Wrong merged text"}]},
            "reviewer",
            "First review.",
        )
        revised = revise_page(
            self.project,
            self.page["page_id"],
            {"blocks": [
                {"order": 1, "type": "paragraph", "text": "Correct first paragraph."},
                {"order": 2, "type": "heading", "text": "Visible heading"},
            ]},
            "reviewer",
            "Second review found a structural omission.",
        )
        self.assertEqual(revised["target_id"], self.page["page_id"])
        active = list_blocks(self.project, self.source["source_id"])
        self.assertEqual(
            [(item["block_type"], item["effective_text"]) for item in active],
            [("paragraph", "Correct first paragraph."), ("heading", "Visible heading")],
        )

    def test_page_number_save_does_not_reload_pending_edits(self) -> None:
        script = (
            Path(__file__).parents[1] / "src" / "research_workbench" / "web_assets" / "app.js"
        ).read_text(encoding="utf-8")
        handler = script.split("$('savePrintedPage').onclick", 1)[1].split("function renderSettings", 1)[0]
        self.assertNotIn("loadSource", handler)
        self.assertIn("page.printed_page = $('printedPage').value.trim()", handler)

    def test_review_reason_clears_when_source_or_page_changes(self) -> None:
        script = (
            Path(__file__).parents[1] / "src" / "research_workbench" / "web_assets" / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn("function clearReviewReason()", script)
        self.assertIn("previousSourceId !== state.view.source?.source_id", script)
        self.assertIn("previousPageId !== currentPage()?.page_id", script)
        self.assertIn("state.pageIndex = index; clearReviewReason(); render();", script)

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
            _, normalized = request_page_ocr(image, openai, {
                "printed_page": "659",
                "blocks": [{"order": 1, "type": "paragraph", "text": "старый текстъ"}],
            })
            request = mocked.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.invalid/v1/chat/completions")
        openai_payload = json.loads(request.data)
        self.assertEqual(openai_payload["model"], "glm-4.6v-flash")
        self.assertEqual(openai_payload["thinking"], {"type": "disabled"})
        self.assertEqual(openai_payload["max_tokens"], 4096)
        self.assertEqual(openai_payload["messages"][0]["content"][0]["type"], "image_url")
        prompt = openai_payload["messages"][0]["content"][1]["text"]
        self.assertIn("старый текстъ", prompt)
        self.assertIn("Never modernize spelling", prompt)
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

    def test_provider_http_error_exposes_only_bounded_error_fields(self) -> None:
        image = self.root / "page.png"
        image.write_bytes(b"fake-png")
        settings = OcrSettings(
            provider="openai_compatible", model="glm-4.6v",
            base_url="https://example.invalid/v1", api_key="secret",
        )
        body = BytesIO(json.dumps({
            "error": {"code": "1305", "message": "model is busy", "request": "must stay hidden"}
        }).encode("utf-8"))
        failure = HTTPError(settings.base_url, 429, "Too Many Requests", {}, body)
        with patch("research_workbench.vision.urlopen", side_effect=failure):
            with self.assertRaisesRegex(RuntimeError, r"HTTP 429: 1305 · model is busy") as raised:
                request_page_ocr(image, settings)
        self.assertNotIn("must stay hidden", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
