from __future__ import annotations

import unittest

from research_workbench.computer_use_mcp import computer_status, desktop_snapshot, window_list


class ComputerUseTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
