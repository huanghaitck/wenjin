from __future__ import annotations

import tempfile
import unittest
import json
import os
from pathlib import Path
from unittest.mock import patch

import research_workbench.authoring as authoring

from research_workbench.authoring import (
    create_journal_template,
    create_writing_proposal,
    decide_writing_proposal,
    import_manuscript,
    manuscript_detail,
    run_manuscript_review,
)
from research_workbench.db import connect
from research_workbench.service import initialize_project
from research_workbench.service import save_source_citation_metadata


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

    def test_review_ledger_uses_the_approved_freeze_referenced_by_the_manuscript(self) -> None:
        manuscript = import_manuscript(
            self.project, "事件证据稿", "# 正文\n\n道路记录。[EVID:EVT_formal]",
        )
        research = {
            "freezes": [{
                "freeze_id": "FRZ_formal", "title": "正式事件冻结", "status": "approved",
                "payload": {"claims": [{
                    "claim_id": "CLM_formal", "text": "道路构成移动条件。",
                    "evidence": [{
                        "evidence_id": "EVT_formal", "relation": "supports", "source_id": "SRC_book",
                        "physical_page": 20, "physical_pages": [20, 21], "printed_pages": ["12", "13"],
                        "qualification": "FROZEN_WRITABLE", "quote": "原文片段",
                    }],
                }]},
            }],
            "claims": [{"claim_id": "CLM_old", "text": "旧账本", "evidence": [{"evidence_id": "EVI_old"}]}],
        }
        prompts: list[str] = []
        with patch("research_workbench.authoring.research_state", return_value=research):
            run_manuscript_review(
                self.project, manuscript["manuscript_id"], "builtin-history-research",
                reviewer=lambda prompt: prompts.append(prompt) or "阻断问题：无。主要问题：无。建议：保留。",
            )
        self.assertTrue(all("批准冻结包 FRZ_formal" in prompt for prompt in prompts))
        self.assertTrue(all("EVT_formal" in prompt and "原书页 12–13｜物理页 20–21" in prompt for prompt in prompts))
        self.assertTrue(all("EVI_old" not in prompt for prompt in prompts))

    def test_review_reads_template_export_preview_instead_of_internal_markers(self) -> None:
        manuscript = import_manuscript(
            self.project, "顺序编码评审稿", "# 正文\n\n道路事实。[EVID:EVT_formal]",
        )
        with connect(self.project) as connection:
            project_id = connection.execute("SELECT project_id FROM projects").fetchone()[0]
            connection.execute(
                "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("SRC_book", project_id, "测试书", "local_file", "book.pdf", "acquired", "ready", "partial", "2026-01-01"),
            )
            connection.execute(
                "INSERT INTO pages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("PAGE_book_20", "SRC_book", 20, "12", "body", "verified", "eligible",
                 "{}", "{}"),
            )
            payload = {"claims": [{"claim_id": "CLM_formal", "text": "道路事实", "evidence": [{
                "evidence_id": "EVT_formal", "relation": "supports", "source_id": "SRC_book",
                "physical_page": 20, "physical_pages": [20], "page_ids": ["PAGE_book_20"], "printed_pages": [],
                "qualification": "FROZEN_WRITABLE", "quote": "原文片段",
            }]}]}
            connection.execute(
                "INSERT INTO evidence_freezes(freeze_id, title, status, payload_json, approved_by, approved_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("FRZ_formal", "正式事件冻结", "approved", json.dumps(payload), "tester", "2026-01-01", "2026-01-01"),
            )
        save_source_citation_metadata(self.project, "SRC_book", {
            "author": "张三", "title": "测试书", "place": "西安", "publisher": "测试出版社",
            "year": "1908", "type_code": "M", "verified_by": "tester",
        })
        template = create_journal_template(
            self.project, "《顺序编码测试》", "参考文献置于文后，按正文出现顺序全文连续编号",
            ["正文", "参考文献", "英文摘要", "作者信息"], requirements={},
        )
        prompts: list[str] = []
        with patch("research_workbench.authoring.current_shared_design", return_value={
            "title": "人工批准的范围", "content": "总框架1861—1879；核心窗口1871—1875。",
        }):
            run_manuscript_review(
                self.project, manuscript["manuscript_id"], template["template_id"],
                reviewer=lambda prompt: prompts.append(prompt) or "阻断问题：无。主要问题：无。建议：保留。",
            )
        self.assertTrue(all("道路事实。[1]12" in prompt for prompt in prompts))
        self.assertTrue(all("[1] 张三. 测试书[M]. 西安：测试出版社，1908" in prompt for prompt in prompts))
        self.assertTrue(all("[EVID:EVT_formal]" not in prompt for prompt in prompts))
        self.assertTrue(all("物理页只用于在 PDF 中回查" in prompt for prompt in prompts))
        self.assertTrue(all("总框架1861—1879；核心窗口1871—1875" in prompt for prompt in prompts))

    def test_review_ledger_includes_citable_direct_page_markers(self) -> None:
        manuscript = import_manuscript(
            self.project, "原页直引评审稿", "# 正文\n\n道路事实。[CITE:SRC_book@PAGE_book_20]",
        )
        with connect(self.project) as connection:
            project_id = connection.execute("SELECT project_id FROM projects").fetchone()[0]
            connection.execute(
                "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("SRC_book", project_id, "测试书", "local_file", "book.pdf", "acquired", "ready", "partial", "2026-01-01"),
            )
            connection.execute(
                "INSERT INTO pages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("PAGE_book_20", "SRC_book", 20, "12", "body", "human_spot_checked",
                 "research_usable", "{}", "{}"),
            )
        save_source_citation_metadata(self.project, "SRC_book", {
            "author": "张三", "title": "测试书", "place": "西安", "publisher": "测试出版社",
            "year": "1908", "type_code": "M", "verified_by": "tester",
        })
        prompts: list[str] = []
        run_manuscript_review(
            self.project, manuscript["manuscript_id"], "builtin-tangdu-current",
            reviewer=lambda prompt: prompts.append(prompt) or "阻断问题：无。主要问题：无。建议：保留。",
        )
        self.assertTrue(all("DIRECT_PAGE_CITABLE｜SRC_book｜PAGE_book_20" in prompt for prompt in prompts))
        self.assertTrue(all("不要因为 DIRECT_PAGE_CITABLE 未进入冻结包" in prompt for prompt in prompts))
        self.assertTrue(all("道路事实。[1]12" in prompt for prompt in prompts))

    def test_deepseek_review_requests_disable_thinking_mode(self) -> None:
        response = {
            "choices": [{"message": {"content": "阻断问题：无。"}, "finish_reason": "stop"}],
        }
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "deepseek-v4-flash",
            "HRW_AGENT_BASE_URL": "https://api.deepseek.com", "HRW_AGENT_API_KEY": "test-key",
        }
        with patch.dict(os.environ, environment, clear=False), patch.object(authoring, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
            self.assertEqual(authoring._review_model_write("直接评审", "HRW_AGENT"), "阻断问题：无。")
            payload = json.loads(urlopen.call_args.args[0].data.decode())
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["max_tokens"], 8192)

    def test_deepseek_writing_uses_configured_budget_and_timeout(self) -> None:
        response = {"choices": [{"message": {"content": "分节正文。"}}]}
        environment = {
            "HRW_AGENT_PROVIDER": "openai_compatible", "HRW_AGENT_MODEL": "deepseek-v4-flash",
            "HRW_AGENT_BASE_URL": "https://api.deepseek.com", "HRW_AGENT_API_KEY": "test-key",
            "HRW_AGENT_WRITE_MAX_TOKENS": "10000", "HRW_AGENT_TIMEOUT_SECONDS": "300",
        }
        with patch.dict(os.environ, environment, clear=False), patch.object(authoring, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
            self.assertEqual(authoring._model_write("写一节正文"), "分节正文。")
            payload = json.loads(urlopen.call_args.args[0].data.decode())
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["max_tokens"], 10000)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 300)


if __name__ == "__main__":
    unittest.main()
