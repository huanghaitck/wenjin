from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from research_workbench.readiness import formal_research_readiness
from research_workbench.research_design import create_design_draft, decide_design
from research_workbench.service import initialize_project


class FormalResearchReadinessTests(unittest.TestCase):
    def test_explicit_plan_event_minimum_and_historiography_are_hard_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            initialize_project(project, "门禁测试")
            draft = create_design_draft(
                project, "共同计划", "每组原则上先形成约30—50条有效记录；并建立学术史。",
                "shared_design", "manual", "Professor",
            )
            decide_design(project, draft["design_id"], True, "Professor", "批准")
            result = formal_research_readiness(project)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["event_requirement"], 30)
            self.assertTrue(any("尚无获批事件" in item for item in result["blockers"]))
            self.assertTrue(any("学术史" in item for item in result["blockers"]))
