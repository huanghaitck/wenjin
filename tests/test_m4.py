from __future__ import annotations

import json
import io
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import ANY, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from research_workbench.agent_runtime import (
    EmptyModelContentError,
    ModelActionFormatError,
    ModelProfile,
    SYSTEM_PROMPT,
    _adaptive_model_timeout,
    _advance_run,
    _agent_research_state,
    _compact_authoring_state,
    _compact_reading_batch,
    _compact_source_list,
    _clean_final_text,
    _model_action,
    _looks_like_internal_tool_transcript,
    _parse_action,
    _planning_context,
    _post_json,
    _read_page,
    _search_source_blocks,
    _execute_tool,
    _explicit_required_tool,
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
from research_workbench.authoring import decide_historiography_entry
from research_workbench.db import SCHEMA_VERSION, _migrate, connect, database_path, utc_now
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
    def test_model_timeout_expands_only_for_deep_or_tool_heavy_turns(self) -> None:
        self.assertEqual(_adaptive_model_timeout(120, "standard", "low", 0), 120)
        self.assertEqual(_adaptive_model_timeout(120, "deep", "high", 0), 300)
        self.assertEqual(_adaptive_model_timeout(120, "standard", "low", 8), 340)

    def test_runtime_diagnosis_and_repair_are_required_from_natural_language(self) -> None:
        self.assertEqual(_explicit_required_tool("检查这台电脑的 Python 和 PowerShell 运行环境"), "computer.runtime_status")
        self.assertEqual(_explicit_required_tool("请修复缺少的 PowerShell 运行环境"), "computer.runtime_repair")
        self.assertEqual(_explicit_required_tool("请修复灾害史领域 Agent 的运行工具"), "plugin.repair")

    def test_public_final_text_strips_provider_protocol_prefix(self) -> None:
        self.assertEqual(_clean_final_text("final answer:\n这是给研究者的答复。"), "这是给研究者的答复。")

    def test_main_agent_keeps_general_file_web_office_and_skill_capabilities(self) -> None:
        for tool in ("computer.file_search", "computer.launch", "computer.runtime_status", "computer.runtime_repair", "research.search", "browser.start", "skill.create"):
            self.assertIn(f'"tool":"{tool}"', SYSTEM_PROMPT)
        self.assertIn("general local computer-use agent", SYSTEM_PROMPT)

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

    def test_approved_browser_start_resumes_the_same_run(self) -> None:
        thread = create_thread(self.project, "browser approval resume")
        actions = [
            {"type": "tool_call", "tool": "browser.start", "arguments": {"url": "https://example.com/"}},
            {"type": "tool_call", "tool": "browser.read", "arguments": {"session_id": "BRS_test"}},
            {"type": "final", "content": "Example Domain · first sentence"},
        ]
        with patch("research_workbench.agent_runtime._mock_action", side_effect=actions), patch(
            "research_workbench.agent_runtime.create_browser_session",
            return_value={"session_id": "BRS_test"},
        ), patch(
            "research_workbench.agent_runtime.launch_controlled_browser",
            return_value={"session_id": "BRS_test", "launched": True},
        ), patch(
            "research_workbench.agent_runtime.read_controlled_browser",
            return_value={"title": "Example Domain", "text": "first sentence"},
        ):
            pending = send_message(
                self.project, thread["thread_id"], "打开并读取示例网页", access_mode="ask",
            )
            approval = pending["runs"][0]["approvals"][0]
            completed = decide_approval(
                self.project, approval["approval_id"], True,
                "researcher", "approved bounded read-only site",
            )
        self.assertEqual(completed["runs"][0]["status"], "COMPLETED")
        self.assertEqual(
            [item["tool_name"] for item in completed["runs"][0]["tool_calls"]],
            ["browser.start", "browser.read"],
        )
        self.assertIn("Example Domain", completed["messages"][-1]["content"]["text"])

    def test_access_modes_auto_approve_only_allowlisted_local_note_write(self) -> None:
        for mode in ("research_assist", "full_computer"):
            thread = create_thread(self.project, f"access {mode}")
            result = send_message(
                self.project, thread["thread_id"], "查看来源和异常并保存研究札记",
                access_mode=mode,
            )
            run = result["runs"][0]
            self.assertEqual(run["status"], "COMPLETED")
            self.assertEqual(run["model_snapshot"]["access_mode"], mode)
            self.assertEqual(run["approvals"][0]["status"], "approved")
            self.assertEqual(run["approvals"][0]["decision"]["access_mode"], mode)
            note = self.project / "research" / "notes" / f"{run['approvals'][0]['approval_id']}.md"
            self.assertTrue(note.is_file())
            event_types = [event["event_type"] for event in run["events"]]
            self.assertIn("approval_auto_decided", event_types)

    def test_unknown_access_mode_is_rejected_before_run_creation(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown agent access mode"):
            send_message(self.project, self.thread["thread_id"], "检查来源", access_mode="unbounded_shell")
        self.assertEqual(thread_view(self.project, self.thread["thread_id"])["runs"], [])

    def test_main_reasoning_controls_are_frozen_and_forwarded(self) -> None:
        with patch("research_workbench.agent_runtime._advance_run") as advance:
            result = send_message(
                self.project, self.thread["thread_id"], "检查来源",
                reasoning_mode="deep", reasoning_effort="high",
            )
        snapshot = result["runs"][0]["model_snapshot"]
        self.assertEqual(snapshot["reasoning_mode"], "deep")
        self.assertEqual(snapshot["reasoning_effort"], "high")
        self.assertEqual(advance.call_args.kwargs["reasoning_mode"], "deep")
        self.assertEqual(advance.call_args.kwargs["reasoning_effort"], "high")

    def test_new_thread_inherits_bounded_parent_conversation_without_copying_messages(self) -> None:
        from research_workbench.agent_runtime import _thread_history

        now = utc_now()
        with connect(self.project) as connection:
            connection.execute(
                "INSERT INTO messages(message_id,thread_id,role,content_json,created_at) "
                "VALUES ('MSG_PARENT',?,'user',?,?)",
                (self.thread["thread_id"], json.dumps({"text": "父对话中的研究边界"}, ensure_ascii=False), now),
            )
        child = create_thread(self.project, "继续讨论", self.thread["thread_id"])
        history, receipt = _thread_history(self.project, child["thread_id"])
        self.assertEqual(child["parent_thread_id"], self.thread["thread_id"])
        self.assertEqual(history[-1]["content"], "父对话中的研究边界")
        self.assertEqual(receipt["message_ids"], ["MSG_PARENT"])
        self.assertEqual(thread_view(self.project, child["thread_id"])["messages"], [])

    def test_history_compacts_at_ninety_percent_of_model_window(self) -> None:
        now = utc_now()
        with connect(self.project) as connection:
            for index in range(12):
                connection.execute("INSERT INTO messages(message_id,thread_id,role,content_json,created_at) VALUES (?,?,?,?,?)", (f"MSG_long_{index}", self.thread["thread_id"], "user" if index % 2 == 0 else "assistant", json.dumps({"text": "长对话内容" * 30}, ensure_ascii=False), now))
        with patch.dict(os.environ, {"HRW_AGENT_CONTEXT_WINDOW": "200"}, clear=False), patch("research_workbench.agent_runtime._role_profile", return_value=ModelProfile("compress","mock","mock","",("text",),"none","available")), patch("research_workbench.agent_runtime._plain_model_call", return_value="保留目标、路径、来源和未决问题。"):
            history, receipt = _thread_history(self.project, self.thread["thread_id"])
        self.assertTrue(receipt["compacted"])
        self.assertEqual(receipt["compression_threshold_tokens"], 180)
        self.assertEqual(history[0]["message_id"], "COMPACTED_HISTORY")

    def test_default_thread_title_uses_title_role_without_overwriting_named_threads(self) -> None:
        thread = create_thread(self.project, "新的研究讨论")
        with patch("research_workbench.agent_runtime._role_profile", return_value=ModelProfile("title","mock","mock","",("text",),"none","available")), patch("research_workbench.agent_runtime._plain_model_call", return_value="秦岭旅行材料整理"), patch("research_workbench.agent_runtime._advance_run"):
            send_message(self.project, thread["thread_id"], "整理秦岭旅行材料")
        self.assertEqual(thread_view(self.project, thread["thread_id"])["thread"]["title"], "秦岭旅行材料整理")

    def test_agent_can_observe_visible_browser_without_form_or_click_tools(self) -> None:
        run_id = send_message(self.project, self.thread["thread_id"], "check")["runs"][0]["run_id"]
        with patch(
            "research_workbench.agent_runtime.inspect_controlled_browser",
            return_value={"session_id": "BRS_demo", "snapshot": "Example Domain"},
        ):
            result = _execute_tool(
                self.project, run_id, "browser.snapshot", {"session_id": "BRS_demo"}
            )
        self.assertEqual(result["snapshot"], "Example Domain")
        self.assertIn('"tool":"browser.read"', SYSTEM_PROMPT)
        self.assertNotIn('"tool":"browser.click"', SYSTEM_PROMPT)

    def test_main_agent_can_discover_and_read_user_action_skills(self) -> None:
        from research_workbench.agent_runtime import _implicit_skill_catalog

        self.assertIn("historical-source-criticism", _implicit_skill_catalog())
        run_id = send_message(self.project, self.thread["thread_id"], "check")["runs"][0]["run_id"]
        listed = _execute_tool(self.project, run_id, "skill.list", {})
        self.assertIn("historical-source-criticism", {item["name"] for item in listed["skills"]})
        loaded = _execute_tool(
            self.project, run_id, "skill.read", {"name": "historical-source-criticism"}
        )
        self.assertTrue(loaded["instructions"])
        self.assertIn('"tool":"skill.read"', SYSTEM_PROMPT)

    def test_computer_use_permissions_match_ask_assist_and_full_access(self) -> None:
        ask_run = send_message(
            self.project, create_thread(self.project, "ask computer")["thread_id"], "check",
            access_mode="ask",
        )["runs"][0]["run_id"]
        with patch("research_workbench.agent_runtime._plugin_tool_risk", return_value="routine"), patch(
            "research_workbench.agent_runtime.call_domain_plugin_tool",
            return_value={"clicked": True},
        ) as execute:
            pending = _execute_tool(self.project, ask_run, "plugin.call", {
                "plugin_name": "computer-use", "tool_name": "click_control",
                "arguments": {"ref": "w1.0"},
            })
            self.assertTrue(pending["waiting_for_approval"])
            execute.assert_not_called()
            decided = decide_approval(
                self.project, pending["approval_id"], True, "researcher", "approved visible click"
            )
            execute.assert_called_once()
        self.assertTrue(any(item["approval_id"]==pending["approval_id"] and item["status"]=="approved" for item in decided["runs"][0]["approvals"]))

        assist_run = send_message(
            self.project, create_thread(self.project, "assist computer")["thread_id"], "check",
            access_mode="research_assist",
        )["runs"][0]["run_id"]
        with patch("research_workbench.agent_runtime._plugin_tool_risk", return_value="sensitive"), patch(
            "research_workbench.agent_runtime.call_domain_plugin_tool",
            return_value={"launched": True},
        ) as execute:
            pending = _execute_tool(self.project, assist_run, "plugin.call", {
                "plugin_name": "computer-use", "tool_name": "launch_program",
                "arguments": {"executable": "demo.exe"},
            })
        self.assertTrue(pending["waiting_for_approval"])
        execute.assert_not_called()

        full_thread = create_thread(self.project, "full computer")
        full_run = send_message(
            self.project, full_thread["thread_id"], "check",
            access_mode="full_computer",
        )["runs"][0]["run_id"]
        with patch("research_workbench.agent_runtime._plugin_tool_risk", return_value="sensitive"), patch(
            "research_workbench.agent_runtime.call_domain_plugin_tool",
            return_value={"exit_code": 0},
        ):
            completed = _execute_tool(self.project, full_run, "plugin.call", {
                "plugin_name": "computer-use", "tool_name": "run_command",
                "arguments": {"executable": "demo.exe"},
            })
        self.assertEqual(completed["exit_code"], 0)
        view = thread_view(self.project, full_thread["thread_id"])
        self.assertEqual(view["runs"][0]["approvals"][0]["status"], "approved")

    def test_plugin_repair_pauses_then_resumes_from_recorded_source(self) -> None:
        run_id = send_message(
            self.project, create_thread(self.project, "repair plugin")["thread_id"], "check",
            access_mode="ask",
        )["runs"][0]["run_id"]
        with patch("research_workbench.agent_runtime.repair_domain_plugin", return_value={"count": 1}) as repair:
            pending = _execute_tool(self.project, run_id, "plugin.repair", {"plugin_name": "disaster-history"})
            self.assertTrue(pending["waiting_for_approval"])
            repair.assert_not_called()
            decided = decide_approval(
                self.project, pending["approval_id"], True, "researcher", "local ZIP checked",
            )
        repair.assert_called_once()
        self.assertTrue(any(
            item["approval_id"] == pending["approval_id"] and item["status"] == "approved"
            for run in decided["runs"] for item in run["approvals"]
        ))

    def test_direct_computer_alias_exposes_bounded_file_search_to_main_agent(self) -> None:
        run_id = send_message(
            self.project, create_thread(self.project, "file search")["thread_id"], "check",
        )["runs"][0]["run_id"]
        with patch("research_workbench.agent_runtime._plugin_tool_risk", return_value="read"), patch(
            "research_workbench.agent_runtime.call_domain_plugin_tool",
            return_value={"matches": [{"path": "D:/Research/disaster.zip"}]},
        ) as execute:
            result = _execute_tool(self.project, run_id, "computer.file_search", {
                "roots": ["D:/Research"], "query": "disaster", "max_results": 20,
            })
        self.assertEqual(result["matches"][0]["path"], "D:/Research/disaster.zip")
        execute.assert_called_once_with(
            ANY, "computer-use", "file_search",
            {"roots": ["D:/Research"], "query": "disaster", "max_results": 20},
        )
        self.assertIn('\"tool\":\"computer.file_search\"', SYSTEM_PROMPT)
        self.assertIn("access is unavailable before attempting those tools", SYSTEM_PROMPT)

    def test_main_agent_can_consult_a_stateful_domain_subagent_without_merging_memory(self) -> None:
        run_id = send_message(
            self.project, create_thread(self.project, "domain consult")["thread_id"], "check",
        )["runs"][0]["run_id"]
        view = {
            "session": {"session_id": "DAS_1", "plugin_name": "disaster-history"},
            "messages": [{"role": "assistant", "content": {"text": "candidate"}}],
            "runs": [{"run_id": "DRN_1", "status": "COMPLETED"}],
            "artifacts": [{"artifact_id": "DAR_1", "status": "candidate"}],
        }
        with patch("research_workbench.domain_agents.send_domain_message", return_value=view) as consult:
            result = _execute_tool(self.project, run_id, "domain_agent.consult", {
                "plugin_name": "disaster-history", "question": "inspect grading",
            })
        self.assertEqual(result["latest_message"]["content"]["text"], "candidate")
        self.assertEqual(result["candidate_artifacts"][0]["status"], "candidate")
        consult.assert_called_once()
        self.assertIn('"tool":"domain_agent.consult"', SYSTEM_PROMPT)

    def test_mock_profile_is_absent_outside_explicit_test_mode(self) -> None:
        other = self.project.parent / "production-profile-project"
        initialize_project(other, "production")
        with patch.dict(os.environ, {"HRW_ENABLE_MOCK_MODEL": ""}, clear=False), patch.object(
            sys, "argv", ["wenjin", "desktop-serve"],
        ):
            profiles = sync_model_profiles(other)
        self.assertNotIn("builtin-mock", {item["profile_id"] for item in profiles})
        with connect(other) as connection:
            assignment = connection.execute(
                "SELECT profile_id FROM model_assignments WHERE role='main_reasoning'"
            ).fetchone()
        self.assertIsNone(assignment)

    def test_agent_domain_pack_creation_is_permission_gated_and_validated(self) -> None:
        thread=create_thread(self.project,"domain pack creator")
        run_id=send_message(
            self.project,thread["thread_id"],"check",access_mode="ask"
        )["runs"][0]["run_id"]
        parent=self.project.parent/"generated-packs"
        pending=_execute_tool(self.project,run_id,"domain_pack.create",{
            "parent":str(parent),"name":"neutral-history-tools",
            "display_name":"Neutral History Tools","description":"Neutral domain-pack test scaffold.",
        })
        self.assertTrue(pending["waiting_for_approval"])
        self.assertFalse((parent/"neutral-history-tools").exists())
        decided=decide_approval(
            self.project,pending["approval_id"],True,"researcher","scope and target checked"
        )
        created=parent/"neutral-history-tools"
        self.assertTrue((created/"wenjin-plugin.json").is_file())
        self.assertTrue(any(item["status"]=="approved" for item in decided["runs"][0]["approvals"]))
        validated=_execute_tool(self.project,run_id,"domain_pack.validate",{"plugin_root":str(created)})
        self.assertEqual(validated["status"],"valid")

    def test_rejection_writes_no_note_and_keeps_decision(self) -> None:
        result = send_message(self.project, self.thread["thread_id"], "检查后先提出札记")
        approval = result["runs"][0]["approvals"][0]
        rejected = decide_approval(
            self.project, approval["approval_id"], False, "professor", "证据范围还不清楚"
        )
        self.assertEqual(rejected["runs"][0]["status"], "COMPLETED")
        self.assertEqual(rejected["runs"][0]["approvals"][0]["status"], "rejected")
        self.assertFalse((self.project / "research" / "notes" / f"{approval['approval_id']}.md").exists())
        self.assertIn("没有改变电脑或项目", rejected["messages"][-1]["content"]["text"])

    def test_agent_research_state_is_a_compact_index(self) -> None:
        state = _agent_research_state(self.project)
        self.assertIn("counts", state)
        self.assertIn("claims", state)
        self.assertIn("freezes", state)
        self.assertNotIn("artifacts", state)
        self.assertLess(len(json.dumps(state, ensure_ascii=False)), 5000)

    def test_agent_authoring_state_omits_full_text(self) -> None:
        from research_workbench.authoring import import_manuscript
        from research_workbench.agent_runtime import _read_authoring_section

        detail = import_manuscript(self.project, "Long draft", "# 第一节\n" + "正文" * 20000)
        state = _compact_authoring_state(self.project)
        manuscript = state["manuscripts"][0]
        self.assertEqual(manuscript["character_count"], 40000)
        self.assertNotIn("content", manuscript["sections"][0])
        self.assertLess(len(json.dumps(state, ensure_ascii=False)), 20000)
        section = _read_authoring_section(self.project, detail["sections"][0]["section_id"])
        self.assertEqual(section["heading"], "第一节")
        self.assertEqual(len(section["content"]), 40000)

    def test_source_list_is_bounded_compact_and_supports_exact_identity(self) -> None:
        source_ids = [list_sources(self.project)[0]["source_id"]]
        for index in range(25):
            original = Path(self.temporary.name) / f"source-{index}.txt"
            original.write_text(f"source {index}", encoding="utf-8")
            source_ids.append(
                register_source(self.project, original, f"Research source {index:02d}")["source_id"]
            )

        default = _compact_source_list(self.project, {})
        self.assertEqual(default["total_count"], 26)
        self.assertEqual(default["returned_count"], 20)
        self.assertTrue(default["has_more"])
        self.assertNotIn("byte_count", default["sources"][0])
        self.assertNotIn("research_context", default["sources"][0])
        self.assertLess(len(json.dumps(default, ensure_ascii=False)), 12000)

        exact = _compact_source_list(self.project, {"source_ids": [source_ids[-1]]})
        self.assertEqual(exact["returned_count"], 1)
        self.assertFalse(exact["has_more"])
        self.assertEqual(exact["sources"][0]["source_id"], source_ids[-1])
        self.assertEqual(exact["sources"][0]["title"], "Research source 24")
        queried = _compact_source_list(self.project, {"query": "source 24", "limit": 5})
        self.assertEqual([item["source_id"] for item in queried["sources"]], [source_ids[-1]])
        with self.assertRaisesRegex(KeyError, "unknown source"):
            _compact_source_list(self.project, {"source_ids": ["SRC_missing"]})

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

    def test_slash_skill_is_versioned_in_the_run_snapshot(self) -> None:
        result = send_message(
            self.project, self.thread["thread_id"],
            "/historical-material-intake 查看项目来源，但不要改变原文件",
        )
        skill = result["runs"][0]["model_snapshot"]["active_skill"]
        self.assertEqual(skill["name"], "historical-material-intake")
        self.assertEqual(len(skill["sha256"]), 64)
        self.assertEqual(skill["invocation"], "/historical-material-intake")
        with self.assertRaises(KeyError):
            send_message(self.project, self.thread["thread_id"], "/not-installed do something")

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
        self.assertFalse(run["artifact_receipt"]["artifacts_saved"])

    def test_failed_final_response_reports_artifacts_already_saved_by_tools(self) -> None:
        source_id = list_sources(self.project)[0]["source_id"]
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://example.invalid/v1", "HRW_AGENT_API_KEY": "secret",
        }
        actions: list[object] = [
            {
                "type": "tool_call", "tool": "reading_job.create",
                "arguments": {
                    "title": "已落盘的阅读任务", "question": "作者如何解释调查？",
                    "mode": "targeted", "source_ids": [source_id],
                    "stop_condition": "完成指定页面。",
                },
            },
            ModelActionFormatError("Expecting ',' delimiter"),
            ModelActionFormatError("Expecting ',' delimiter"),
        ]

        def next_action(*_args: object) -> dict[str, object]:
            action = actions.pop(0)
            if isinstance(action, Exception):
                raise action
            return action

        with patch.dict(os.environ, environment, clear=False):
            sync_model_profiles(self.project)
            assign_model(self.project, "environment-main")
            with patch("research_workbench.agent_runtime._model_action", side_effect=next_action):
                with self.assertRaisesRegex(RuntimeError, "invalid model action"):
                    send_message(self.project, self.thread["thread_id"], "建立阅读任务后说明结果")

        run = thread_view(self.project, self.thread["thread_id"])["runs"][0]
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual(run["artifact_receipt"]["saved_artifact_count"], 1)
        self.assertEqual(run["artifact_receipt"]["saved_artifacts"][0]["tool"], "reading_job.create")
        failure = next(event for event in run["events"] if event["event_type"] == "run_failed")
        self.assertTrue(failure["payload"]["artifacts_saved"])
        self.assertEqual(failure["payload"]["saved_artifact_count"], 1)
        with connect(self.project) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM reading_jobs WHERE title = '已落盘的阅读任务'"
                ).fetchone()[0],
                1,
            )

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

    def test_event_batch_validation_failure_allows_one_correction(self) -> None:
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
                    "调用 research_event.propose_batch 一次提交事件。",
                )

        run = result["runs"][0]
        event_calls = [
            call for call in run["tool_calls"]
            if call["tool_name"] == "research_event.propose_batch"
        ]
        self.assertEqual([call["status"] for call in event_calls], ["FAILED", "COMPLETED"])
        self.assertEqual(run["status"], "COMPLETED")
        create_candidates.assert_called_once()

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

    def test_local_file_search_request_cannot_end_with_an_untried_refusal(self) -> None:
        from research_workbench.agent_runtime import _explicit_required_tool
        self.assertEqual(
            _explicit_required_tool("请检查电脑里的灾害史领域包文件"),
            "computer.file_search",
        )

    def test_natural_domain_request_requires_consult_without_tool_syntax(self) -> None:
        from research_workbench.agent_runtime import _domain_agent_catalog, _natural_domain_tool

        plugin = {
            "name": "disaster-history", "kind": "domain", "status": "ready",
            "description": "地方志灾害资料处理", "agent_tools": ["propagate_event_grades_to_all_rows"],
            "agent": {"id": "disaster-researcher", "routing_triggers": ["灾害等级", "定等"]},
        }
        with patch("research_workbench.domain_plugins.plugin_state", return_value={"plugins": [plugin]}):
            self.assertEqual(
                _natural_domain_tool(self.project, "把江西表里尚未定等的县级行全部定等"),
                "domain_agent.consult",
            )
            catalog = _domain_agent_catalog(self.project)
        self.assertIn("disaster-history", catalog)
        self.assertIn("same main conversation", catalog)

    def test_domain_tool_trigger_also_routes_ordinary_language_to_specialist(self) -> None:
        from research_workbench.agent_runtime import _matching_domain_agent

        plugin = {
            "name": "disaster-history", "kind": "domain", "status": "ready",
            "agent_tools": ["convert_half_finished_workbook"],
            "agent": {
                "id": "disaster-researcher", "routing_triggers": ["灾害史"],
                "tool_triggers": {"convert_half_finished_workbook": ["22列", "成品表"]},
            },
        }
        with patch("research_workbench.domain_plugins.plugin_state", return_value={"plugins": [plugin]}):
            self.assertEqual(
                _matching_domain_agent(self.project, "把这个工作簿转换为标准22列候选表"),
                "disaster-history",
            )

    def test_domain_pack_ui_question_does_not_force_specialist_consult(self) -> None:
        from research_workbench.agent_runtime import _natural_domain_tool

        plugin = {
            "name": "disaster-history", "kind": "domain", "status": "ready",
            "agent": {"id": "disaster-researcher", "routing_triggers": ["灾害史"]},
        }
        with patch("research_workbench.domain_plugins.plugin_state", return_value={"plugins": [plugin]}):
            self.assertEqual(_natural_domain_tool(self.project, "灾害史领域包界面怎么设计"), "")

    def test_domain_followup_reuses_recent_specialist_context(self) -> None:
        from research_workbench.agent_runtime import _matching_domain_agent

        plugin = {
            "name": "disaster-history", "kind": "domain", "status": "ready",
            "agent": {"id": "disaster-researcher", "routing_triggers": ["南昌县志", "灾害史"]},
        }
        history = [{"role": "user", "content": "请让灾害史领域Agent处理南昌县志。"}]
        with patch("research_workbench.domain_plugins.plugin_state", return_value={"plugins": [plugin]}):
            self.assertEqual(
                _matching_domain_agent(self.project, "继续上一轮断点续跑", history),
                "disaster-history",
            )

    def test_explicit_followup_reuses_the_only_ready_domain_agent_without_history(self) -> None:
        from research_workbench.agent_runtime import _matching_domain_agent

        plugin = {
            "name": "disaster-history", "kind": "domain", "status": "ready",
            "agent": {"id": "disaster-researcher", "routing_triggers": ["灾害史"]},
        }
        with patch("research_workbench.domain_plugins.plugin_state", return_value={"plugins": [plugin]}):
            self.assertEqual(
                _matching_domain_agent(self.project, "继续同一任务，并沿用原领域Agent", []),
                "disaster-history",
            )

    def test_natural_domain_request_consults_before_the_main_model_selects_tools(self) -> None:
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://example.invalid/v1", "HRW_AGENT_API_KEY": "secret",
            "HRW_MOA_ENABLED": "0", "WENJIN_HARNESS_BACKEND": "codex",
        }
        plugin = {
            "name": "disaster-history", "kind": "domain", "status": "ready",
            "agent_tools": ["propagate"],
            "agent": {"id": "disaster-researcher", "routing_triggers": ["定等"]},
        }
        view = {
            "session": {"session_id": "DAS_1", "plugin_name": "disaster-history"},
            "messages": [{"role": "assistant", "content": {"text": "candidate ready"}}],
            "runs": [{"run_id": "DRN_1", "status": "COMPLETED"}],
            "artifacts": [],
        }
        with patch.dict(os.environ, environment, clear=False):
            sync_model_profiles(self.project)
            assign_model(self.project, "environment-main")
            with patch("research_workbench.domain_plugins.plugin_state", return_value={"plugins": [plugin]}), patch(
                "research_workbench.domain_agents.send_domain_message", return_value=view,
            ) as consult, patch("research_workbench.agent_runtime._model_action") as model:
                result = send_message(
                    self.project, self.thread["thread_id"], "把县级行全部定等",
                    access_mode="research_assist",
                )
        self.assertEqual(result["runs"][0]["status"], "COMPLETED")
        self.assertEqual(result["messages"][-1]["content"]["text"], "candidate ready")
        consult.assert_called_once()
        model.assert_not_called()

    def test_codex_backend_uses_the_same_natural_domain_routing(self) -> None:
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://example.invalid/v1", "HRW_AGENT_API_KEY": "secret",
            "HRW_HARNESS_BACKEND": "codex", "HRW_MOA_ENABLED": "0",
        }
        plugin = {
            "name": "disaster-history", "kind": "domain", "status": "ready",
            "agent_tools": ["chronology_vocabulary"],
            "agent": {"id": "disaster-researcher", "routing_triggers": ["灾害史"]},
        }
        view = {
            "session": {"session_id": "DAS_1", "plugin_name": "disaster-history"},
            "messages": [{"role": "assistant", "content": {"text": "纪年词表已读取。"}}],
            "runs": [{"run_id": "DRN_1", "status": "COMPLETED"}],
            "artifacts": [],
        }
        with patch.dict(os.environ, environment, clear=False):
            sync_model_profiles(self.project)
            assign_model(self.project, "environment-main")
            with patch("research_workbench.domain_plugins.plugin_state", return_value={"plugins": [plugin]}), patch(
                "research_workbench.domain_agents.send_domain_message", return_value=view,
            ) as consult, patch("research_workbench.codex_harness.run_turn") as codex_turn:
                result = send_message(
                    self.project, self.thread["thread_id"],
                    "请让灾害史领域 Agent 检查纪年词表。", access_mode="research_assist",
                )
        self.assertEqual(result["runs"][0]["status"], "COMPLETED")
        self.assertEqual(result["messages"][-1]["content"]["text"], "纪年词表已读取。")
        consult.assert_called_once()
        codex_turn.assert_not_called()

    def test_attachment_is_inspected_once_then_delegated_without_a_second_main_model_step(self) -> None:
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://example.invalid/v1", "HRW_AGENT_API_KEY": "secret",
            "HRW_MOA_ENABLED": "0", "WENJIN_HARNESS_BACKEND": "codex",
        }
        plugin = {
            "name": "disaster-history", "kind": "domain", "status": "ready",
            "agent_tools": ["normalize_disaster_type"],
            "agent": {"id": "disaster-researcher", "routing_triggers": ["灾害史"]},
        }
        attachment_id = "ATT_" + "a" * 32
        calls = []

        def execute(_project, _run, tool, arguments):
            calls.append((tool, arguments))
            if tool == "attachment.inspect":
                return {"analysis": "版心页码四二三；本页未见灾害条目。"}
            return {
                "latest_message": {"content": {"text": "本页没有可提取的灾害记载。"}}
            }

        with patch.dict(os.environ, environment, clear=False):
            sync_model_profiles(self.project)
            assign_model(self.project, "environment-main")
            with patch("research_workbench.domain_plugins.plugin_state", return_value={"plugins": [plugin]}), patch(
                "research_workbench.agent_runtime._model_action",
                return_value={
                    "type": "tool_call", "tool": "attachment.inspect",
                    "arguments": {"attachment_id": attachment_id, "prompt": "读取页码和正文"},
                },
            ) as model, patch("research_workbench.agent_runtime._execute_tool", side_effect=execute), patch(
                "research_workbench.codex_harness.run_turn",
            ) as codex_turn:
                result = send_message(
                    self.project, self.thread["thread_id"], "读取附件后交给灾害史专业Agent判断。",
                    context={"attached_refs": [{"attachment_id": attachment_id, "original_name": "page.png"}]},
                    access_mode="research_assist",
                )
        self.assertEqual(result["runs"][0]["status"], "COMPLETED")
        self.assertEqual(result["messages"][-1]["content"]["text"], "本页没有可提取的灾害记载。")
        self.assertEqual([item[0] for item in calls], ["attachment.inspect", "domain_agent.consult"])
        self.assertIn("ATTACHMENT_INSPECTION_RECEIPTS", calls[1][1]["question"])
        model.assert_not_called()
        codex_turn.assert_not_called()

    def test_generic_spreadsheet_attachment_uses_the_only_inspector_domain_agent(self) -> None:
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://example.invalid/v1", "HRW_AGENT_API_KEY": "secret",
            "HRW_MOA_ENABLED": "0", "WENJIN_HARNESS_BACKEND": "codex",
        }
        plugin = {
            "name": "disaster-history", "kind": "domain", "status": "ready",
            "agent_tools": ["inspect_half_finished_workbook"], "agent": {"routing_triggers": []},
        }
        attachment_id = "ATT_" + "b" * 32
        calls = []

        def execute(_project, _run, tool, arguments):
            calls.append((tool, arguments))
            if tool == "attachment.inspect":
                return {"kind": "spreadsheet", "absolute_path": "C:/tmp/source.xlsx"}
            return {
                "latest_message": {"content": {"text": "只读检查完成。"}},
                "latest_run": {"status": "COMPLETED"},
            }

        with patch.dict(os.environ, environment, clear=False):
            sync_model_profiles(self.project)
            assign_model(self.project, "environment-main")
            with patch("research_workbench.domain_plugins.plugin_state", return_value={"plugins": [plugin]}), patch(
                "research_workbench.agent_runtime._execute_tool", side_effect=execute,
            ), patch(
                "research_workbench.agent_runtime._model_action",
                return_value={"type": "tool_call", "tool": "attachment.inspect", "arguments": {"attachment_id": attachment_id}},
            ), patch("research_workbench.codex_harness.run_turn") as codex_turn:
                result = send_message(
                    self.project, self.thread["thread_id"], "请检查本轮附件",
                    context={"attached_refs": [{"attachment_id": attachment_id, "original_name": "source.xlsx"}]},
                    access_mode="research_assist",
                )
        self.assertEqual(result["runs"][0]["status"], "COMPLETED")
        self.assertEqual([item[0] for item in calls], ["attachment.inspect", "domain_agent.consult"])
        codex_turn.assert_not_called()

    def test_explicit_domain_tool_still_routes_directly_to_its_domain_agent(self) -> None:
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://example.invalid/v1", "HRW_AGENT_API_KEY": "secret",
            "HRW_MOA_ENABLED": "0",
        }
        plugin = {
            "name": "disaster-history", "kind": "domain", "status": "ready",
            "agent_tools": ["run_book_pages"],
            "agent": {"id": "disaster-researcher", "routing_triggers": ["南昌县志"]},
        }
        view = {
            "session": {"session_id": "DAS_1", "plugin_name": "disaster-history"},
            "messages": [{"role": "assistant", "content": {"text": "candidate ready"}}],
            "runs": [{"run_id": "DRN_1", "status": "COMPLETED"}], "artifacts": [],
        }
        with patch.dict(os.environ, environment, clear=False):
            sync_model_profiles(self.project)
            assign_model(self.project, "environment-main")
            with patch("research_workbench.domain_plugins.plugin_state", return_value={"plugins": [plugin]}), patch(
                "research_workbench.domain_agents.send_domain_message", return_value=view,
            ) as consult, patch("research_workbench.agent_runtime._model_action") as model:
                result = send_message(
                    self.project, self.thread["thread_id"],
                    "处理南昌县志，只调用一次 run_book_pages。", access_mode="research_assist",
                )
        self.assertEqual(result["runs"][0]["status"], "COMPLETED")
        consult.assert_called_once()
        model.assert_not_called()

    def test_explicit_single_event_batch_completes_from_tool_receipt(self) -> None:
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://example.invalid/v1", "HRW_AGENT_API_KEY": "secret",
        }
        actions = iter([
            {
                "type": "tool_call", "tool": "research_event.propose_batch",
                "arguments": {"events": [{"case_id": "CASE_1"}]},
            },
        ])

        with patch.dict(os.environ, environment, clear=False):
            sync_model_profiles(self.project)
            assign_model(self.project, "environment-main")
            with (
                patch("research_workbench.agent_runtime._model_action", side_effect=lambda *args: next(actions)) as model,
                patch(
                    "research_workbench.agent_runtime.create_event_candidates",
                    return_value=[{"event_id": "EVT_1"}],
                ),
            ):
                result = send_message(
                    self.project, self.thread["thread_id"],
                    "只调用一次 research_event.propose_batch 保存候选，随后结束。",
                )

        run = result["runs"][0]
        self.assertEqual(run["status"], "COMPLETED")
        self.assertEqual(model.call_count, 1)
        self.assertIn("已保存 1 条待审事件候选", result["messages"][-1]["content"]["text"])

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

    def test_claimed_event_submission_requires_an_actual_tool_receipt(self) -> None:
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://example.invalid/v1", "HRW_AGENT_API_KEY": "secret",
        }
        actions = iter([
            {"type": "final", "content": "现提交5条待审候选。"},
            {
                "type": "tool_call", "tool": "research_event.propose_batch",
                "arguments": {"events": [{"case_id": "CASE_1"}]},
            },
            {"type": "final", "content": "已依据工具回执提交5条待审候选。"},
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
                    "先核对来源，最多一次 research_event.propose_batch，按证据边界提案。",
                )

        run = result["runs"][0]
        self.assertIn("required_tool_missing", [event["event_type"] for event in run["events"]])
        create_candidates.assert_called_once()

    def test_negative_event_submission_statement_does_not_force_a_write(self) -> None:
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://example.invalid/v1", "HRW_AGENT_API_KEY": "secret",
        }
        with patch.dict(os.environ, environment, clear=False):
            sync_model_profiles(self.project)
            assign_model(self.project, "environment-main")
            with patch(
                "research_workbench.agent_runtime._model_action",
                return_value={"type": "final", "content": "核验完成，未提交任何事件。"},
            ):
                result = send_message(
                    self.project, self.thread["thread_id"],
                    "检查是否适合 research_event.propose_batch，不合适就停止。",
                )

        run = result["runs"][0]
        self.assertNotIn("required_tool_missing", [event["event_type"] for event in run["events"]])
        self.assertFalse(run["tool_calls"])

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
        self.assertIn("研究产物已保存", script)
        self.assertIn("artifact_receipt", script)

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

    def test_agent_can_persist_reading_job_and_historiography(self) -> None:
        source_id = list_sources(self.project)[0]["source_id"]
        connection = sqlite3.connect(database_path(self.project))
        try:
            run_id = connection.execute("SELECT run_id FROM runs LIMIT 1").fetchone()
            if run_id is None:
                result = send_message(self.project, self.thread["thread_id"], "check")
                run_id = (result["runs"][0]["run_id"],)
        finally:
            connection.close()

        reading = _execute_tool(
            self.project,
            run_id[0],
            "reading_job.create",
            {
                "title": "直接研究定向阅读",
                "question": "作者如何解释旅行者的地方中介？",
                "mode": "targeted",
                "source_ids": [source_id],
                "stop_condition": "连续两轮不再出现新的材料路径。",
            },
        )
        self.assertEqual(reading["status"], "running")
        indexed = _agent_research_state(self.project)
        indexed_job = next(item for item in indexed["reading_jobs"] if item["job_id"] == reading["job_id"])
        self.assertEqual(indexed_job["source_ids"], [source_id])
        self.assertEqual(indexed_job["note_count"], 0)
        self.assertNotIn("notes", indexed_job)
        batch = _execute_tool(
            self.project,
            run_id[0],
            "reading_job.batch",
            {"job_id": reading["job_id"], "source_id": source_id, "page_limit": 10},
        )
        self.assertTrue(batch["pages"])
        self.assertIn("text", batch["pages"][0])
        self.assertNotIn("blocks", batch["pages"][0])
        saved = _execute_tool(
            self.project,
            run_id[0],
            "reading_note.save",
            {
                "job_id": reading["job_id"],
                "source_id": source_id,
                "physical_pages": [page["physical_page"] for page in batch["pages"]],
                "content": "作者从地方中介解释旅行者的移动。",
                "complete": True,
            },
        )
        self.assertEqual(saved["status"], "completed")
        historiography = _execute_tool(
            self.project,
            run_id[0],
            "historiography.create",
            {
                "work_title": "Test source",
                "position": "从地方中介解释进入路径",
                "contribution": "识别道路使用者和引导者",
                "limitation": "未比较三个考察案例",
                "relevance": "作为中介网络解释路径的直接研究",
                "source_refs": [source_id],
            },
        )
        self.assertEqual(historiography["status"], "candidate")
        self.assertIn('"tool":"reading_job.create"', SYSTEM_PROMPT)
        self.assertIn('"tool":"reading_job.batch"', SYSTEM_PROMPT)
        self.assertIn('"tool":"reading_note.save"', SYSTEM_PROMPT)
        self.assertIn('"tool":"historiography.create"', SYSTEM_PROMPT)

    def test_reading_tools_bind_canonical_source_identity_and_report_savable_pages(self) -> None:
        source_id = list_sources(self.project)[0]["source_id"]
        connection = sqlite3.connect(database_path(self.project))
        try:
            run_id = connection.execute("SELECT run_id FROM runs LIMIT 1").fetchone()
            if run_id is None:
                result = send_message(self.project, self.thread["thread_id"], "check")
                run_id = (result["runs"][0]["run_id"],)
            connection.execute(
                "UPDATE pages SET use_state = 'blocked' WHERE source_id = ? AND physical_page = 2",
                (source_id,),
            )
            connection.commit()
        finally:
            connection.close()
        reading = _execute_tool(
            self.project, run_id[0], "reading_job.create",
            {"title": "身份校验", "question": "如何论证？", "mode": "targeted",
             "source_ids": [source_id], "stop_condition": "读完当前页。"},
        )
        batch = _execute_tool(
            self.project, run_id[0], "reading_job.batch",
            {"job_id": reading["job_id"], "source_id": source_id, "page_limit": 10},
        )
        self.assertEqual(batch["source_identity"]["source_id"], source_id)
        self.assertEqual(batch["canonical_title"], "Test source")
        self.assertEqual(batch["blocked_or_unusable_physical_pages"], [2])
        with self.assertRaisesRegex(ValueError, "savable_physical_pages") as blocked:
            _execute_tool(
                self.project, run_id[0], "reading_note.save",
                {"job_id": reading["job_id"], "source_id": source_id,
                 "physical_pages": [2], "content": "分析。"},
            )
        self.assertIn(source_id, str(blocked.exception))

        saved = _execute_tool(
            self.project, run_id[0], "reading_note.save",
            {"job_id": reading["job_id"], "source_id": source_id,
             "physical_pages": [1], "content": "作者强调地方中介。", "complete": True},
        )
        self.assertEqual(saved["source_identity"]["canonical_title"], "Test source")
        with connect(self.project) as project_connection:
            content = project_connection.execute(
                "SELECT content FROM reading_notes WHERE note_id = ?", (saved["note_id"],),
            ).fetchone()[0]
        self.assertTrue(content.startswith(f"[来源身份｜source_id={source_id}｜canonical_title=《Test source》]"))

    def test_wrong_source_reading_note_is_rejected_and_cannot_feed_historiography(self) -> None:
        source_id = list_sources(self.project)[0]["source_id"]
        result = send_message(self.project, self.thread["thread_id"], "check")
        run_id = result["runs"][0]["run_id"]
        reading = _execute_tool(
            self.project, run_id, "reading_job.create",
            {"title": "身份校验", "question": "如何论证？", "mode": "targeted",
             "source_ids": [source_id], "stop_condition": "读完当前页。"},
        )
        with self.assertRaisesRegex(ValueError, "source identity mismatch"):
            _execute_tool(
                self.project, run_id, "reading_note.save",
                {"job_id": reading["job_id"], "source_id": source_id, "physical_pages": [1],
                 "content": "来源题名：张晓虹的另一篇研究\n作者强调地方中介。"},
            )
        with connect(self.project) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM reading_notes").fetchone()[0], 0)
        with self.assertRaisesRegex(ValueError, "no identity-consistent reading note"):
            _execute_tool(
                self.project, run_id, "historiography.create",
                {"work_title": "Test source", "position": "立场", "contribution": "贡献",
                 "limitation": "限制", "relevance": "关系", "source_refs": [source_id]},
            )

    def test_historiography_requires_human_decision_before_consumption(self) -> None:
        source_id = list_sources(self.project)[0]["source_id"]
        result = send_message(self.project, self.thread["thread_id"], "check")
        run_id = result["runs"][0]["run_id"]
        reading = _execute_tool(
            self.project, run_id, "reading_job.create",
            {"title": "定向阅读", "question": "如何论证？", "mode": "targeted",
             "source_ids": [source_id], "stop_condition": "当前页。"},
        )
        _execute_tool(
            self.project, run_id, "reading_note.save",
            {"job_id": reading["job_id"], "source_id": source_id, "physical_pages": [1],
             "content": "作者强调地方中介。", "complete": True},
        )
        entry = _execute_tool(
            self.project, run_id, "historiography.create",
            {"work_title": "Test source", "position": "立场", "contribution": "贡献",
             "limitation": "限制", "relevance": "关系", "source_refs": [source_id]},
        )
        decided = decide_historiography_entry(
            self.project, entry["entry_id"], True, "Professor", "核对来源身份和阅读札记。",
        )
        self.assertEqual(decided["status"], "approved")
        self.assertEqual(decided["decision"]["reviewer"], "Professor")
        with self.assertRaisesRegex(ValueError, "already approved"):
            decide_historiography_entry(
                self.project, entry["entry_id"], False, "Professor", "不能重复决定。",
            )

    def test_human_historiography_decision_quarantines_legacy_wrong_identity_note(self) -> None:
        source_id = list_sources(self.project)[0]["source_id"]
        result = send_message(self.project, self.thread["thread_id"], "check")
        run_id = result["runs"][0]["run_id"]
        reading = _execute_tool(
            self.project, run_id, "reading_job.create",
            {"title": "定向阅读", "question": "如何论证？", "mode": "targeted",
             "source_ids": [source_id], "stop_condition": "当前页。"},
        )
        _execute_tool(
            self.project, run_id, "reading_note.save",
            {"job_id": reading["job_id"], "source_id": source_id, "physical_pages": [1],
             "content": "作者强调地方中介。", "complete": True},
        )
        with connect(self.project) as connection:
            connection.execute(
                """INSERT INTO reading_notes(note_id, job_id, source_id, page_refs_json, content,
                   qualification, created_at) VALUES ('RDN_legacy_wrong', ?, ?, '[]', ?,
                   'READING_NOTE_NOT_EVIDENCE', '2026-01-01')""",
                (reading["job_id"], source_id, "来源题名：张晓虹的另一篇研究\n错误旧札记。"),
            )
        entry = _execute_tool(
            self.project, run_id, "historiography.create",
            {"work_title": "Test source", "position": "立场", "contribution": "贡献",
             "limitation": "限制", "relevance": "关系", "source_refs": [source_id]},
        )
        decide_historiography_entry(
            self.project, entry["entry_id"], True, "Professor", "保留正确札记并隔离错误旧札记。",
        )
        with connect(self.project) as connection:
            qualification = connection.execute(
                "SELECT qualification FROM reading_notes WHERE note_id = 'RDN_legacy_wrong'"
            ).fetchone()[0]
        self.assertEqual(qualification, "QUARANTINED_SOURCE_IDENTITY_MISMATCH")

    def test_current_schema_migration_does_not_commit_an_active_transaction(self) -> None:
        connection = sqlite3.connect(database_path(self.project))
        connection.row_factory = sqlite3.Row
        stage = "UNCOMMITTED"
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE projects SET current_stage = 'UNCOMMITTED'")
            _migrate(connection)
            connection.rollback()
            stage = connection.execute("SELECT current_stage FROM projects").fetchone()[0]
        finally:
            connection.close()
        self.assertNotEqual(stage, "UNCOMMITTED")

    def test_connect_waits_for_a_concurrent_writer_in_wal_mode(self) -> None:
        holder = sqlite3.connect(database_path(self.project), check_same_thread=False)
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("UPDATE projects SET current_stage = current_stage")
        outcome: list[object] = []

        def write_after_lock() -> None:
            try:
                with connect(self.project) as connection:
                    outcome.append(connection.execute("PRAGMA busy_timeout").fetchone()[0])
                    outcome.append(connection.execute("PRAGMA journal_mode").fetchone()[0])
                    connection.execute("UPDATE projects SET current_stage = current_stage")
            except Exception as error:
                outcome.append(error)

        worker = threading.Thread(target=write_after_lock)
        worker.start()
        threading.Event().wait(0.1)
        holder.commit()
        holder.close()
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(outcome, [30000, "wal"])

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
        self.assertEqual(version, SCHEMA_VERSION)
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

    def test_deepseek_domain_reasoning_mode_is_sent_explicitly(self) -> None:
        requests: list[object] = []

        def respond(request: object, timeout: float, **_: object) -> FakeResponse:
            requests.append(request)
            return FakeResponse({"choices": [{"message": {"content": '{"type":"final","content":"ok"}'}}]})

        profile = ModelProfile(
            "deepseek-test", "openai_compatible", "deepseek-v4-flash", "https://api.deepseek.com",
            ("text", "tool_calling"), "credential", "available", "secret", 5,
        )
        with patch("research_workbench.agent_runtime.urlopen", side_effect=respond):
            self.assertEqual(
                _model_action(profile, "check", [], reasoning_mode="deep", reasoning_effort="high")["type"],
                "final",
            )
        payload = json.loads(getattr(requests[0], "data").decode("utf-8"))
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertEqual(payload["reasoning_effort"], "high")

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

    def test_provider_timeout_marks_run_failed_inside_runtime(self) -> None:
        now = "2026-01-01T00:00:00Z"
        with connect(self.project) as connection:
            connection.execute(
                "INSERT INTO goals(goal_id, thread_id, objective, status, created_at) "
                "VALUES ('GOL_timeout', ?, 'timeout', 'active', ?)",
                (self.thread["thread_id"], now),
            )
            connection.execute(
                """INSERT INTO runs(run_id, thread_id, goal_id, status, model_snapshot_json,
                   created_at, updated_at) VALUES ('RUN_timeout', ?, 'GOL_timeout', 'RUNNING', '{}', ?, ?)""",
                (self.thread["thread_id"], now, now),
            )
        profile = ModelProfile(
            "timeout", "openai_compatible", "remote", "https://models.invalid/v1",
            ("text",), "env:key", "available", "secret", 0.01,
        )
        with patch(
            "research_workbench.agent_runtime._model_action",
            side_effect=TimeoutError("agent provider step exceeded 0.01 seconds"),
        ):
            with self.assertRaisesRegex(TimeoutError, "exceeded"):
                _advance_run(self.project, "RUN_timeout", "timeout", profile)
        with connect(self.project) as connection:
            run = connection.execute(
                "SELECT status, error, completed_at FROM runs WHERE run_id = 'RUN_timeout'"
            ).fetchone()
            goal = connection.execute(
                "SELECT status FROM goals WHERE goal_id = 'GOL_timeout'"
            ).fetchone()
            failures = connection.execute(
                "SELECT COUNT(*) FROM run_events WHERE run_id = 'RUN_timeout' AND event_type = 'run_failed'"
            ).fetchone()[0]
        self.assertEqual(run["status"], "FAILED")
        self.assertIn("exceeded", run["error"])
        self.assertTrue(run["completed_at"])
        self.assertEqual(goal["status"], "failed")
        self.assertEqual(failures, 1)

    def test_transient_provider_error_retries_once_inside_runtime(self) -> None:
        now = "2026-01-01T00:00:00Z"
        with connect(self.project) as connection:
            connection.execute(
                "INSERT INTO goals(goal_id, thread_id, objective, status, created_at) "
                "VALUES ('GOL_retry', ?, 'retry', 'active', ?)",
                (self.thread["thread_id"], now),
            )
            connection.execute(
                """INSERT INTO runs(run_id, thread_id, goal_id, status, model_snapshot_json,
                   created_at, updated_at) VALUES ('RUN_retry', ?, 'GOL_retry', 'RUNNING', '{}', ?, ?)""",
                (self.thread["thread_id"], now, now),
            )
        profile = ModelProfile(
            "retry", "openai_compatible", "remote", "https://models.invalid/v1",
            ("text",), "env:key", "available", "secret", 1,
        )
        with patch(
            "research_workbench.agent_runtime._model_action",
            side_effect=[RuntimeError("agent provider returned HTTP 429"), {"type": "final", "content": "已完成。"}],
        ) as action:
            _advance_run(self.project, "RUN_retry", "retry", profile)
        self.assertEqual(action.call_count, 2)
        with connect(self.project) as connection:
            events = connection.execute(
                "SELECT event_type FROM run_events WHERE run_id = 'RUN_retry' ORDER BY sequence"
            ).fetchall()
        self.assertIn("model_request_retry", [event["event_type"] for event in events])

    def test_model_http_error_includes_safe_provider_detail(self) -> None:
        error = HTTPError(
            "https://models.invalid/chat/completions", 400, "bad request", {},
            io.BytesIO(b'{"error":{"code":"invalid_request","message":"model is unavailable"}}'),
        )
        with patch("research_workbench.agent_runtime.urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "invalid_request.*model is unavailable"):
                _post_json("https://models.invalid/chat/completions", {}, {}, 1)

    def test_parser_uses_first_action_when_provider_batches_json_objects(self) -> None:
        action = _parse_action(
            '{"type":"tool_call","tool":"project.status","arguments":{}}\n'
            '{"type":"tool_call","tool":"source.list","arguments":{}}'
        )
        self.assertEqual(action["tool"], "project.status")

    def test_parser_treats_plain_provider_text_as_safe_final_answer(self) -> None:
        action = _parse_action("候选页已定位；请人工核对原页。")
        self.assertEqual(action, {"type": "final", "content": "候选页已定位；请人工核对原页。"})

    def test_system_prompt_separates_processing_state_from_material_quality(self) -> None:
        self.assertIn("Never translate a blocked, pending, partial or zero-page processing state", SYSTEM_PROMPT)
        self.assertIn("page processing is unfinished", SYSTEM_PROMPT)
        self.assertIn("compact, bounded index", SYSTEM_PROMPT)
        self.assertIn('source_ids=["..."]', SYSTEM_PROMPT)

    def test_planning_context_explains_source_state_semantics(self) -> None:
        context = _planning_context(self.project)
        semantics = context["source_state_semantics"]
        self.assertIn("not the historical value", semantics["processing_state"])
        self.assertIn("not evidence", semantics["zero_pages"])

    def test_parser_accepts_observed_deepseek_tool_wrappers_only_when_they_wrap_the_whole_action(self) -> None:
        action = _parse_action(
            '<json_logic><tool_call>{"type":"tool_call","tool":"source.page",'
            '"arguments":{"source_id":"SRC_1","physical_page":251}}</tool_call></json_logic>'
        )
        self.assertEqual(action["tool"], "source.page")
        self.assertEqual(action["arguments"]["physical_page"], 251)
        prose = '示例：<tool_call>{"type":"tool_call","tool":"source.page","arguments":{}}</tool_call>'
        self.assertEqual(_parse_action(prose), {"type": "final", "content": prose})

    def test_parser_accepts_observed_deepseek_pro_repeated_tool_call_wrapper(self) -> None:
        action = _parse_action(
            '<tool_call type="tool_call"><tool_call name="source.page">'
            '{"source_id":"SRC_1","physical_page":251}'
            '</tool_call></tool_call>'
        )
        self.assertEqual(action, {
            "type": "tool_call", "tool": "source.page",
            "arguments": {"source_id": "SRC_1", "physical_page": 251},
        })
        full_action = _parse_action(
            '<tool_call type="tool_call"><tool_call type="tool_call">'
            '{"type":"tool_call","tool":"source.list","arguments":{}}'
            '</tool_call></tool_call>'
        )
        self.assertEqual(full_action, {
            "type": "tool_call", "tool": "source.list", "arguments": {},
        })
        truncated_outer = _parse_action(
            '<tool_call type="tool_call"><tool_call name="source.page">'
            '{"source_id":"SRC_1","physical_page":252}'
            '</tool_call>'
        )
        self.assertEqual(truncated_outer, {
            "type": "tool_call", "tool": "source.page",
            "arguments": {"source_id": "SRC_1", "physical_page": 252},
        })

    def test_parser_rejects_ambiguous_repeated_tool_call_wrapper(self) -> None:
        malformed = (
            '<tool_call name="source.list"><tool_call name="project.status">'
            '{"type":"tool_call","tool":"project.status","arguments":{}}'
            '</tool_call></tool_call>'
        )
        with self.assertRaisesRegex(ValueError, "multiple tools"):
            _parse_action(malformed)
        self.assertTrue(_looks_like_internal_tool_transcript(malformed))
        self.assertTrue(_looks_like_internal_tool_transcript("我将调用工具：\n" + malformed))

    def test_nested_tool_wrapper_retries_then_executes_without_persisting_wrapper(self) -> None:
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://models.invalid/v1", "HRW_AGENT_API_KEY": "secret",
        }
        responses = iter([
            FakeResponse({"choices": [{"message": {"content": (
                '<tool_call name="source.list"><tool_call name="project.status">'
                '{"type":"tool_call","tool":"project.status","arguments":{}}'
                '</tool_call></tool_call>'
            )}}]}),
            FakeResponse({"choices": [{"message": {"content": (
                '<tool_call type="tool_call"><tool_call name="project.status">'
                '{}'
                '</tool_call></tool_call>'
            )}}]}),
            FakeResponse({"choices": [{"message": {"content": (
                '{"type":"final","content":"已读取项目状态并完成检查。"}'
            )}}]}),
        ])
        with patch.dict(os.environ, environment, clear=False):
            sync_model_profiles(self.project)
            assign_model(self.project, "environment-main")
            with patch("research_workbench.agent_runtime.urlopen", side_effect=lambda *_args, **_kwargs: next(responses)):
                result = send_message(self.project, self.thread["thread_id"], "读取项目状态")

        run = result["runs"][0]
        self.assertEqual(run["status"], "COMPLETED")
        self.assertEqual([call["tool_name"] for call in run["tool_calls"]], ["project.status"])
        self.assertIn("model_action_invalid", [event["event_type"] for event in run["events"]])
        assistant_text = result["messages"][-1]["content"]["text"]
        self.assertEqual(assistant_text, "已读取项目状态并完成检查。")
        self.assertNotIn("tool_call", assistant_text)

    def test_repeated_internal_wrapper_final_fails_without_persisting_assistant_text(self) -> None:
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "test-model",
            "HRW_AGENT_BASE_URL": "https://models.invalid/v1", "HRW_AGENT_API_KEY": "secret",
        }
        internal = (
            '我将调用工具：<tool_call name="source.list">'
            '{"type":"tool_call","tool":"source.list","arguments":{}}'
            '</tool_call>'
        )
        with patch.dict(os.environ, environment, clear=False):
            sync_model_profiles(self.project)
            assign_model(self.project, "environment-main")
            with patch(
                "research_workbench.agent_runtime._model_action",
                return_value={"type": "final", "content": internal},
            ) as model_action:
                with self.assertRaisesRegex(RuntimeError, "internal TOOL_RESULT transcripts"):
                    send_message(self.project, self.thread["thread_id"], "读取来源")

        self.assertEqual(model_action.call_count, 2)
        thread = thread_view(self.project, self.thread["thread_id"])
        run = thread["runs"][0]
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual([message["role"] for message in thread["messages"]], ["user"])
        self.assertNotIn(internal, json.dumps(thread, ensure_ascii=False))

    def test_parser_accepts_deepseek_pro_tagged_tool_action(self) -> None:
        action = _parse_action(
            '<tool_call><type>tool_call</type><tool>source.search</tool>'
            '<arguments>{"query":"1861","source_id":"SRC_1","limit":10}</arguments></invoke>'
        )
        self.assertEqual(action, {
            "type": "tool_call", "tool": "source.search",
            "arguments": {"query": "1861", "source_id": "SRC_1", "limit": 10},
        })

    def test_parser_accepts_deepseek_pro_invoke_parameters(self) -> None:
        action = _parse_action(
            '<tool_calls><invoke name="source.search">'
            '<parameter name="query">1879</parameter>'
            '<parameter name="source_id">SRC_1</parameter>'
            '<parameter name="limit">10</parameter>'
            '</invoke></tool_calls>'
        )
        self.assertEqual(action, {
            "type": "tool_call", "tool": "source.search",
            "arguments": {"query": 1879, "source_id": "SRC_1", "limit": 10},
        })

    def test_parser_accepts_extra_invoke_parameter_attributes(self) -> None:
        action = _parse_action(
            '<tool_calls><invoke name="source.page">'
            '<parameter name="source_id" string="true">SRC_1</parameter>'
            '<parameter name="physical_page" type="number">230</parameter>'
            '</invoke></tool_calls>'
        )
        self.assertEqual(action["arguments"], {"source_id": "SRC_1", "physical_page": 230})

    def test_parser_accepts_bare_invoke(self) -> None:
        action = _parse_action(
            '<invoke name="source.search">'
            '<parameter name="query">Tfinling</parameter>'
            '<parameter name="source_id">SRC_1</parameter>'
            '<parameter name="limit">10</parameter>'
            '</invoke>'
        )
        self.assertEqual(action["tool"], "source.search")
        self.assertEqual(action["arguments"]["query"], "Tfinling")

    def test_parser_accepts_observed_deepseek_dsml_only_as_the_whole_response(self) -> None:
        action = _parse_action(
            '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="source.page">'
            '<｜｜DSML｜｜parameter argument="source_id" string="true">SRC_1</｜｜DSML｜｜parameter>'
            '<｜｜DSML｜｜parameter argument="physical_page">232</｜｜DSML｜｜parameter>'
            '</｜｜DSML｜｜invoke></｜｜DSML｜｜tool_calls>'
        )
        self.assertEqual(action, {
            "type": "tool_call", "tool": "source.page",
            "arguments": {"source_id": "SRC_1", "physical_page": 232},
        })
        prose = '模型示例：<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="source.page"></｜｜DSML｜｜invoke></｜｜DSML｜｜tool_calls>'
        self.assertEqual(_parse_action(prose), {"type": "final", "content": prose})

    def test_parser_decodes_dsml_json_arguments(self) -> None:
        action = _parse_action(
            '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="research_event.list">'
            '<｜｜DSML｜｜parameter argument="case_ids">["DAVID"]</｜｜DSML｜｜parameter>'
            '</｜｜DSML｜｜invoke></｜｜DSML｜｜tool_calls>'
        )
        self.assertEqual(action["arguments"]["case_ids"], ["DAVID"])

    def test_parser_accepts_dsml_name_attribute_observed_from_deepseek(self) -> None:
        action = _parse_action(
            '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="source.page">'
            '<｜｜DSML｜｜parameter argument="physical_page" string="true">230</｜｜DSML｜｜parameter>'
            '<｜｜DSML｜｜parameter name="source_id" string="true">SRC_1</｜｜DSML｜｜parameter>'
            '</｜｜DSML｜｜invoke></｜｜DSML｜｜tool_calls>'
        )
        self.assertEqual(action, {
            "type": "tool_call", "tool": "source.page",
            "arguments": {"physical_page": "230", "source_id": "SRC_1"},
        })

    def test_parser_accepts_dsml_packed_arguments_observed_from_deepseek(self) -> None:
        action = _parse_action(
            '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="research_event.list">'
            '<｜｜DSML｜｜parameter arguments="{}" string="true">{}</｜｜DSML｜｜parameter>'
            '</｜｜DSML｜｜invoke></｜｜DSML｜｜tool_calls>'
        )
        self.assertEqual(action, {
            "type": "tool_call", "tool": "research_event.list", "arguments": {},
        })

        malformed = (
            '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="research_event.list">'
            '<｜｜DSML｜｜parameter arguments="[]">[]</｜｜DSML｜｜parameter>'
            '</｜｜DSML｜｜invoke></｜｜DSML｜｜tool_calls>'
        )
        self.assertEqual(_parse_action(malformed), {"type": "final", "content": malformed})

    def test_parser_accepts_observed_angle_bracketed_action_only_as_the_whole_response(self) -> None:
        action = _parse_action(
            '<{"type":"tool_call","tool":"research_event.list","arguments":{}}>'
        )
        self.assertEqual(action["type"], "tool_call")
        self.assertEqual(action["tool"], "research_event.list")
        prose = '模型示例：<{"type":"tool_call","tool":"research_event.list","arguments":{}}>'
        self.assertEqual(_parse_action(prose), {"type": "final", "content": prose})

    def test_parser_normalizes_unambiguous_local_model_aliases(self) -> None:
        self.assertEqual(
            _parse_action('{"tool":"source.list","arguments":{}}'),
            {"type": "tool_call", "tool": "source.list", "arguments": {}},
        )
        self.assertEqual(
            _parse_action('{"action":"final","content":"审稿完成"}'),
            {"type": "final", "action": "final", "content": "审稿完成"},
        )
        self.assertEqual(
            _parse_action('{"final_answer":"审稿完成"}'),
            {"type": "final", "content": "审稿完成"},
        )

    def test_agent_prompt_routes_coverage_audits_to_deterministic_tool(self) -> None:
        self.assertIn('"tool":"research_event.coverage"', SYSTEM_PROMPT)
        self.assertIn("exact intended case_ids", SYSTEM_PROMPT)
        self.assertIn('statuses=["approved"] and detail="summary"', SYSTEM_PROMPT)
        self.assertIn("end_place is the journey endpoint", SYSTEM_PROMPT)
        self.assertIn("outcome_destination is where a research or knowledge product goes", SYSTEM_PROMPT)
        self.assertIn("never put lodging", SYSTEM_PROMPT)
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
        self.assertEqual(len(page["adjacent_relations"]), 1)
        self.assertEqual(page["adjacent_relations"][0]["from_block_id"], f"{source_id}:B2")
        self.assertEqual(page["adjacent_relations"][0]["to_block_id"], f"{source_id}:B3")
        self.assertTrue(page["adjacent_relations"][0]["effective_value"])
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
