from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from research_workbench.plugin_sdk import create_local_skill, create_plugin_project
from research_workbench.skill_registry import discover_skills
from unittest.mock import patch


class PluginSdkTests(unittest.TestCase):
    def test_local_skill_is_created_and_immediately_discoverable(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"WENJIN_CONFIG_ROOT": directory}, clear=False,
        ):
            result = create_local_skill(
                Path(directory), "Archive Helper", "整理档案文件。",
                "读取用户指定目录，先列出文件，再提出整理方案。", "档案助手",
            )
            skill = next(item for item in discover_skills() if item["name"] == "archive-helper")
            self.assertEqual(Path(result["skill_file"]), Path(directory) / "skills" / "archive-helper" / "SKILL.md")
            self.assertTrue(skill["agent_program"]["allow_implicit_invocation"])

    def test_scaffold_is_immediately_valid_and_has_both_wenjin_and_codex_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = create_plugin_project(Path(directory), "Environmental History", "环境史", "环境史领域研究工具。")
            root = Path(result["plugin_root"])
            self.assertEqual(root.name, "environmental-history")
            self.assertEqual(result["status"], "valid")
            self.assertTrue((root / "wenjin-plugin.json").is_file())
            self.assertTrue((root / ".codex-plugin" / "plugin.json").is_file())
            self.assertTrue((root / "src" / "environmental_history" / "mcp_server.py").is_file())
            self.assertTrue((root / "README.md").is_file())
            manifest=json.loads((root / "wenjin-plugin.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["tool_permissions"]["plugin_status"], "read")
            self.assertEqual(set(manifest["contributions"]), {"methods", "schemas", "processors", "graph_adapters", "ui_panels"})


if __name__ == "__main__":
    unittest.main()
