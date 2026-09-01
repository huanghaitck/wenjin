from __future__ import annotations

import json
import re
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class ReleaseGateTests(unittest.TestCase):
    def test_application_versions_and_help_resources_are_consistent(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        tauri = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
        cargo = tomllib.loads((ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8"))
        init = (ROOT / "src" / "research_workbench" / "__init__.py").read_text(encoding="utf-8")
        python_version = re.search(r'__version__\s*=\s*"([^"]+)"', init).group(1)
        self.assertEqual({pyproject["project"]["version"], package["version"], tauri["version"], cargo["package"]["version"], python_version}, {python_version})
        resources = tauri["bundle"]["resources"]
        self.assertEqual(resources["../docs/USER_MANUAL_ZH.md"], "help/USER_MANUAL_ZH.md")
        self.assertEqual(resources["../docs/USER_MANUAL_EN.md"], "help/USER_MANUAL_EN.md")
        self.assertEqual(resources["../CHANGELOG.md"], "help/CHANGELOG.md")

    def test_build_id_is_passed_from_desktop_shell_to_sidecar(self) -> None:
        build = (ROOT / "src-tauri" / "build.rs").read_text(encoding="utf-8")
        rust = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
        self.assertIn("WENJIN_BUILD_ID", build)
        self.assertIn('env!("WENJIN_BUILD_ID")', rust)
        self.assertIn('"--desktop-build"', rust)

    def test_mcp_server_reports_the_application_version(self) -> None:
        source = (ROOT / "src" / "research_workbench" / "mcp_server.py").read_text(encoding="utf-8")
        self.assertIn('"version": __version__', source)
        self.assertNotIn('"version": "0.1.2"', source)

    def test_offline_bundle_builder_requires_manifest_and_never_uses_fixed_machine_paths(self) -> None:
        script = (ROOT / "scripts" / "build_offline_bundle.ps1").read_text(encoding="utf-8")
        self.assertIn("build-manifest.json", script)
        self.assertIn("MicrosoftEdgeWebView2RuntimeInstallerX64.exe", script)
        self.assertIn("Get-FileHash", script)
        self.assertNotIn("D:\\AI_Workflows", script)
        verifier = (ROOT / "scripts" / "verify_offline_bundle.py").read_text(encoding="utf-8")
        self.assertIn("bundle hash mismatch", verifier)


if __name__ == "__main__":
    unittest.main()
