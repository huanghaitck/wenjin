from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from research_workbench.memory_adapter import (
    memory_promotion_receipts, promote_memory_candidate, save_memory_settings,
)
from research_workbench.scholarship import create_memory_candidate, decide_memory_candidate
from research_workbench.service import initialize_project


class MemoryAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.config = self.root / "config"
        self.historical = self.root / "historical-memory"
        self.engineering = self.root / "codex-memory"
        self.historical.mkdir()
        self.engineering.mkdir()
        initialize_project(self.project, "Memory project")
        save_memory_settings(self.config, str(self.historical), str(self.engineering))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_only_approved_candidate_can_be_promoted_and_is_idempotent(self) -> None:
        candidate = create_memory_candidate(self.project, "阴性结果", "没有找到相应记录。", ["SRC_1@P2"])
        with self.assertRaisesRegex(ValueError, "approved_local"):
            promote_memory_candidate(self.project, self.config, candidate["candidate_id"], "historical")
        decide_memory_candidate(self.project, candidate["candidate_id"], True)
        first = promote_memory_candidate(self.project, self.config, candidate["candidate_id"], "historical")
        second = promote_memory_candidate(self.project, self.config, candidate["candidate_id"], "historical")
        self.assertEqual(first["path"], second["path"])
        self.assertEqual(second["status"], "already_promoted")
        text = Path(first["path"]).read_text(encoding="utf-8")
        self.assertIn('status: "draft"', text)
        self.assertIn("SRC_1@P2", text)
        self.assertEqual(len(memory_promotion_receipts(self.project)), 2)


if __name__ == "__main__":
    unittest.main()
