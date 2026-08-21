from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from research_workbench.domain_plugins import (
    bind_domain_plugin_data, call_domain_plugin_tool, install_domain_plugin, plugin_state,
    remove_domain_plugin,
)


class DomainPluginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = self.root / "config"
        self.plugin = self.root / "plugin"
        (self.plugin / "skills" / "sample").mkdir(parents=True)
        (self.plugin / "skills" / "sample" / "SKILL.md").write_text(
            "---\nname: sample\ndescription: sample domain skill\n---\n\n# Sample\n", encoding="utf-8",
        )
        (self.plugin / "wenjin-plugin.json").write_text(json.dumps({
            "schema_version": 1, "name": "sample-domain", "version": "0.1.0",
            "display_name": "Sample domain", "description": "Test plugin", "kind": "domain",
            "runtime": {"type": "mcp_stdio", "command": "missing-sample-command", "args": []},
            "skills": ["skills/sample/SKILL.md"], "agent_tools": ["safe_read"],
            "data_packs": [{"id": "pack", "downloads": []}],
            "local_data_sources": [{
                "id": "local-corpus", "label": "Local corpus", "kind": "file",
                "extensions": [".sqlite", ".db"],
            }],
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_install_is_versioned_and_reports_missing_runtime(self) -> None:
        state = install_domain_plugin(self.config, self.plugin)
        self.assertEqual(state["count"], 1)
        installed = state["plugins"][0]
        self.assertEqual(installed["name"], "sample-domain")
        self.assertEqual(installed["status"], "runtime_missing")
        self.assertTrue(Path(installed["installed_path"]).is_dir())
        self.assertFalse(installed["package_changed"])

    def test_remove_deletes_only_the_named_plugin_copy(self) -> None:
        install_domain_plugin(self.config, self.plugin)
        state = remove_domain_plugin(self.config, "sample-domain")
        self.assertEqual(state["count"], 0)
        self.assertTrue(self.plugin.is_dir())

    def test_manifest_skill_must_stay_inside_plugin(self) -> None:
        data = json.loads((self.plugin / "wenjin-plugin.json").read_text())
        data["skills"] = ["../outside.md"]
        (self.plugin / "wenjin-plugin.json").write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "escapes"):
            install_domain_plugin(self.config, self.plugin)

    def test_main_agent_cannot_call_a_tool_outside_manifest_allowlist(self) -> None:
        install_domain_plugin(self.config, self.plugin, runtime_command=__file__)
        with self.assertRaisesRegex(ValueError, "not approved"):
            call_domain_plugin_tool(self.config, "sample-domain", "paid_write", {})

    def test_self_contained_runtime_resolves_inside_installed_copy(self) -> None:
        runtime = self.plugin / "runtime" / "sample.exe"
        runtime.parent.mkdir()
        runtime.write_bytes(b"runtime")
        data = json.loads((self.plugin / "wenjin-plugin.json").read_text())
        data["runtime"] = {
            "type": "mcp_stdio", "command": "runtime/sample.exe", "args": [],
            "cwd": ".", "self_contained": True,
        }
        (self.plugin / "wenjin-plugin.json").write_text(json.dumps(data), encoding="utf-8")
        state = install_domain_plugin(self.config, self.plugin)
        installed = state["plugins"][0]
        self.assertTrue(installed["runtime_available"])
        self.assertTrue(Path(installed["runtime_command"]).is_relative_to(self.config.resolve()))
        self.assertEqual(Path(installed["runtime_cwd"]), Path(installed["installed_path"]))

    def test_zip_package_installs_without_path_traversal(self) -> None:
        package = self.root / "sample.zip"
        with zipfile.ZipFile(package, "w") as archive:
            for path in self.plugin.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(self.plugin))
        state = install_domain_plugin(self.config, package)
        self.assertEqual(state["plugins"][0]["name"], "sample-domain")

    def test_local_database_binding_records_identity_and_reaches_plugin_environment(self) -> None:
        install_domain_plugin(self.config, self.plugin)
        database = self.root / "corpus.sqlite"
        database.write_bytes(b"SQLite format 3\x00test")
        state = bind_domain_plugin_data(
            self.config, "sample-domain", "local-corpus", str(database)
        )
        source = state["plugins"][0]["local_data_sources"][0]
        self.assertTrue(source["bound"])
        self.assertEqual(source["binding"]["path"], str(database.resolve()))
        self.assertEqual(len(source["binding"]["sha256"]), 64)
        wrong = self.root / "wrong.txt"
        wrong.write_text("wrong", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not accepted"):
            bind_domain_plugin_data(
                self.config, "sample-domain", "local-corpus", str(wrong)
            )


if __name__ == "__main__":
    unittest.main()
