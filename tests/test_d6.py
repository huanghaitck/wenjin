from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from research_workbench.authoring import (
    create_writing_proposal,
    decide_writing_proposal,
    import_manuscript,
    manuscript_detail,
    run_manuscript_review,
)
from research_workbench.service import initialize_project


class D6ManuscriptReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        initialize_project(self.project, "多角色评审")
        self.manuscript = import_manuscript(
            self.project,
            "秦岭道路研究",
            "# 导论\n\n本文讨论道路与移动。\n\n# 第一节\n\n材料只支持有限的行程事实。",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_three_roles_are_version_pinned_and_do_not_partially_persist(self) -> None:
        calls = 0

        def fail_second(prompt: str) -> str:
            nonlocal calls
            calls += 1
            return "这是一份足够长的第一份评审报告，指出具体问题和回退步骤。" if calls == 1 else ""

        with self.assertRaisesRegex(ValueError, "empty or unusably short"):
            run_manuscript_review(
                self.project, self.manuscript["manuscript_id"], "builtin-history-research",
                reviewer=fail_second,
            )
        self.assertEqual(manuscript_detail(self.project, self.manuscript["manuscript_id"])["review_groups"], [])

        prompts: list[str] = []

        def review(prompt: str) -> str:
            prompts.append(prompt)
            return "阻断问题：无。主要问题：证据边界仍需说明。建议回退到已登记证据逐项核对。"

        result = run_manuscript_review(
            self.project, self.manuscript["manuscript_id"], "builtin-history-research",
            reviewer=review,
        )
        self.assertEqual(len(result["reports"]), 3)
        self.assertEqual(len(prompts), 3)
        self.assertTrue(any("argument_reviewer" in prompt for prompt in prompts))
        self.assertTrue(any("source_critic" in prompt for prompt in prompts))
        self.assertTrue(any("citation_editor" in prompt for prompt in prompts))
        self.assertTrue(all("CANDIDATE_NOT_FROZEN" in prompt for prompt in prompts))
        detail = manuscript_detail(self.project, self.manuscript["manuscript_id"])
        self.assertTrue(detail["review_groups"][0]["is_current"])

        section = detail["sections"][0]
        proposal = create_writing_proposal(
            self.project, section["section_id"], "polish", "轻微调整",
            writer=lambda prompt: "本文讨论道路、移动及其证据边界。",
        )
        decide_writing_proposal(
            self.project, proposal["proposal_id"], True, "Professor",
            "本文讨论道路、移动及其证据边界。", "已核对事实未变化",
        )
        self.assertFalse(
            manuscript_detail(self.project, self.manuscript["manuscript_id"])["review_groups"][0]["is_current"]
        )

    def test_optional_secondary_reviewer_uses_adversarial_role(self) -> None:
        prompts: list[str] = []
        result = run_manuscript_review(
            self.project, self.manuscript["manuscript_id"], "builtin-history-research", True,
            reviewer=lambda prompt: prompts.append(prompt) or
            "阻断问题：引文尚未形成独立交叉支持。主要问题：需要检验替代解释。",
        )
        self.assertEqual(len(result["reports"]), 1)
        self.assertEqual(result["reports"][0]["reviewer_role"], "adversarial_reviewer")
        self.assertIn("adversarial_reviewer", prompts[0])


if __name__ == "__main__":
    unittest.main()
