from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

from research_workbench.agent_runtime import (
    ModelProfile,
    _model_action,
    _parse_action,
    _search_source_blocks,
    assign_model,
    create_thread,
    decide_approval,
    list_threads,
    send_message,
    sync_model_profiles,
    thread_view,
)
from research_workbench.db import database_path
from research_workbench.service import import_structure, initialize_project, register_source
from research_workbench.web import build_server


FIXTURE = Path(__file__).parent / "fixtures" / "m1_structure.json"


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class M4AgentWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.project = root / "project"
        initialize_project(self.project, "M4 test project")
        original = root / "source.txt"
        original.write_text("immutable original", encoding="utf-8")
        source = register_source(self.project, original, "Test source")
        import_structure(self.project, source["source_id"], FIXTURE)
        self.thread = create_thread(self.project, "来源检查")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_mock_run_pauses_for_editable_note_approval_and_recovers(self) -> None:
        result = send_message(self.project, self.thread["thread_id"], "查看来源和异常并保存研究札记")
        run = result["runs"][0]
        self.assertEqual(run["status"], "WAITING_FOR_APPROVAL")
        self.assertEqual(
            [call["tool_name"] for call in run["tool_calls"]],
            ["project.status", "source.list", "source.page", "research.state", "authoring.state", "save_research_note"],
        )
        approval = run["approvals"][0]
        self.assertEqual(approval["status"], "pending")
        self.assertFalse((self.project / "research" / "notes" / f"{approval['approval_id']}.md").exists())

        recovered = thread_view(self.project, self.thread["thread_id"])
        self.assertEqual(recovered["runs"][0]["status"], "WAITING_FOR_APPROVAL")
        completed = decide_approval(
            self.project,
            approval["approval_id"],
            True,
            "professor",
            "Checked against the workbench state",
            {"title": "人工修订标题", "content": "人工修订后的札记正文。"},
        )
        self.assertEqual(completed["runs"][0]["status"], "COMPLETED")
        note = self.project / "research" / "notes" / f"{approval['approval_id']}.md"
        self.assertIn("人工修订后的札记正文", note.read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            decide_approval(self.project, approval["approval_id"], True, "professor", "repeat")

    def test_rejection_writes_no_note_and_keeps_decision(self) -> None:
        result = send_message(self.project, self.thread["thread_id"], "检查后先提出札记")
        approval = result["runs"][0]["approvals"][0]
        rejected = decide_approval(
            self.project, approval["approval_id"], False, "professor", "证据范围还不清楚"
        )
        self.assertEqual(rejected["runs"][0]["status"], "COMPLETED")
        self.assertEqual(rejected["runs"][0]["approvals"][0]["status"], "rejected")
        self.assertFalse((self.project / "research" / "notes" / f"{approval['approval_id']}.md").exists())
        self.assertIn("未写入项目", rejected["messages"][-1]["content"]["text"])

    def test_profiles_and_assignment_never_persist_api_key(self) -> None:
        secret = "not-for-database"
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible",
            "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://example.invalid/v1",
            "HRW_AGENT_API_KEY": secret,
        }
        with patch.dict(os.environ, environment, clear=False):
            profiles = sync_model_profiles(self.project)
            self.assertIn("environment-main", {item["profile_id"] for item in profiles})
            assign_model(self.project, "environment-main")
        with patch.dict(os.environ, {}, clear=True):
            unavailable = {item["profile_id"]: item for item in sync_model_profiles(self.project)}
        self.assertEqual(unavailable["environment-main"]["status"], "unavailable")
        raw = database_path(self.project).read_bytes()
        self.assertNotIn(secret.encode("utf-8"), raw)
        connection = sqlite3.connect(database_path(self.project))
        try:
            assignment = connection.execute(
                "SELECT profile_id FROM model_assignments WHERE role = 'main_reasoning'"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(assignment, "environment-main")

    def test_thread_list_reports_latest_run(self) -> None:
        self.assertEqual(list_threads(self.project)[0]["message_count"], 0)
        send_message(self.project, self.thread["thread_id"], "形成待审札记")
        summary = list_threads(self.project)[0]
        self.assertEqual(summary["message_count"], 1)
        self.assertEqual(summary["latest_run_status"], "WAITING_FOR_APPROVAL")

    def test_schema_v2_project_migrates_on_open(self) -> None:
        connection = sqlite3.connect(database_path(self.project))
        try:
            connection.execute("DROP TABLE threads")
            connection.execute("DELETE FROM schema_meta WHERE version = 3")
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(list_threads(self.project), [])
        connection = sqlite3.connect(database_path(self.project))
        try:
            version = connection.execute("SELECT MAX(version) FROM schema_meta").fetchone()[0]
            table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'threads'"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(version, 7)
        self.assertIsNotNone(table)

    def test_openai_and_ollama_text_requests_are_explicit(self) -> None:
        requests: list[object] = []

        def respond(request: object, timeout: float, **_: object) -> FakeResponse:
            requests.append(request)
            if str(getattr(request, "full_url")).endswith("/api/chat"):
                return FakeResponse({"message": {"content": '{"type":"final","content":"ok"}'}})
            return FakeResponse({"choices": [{"message": {"content": '{"type":"final","content":"ok"}'}}]})

        openai = ModelProfile(
            "openai-test", "openai_compatible", "remote-model", "https://models.invalid/v1",
            ("text", "tool_calling"), "env:HRW_AGENT_API_KEY", "available", "secret", 5,
        )
        ollama = ModelProfile(
            "ollama-test", "ollama", "local-model", "http://127.0.0.1:11434",
            ("text", "tool_calling"), "none", "available", "", 5,
        )
        with patch("research_workbench.agent_runtime.urlopen", side_effect=respond):
            self.assertEqual(_model_action(openai, "check", [])["type"], "final")
            self.assertEqual(_model_action(ollama, "check", [])["type"], "final")
        self.assertTrue(str(getattr(requests[0], "full_url")).endswith("/chat/completions"))
        self.assertEqual(getattr(requests[0], "headers")["Authorization"], "Bearer secret")
        openai_payload = json.loads(getattr(requests[0], "data").decode("utf-8"))
        self.assertIn("Reserve one model turn", openai_payload["messages"][1]["content"])
        ollama_payload = json.loads(getattr(requests[1], "data").decode("utf-8"))
        self.assertFalse(ollama_payload["stream"])
        self.assertEqual(ollama_payload["format"], "json")

    def test_parser_uses_first_action_when_provider_batches_json_objects(self) -> None:
        action = _parse_action(
            '{"type":"tool_call","tool":"project.status","arguments":{}}\n'
            '{"type":"tool_call","tool":"source.list","arguments":{}}'
        )
        self.assertEqual(action["tool"], "project.status")

    def test_parser_treats_plain_provider_text_as_safe_final_answer(self) -> None:
        action = _parse_action("候选页已定位；请人工核对原页。")
        self.assertEqual(action, {"type": "final", "content": "候选页已定位；请人工核对原页。"})

    def test_source_search_returns_page_and_block_anchors(self) -> None:
        results = _search_source_blocks(self.project, "page boundary")
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["page_id"].endswith(":P1"))
        self.assertTrue(results[0]["block_id"].endswith(":B2"))

    def test_source_search_splits_multilingual_alternatives(self) -> None:
        results = _search_source_blocks(self.project, "station/page boundary")
        self.assertEqual(len(results), 2)
        self.assertEqual({query for item in results for query in item["matched_queries"]}, {"station", "page boundary"})

    def test_source_search_does_not_let_first_variant_consume_limit(self) -> None:
        results = _search_source_blocks(self.project, "The/following", limit=2)
        self.assertEqual(len(results), 2)
        self.assertIn("following", {query for item in results for query in item["matched_queries"]})

    def test_agent_prompt_requires_researcher_readable_final_text(self) -> None:
        from research_workbench.agent_runtime import SYSTEM_PROMPT

        self.assertIn("Do not return a Python repr", SYSTEM_PROMPT)

    def test_loopback_api_exposes_thread_run_and_approval(self) -> None:
        server = build_server(self.project, port=0)
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
            self.assertEqual(snapshot["model_profiles"][0]["profile_id"], "builtin-mock")
            created = post("/api/thread/create", {"title": "API thread"})
            result = post(
                "/api/agent/message",
                {"thread_id": created["thread_id"], "content": "检查项目并提出札记"},
            )
            approval = result["runs"][0]["approvals"][0]
            decided = post(
                "/api/approval/decide",
                {
                    "approval_id": approval["approval_id"],
                    "approved": False,
                    "reviewer": "professor",
                    "reason": "API review",
                },
            )
            self.assertEqual(decided["runs"][0]["status"], "COMPLETED")
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
