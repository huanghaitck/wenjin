from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from research_workbench.domain_plugins import (
    _plugin_model_environment, bind_domain_plugin_data, call_domain_plugin_tool,
    install_domain_plugin, plugin_state, public_domain_model_settings,
    remove_domain_plugin, repair_domain_plugin, save_domain_model_role,
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
            "model_roles": [{"id": "domain_reasoning", "label": "Domain reasoning", "env_prefix": "TEXT_API", "required": True}],
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

    def test_reinstall_keeps_an_existing_runtime_override(self) -> None:
        install_domain_plugin(self.config, self.plugin, runtime_command=__file__)
        data = json.loads((self.plugin / "wenjin-plugin.json").read_text(encoding="utf-8"))
        data["version"] = "0.1.1"
        (self.plugin / "wenjin-plugin.json").write_text(json.dumps(data), encoding="utf-8")
        state = install_domain_plugin(self.config, self.plugin)
        self.assertEqual(state["plugins"][0]["runtime_command"], str(Path(__file__).resolve()))
        self.assertEqual(state["plugins"][0]["status"], "ready")

    def test_repair_reinstalls_from_the_recorded_local_source(self) -> None:
        state = install_domain_plugin(self.config, self.plugin, runtime_command=__file__)
        installed = Path(state["plugins"][0]["installed_path"])
        (installed / "skills" / "sample" / "SKILL.md").write_text("broken", encoding="utf-8")
        repaired = repair_domain_plugin(self.config, "sample-domain")
        self.assertIn("# Sample", (Path(repaired["plugins"][0]["installed_path"]) / "skills" / "sample" / "SKILL.md").read_text(encoding="utf-8"))

    def test_remove_deletes_only_the_named_plugin_copy(self) -> None:
        install_domain_plugin(self.config, self.plugin)
        (self.config / "domain-model-settings.json").write_text(json.dumps({"schema_version": 1, "plugins": {"sample-domain": {"domain_reasoning": {"provider": "inherit"}}}}), encoding="utf-8")
        with patch("research_workbench.domain_plugins.delete_credential") as delete:
            state = remove_domain_plugin(self.config, "sample-domain")
        self.assertEqual(state["count"], 0)
        self.assertTrue(self.plugin.is_dir())
        delete.assert_called_once()
        saved = json.loads((self.config / "domain-model-settings.json").read_text(encoding="utf-8"))
        self.assertNotIn("sample-domain", saved["plugins"])

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
        install_domain_plugin(self.config, self.plugin, runtime_command=__file__)
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
        installed = Path(state["plugins"][0]["installed_path"])
        (installed / "skills" / "sample" / "SKILL.md").write_text("broken", encoding="utf-8")
        repaired = repair_domain_plugin(self.config, "sample-domain")
        self.assertIn("# Sample", (Path(repaired["plugins"][0]["installed_path"]) / "skills" / "sample" / "SKILL.md").read_text(encoding="utf-8"))

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

    def test_wenjin_model_roles_are_injected_into_portable_plugin_environment(self) -> None:
        configured = {
            "HRW_DOMAIN_MODEL_BASE_URL": "https://text.example/v1",
            "HRW_DOMAIN_MODEL_API_KEY": "text-secret",
            "HRW_DOMAIN_MODEL_MODEL": "deepseek-v4-flash",
            "HRW_OCR_MODEL": "deepseek-v4-flash-vision-exp",
            "HRW_VISION_REVIEW_MODEL": "glm-4.6v",
            "HRW_REVIEW_MODEL": "fallback-model",
        }
        with patch.dict(os.environ, configured, clear=True):
            environment = _plugin_model_environment()
        self.assertEqual(environment["TEXT_API_MODEL"], "deepseek-v4-flash")
        self.assertEqual(environment["VISION_API_MODEL"], "deepseek-v4-flash-vision-exp")
        self.assertEqual(environment["VISION_QA_API_MODEL"], "glm-4.6v")
        self.assertEqual(environment["FALLBACK_API_MODEL"], "fallback-model")
        self.assertEqual(environment["TEXT_API_KEY"], "text-secret")

    def test_each_domain_agent_keeps_an_independent_model_override(self) -> None:
        install_domain_plugin(self.config, self.plugin)
        other = self.root / "other-plugin"
        shutil.copytree(self.plugin, other)
        manifest = json.loads((other / "wenjin-plugin.json").read_text(encoding="utf-8"))
        manifest["name"] = "other-domain"
        (other / "wenjin-plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        install_domain_plugin(self.config, other)
        secrets: dict[str, str] = {}
        with patch("research_workbench.domain_plugins.save_credential", side_effect=lambda target, secret, *_: secrets.__setitem__(target, secret)), patch("research_workbench.domain_plugins.read_credential", side_effect=lambda target: secrets.get(target, "")):
            save_domain_model_role(self.config, "sample-domain", "domain_reasoning", {
                "provider": "openai_compatible", "model": "sample-model",
                "base_url": "https://sample.example/v1", "api_key": "sample-key",
            })
            save_domain_model_role(self.config, "other-domain", "domain_reasoning", {
                "provider": "openai_compatible", "model": "other-model",
                "base_url": "https://other.example/v1", "api_key": "other-key",
            })
            sample = _plugin_model_environment(self.config, "sample-domain")
            other_env = _plugin_model_environment(self.config, "other-domain")
            self.assertEqual(public_domain_model_settings(self.config, "sample-domain")["roles"][0]["effective_model"], "sample-model")
        self.assertEqual(sample["TEXT_API_MODEL"], "sample-model")
        self.assertEqual(other_env["TEXT_API_MODEL"], "other-model")
        self.assertEqual(sample["TEXT_API_KEY"], "sample-key")
        self.assertEqual(other_env["TEXT_API_KEY"], "other-key")


if __name__ == "__main__":
    unittest.main()
