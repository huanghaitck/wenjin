from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz

from research_workbench.agent_runtime import create_thread, decide_approval, send_message
from research_workbench.codex_harness import _Host
from research_workbench.library import approve_candidates, scan_directory, work_detail
from research_workbench.service import initialize_project, project_status
from research_workbench.db import connect, utc_now


class CodexHarnessTests(unittest.TestCase):
    def test_domain_tool_reuses_an_identical_successful_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_project(root, "Domain receipt")
            now = utc_now()
            with connect(root) as connection:
                connection.execute(
                    "INSERT INTO domain_agent_sessions(session_id,plugin_name,agent_id,title,status,memory_json,created_at,updated_at) "
                    "VALUES ('S','p','a','A','active','{}',?,?)", (now, now),
                )
                connection.execute(
                    "INSERT INTO domain_agent_runs(run_id,session_id,status,model_snapshot_json,created_at,updated_at) "
                    "VALUES ('D','S','RUNNING','{}',?,?)", (now, now),
                )
            host = _Host(root, "test", None)  # type: ignore[arg-type]
            binding = {"run_id": "D", "session_id": "S", "plugin_name": "p",
                       "plugin": {"tool_permissions": {"inspect": "read"}},
                       "tools": {"inspect"}, "access_mode": "ask", "parent_run_id": ""}
            request = {"namespace": "domain", "tool": "inspect", "arguments": {"page": 1}}
            with patch(
                "research_workbench.domain_plugins.call_domain_plugin_tool",
                return_value={"structuredContent": {"read_only": True}},
            ) as tool:
                first = host._handle_domain_tool(request, binding)
                second = host._handle_domain_tool(request, binding)
            self.assertTrue(first["success"])
            self.assertTrue(second["success"])
            self.assertEqual(tool.call_count, 1)
            self.assertTrue(json.loads(second["contentItems"][0]["text"])["already_succeeded"])

    def test_library_adoption_pauses_then_ingests_the_selected_exact_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, library, materials = Path(directory) / "project", Path(directory) / "library", Path(directory) / "materials"
            materials.mkdir()
            initialize_project(root, "Library adoption")
            pdf = materials / "Qinling study.pdf"
            document = fitz.open(); document.new_page().insert_text((72, 72), "Qinling historical study")
            document.save(pdf); document.close()
            scan = scan_directory(root, materials, library)
            approved = approve_candidates(root, scan["session_id"], None, library)
            work_id = approved["approved"][0]["work_id"]
            file_id = work_detail(root, work_id, library)["files"][0]["file_id"]
            thread = create_thread(root, "Adopt one work")
            calls = 0

            def fake_turn(project_root, _thread_id, run_id, *_args):
                nonlocal calls
                calls += 1
                if calls == 1:
                    host = _Host(project_root, "test", None)  # type: ignore[arg-type]
                    host.active_runs["codex-thread"] = run_id
                    host.handle_request("item/tool/call", {
                        "threadId": "codex-thread", "namespace": "wenjin", "tool": "library__add_to_project",
                        "arguments": {"work_id": work_id, "file_id": file_id},
                    })
                    return "等待批准"
                return "采用和清洗完成。"

            with patch.dict(os.environ, {"HRW_LIBRARY_ROOT": str(library), "WENJIN_HARNESS_BACKEND": "codex"}, clear=False), patch(
                "research_workbench.codex_harness.run_turn", side_effect=fake_turn
            ):
                waiting = send_message(root, thread["thread_id"], "采用这篇文献", access_mode="ask")
                approval_id = waiting["runs"][0]["approvals"][0]["approval_id"]
                completed = decide_approval(root, approval_id, True, "测试用户", "精确版本无误")

            self.assertEqual(completed["runs"][0]["status"], "COMPLETED")
            self.assertEqual(project_status(root)["source_count"], 1)

    def test_send_message_uses_native_project_tool_and_keeps_existing_view(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "HRW_ENABLE_MOCK_MODEL": "1",
            "WENJIN_HARNESS_BACKEND": "codex",
        }, clear=False):
            root = Path(directory)
            initialize_project(root, "Native tool project")
            thread = create_thread(root, "Native tool test")

            def fake_turn(project_root, _thread_id, run_id, *_args):
                host = _Host(project_root, "test", None)  # type: ignore[arg-type]
                host.active_runs["codex-thread"] = run_id
                receipt = host.handle_request("item/tool/call", {
                    "threadId": "codex-thread", "namespace": None,
                    "tool": "wenjin__project__status", "arguments": {},
                })
                status = json.loads(receipt["contentItems"][0]["text"])
                return f"{status['title']} / {status['source_count']}"

            with patch("research_workbench.codex_harness.run_turn", side_effect=fake_turn):
                view = send_message(root, thread["thread_id"], "请读取当前项目状态")

            self.assertEqual(view["messages"][-1]["content"]["text"], "Native tool project / 0")
            events = [item["event_type"] for item in view["runs"][0]["events"]]
            self.assertIn("tool_started", events)
            self.assertIn("tool_completed", events)
            self.assertEqual(view["runs"][0]["status"], "COMPLETED")

    def test_ask_mode_pauses_native_write_and_resumes_same_run_after_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "HRW_ENABLE_MOCK_MODEL": "1",
            "WENJIN_HARNESS_BACKEND": "codex",
        }, clear=False):
            root = Path(directory)
            initialize_project(root, "Approval project")
            thread = create_thread(root, "Approval test")
            calls = 0

            def fake_turn(project_root, _thread_id, run_id, *_args):
                nonlocal calls
                calls += 1
                if calls == 1:
                    host = _Host(project_root, "test", None)  # type: ignore[arg-type]
                    host.active_runs["codex-thread"] = run_id
                    host.handle_request("item/tool/call", {
                        "threadId": "codex-thread", "namespace": "wenjin",
                        "tool": "save_research_note",
                        "arguments": {"title": "候选札记", "content": "待批准内容"},
                    })
                    return "等待批准"
                return "已按批准结果继续同一任务。"

            with patch("research_workbench.codex_harness.run_turn", side_effect=fake_turn):
                waiting = send_message(root, thread["thread_id"], "保存一份研究札记")
                self.assertEqual(waiting["runs"][0]["status"], "WAITING_FOR_APPROVAL")
                approval_id = waiting["runs"][0]["approvals"][0]["approval_id"]
                completed = decide_approval(root, approval_id, True, "测试用户", "内容无误")

            self.assertEqual(calls, 2)
            self.assertEqual(completed["runs"][0]["status"], "COMPLETED")
            self.assertEqual(completed["messages"][-1]["content"]["text"], "已按批准结果继续同一任务。")


if __name__ == "__main__":
    unittest.main()
