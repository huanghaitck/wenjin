from __future__ import annotations

import unittest
import tempfile
from _ctypes import COMError
from pathlib import Path
from unittest.mock import patch

from research_workbench.computer_use_mcp import (
    computer_status, desktop_snapshot, file_search, filesystem_roots, runtime_status, window_list,
)


class ComputerUseTests(unittest.TestCase):
    def test_runtime_status_distinguishes_packaged_core_from_optional_script_runtimes(self) -> None:
        status = runtime_status()
        self.assertTrue(status["wenjin_backend"]["available"])
        self.assertIn("python", status["optional_script_runtimes"])
        self.assertIn("powershell7", status["optional_script_runtimes"])
        self.assertIn("do not require system Python", status["wenjin_backend"]["note"])

    def test_windows_accessibility_backend_returns_bounded_visible_state(self) -> None:
        status = computer_status()
        self.assertEqual(status["backend"], "Windows UI Automation")
        self.assertGreater(status["screen_width"], 0)
        windows = window_list(10)
        self.assertLessEqual(windows["count"], 10)
        snapshot = desktop_snapshot(depth=1, limit=30)
        self.assertLessEqual(snapshot["count"], 30)
        for control in snapshot["controls"]:
            if control["password"]:
                self.assertEqual(control["name"], "[password]")

    def test_closed_window_during_enumeration_is_skipped(self) -> None:
        class ClosedWindow:
            @property
            def IsOffscreen(self):
                raise COMError(-2147220991, "stale window", None)

        class Root:
            @staticmethod
            def GetChildren():
                return [ClosedWindow()]

        with patch("research_workbench.computer_use_mcp.automation.GetRootControl", return_value=Root()):
            self.assertEqual(window_list(10), {"windows": [], "count": 0})
            self.assertEqual(desktop_snapshot(depth=1, limit=30)["count"], 0)

    def test_bounded_file_search_reads_names_and_metadata_without_file_contents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "灾害史领域包.zip").write_text("secret body is not returned", encoding="utf-8")
            (root / "other.txt").write_text("other", encoding="utf-8")
            result = file_search([str(root)], "灾害史", [".zip"], max_results=10)
        self.assertEqual(result["returned_count"], 1)
        self.assertEqual(result["matches"][0]["name"], "灾害史领域包.zip")
        self.assertNotIn("secret body", str(result))
        self.assertFalse(result["truncated"])
        self.assertIn("drives", filesystem_roots())


if __name__ == "__main__":
    unittest.main()
