from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_workbench.codex_bridge import (
    build_codex_exec_command,
    codex_capability,
    register_with_codex,
)


class _Result:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class CodexBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @patch("research_workbench.codex_bridge._codex_executable", return_value=r"C:\Tools\codex.exe")
    def test_codex_exec_command_is_bounded_to_supported_sandboxes(self, _which) -> None:
        output = self.root / "final.txt"
        command = build_codex_exec_command(self.root, output, sandbox="read-only")
        self.assertIn("--json", command)
        self.assertIn("read-only", command)
        self.assertIn("never", command)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
        with self.assertRaisesRegex(ValueError, "read-only or workspace-write"):
            build_codex_exec_command(self.root, output, sandbox="danger-full-access")

    @patch("research_workbench.codex_bridge.shutil.which")
    @patch("research_workbench.codex_bridge._codex_executable", return_value=r"C:\Users\u\AppData\Roaming\npm\codex.cmd")
    def test_npm_cmd_resolves_to_node_script_without_cmd_shell(self, _executable, which) -> None:
        npm = self.root / "npm"
        script = npm / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        script.parent.mkdir(parents=True)
        script.write_text("", encoding="utf-8")
        _executable.return_value = str(npm / "codex.cmd")
        which.side_effect = lambda name: r"C:\Program Files\nodejs\node.exe" if name in {"node", "node.exe"} else None
        command = build_codex_exec_command(self.root, self.root / "final.txt")
        self.assertEqual(command[:2], [r"C:\Program Files\nodejs\node.exe", str(script)])

    @patch("research_workbench.codex_bridge._codex_executable", return_value=r"C:\Tools\codex.exe")
    def test_registration_uses_wenjin_mcp_stdio_without_credentials(self, _which) -> None:
        calls = []

        def runner(command, **_kwargs):
            calls.append(command)
            return _Result(1) if command[1:3] == ["mcp", "get"] else _Result(0, "added")

        result = register_with_codex(self.root, runner=runner)
        self.assertEqual(result["status"], "registered")
        self.assertEqual(calls[1][1:3], ["mcp", "add"])
        self.assertIn("mcp-server", calls[1])
        self.assertFalse(any("KEY" in value.upper() for value in calls[1]))

    @patch("research_workbench.codex_bridge._codex_executable", return_value=r"C:\Tools\codex.exe")
    def test_capability_exposes_both_inbound_and_outbound_modes(self, _which) -> None:
        result = codex_capability(self.root)
        self.assertTrue(result["installed"])
        self.assertEqual(result["inbound_mode"], "wenjin_mcp_stdio")
        self.assertEqual(result["outbound_mode"], "codex_exec_jsonl")


if __name__ == "__main__":
    unittest.main()
