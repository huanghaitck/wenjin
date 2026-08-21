from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from research_workbench.db import initialize_database
from research_workbench.research_design import create_design_draft, decide_design, design_state


class ResearchDesignTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        initialize_database(self.project, "PRJ_test", "Research design test")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_baseline_and_shared_design_are_separate(self) -> None:
        baseline = create_design_draft(
            self.project, "心中方案", "五年窗口", "researcher_baseline", "imported", "Professor"
        )
        decide_design(self.project, baseline["design_id"], True, "Professor", "从旧讨论恢复")
        state = design_state(self.project)
        self.assertEqual(state["researcher_baseline"]["content"], "五年窗口")
        self.assertIsNone(state["shared_design"])

    def test_approving_successor_preserves_old_version(self) -> None:
        first = create_design_draft(
            self.project, "共同计划 v1", "旧内容", "shared_design", "manual", "Professor"
        )
        decide_design(self.project, first["design_id"], True, "Professor", "初版")
        second = create_design_draft(
            self.project, "共同计划 v2", "新内容", "shared_design", "conversation", "Professor",
            base_design_id=first["design_id"],
        )
        decide_design(self.project, second["design_id"], True, "Professor", "讨论后修订")
        state = design_state(self.project)
        self.assertEqual(state["shared_design"]["design_id"], second["design_id"])
        old = next(item for item in state["versions"] if item["design_id"] == first["design_id"])
        self.assertEqual(old["status"], "superseded")

    def test_rejected_draft_does_not_change_current_design(self) -> None:
        current = create_design_draft(
            self.project, "共同计划", "保留内容", "shared_design", "manual", "Professor"
        )
        decide_design(self.project, current["design_id"], True, "Professor", "批准")
        candidate = create_design_draft(
            self.project, "模型建议", "跑偏内容", "shared_design", "model", "DeepSeek"
        )
        decide_design(self.project, candidate["design_id"], False, "Professor", "偏离范围")
        self.assertEqual(design_state(self.project)["shared_design"]["design_id"], current["design_id"])


if __name__ == "__main__":
    unittest.main()
