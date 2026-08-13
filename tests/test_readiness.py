from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from research_workbench.db import connect
from research_workbench.readiness import formal_research_readiness
from research_workbench.research_design import create_design_draft, decide_design
from research_workbench.scholarship import create_claim
from research_workbench.service import initialize_project


class FormalResearchReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        initialize_project(self.project, "门禁测试")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def approve_design(self, content: str) -> None:
        draft = create_design_draft(
            self.project, "共同计划", content, "shared_design", "manual", "Professor",
        )
        decide_design(self.project, draft["design_id"], True, "Professor", "批准")

    def insert_freeze(self, payload: dict[str, object], status: str = "approved") -> None:
        with connect(self.project) as connection:
            connection.execute(
                """INSERT INTO evidence_freezes(
                       freeze_id, title, status, payload_json, approved_by, approved_at, created_at
                   ) VALUES ('FRZ_test', '测试冻结', ?, ?, 'Professor', '2026-01-01', '2026-01-01')""",
                (status, json.dumps(payload, ensure_ascii=False)),
            )

    def insert_historiography(self, status: str) -> None:
        with connect(self.project) as connection:
            connection.execute(
                """INSERT INTO historiography_entries(
                       entry_id, work_title, position, contribution, limitation, relevance,
                       source_refs_json, status, created_at
                   ) VALUES (?, 'A Study', '立场', '贡献', '限制', '相关', '[]', ?, '2026-01-01')""",
                (f"HIS_{status}", status),
            )

    @staticmethod
    def nonempty_freeze_payload(claim_id: str = "CLM_test") -> dict[str, object]:
        return {
            "claims": [{
                "claim_id": claim_id,
                "text": "有限主张",
                "evidence": [{"evidence_id": "EVI_test", "source_id": "SRC_test"}],
            }],
        }

    def test_explicit_plan_event_minimum_and_historiography_are_hard_gates(self) -> None:
        self.approve_design("每组原则上先形成约30—50条有效记录；并建立学术史。")

        result = formal_research_readiness(self.project)

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["stage"], "CONTINUE_RESEARCH")
        self.assertEqual(result["event_requirement"], 30)
        self.assertTrue(any("尚无获批事件" in item for item in result["blockers"]))
        self.assertTrue(any("人工批准的学术史" in item for item in result["blockers"]))
        self.assertTrue(any("批准冻结包" in item for item in result["blockers"]))

    def test_candidate_historiography_does_not_satisfy_an_explicit_historiography_gate(self) -> None:
        self.approve_design("完成学术史后进入正式写作。")
        self.insert_historiography("candidate")
        self.insert_freeze(self.nonempty_freeze_payload())

        result = formal_research_readiness(self.project)

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["historiography_entries"], 1)
        self.assertEqual(result["candidate_historiography_entries"], 1)
        self.assertEqual(result["approved_historiography_entries"], 0)
        self.assertTrue(any("人工批准的学术史" in item for item in result["blockers"]))

    def test_candidate_historiography_and_claims_without_a_freeze_cannot_report_ready(self) -> None:
        self.approve_design("完成学术史后进入正式写作。")
        self.insert_historiography("candidate")
        create_claim(self.project, "尚未冻结的候选主张。")

        result = formal_research_readiness(self.project)

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["stage"], "CONTINUE_RESEARCH")
        self.assertFalse(result["formal_draft_ready"])
        self.assertFalse(result["submission_ready"])
        self.assertTrue(any("人工批准的学术史" in item for item in result["blockers"]))
        self.assertTrue(any("批准冻结包" in item for item in result["blockers"]))

    def test_approved_historiography_and_nonempty_freeze_allow_formal_drafting(self) -> None:
        self.approve_design("完成学术史后进入正式写作。")
        self.insert_historiography("approved")
        self.insert_freeze(self.nonempty_freeze_payload())

        result = formal_research_readiness(self.project)

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["stage"], "FORMAL_DRAFT_READY")
        self.assertTrue(result["formal_draft_ready"])
        self.assertFalse(result["continue_research"])
        self.assertFalse(result["submission_ready"])
        self.assertEqual(result["submission_status"], "REQUIRES_MANUSCRIPT_EXPORT_CHECK")

    def test_generic_design_still_requires_an_approved_nonempty_freeze(self) -> None:
        self.approve_design("围绕明确时段和材料形成有限解释。")
        claim = create_claim(self.project, "仍待冻结的候选主张。")

        result = formal_research_readiness(self.project)

        self.assertEqual(claim["status"], "candidate")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["approved_nonempty_freeze_count"], 0)
        self.assertEqual(result["submission_status"], "RESEARCH_NOT_READY")
        self.assertTrue(any("批准冻结包" in item for item in result["blockers"]))

    def test_empty_approved_freeze_does_not_open_formal_drafting(self) -> None:
        self.approve_design("围绕明确时段和材料形成有限解释。")
        self.insert_freeze({"claims": []})

        result = formal_research_readiness(self.project)

        self.assertEqual(result["approved_freeze_count"], 1)
        self.assertEqual(result["approved_nonempty_freeze_count"], 0)
        self.assertEqual(result["stage"], "CONTINUE_RESEARCH")

    def test_approved_freeze_is_the_authoritative_promotion_for_candidate_claims(self) -> None:
        self.approve_design("围绕明确时段和材料形成有限解释。")
        claim = create_claim(self.project, "经冻结包批准的解释性主张。")
        self.insert_freeze(self.nonempty_freeze_payload(claim["claim_id"]))

        result = formal_research_readiness(self.project)

        self.assertEqual(claim["status"], "candidate")
        self.assertEqual(result["status"], "READY")
        self.assertTrue(result["formal_draft_ready"])
        self.assertEqual(result["approved_nonempty_freeze_count"], 1)

    def test_no_approved_design_returns_the_compatibility_and_stage_fields(self) -> None:
        result = formal_research_readiness(self.project)

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["stage"], "CONTINUE_RESEARCH")
        self.assertTrue(result["continue_research"])
        self.assertFalse(result["formal_draft_ready"])
        self.assertFalse(result["submission_ready"])


if __name__ == "__main__":
    unittest.main()
