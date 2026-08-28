from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_workbench.agent_runtime import create_thread, decide_approval, send_message
from research_workbench.codex_harness import _Host
from research_workbench.service import initialize_project


class CodexHarnessTests(unittest.TestCase):
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
