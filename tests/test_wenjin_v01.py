from __future__ import annotations

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
from research_workbench.web import WorkbenchHandler


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
        self.assertEqual(len(public_settings(Path(self.temporary.name) / "config")["roles"]), 7)

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

    def test_ui_exposes_brand_language_persona_moa_and_mcp_copy(self) -> None:
        root = Path(__file__).parents[1] / "src" / "research_workbench" / "web_assets"
        html = (root / "index.html").read_text(encoding="utf-8")
        script = (root / "app.js").read_text(encoding="utf-8")
        self.assertIn("问津", html)
        self.assertIn('id="languageToggle"', html)
        self.assertIn("/api/agent-profile/save", script)
        self.assertIn("/api/model-settings/moa", script)
        self.assertIn("Mixture of Agents", script)


if __name__ == "__main__":
    unittest.main()
