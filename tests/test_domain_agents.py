from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_workbench.agent_runtime import create_thread, recover_interrupted_runs
from research_workbench.attachments import save_attachment
from research_workbench.db import SCHEMA_VERSION, connect, utc_now
from research_workbench.domain_agents import (
    _domain_history, _domain_prompt, _nested_domain_tool_action, _tool_requirements, ensure_domain_session,
    send_domain_message,
)
from research_workbench.service import initialize_project


class DomainAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        initialize_project(self.project, "domain agent")
        self.plugin = {
            "name": "disaster-history", "display_name": "灾害史Subagent",
            "kind": "domain", "status": "ready", "agent_tools": ["inspect", "build_candidate"],
            "tool_permissions": {"inspect": "read", "build_candidate": "routine"},
            "boundaries": ["outputs remain candidates"],
            "agent": {"id": "disaster-researcher", "display_name": "灾害史Subagent"},
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_schema_23_adds_isolated_domain_agent_tables(self) -> None:
        with connect(self.project) as connection:
            version = connection.execute("SELECT MAX(version) FROM schema_meta").fetchone()[0]
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(version, SCHEMA_VERSION)
        self.assertTrue({"domain_agent_sessions", "domain_agent_messages", "domain_agent_runs", "domain_agent_tool_calls", "domain_agent_artifacts"} <= tables)

    def test_domain_agent_prompt_loads_its_installed_skill(self) -> None:
        root = self.project / "plugin"
        skill = root / "skills" / "domain" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("确定性程序先行；模型只提出候选。", encoding="utf-8")
        prompt = _domain_prompt({
            **self.plugin, "installed_path": str(root),
            "skills": ["skills/domain/SKILL.md"],
        })
        self.assertIn("确定性程序先行", prompt)
        self.assertIn("Do not replace an available program step", prompt)

    def test_domain_agent_prompt_includes_mcp_argument_contract(self) -> None:
        prompt = _domain_prompt(self.plugin, [{
            "name": "inspect", "inputSchema": {
                "type": "object", "properties": {"input_path": {"type": "string"}},
                "required": ["input_path"],
            },
        }])
        self.assertIn('"input_path"', prompt)
        self.assertIn('"required": ["input_path"]', prompt)

    def test_numbered_disaster_samples_require_one_program_call_each(self) -> None:
        plugin = {
            **self.plugin,
            "agent_tools": ["normalize_disaster_type"],
            "agent": {
                **self.plugin["agent"],
                "tool_triggers": {"normalize_disaster_type": ["灾种不明"]},
            },
        }
        requirements = _tool_requirements(
            plugin, "请分别调用 normalize_disaster_type 核对：①蝗灾；②大旱；③岁饥；④大风。"
        )
        self.assertEqual(requirements[0]["minimum_calls"], 4)

    def test_explicit_tool_call_count_is_a_completion_requirement(self) -> None:
        plugin = {**self.plugin, "agent_tools": ["historical_admin_lookup"]}
        requirements = _tool_requirements(
            plugin, "必须分别调用 historical_admin_lookup 三次，再比较回执。"
        )
        self.assertEqual(requirements[0]["minimum_calls"], 3)

    def test_negated_domain_trigger_does_not_require_the_opposite_action(self) -> None:
        plugin = {
            **self.plugin,
            "agent_tools": ["run_book_pages"],
            "agent": {**self.plugin["agent"], "tool_triggers": {"run_book_pages": ["整书"]}},
        }
        self.assertEqual(_tool_requirements(plugin, "只判断图片，不要启动整书处理"), [])
        self.assertEqual(_tool_requirements(plugin, "这是一项整书研究，但先讨论方案"), [])

    def test_domain_agent_keeps_private_thread_and_records_candidate_artifact(self) -> None:
        main_thread = create_thread(self.project, "main")
        output = self.project / "domain" / "candidate.xlsx"
        actions = iter([
            {"type": "tool_call", "tool": "build_candidate", "arguments": {"input": "source.xlsx"}},
            {"type": "final", "content": "候选工作簿已经生成，仍需主Agent和用户复核。"},
        ])
        with patch("research_workbench.domain_agents._plugin", return_value=self.plugin), patch(
            "research_workbench.domain_agents._model_action", side_effect=lambda *args, **kwargs: next(actions),
        ), patch(
            "research_workbench.domain_agents.call_domain_plugin_tool",
            return_value={"structuredContent": {"output_path": str(output), "status": "candidate"}},
        ):
            result = send_domain_message(
                self.project, "disaster-history", "建立候选", main_thread_id=main_thread["thread_id"],
                access_mode="research_assist",
            )
        self.assertEqual(result["session"]["plugin_name"], "disaster-history")
        self.assertEqual([item["role"] for item in result["messages"]], ["user", "assistant"])
        self.assertEqual(result["runs"][0]["status"], "COMPLETED")
        self.assertEqual(result["runs"][0]["tool_calls"][0]["tool_name"], "build_candidate")
        self.assertEqual(result["artifacts"][0]["status"], "candidate")
        self.assertEqual(result["artifacts"][0]["native_path"], str(output.resolve()))
        with connect(self.project) as connection:
            main_messages = connection.execute(
                "SELECT COUNT(*) FROM messages WHERE thread_id=?", (main_thread["thread_id"],)
            ).fetchone()[0]
        self.assertEqual(main_messages, 0)

    def test_explicit_domain_candidate_write_runs_in_ask_mode_without_permission_loop(self) -> None:
        actions = iter([
            {"type": "tool_call", "tool": "build_candidate", "arguments": {"input": "source.xlsx"}},
            {"type": "final", "content": "候选已生成。"},
        ])
        with patch("research_workbench.domain_agents._plugin", return_value=self.plugin), patch(
            "research_workbench.domain_agents._model_action", side_effect=lambda *args, **kwargs: next(actions),
        ), patch(
            "research_workbench.domain_agents.call_domain_plugin_tool",
            return_value={"structuredContent": {"status": "candidate"}},
        ) as tool:
            result = send_domain_message(self.project, "disaster-history", "建立候选", access_mode="ask")
        self.assertEqual(result["runs"][0]["status"], "COMPLETED")
        tool.assert_called_once()

    def test_domain_agent_executes_tool_call_embedded_in_final_content(self) -> None:
        actions = iter([
            {
                "type": "final",
                "content": '继续核对。\n{"type":"tool_call","tool":"inspect","arguments":{}}',
            },
            {"type": "final", "content": "已根据回执完成核对。"},
        ])
        with patch("research_workbench.domain_agents._plugin", return_value=self.plugin), patch(
            "research_workbench.domain_agents._model_action", side_effect=lambda *args, **kwargs: next(actions),
        ), patch(
            "research_workbench.domain_agents.call_domain_plugin_tool",
            return_value={"structuredContent": {"read_only": True}},
        ) as tool:
            result = send_domain_message(self.project, "disaster-history", "继续核对")
        tool.assert_called_once_with(
            unittest.mock.ANY, "disaster-history", "inspect", {},
            progress_callback=unittest.mock.ANY,
        )
        self.assertEqual(result["runs"][0]["status"], "COMPLETED")

    def test_domain_agent_recovers_trailing_tool_json_without_type(self) -> None:
        action = _nested_domain_tool_action(
            '继续核查。\n{"arguments":{"name":"万州","year":1647},'
            '"tool":"historical_admin_lookup"}'
        )
        self.assertEqual(action, {
            "type": "tool_call", "tool": "historical_admin_lookup",
            "arguments": {"name": "万州", "year": 1647},
        })

    def test_domain_agent_retries_one_empty_tool_action(self) -> None:
        actions = iter([
            {"type": "tool_call", "tool": "", "arguments": {}},
            {"type": "tool_call", "tool": "inspect", "arguments": {}},
            {"type": "final", "content": "已按回执完成。"},
        ])
        with patch("research_workbench.domain_agents._plugin", return_value=self.plugin), patch(
            "research_workbench.domain_agents._model_action", side_effect=lambda *args, **kwargs: next(actions),
        ), patch(
            "research_workbench.domain_agents.call_domain_plugin_tool",
            return_value={"structuredContent": {"read_only": True}},
        ) as tool:
            result = send_domain_message(self.project, "disaster-history", "继续核对")
        self.assertEqual(result["runs"][0]["status"], "COMPLETED")
        tool.assert_called_once()

    def test_attachment_receipt_turn_cannot_start_whole_book_processing(self) -> None:
        plugin = {**self.plugin, "agent_tools": ["run_book_pages", "ocr_page_api"]}
        actions = iter([
            {"type": "tool_call", "tool": "ocr_page_api", "arguments": {"book_id": "old-book", "page": 1}},
            {"type": "final", "content": "仅按当前图片回执判断：未见可提取的灾害记载。"},
        ])
        content = "只判断这张图片。\nATTACHMENT_INSPECTION_RECEIPTS [{\"analysis\":\"未见灾害\"}]"
        with patch("research_workbench.domain_agents._plugin", return_value=plugin), patch(
            "research_workbench.domain_agents._model_action", side_effect=lambda *args, **kwargs: next(actions),
        ), patch("research_workbench.domain_agents.call_domain_plugin_tool") as tool:
            result = send_domain_message(self.project, "disaster-history", content)
        self.assertEqual(result["runs"][0]["status"], "COMPLETED")
        self.assertIn("未见可提取", result["messages"][-1]["content"]["text"])
        tool.assert_not_called()

    def test_attachment_disaster_normalization_finishes_from_receipt_without_second_model_call(self) -> None:
        plugin = {
            **self.plugin,
            "agent_tools": ["normalize_disaster_type"],
            "tool_permissions": {"normalize_disaster_type": "read"},
        }
        content = "只判断图片。\nATTACHMENT_INSPECTION_RECEIPTS [{\"analysis\":\"版心四二三；正文见大旱。\"}]"
        with patch("research_workbench.domain_agents._plugin", return_value=plugin), patch(
            "research_workbench.domain_agents._model_action",
            return_value={
                "type": "tool_call", "tool": "normalize_disaster_type",
                "arguments": {"raw_type": "灾种不明", "disaster_text": "大旱"},
            },
        ) as model, patch(
            "research_workbench.domain_agents.call_domain_plugin_tool",
            return_value={"structuredContent": {"disaster_types": ["旱灾"], "warnings": []}},
        ):
            result = send_domain_message(self.project, "disaster-history", content)
        self.assertEqual(result["runs"][0]["status"], "COMPLETED")
        self.assertIn("版心四二三", result["messages"][-1]["content"]["text"])
        self.assertIn("旱灾", result["messages"][-1]["content"]["text"])
        model.assert_called_once()

    def test_domain_agent_does_not_repeat_an_identical_successful_tool_call(self) -> None:
        actions = iter([
            {"type": "tool_call", "tool": "inspect", "arguments": {"page": 1}},
            {"type": "tool_call", "tool": "inspect", "arguments": {"page": 1}},
            {"type": "final", "content": "已按首次回执完成。"},
        ])
        with patch("research_workbench.domain_agents._plugin", return_value=self.plugin), patch(
            "research_workbench.domain_agents._model_action", side_effect=lambda *args, **kwargs: next(actions),
        ), patch(
            "research_workbench.domain_agents.call_domain_plugin_tool",
            return_value={"structuredContent": {"read_only": True}},
        ) as tool:
            result = send_domain_message(self.project, "disaster-history", "继续核对")
        self.assertEqual(result["runs"][0]["status"], "COMPLETED")
        tool.assert_called_once()

    def test_domain_agent_session_is_stable_per_project_and_plugin(self) -> None:
        with patch("research_workbench.domain_agents._plugin", return_value=self.plugin):
            first = ensure_domain_session(self.project, "disaster-history")
            second = ensure_domain_session(self.project, "disaster-history")
        self.assertEqual(first["session_id"], second["session_id"])
        renamed = {**self.plugin, "agent": {**self.plugin["agent"], "display_name": "灾害史领域 Agent"}}
        with patch("research_workbench.domain_agents._plugin", return_value=renamed):
            updated = ensure_domain_session(self.project, "disaster-history")
        self.assertEqual(updated["session_id"], first["session_id"])
        self.assertEqual(updated["title"], "灾害史领域 Agent")

    def test_domain_agent_receives_attachments_and_reasoning_controls(self) -> None:
        thread = create_thread(self.project, "domain files")
        attachment = save_attachment(
            self.project, thread["thread_id"], "source.txt", "大旱，岁饥。".encode("utf-8"),
        )
        with patch("research_workbench.domain_agents._plugin", return_value=self.plugin), patch(
            "research_workbench.domain_agents._model_action",
            return_value={"type": "final", "content": "已按附件处理。"},
        ) as model:
            result = send_domain_message(
                self.project, "disaster-history", "判断附件",
                main_thread_id=thread["thread_id"],
                attached_refs=[attachment], reasoning_mode="deep", reasoning_effort="high",
            )
        self.assertEqual(result["runs"][0]["model_snapshot"]["reasoning_mode"], "deep")
        self.assertEqual(result["runs"][0]["model_snapshot"]["reasoning_effort"], "high")
        self.assertEqual(result["messages"][-2]["content"]["attached_refs"][0]["attachment_id"], attachment["attachment_id"])
        self.assertEqual(model.call_args.kwargs["reasoning_mode"], "deep")
        self.assertEqual(model.call_args.kwargs["reasoning_effort"], "high")
        self.assertIn('\"tool_path\":', model.call_args.args[1])
        self.assertIn("source.txt", model.call_args.args[1])

    def test_all_rows_wording_cannot_reuse_an_old_answer_without_running_the_tool(self) -> None:
        plugin = {
            **self.plugin,
            "agent_tools": ["propagate_event_grades_to_all_rows"],
            "tool_permissions": {"propagate_event_grades_to_all_rows": "routine"},
        }
        actions = iter([
            {"type": "final", "content": "沿用上次结果。"},
            {
                "type": "tool_call", "tool": "propagate_event_grades_to_all_rows",
                "arguments": {"input_path": "in.xlsx", "output_path": "out.xlsx"},
            },
            {"type": "final", "content": "已按本轮工具回执生成候选。"},
        ])
        with patch("research_workbench.domain_agents._plugin", return_value=plugin), patch(
            "research_workbench.domain_agents._model_action", side_effect=lambda *args, **kwargs: next(actions),
        ), patch(
            "research_workbench.domain_agents.call_domain_plugin_tool",
            return_value={"structuredContent": {"output_path": str(self.project / "out.xlsx")}},
        ) as tool:
            result = send_domain_message(
                self.project, "disaster-history", "把所有县级行补齐定等",
                access_mode="research_assist",
            )
        self.assertEqual(result["runs"][0]["status"], "COMPLETED")
        tool.assert_called_once()

    def test_workbook_preview_must_cover_every_explicit_path_before_completion(self) -> None:
        plugin = {
            **self.plugin,
            "agent_tools": ["inspect_half_finished_workbook"],
            "tool_permissions": {"inspect_half_finished_workbook": "read"},
            "agent": {
                **self.plugin["agent"],
                "tool_triggers": {"inspect_half_finished_workbook": ["检查表头"]},
            },
        }
        first, second = r"D:\data\fire.xlsx", r"D:\data\drought.xlsx"
        actions = iter([
            {"type": "final", "content": "两张表都看过了。"},
            {"type": "tool_call", "tool": "inspect_half_finished_workbook", "arguments": {"input_path": first}},
            {"type": "final", "content": "完成。"},
            {"type": "tool_call", "tool": "inspect_half_finished_workbook", "arguments": {"input_path": second}},
            {"type": "final", "content": "两张表均已只读检查。"},
        ])
        with patch("research_workbench.domain_agents._plugin", return_value=plugin), patch(
            "research_workbench.domain_agents._model_action", side_effect=lambda *args, **kwargs: next(actions),
        ), patch(
            "research_workbench.domain_agents.call_domain_plugin_tool",
            return_value={"structuredContent": {"read_only": True}},
        ) as tool:
            result = send_domain_message(
                self.project, "disaster-history",
                f"检查表头：{first}；{second}", access_mode="research_assist",
            )
        self.assertEqual(result["runs"][0]["status"], "COMPLETED")
        self.assertEqual(
            [call.args[3]["input_path"] for call in tool.call_args_list], [first, second]
        )

    def test_uploaded_workbooks_must_be_inspected_by_the_domain_tool(self) -> None:
        plugin = {
            **self.plugin,
            "agent_tools": ["inspect_half_finished_workbook"],
            "tool_permissions": {"inspect_half_finished_workbook": "read"},
        }
        first, second = str(self.project / "fire.xlsx"), str(self.project / "drought.xlsx")
        actions = iter([
            {"type": "final", "content": "已查看。"},
            {"type": "tool_call", "tool": "inspect_half_finished_workbook", "arguments": {"input_path": first}},
            {"type": "tool_call", "tool": "inspect_half_finished_workbook", "arguments": {"input_path": second}},
            {"type": "final", "content": "两张表均已由领域工具只读检查。"},
        ])
        receipts = {
            "A1": {"attachment_id": "A1", "kind": "spreadsheet", "absolute_path": first,
                   "original_name": "fire.xlsx", "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
            "A2": {"attachment_id": "A2", "kind": "spreadsheet", "absolute_path": second,
                   "original_name": "drought.xlsx", "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        }
        with patch("research_workbench.domain_agents._plugin", return_value=plugin), patch(
            "research_workbench.domain_agents.inspect_attachment", side_effect=lambda _root, key: receipts[key].copy(),
        ), patch(
            "research_workbench.domain_agents._model_action", side_effect=lambda *args, **kwargs: next(actions),
        ), patch(
            "research_workbench.domain_agents.call_domain_plugin_tool",
            return_value={"structuredContent": {"read_only": True}},
        ) as tool:
            send_domain_message(
                self.project, "disaster-history", "请检查工作表、真实表头和前三条记录",
                attached_refs=[{"attachment_id": "A1"}, {"attachment_id": "A2"}],
                access_mode="research_assist",
            )
        self.assertEqual(
            [call.args[3]["input_path"] for call in tool.call_args_list], [first, second]
        )

    def test_startup_recovery_closes_interrupted_domain_run(self) -> None:
        with patch("research_workbench.domain_agents._plugin", return_value=self.plugin):
            session = ensure_domain_session(self.project, "disaster-history")
        now = utc_now()
        with connect(self.project) as connection:
            connection.execute(
                "INSERT INTO domain_agent_runs(run_id,session_id,status,model_snapshot_json,created_at,updated_at) "
                "VALUES ('DRN_INTERRUPTED',?,'RUNNING','{}',?,?)",
                (session["session_id"], now, now),
            )
            connection.execute(
                "INSERT INTO domain_agent_tool_calls(tool_call_id,run_id,tool_name,input_json,status,created_at) "
                "VALUES ('DTC_INTERRUPTED','DRN_INTERRUPTED','inspect','{}','RUNNING',?)",
                (now,),
            )
        self.assertEqual(recover_interrupted_runs(self.project), 1)
        with connect(self.project) as connection:
            run = connection.execute(
                "SELECT status,error FROM domain_agent_runs WHERE run_id='DRN_INTERRUPTED'"
            ).fetchone()
            call = connection.execute(
                "SELECT status,output_json FROM domain_agent_tool_calls WHERE tool_call_id='DTC_INTERRUPTED'"
            ).fetchone()
        self.assertEqual(run["status"], "FAILED")
        self.assertIn("restart", run["error"])
        self.assertEqual(call["status"], "FAILED")
        self.assertIn("restart", call["output_json"])

    def test_domain_memory_is_partitioned_by_main_thread_and_inherits_only_parent(self) -> None:
        first = create_thread(self.project, "first")
        child = create_thread(self.project, "child", first["thread_id"])
        other = create_thread(self.project, "other")
        with patch("research_workbench.domain_agents._plugin", return_value=self.plugin):
            session = ensure_domain_session(self.project, "disaster-history")
        now = utc_now()
        with connect(self.project) as connection:
            for message_id, thread_id, text in (
                ("DMS_PARENT", first["thread_id"], "parent path"),
                ("DMS_OTHER", other["thread_id"], "unrelated old path"),
            ):
                connection.execute(
                    "INSERT INTO domain_agent_messages(message_id,session_id,role,content_json,created_at) "
                    "VALUES (?,?,'user',?,?)",
                    (message_id, session["session_id"], json.dumps({
                        "text": text, "main_thread_id": thread_id,
                    }, ensure_ascii=False), now),
                )
        history = _domain_history(self.project, session["session_id"], child["thread_id"])
        self.assertEqual([item["content"] for item in history], ["parent path"])


if __name__ == "__main__":
    unittest.main()
