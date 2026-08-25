from __future__ import annotations

import json
import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

from research_workbench import agent_runtime
from research_workbench.agent_profile import agent_profile_prompt, public_agent_profile, save_agent_profile
from research_workbench.mcp_server import handle_request
from research_workbench.model_settings import public_settings, save_moa
from research_workbench.service import initialize_project
from research_workbench.db import connect
from research_workbench.scholarship import (
    computer_use_capability, create_browser_session, inspect_controlled_browser,
    launch_controlled_browser, navigate_controlled_browser, read_controlled_browser,
)
from research_workbench.web import WorkbenchHandler
from research_workbench.authoring import ensure_journal_templates
from research_workbench.desktop_runtime import _install_builtin_computer_use
from research_workbench.domain_plugins import plugin_state


class WenjinV01Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        initialize_project(self.project, "问津测试项目")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_loopback_client_disconnect_does_not_escape_response_writer(self) -> None:
        handler = object.__new__(WorkbenchHandler)
        handler.send_response = lambda _status: None
        handler.send_header = lambda _name, _value: None
        handler.end_headers = lambda: (_ for _ in ()).throw(ConnectionAbortedError())
        handler._send(200, b"ok", "text/plain")

    def test_agent_persona_is_versioned_and_cannot_replace_harness(self) -> None:
        saved = save_agent_profile(self.project, {
            "display_name": "经史助手", "address_user": "老师",
            "custom_instructions": "优先讨论史料生成过程。",
        })
        self.assertTrue(saved["profile_id"].startswith("AGP_"))
        self.assertIn("证据冻结", saved["harness_constitution"])
        self.assertIn("经史助手", agent_profile_prompt(self.project))
        self.assertEqual(public_agent_profile(self.project)["address_user"], "老师")
        self.assertTrue((self.project / "research" / "agent-profile.json").is_file())

    def test_moa_configuration_uses_auxiliary_reference_roles(self) -> None:
        settings = save_moa(Path(self.temporary.name) / "config", {
            "enabled": True, "reference_roles": ["review_secondary", "translation_helper"],
            "fanout": "user_turn",
        })
        self.assertTrue(settings["moa"]["enabled"])
        self.assertEqual(settings["moa"]["aggregator_role"], "main_reasoning")
        self.assertEqual(len(public_settings(Path(self.temporary.name) / "config")["roles"]), 9)

    def test_moa_reference_failure_is_reported_without_aborting_other_advice(self) -> None:
        environment = {
            "HRW_MOA_ENABLED": "1", "HRW_MOA_REFERENCE_ROLES": "translation_helper,review_secondary",
            "HRW_TRANSLATION_PROVIDER": "ollama", "HRW_TRANSLATION_MODEL": "translator",
            "HRW_TRANSLATION_BASE_URL": "http://127.0.0.1:11434",
            "HRW_REVIEW_PROVIDER": "ollama", "HRW_REVIEW_MODEL": "reviewer",
            "HRW_REVIEW_BASE_URL": "http://127.0.0.1:11434",
        }
        with patch.dict(os.environ, environment, clear=False), patch.object(
            agent_runtime, "_plain_model_call", side_effect=["translation advice", RuntimeError("offline")]
        ):
            result = agent_runtime._moa_guidance("compare sources", [])
        self.assertEqual(result[0]["content"], "translation advice")
        self.assertEqual(result[1]["error"], "offline")
        self.assertIn("translation advice", agent_runtime._format_moa_guidance(result))

    def test_mcp_server_exposes_real_project_tools_resources_and_prompt(self) -> None:
        initialized = handle_request(self.project, None, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "wenjin-research")
        tools = handle_request(self.project, None, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertIn("project_status", [item["name"] for item in tools["result"]["tools"]])
        called = handle_request(self.project, None, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "project_status", "arguments": {}}})
        self.assertEqual(called["result"]["structuredContent"]["title"], "问津测试项目")
        resources = handle_request(self.project, None, {"jsonrpc": "2.0", "id": 4, "method": "resources/list"})
        self.assertIn("wenjin://agent/profile", [item["uri"] for item in resources["result"]["resources"]])
        prompts = handle_request(self.project, None, {"jsonrpc": "2.0", "id": 5, "method": "prompts/list"})
        self.assertEqual(prompts["result"]["prompts"][0]["name"], "research_status_review")

    def test_cli_module_has_a_real_module_entrypoint(self) -> None:
        cli = (Path(__file__).parents[1] / "src" / "research_workbench" / "cli.py").read_text(encoding="utf-8")
        self.assertIn('if __name__ == "__main__":', cli)
        self.assertIn("raise SystemExit(main())", cli)

    def test_evidence_preserving_historical_humanizer_is_bundled_for_clean_installs(self) -> None:
        root = Path(__file__).parents[1] / "src" / "research_workbench" / "builtin_skills" / "historical-humanizer-zh"
        self.assertTrue((root / "SKILL.md").is_file())
        self.assertTrue((root / "references" / "evidence-integrity.md").is_file())
        self.assertTrue((root / "scripts" / "guard_historical_revision.py").is_file())
        package = (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"builtin_skills/*/references/*.md"', package)
        self.assertIn('"builtin_skills/*/scripts/*.py"', package)

    def test_complete_historical_research_skill_pack_is_bundled(self) -> None:
        root = Path(__file__).parents[1] / "src" / "research_workbench" / "builtin_skillpacks" / "historical-research"
        names = {path.parent.name for path in (root / "skills").glob("*/SKILL.md")}
        self.assertEqual(len(names), 16)
        self.assertTrue({
            "historical-question-and-scope", "historical-literature-search",
            "historical-source-criticism", "historical-historiography",
            "historical-evidence-freeze", "historical-review-and-revision",
            "historical-final-audit", "historical-drafting",
        }.issubset(names))
        self.assertTrue((root / "references" / "core-policy.md").is_file())
        self.assertTrue((root / "LICENSE-APACHE-2.0").is_file())
        package = (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"builtin_skillpacks/*/skills/*/SKILL.md"', package)

    def test_builtin_computer_use_pack_installs_with_the_frozen_sidecar(self) -> None:
        config = Path(self.temporary.name) / "computer-config"
        with patch("research_workbench.desktop_runtime.sys.frozen", True, create=True):
            _install_builtin_computer_use(config)
        plugin = next(item for item in plugin_state(config)["plugins"] if item["name"] == "computer-use")
        self.assertEqual(plugin["version"], "0.1.2")
        self.assertEqual(plugin["tool_permissions"]["run_command"], "sensitive")
        self.assertIn("desktop_snapshot", plugin["agent_tools"])
        self.assertIn("file_search", plugin["agent_tools"])

    def test_bundled_browser_runtime_uses_explicit_chromium_executable(self) -> None:
        root = Path(self.temporary.name)
        runtime = root / "agent-browser.exe"
        browser = root / "chrome.exe"
        runtime.write_bytes(b"runtime")
        browser.write_bytes(b"browser")
        with patch.dict(os.environ, {
            "WENJIN_AGENT_BROWSER": str(runtime),
            "WENJIN_BROWSER_EXECUTABLE": str(browser),
        }, clear=False):
            capability = computer_use_capability()
            self.assertTrue(capability["visible_browser_launch"])
            self.assertTrue(capability["agent_actuated"])
            self.assertEqual(capability["agent_actions"], ["observe", "read", "same_domain_navigate"])
            self.assertEqual(capability["runtime_origin"], "configured")
            self.assertEqual(capability["browser_origin"], "configured")
            session = create_browser_session(self.project, "https://example.com", "example.com")
            with patch("research_workbench.scholarship.subprocess.Popen") as popen:
                launch_controlled_browser(self.project, session["session_id"])
            command = popen.call_args.args[0]
            self.assertEqual(command[0], str(runtime.resolve()))
            self.assertEqual(command[1:3], ["--executable-path", str(browser.resolve())])

    def test_agent_browser_tools_are_visible_bounded_and_same_domain_only(self) -> None:
        session = create_browser_session(self.project, "https://example.com/start", "example.com")
        with connect(self.project) as connection:
            connection.execute(
                "UPDATE browser_sessions SET status = 'controlled_browser_open' WHERE session_id = ?",
                (session["session_id"],),
            )
        snapshot_payload = json.dumps({
            "success": True,
            "data": {
                "origin": "https://example.com/start",
                "snapshot": '- link "Next" [ref=e1, url=https://example.com/next]',
                "refs": {"e1": {"name": "Next", "role": "link"}},
            },
        })
        with patch("research_workbench.scholarship._run_browser_command", return_value=snapshot_payload):
            inspected = inspect_controlled_browser(self.project, session["session_id"])
        self.assertEqual(inspected["allowed_domain"], "example.com")
        self.assertIn("Next", inspected["snapshot"])

        with patch(
            "research_workbench.scholarship._run_browser_command",
            side_effect=["Rendered research page", "https://example.com/start", "Research"],
        ):
            read = read_controlled_browser(self.project, session["session_id"])
        self.assertEqual(read["title"], "Research")
        self.assertIn("Rendered research page", read["text"])

        with patch(
            "research_workbench.scholarship._run_browser_command",
            side_effect=["", "https://example.com/next", "Next"],
        ):
            navigated = navigate_controlled_browser(
                self.project, session["session_id"], "https://sub.example.com/next"
            )
        self.assertEqual(navigated["title"], "Next")
        with self.assertRaisesRegex(ValueError, "approved domain"):
            navigate_controlled_browser(
                self.project, session["session_id"], "https://outside.example.net/"
            )

    def test_ui_exposes_brand_language_persona_moa_and_mcp_copy(self) -> None:
        root = Path(__file__).parents[1] / "src" / "research_workbench" / "web_assets"
        html = (root / "index.html").read_text(encoding="utf-8")
        script = (root / "app.js").read_text(encoding="utf-8")
        self.assertIn("问津", html)
        self.assertNotIn("研究者保留证据与写作决定权", html)
        self.assertNotIn("研究者保留证据与写作决定权", script)
        self.assertNotIn("等待你的决定", script)
        self.assertIn('id="languageToggle"', html)
        self.assertIn('id="modelOnboarding"', html)
        self.assertIn("问津不会用 Mock 冒充模型", html)
        self.assertIn("/api/agent-profile/save", script)
        self.assertIn("/api/model-settings/moa", script)
        self.assertIn('id="agentAccessMode"', html)
        self.assertIn("research_assist", script)
        self.assertIn("full_computer", script)
        self.assertIn("Mixture of Agents", script)
        self.assertIn("Codex 双向桥接", script)
        self.assertIn("/api/codex/register-mcp", script)
        self.assertIn("领域包编排教程", script)

    def test_english_ui_has_an_english_history_template_and_domain_pack_copy(self) -> None:
        ensure_journal_templates(self.project)
        with connect(self.project) as connection:
            connection.execute(
                "UPDATE journal_template_revisions SET requirements_json = '{}' "
                "WHERE template_id = 'builtin-history-research'"
            )
        templates = ensure_journal_templates(self.project)
        template = next(
            item for item in templates
            if item["template_id"] == "builtin-english-history-chicago-nb"
        )
        self.assertEqual(template["requirements"]["language"], "en")
        self.assertEqual(template["requirements"]["citation_system"], "notes_bibliography")
        history = next(item for item in templates if item["template_id"] == "builtin-history-research")
        self.assertEqual(history["requirements"]["language"], "zh-CN")
        script = (Path(__file__).parents[1] / "src" / "research_workbench" / "web_assets" / "app.js").read_text(encoding="utf-8")
        html = (Path(__file__).parents[1] / "src" / "research_workbench" / "web_assets" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Import one or start the guided creator", script)
        self.assertIn('id="domainImportPanel"', html)
        self.assertIn('id="domainCreatePanel"', html)
        self.assertNotIn("Create a neutral domain-pack project", script)
        self.assertNotIn("You may install the Gazetteer Disaster History plugin", script)
        self.assertIn("builtin-english-history-chicago-nb", script)
        self.assertIn("/api/codex/task/start", script)
        self.assertIn("/api/backups/create", script)
        self.assertIn("/api/backups/restore", script)
        self.assertIn("/api/memory/settings", script)
        self.assertIn("/api/memory/promote", script)
        self.assertIn("Local long-term memory adapters", script)
        self.assertIn("Privacy and confirmations", script)
        self.assertIn("Project backup and recovery", script)
        self.assertIn("Restore as a new project copy", script)
        self.assertIn('id="planningOptions"', html)
        self.assertIn("只处理当前问题", html)
        self.assertNotIn("对话状态", html)

    def test_ui_separates_agent_configuration_and_draws_library_graph(self) -> None:
        root = Path(__file__).parents[1] / "src" / "research_workbench" / "web_assets"
        html = (root / "index.html").read_text(encoding="utf-8")
        script = (root / "app.js").read_text(encoding="utf-8")
        styles = (root / "styles.css").read_text(encoding="utf-8")
        self.assertIn('id="settingsTabs"', html)
        self.assertIn('id="projectWorkbench"', html)
        self.assertIn('id="projectMode"', html)
        self.assertIn('/api/project/workspace', script)
        self.assertIn('/api/project/register', script)
        for tab in ("models", "routing", "persona", "memory", "connectors", "runtime"):
            self.assertIn(f'data-settings-tab="{tab}"', html)
        self.assertNotIn('data-settings-tab="plugins"', html)
        for control in ("domainImportToggle", "domainCreateToggle", "domainAttachmentInput", "domainReasoningMode", "domainReasoningEffort", "domainConfigureModel"):
            self.assertIn(f'id="{control}"', html)
        self.assertIn('id="libraryViews"', html)
        for view in ("list", "chronicle", "graph", "intake"):
            self.assertIn(f'data-library-view="{view}"', html)
        self.assertIn("renderSourceChronicle", script)
        self.assertIn("/api/source-chronicle", script)
        self.assertIn("renderKnowledgeGraph", script)
        self.assertIn("How to use this graph", script)
        self.assertIn("graph-work-cards", script)
        self.assertIn("Open project source pages", script)
        self.assertIn("Project content graph", script)
        self.assertIn("Open anchored source page", script)
        self.assertIn("/api/plugins/install", script)
        self.assertIn("/api/thread/attachment/file", script)
        self.assertIn("open_path", script)
        self.assertIn("mode-intake", script)
        self.assertIn("createElementNS('http://www.w3.org/2000/svg'", script)
        self.assertIn("graph-stage", styles)
        self.assertIn(".library-workbench.mode-intake", styles)
        self.assertIn(".check-label input[type=\"checkbox\"]", styles)
        self.assertIn("overflow-wrap: anywhere", styles)


if __name__ == "__main__":
    unittest.main()
