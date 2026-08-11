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
    EmptyModelContentError,
    ModelActionFormatError,
    ModelProfile,
    SYSTEM_PROMPT,
    _model_action,
    _looks_like_internal_tool_transcript,
    _parse_action,
    _post_json,
    _read_page,
    _search_source_blocks,
    _thread_history,
    assign_model,
    create_thread,
    decide_approval,
    list_threads,
    recover_interrupted_runs,
    send_message,
    sync_model_profiles,
    thread_view,
)
from research_workbench.db import database_path
from research_workbench.research_design import create_design_draft, decide_design
from research_workbench.service import import_structure, initialize_project, register_source, verify_block
from research_workbench.service import list_sources, source_view
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

    def test_interrupted_running_run_is_failed_on_recovery(self) -> None:
        with patch("research_workbench.agent_runtime._mock_action", side_effect=RuntimeError("stop")):
            with self.assertRaises(RuntimeError):
                send_message(self.project, self.thread["thread_id"], "会失败")
        connection = sqlite3.connect(database_path(self.project))
        try:
            connection.execute("UPDATE runs SET status = 'RUNNING', error = NULL, completed_at = NULL")
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(recover_interrupted_runs(self.project), 1)
        recovered = thread_view(self.project, self.thread["thread_id"])["runs"][0]
        self.assertEqual(recovered["status"], "FAILED")
        self.assertIn("application restart", recovered["error"])

    def test_model_can_recover_from_a_bad_page_locator(self) -> None:
        source_id = list_sources(self.project)[0]["source_id"]
        valid_page_id = f"{source_id}:P1"
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://example.invalid/v1", "HRW_AGENT_API_KEY": "secret",
        }
        actions = iter([
            {"type": "tool_call", "tool": "source.page", "arguments": {"page_id": "P0249"}},
            {"type": "tool_call", "tool": "source.page", "arguments": {"page_id": valid_page_id}},
            {"type": "final", "content": "已根据工具错误改用项目中的精确页标识。"},
        ])
        observations: list[list[dict[str, object]]] = []

        def next_action(*args: object) -> dict[str, object]:
            observations.append(list(args[2]))
            return next(actions)

        with patch.dict(os.environ, environment, clear=False):
            sync_model_profiles(self.project)
            assign_model(self.project, "environment-main")
            with patch("research_workbench.agent_runtime._model_action", side_effect=next_action):
                result = send_message(self.project, self.thread["thread_id"], "读取第一页")

        run = result["runs"][0]
        self.assertEqual(run["status"], "COMPLETED")
        self.assertEqual([call["status"] for call in run["tool_calls"]], ["FAILED", "COMPLETED"])
        self.assertIn("unknown page", observations[1][0]["error"])
        self.assertIn("tool_failed", [event["event_type"] for event in run["events"]])
        self.assertNotIn("run_failed", [event["event_type"] for event in run["events"]])

    def test_model_can_retry_a_malformed_action_without_restarting_the_run(self) -> None:
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://example.invalid/v1", "HRW_AGENT_API_KEY": "secret",
        }
        actions: list[object] = [
            ModelActionFormatError("Expecting ',' delimiter"),
            {"type": "final", "content": "已用较短的合法动作完成重试。"},
        ]
        observations: list[list[dict[str, object]]] = []

        def next_action(*args: object) -> dict[str, object]:
            observations.append(list(args[2]))
            action = actions.pop(0)
            if isinstance(action, Exception):
                raise action
            return action

        with patch.dict(os.environ, environment, clear=False):
            sync_model_profiles(self.project)
            assign_model(self.project, "environment-main")
            with patch("research_workbench.agent_runtime._model_action", side_effect=next_action):
                result = send_message(self.project, self.thread["thread_id"], "完成一个长动作")

        run = result["runs"][0]
        self.assertEqual(run["status"], "COMPLETED")
        self.assertIn("invalid model action", observations[1][0]["error"])
        self.assertIn("model_action_invalid", [event["event_type"] for event in run["events"]])
        self.assertNotIn("run_failed", [event["event_type"] for event in run["events"]])

    def test_repeated_malformed_actions_fail_after_one_retry(self) -> None:
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://example.invalid/v1", "HRW_AGENT_API_KEY": "secret",
        }

        with patch.dict(os.environ, environment, clear=False):
            sync_model_profiles(self.project)
            assign_model(self.project, "environment-main")
            with patch(
                "research_workbench.agent_runtime._model_action",
                side_effect=ModelActionFormatError("Expecting ',' delimiter"),
            ) as model_action:
                with self.assertRaisesRegex(RuntimeError, "invalid model action"):
                    send_message(self.project, self.thread["thread_id"], "完成一个长动作")

        self.assertEqual(model_action.call_count, 2)
        run = thread_view(self.project, self.thread["thread_id"])["runs"][0]
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual(
            [event["event_type"] for event in run["events"]].count("model_action_invalid"),
            2,
        )
        self.assertIn("run_failed", [event["event_type"] for event in run["events"]])

    def test_event_batch_can_mutate_only_once_per_run(self) -> None:
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://example.invalid/v1", "HRW_AGENT_API_KEY": "secret",
        }
        proposal = {
            "type": "tool_call", "tool": "research_event.propose_batch",
            "arguments": {"events": [{"case_id": "CASE_1"}]},
        }
        actions = iter([proposal, proposal, {"type": "final", "content": "已提交一次并停止。"}])

        with patch.dict(os.environ, environment, clear=False):
            sync_model_profiles(self.project)
            assign_model(self.project, "environment-main")
            with (
                patch("research_workbench.agent_runtime._model_action", side_effect=lambda *args: next(actions)),
                patch(
                    "research_workbench.agent_runtime.create_event_candidates",
                    return_value=[{"event_id": "EVT_1"}],
                ) as create_candidates,
            ):
                result = send_message(self.project, self.thread["thread_id"], "只提交一批事件")

        run = result["runs"][0]
        event_calls = [
            call for call in run["tool_calls"]
            if call["tool_name"] == "research_event.propose_batch"
        ]
        self.assertEqual([call["status"] for call in event_calls], ["COMPLETED"])
        self.assertIn("tool_retry_blocked", [event["event_type"] for event in run["events"]])
        create_candidates.assert_called_once()

    def test_event_batch_validation_failure_cannot_be_retried_in_same_run(self) -> None:
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://example.invalid/v1", "HRW_AGENT_API_KEY": "secret",
        }
        actions = iter([
            {
                "type": "tool_call", "tool": "research_event.propose_batch",
                "arguments": {"events": {}},
            },
            {
                "type": "tool_call", "tool": "research_event.propose_batch",
                "arguments": {"events": [{"case_id": "CASE_1"}]},
            },
            {"type": "final", "content": "首次提交校验失败；遵守一次尝试约束，没有重试。"},
        ])

        with patch.dict(os.environ, environment, clear=False):
            sync_model_profiles(self.project)
            assign_model(self.project, "environment-main")
            with (
                patch("research_workbench.agent_runtime._model_action", side_effect=lambda *args: next(actions)),
                patch("research_workbench.agent_runtime.create_event_candidates") as create_candidates,
            ):
                result = send_message(
                    self.project, self.thread["thread_id"],
                    "调用 research_event.propose_batch 一次；失败也不要重试。",
                )

        run = result["runs"][0]
        self.assertEqual(run["status"], "COMPLETED")
        event_calls = [
            call for call in run["tool_calls"]
            if call["tool_name"] == "research_event.propose_batch"
        ]
        self.assertEqual([call["status"] for call in event_calls], ["FAILED"])
        self.assertIn("tool_retry_blocked", [event["event_type"] for event in run["events"]])
        create_candidates.assert_not_called()

    def test_explicit_required_tool_prevents_a_premature_final_answer(self) -> None:
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://example.invalid/v1", "HRW_AGENT_API_KEY": "secret",
        }
        actions = iter([
            {"type": "final", "content": "下一步继续读取并提交。"},
            {
                "type": "tool_call", "tool": "research_event.propose_batch",
                "arguments": {"events": [{"case_id": "CASE_1"}]},
            },
            {"type": "final", "content": "已按完成契约提交一次。"},
        ])
        observations: list[list[dict[str, object]]] = []

        def next_action(*args: object) -> dict[str, object]:
            observations.append(list(args[2]))
            return next(actions)

        with patch.dict(os.environ, environment, clear=False):
            sync_model_profiles(self.project)
            assign_model(self.project, "environment-main")
            with (
                patch("research_workbench.agent_runtime._model_action", side_effect=next_action),
                patch(
                    "research_workbench.agent_runtime.create_event_candidates",
                    return_value=[{"event_id": "EVT_1"}],
                ) as create_candidates,
            ):
                result = send_message(
                    self.project, self.thread["thread_id"],
                    "恰好成功调用一次 research_event.propose_batch，提交后结束。",
                )

        run = result["runs"][0]
        self.assertEqual(run["status"], "COMPLETED")
        self.assertIn("required_tool_missing", [event["event_type"] for event in run["events"]])
        self.assertIn("explicitly required", observations[1][0]["error"])
        create_candidates.assert_called_once()

    def test_natural_required_tool_order_prevents_a_premature_final_answer(self) -> None:
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://example.invalid/v1", "HRW_AGENT_API_KEY": "secret",
        }
        actions = iter([
            {"type": "final", "content": "读取物理页239以重新核对。"},
            {
                "type": "tool_call", "tool": "research_event.propose_batch",
                "arguments": {"events": [{"case_id": "CASE_1"}]},
            },
            {"type": "final", "content": "已重新提交一次。"},
        ])

        with patch.dict(os.environ, environment, clear=False):
            sync_model_profiles(self.project)
            assign_model(self.project, "environment-main")
            with (
                patch("research_workbench.agent_runtime._model_action", side_effect=lambda *args: next(actions)),
                patch(
                    "research_workbench.agent_runtime.create_event_candidates",
                    return_value=[{"event_id": "EVT_1"}],
                ) as create_candidates,
            ):
                result = send_message(
                    self.project, self.thread["thread_id"],
                    "请重新读取来源，再调用 research_event.propose_batch 一次。",
                )

        run = result["runs"][0]
        self.assertEqual(run["status"], "COMPLETED")
        self.assertIn("required_tool_missing", [event["event_type"] for event in run["events"]])
        create_candidates.assert_called_once()

    def test_internal_tool_transcript_is_rejected_before_natural_completion(self) -> None:
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://example.invalid/v1", "HRW_AGENT_API_KEY": "secret",
        }
        actions = iter([
            {"type": "final", "content": 'TOOL_RESULT {"tool":"source.page","result":{}}'},
            {"type": "final", "content": "已定位实际出发页；仍需人工核对日期与跨页关系。"},
        ])
        observations: list[list[dict[str, object]]] = []

        def next_action(*args: object) -> dict[str, object]:
            observations.append(list(args[2]))
            return next(actions)

        with patch.dict(os.environ, environment, clear=False):
            sync_model_profiles(self.project)
            assign_model(self.project, "environment-main")
            with patch("research_workbench.agent_runtime._model_action", side_effect=next_action):
                result = send_message(self.project, self.thread["thread_id"], "定位实际出发页")

        run = result["runs"][0]
        self.assertEqual(run["status"], "COMPLETED")
        self.assertIn("model_action_invalid", [event["event_type"] for event in run["events"]])
        self.assertIn("not a researcher-readable final answer", observations[1][-1]["error"])
        self.assertEqual(
            result["messages"][-1]["content"]["text"],
            "已定位实际出发页；仍需人工核对日期与跨页关系。",
        )

    def test_internal_tool_transcript_detector_does_not_match_normal_research_prose(self) -> None:
        self.assertTrue(_looks_like_internal_tool_transcript('TOOL_RESULT {"result": {}}'))
        self.assertFalse(_looks_like_internal_tool_transcript("已依据工具返回结果完成有界定位。"))

    def test_bounded_history_omits_stored_internal_tool_transcripts(self) -> None:
        connection = sqlite3.connect(database_path(self.project))
        try:
            connection.execute(
                "INSERT INTO messages(message_id, thread_id, role, content_json, created_at) "
                "VALUES ('MSG_internal', ?, 'assistant', ?, '2026-08-11T00:00:00+00:00')",
                (self.thread["thread_id"], json.dumps({"text": 'TOOL_RESULT {"result": {}}'})),
            )
            connection.commit()
        finally:
            connection.close()

        history, receipt = _thread_history(self.project, self.thread["thread_id"])
        self.assertEqual(history, [])
        self.assertTrue(receipt["truncated"])

    def test_model_retries_empty_content_once_without_restarting_the_run(self) -> None:
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://example.invalid/v1", "HRW_AGENT_API_KEY": "secret",
        }
        actions: list[object] = [
            EmptyModelContentError("agent provider returned empty content"),
            {"type": "final", "content": "空响应后已在同一运行恢复。"},
        ]
        observations: list[list[dict[str, object]]] = []

        def next_action(*args: object) -> dict[str, object]:
            observations.append(list(args[2]))
            action = actions.pop(0)
            if isinstance(action, Exception):
                raise action
            return action

        with patch.dict(os.environ, environment, clear=False):
            sync_model_profiles(self.project)
            assign_model(self.project, "environment-main")
            with patch("research_workbench.agent_runtime._model_action", side_effect=next_action):
                result = send_message(self.project, self.thread["thread_id"], "完成一次来源定位")

        run = result["runs"][0]
        self.assertEqual(run["status"], "COMPLETED")
        self.assertIn("Retry the same action once", observations[1][0]["error"])
        self.assertIn("model_response_empty", [event["event_type"] for event in run["events"]])
        self.assertNotIn("run_failed", [event["event_type"] for event in run["events"]])

    def test_independent_planning_hides_baseline_and_guided_mode_injects_only_shared_design(self) -> None:
        baseline = create_design_draft(
            self.project, "隐藏基线", "五年核心窗口秘密", "researcher_baseline", "imported", "Professor"
        )
        decide_design(self.project, baseline["design_id"], True, "Professor", "旧讨论恢复")
        shared = create_design_draft(
            self.project, "共同计划", "共同执行边界", "shared_design", "manual", "Professor"
        )
        decide_design(self.project, shared["design_id"], True, "Professor", "共同批准")
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://example.invalid/v1", "HRW_AGENT_API_KEY": "secret",
        }
        contexts: list[str] = []
        histories: list[list[dict[str, str]]] = []

        connection = sqlite3.connect(database_path(self.project))
        try:
            connection.execute(
                "INSERT INTO messages(message_id, thread_id, role, content_json, created_at) VALUES (?, ?, 'user', ?, ?)",
                ("MSG_seed", self.thread["thread_id"], json.dumps({"text": "旧线程讨论"}), "2026-01-01"),
            )
            connection.commit()
        finally:
            connection.close()

        def final(*args: object) -> dict[str, str]:
            contexts.append(str(args[4]))
            histories.append(list(args[5]))
            return {"type": "final", "content": "ok"}

        with patch.dict(os.environ, environment, clear=False):
            sync_model_profiles(self.project)
            assign_model(self.project, "environment-main")
            with patch("research_workbench.agent_runtime._model_action", side_effect=final):
                send_message(self.project, self.thread["thread_id"], "独立想方案", planning_mode="independent_planning")
                send_message(self.project, self.thread["thread_id"], "按计划推进", planning_mode="guided_execution")
        self.assertIn("intentionally withheld", contexts[0])
        self.assertNotIn("五年核心窗口秘密", contexts[0])
        self.assertNotIn("共同执行边界", contexts[0])
        self.assertEqual(histories[0], [])
        self.assertIn("共同执行边界", contexts[1])
        self.assertNotIn("五年核心窗口秘密", contexts[1])
        self.assertEqual(histories[1][0]["content"], "旧线程讨论")
        self.assertEqual(histories[1][-2]["content"], "独立想方案")
        self.assertEqual(histories[1][-1]["content"], "ok")
        guided = thread_view(self.project, self.thread["thread_id"])["runs"][0]
        self.assertEqual(guided["model_snapshot"]["history_policy"], "bounded_thread_history")
        self.assertEqual(
            guided["model_snapshot"]["history_message_ids"],
            [item["message_id"] for item in histories[1]],
        )

    def test_planning_mode_selection_survives_browser_refresh(self) -> None:
        script = (
            Path(__file__).parents[1] / "src" / "research_workbench" / "web_assets" / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn("sessionStorage.getItem('hrwPlanningMode')", script)
        self.assertIn("sessionStorage.setItem('hrwPlanningMode', state.planningMode)", script)

    def test_source_list_exposes_optional_research_context(self) -> None:
        source_id = list_sources(self.project)[0]["source_id"]
        research = self.project / "research"
        research.mkdir(exist_ok=True)
        (research / "source_manifest.csv").write_text(
            "source_id,source_type,carrier,witness_relation,reading_status,verification_status,citable,notes\n"
            f"{source_id},search_carrier,TXT,same witness as original,TARGETED_READ,FILE_VERIFIED,false,"
            "Only a locator; the original volume remains the citation witness\n",
            encoding="utf-8",
        )

        listed = list_sources(self.project)[0]["research_context"]
        self.assertEqual(listed["source_type"], "search_carrier")
        self.assertEqual(listed["witness_relation"], "same witness as original")
        self.assertFalse(listed["citable"])
        self.assertIn("Only a locator", listed["notes"])
        self.assertEqual(source_view(self.project, source_id)["source"]["research_context"], listed)

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
        self.assertEqual(version, 13)
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

    def test_model_http_step_has_a_total_deadline(self) -> None:
        release = threading.Event()

        def never_returns(*_: object, **__: object) -> dict[str, object]:
            release.wait(1)
            return {}

        try:
            with patch("research_workbench.agent_runtime._post_json_blocking", side_effect=never_returns):
                with self.assertRaisesRegex(TimeoutError, "exceeded"):
                    _post_json("https://example.invalid", {}, {}, 0.01)
        finally:
            release.set()

    def test_parser_uses_first_action_when_provider_batches_json_objects(self) -> None:
        action = _parse_action(
            '{"type":"tool_call","tool":"project.status","arguments":{}}\n'
            '{"type":"tool_call","tool":"source.list","arguments":{}}'
        )
        self.assertEqual(action["tool"], "project.status")

    def test_parser_treats_plain_provider_text_as_safe_final_answer(self) -> None:
        action = _parse_action("候选页已定位；请人工核对原页。")
        self.assertEqual(action, {"type": "final", "content": "候选页已定位；请人工核对原页。"})

    def test_parser_accepts_observed_deepseek_tool_wrappers_only_when_they_wrap_the_whole_action(self) -> None:
        action = _parse_action(
            '<json_logic><tool_call>{"type":"tool_call","tool":"source.page",'
            '"arguments":{"source_id":"SRC_1","physical_page":251}}</tool_call></json_logic>'
        )
        self.assertEqual(action["tool"], "source.page")
        self.assertEqual(action["arguments"]["physical_page"], 251)
        prose = '示例：<tool_call>{"type":"tool_call","tool":"source.page","arguments":{}}</tool_call>'
        self.assertEqual(_parse_action(prose), {"type": "final", "content": prose})

    def test_parser_accepts_observed_angle_bracketed_action_only_as_the_whole_response(self) -> None:
        action = _parse_action(
            '<{"type":"tool_call","tool":"research_event.list","arguments":{}}>'
        )
        self.assertEqual(action["type"], "tool_call")
        self.assertEqual(action["tool"], "research_event.list")
        prose = '模型示例：<{"type":"tool_call","tool":"research_event.list","arguments":{}}>'
        self.assertEqual(_parse_action(prose), {"type": "final", "content": prose})

    def test_agent_prompt_routes_coverage_audits_to_deterministic_tool(self) -> None:
        self.assertIn('"tool":"research_event.coverage"', SYSTEM_PROMPT)
        self.assertIn("exact intended case_ids", SYSTEM_PROMPT)
        action = _parse_action(
            '<{"type":"tool_call","tool":"research_event.coverage",'
            '"arguments":{"case_ids":["DAVID","PIAS","RICH"]}}>'
        )
        self.assertEqual(action["tool"], "research_event.coverage")
        self.assertEqual(action["arguments"]["case_ids"], ["DAVID", "PIAS", "RICH"])

    def test_parser_accepts_observed_unclosed_angle_action_only_as_the_whole_response(self) -> None:
        action = _parse_action(
            '<{"type":"tool_call","tool":"source.page",'
            '"arguments":{"source_id":"SRC_1","physical_page":260}}'
        )
        self.assertEqual(action["tool"], "source.page")
        self.assertEqual(action["arguments"]["physical_page"], 260)
        prose = '模型示例：<{"type":"tool_call","tool":"source.page","arguments":{}}'
        self.assertEqual(_parse_action(prose), {"type": "final", "content": prose})

    def test_parser_accepts_one_complete_trailing_tool_action_after_a_short_preface(self) -> None:
        action = _parse_action(
            '继续读取物理页253以完成跨页终点判断。\n\n'
            '{"type":"tool_call","tool":"source.page",'
            '"arguments":{"source_id":"SRC_1","physical_page":253}}'
        )
        self.assertEqual(action["tool"], "source.page")
        self.assertEqual(action["arguments"]["physical_page"], 253)
        prose = '研究说明中的对象不是动作：\n{"type":"final","content":"示例"}'
        self.assertEqual(_parse_action(prose), {"type": "final", "content": prose})

    def test_parser_accepts_provider_json_with_literal_newline_in_content(self) -> None:
        action = _parse_action('{"type":"final","content":"第一条\n第二条"}')
        self.assertEqual(action, {"type": "final", "content": "第一条\n第二条"})

    def test_source_search_returns_page_and_block_anchors(self) -> None:
        results = _search_source_blocks(self.project, "page boundary")
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["page_id"].endswith(":P1"))
        self.assertTrue(results[0]["block_id"].endswith(":B2"))

    def test_source_page_accepts_human_physical_page_locator(self) -> None:
        source_id = list_sources(self.project)[0]["source_id"]
        page = _read_page(self.project, source_id=source_id, physical_page=1)
        self.assertEqual(page["physical_page"], 1)
        self.assertEqual(page["page_id"], f"{source_id}:P1")
        self.assertTrue(all("verification_state" in block for block in page["blocks"]))
        self.assertTrue(all("use_state" in block for block in page["blocks"]))
        self.assertFalse(any(block["usable_for_evidence"] for block in page["blocks"]))

        block_id = f"{source_id}:B2"
        verify_block(self.project, block_id, "Professor", "Checked against the source page")
        checked = _read_page(self.project, source_id=source_id, physical_page=1)
        target = next(block for block in checked["blocks"] if block["block_id"] == block_id)
        self.assertEqual(target["verification_state"], "human_verified")
        self.assertTrue(target["usable_for_evidence"])

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
        self.assertIn("prioritize dates", SYSTEM_PROMPT)
        self.assertIn("unfinished at the bottom of a page", SYSTEM_PROMPT)
        self.assertIn("not independent corroboration", SYSTEM_PROMPT)
        self.assertIn("Prior thread messages", SYSTEM_PROMPT)
        self.assertIn("unqualified historical fact", SYSTEM_PROMPT)

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
