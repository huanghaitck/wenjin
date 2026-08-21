from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from research_workbench.plugin_sdk import create_plugin_project


class PluginSdkTests(unittest.TestCase):
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
