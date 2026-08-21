from __future__ import annotations

import tempfile
import unittest
import json
import os
import re
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import research_workbench.authoring as authoring

from research_workbench.authoring import (
    create_historiography_entry,
    create_journal_template,
    create_reading_job,
    create_writing_proposal,
    decide_writing_proposal,
    import_manuscript,
    manuscript_detail,
    run_manuscript_review,
    save_reading_note,
)
from research_workbench.db import connect
from research_workbench.research_events import create_event_candidates, decide_event
from research_workbench.scholarship import approve_freeze, create_event_freeze
from research_workbench.service import correct_block, initialize_project
from research_workbench.service import import_structure, register_source
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

    def _approved_event_freeze(self, label: str, event_date: str, route: str,
                               anchor_text: str) -> str:
        source_file = Path(self.temporary.name) / f"{label}.txt"
        source_file.write_text(f"immutable fixture {label}", encoding="utf-8")
        source = register_source(self.project, source_file, label)
        import_structure(
            self.project, source["source_id"],
            Path(__file__).parent / "fixtures" / "m1_structure.json",
        )
        block_id = f"{source['source_id']}:B2"
        correct_block(
            self.project, block_id, anchor_text, "Professor", "逐字核对事件锚块",
        )
        with connect(self.project) as connection:
            connection.execute(
                "UPDATE pages SET verification_state = 'human_spot_checked', "
                "use_state = 'research_usable' WHERE page_id = ?",
                (f"{source['source_id']}:P1",),
            )
        event = create_event_candidates(
            self.project,
            [{
                "case_id": label, "event_date": event_date, "route": route,
                "source_id": source["source_id"], "block_ids": [block_id],
                "field_anchors": {
                    "event_date": [block_id], "route": [block_id],
                    "original_text": [block_id],
                },
                "original_text": anchor_text,
                "notes": "原页已人工复核；日期和路线只按锚块使用。",
            }],
            "test-model",
        )[0]
        event = decide_event(
            self.project, event["event_id"], True, "Professor", "逐字核对原页",
        )
        freeze = create_event_freeze(
            self.project, f"{label} freeze",
            [{
                "text": f"{label} 的日期和路线有原页支持。",
                "does_not_support": "不得换成别的日期、页码或地名。",
                "evidence": [{"event_id": event["event_id"], "relation": "supports"}],
            }],
        )
        approve_freeze(
            self.project, freeze["freeze_id"], "Professor", "批准日期、路线和边界",
        )
        return str(event["event_id"])

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

    def test_review_returns_warning_only_source_coverage_receipt(self) -> None:
        source_file = Path(self.temporary.name) / "study.pdf"
        source_file.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
        source = register_source(self.project, source_file, "已读直接研究")
        import_structure(self.project, source["source_id"], Path(__file__).parent / "fixtures" / "m1_structure.json")
        with connect(self.project) as connection:
            connection.execute(
                "UPDATE pages SET verification_state = 'human_verified', use_state = 'research_usable' "
                "WHERE source_id = ? AND physical_page = 1", (source["source_id"],),
            )
            connection.execute(
                "UPDATE blocks SET verification_state = 'human_verified', use_state = 'research_usable' "
                "WHERE page_id = ?", (f"{source['source_id']}:P1",),
            )
        job = create_reading_job(
            self.project, "直接研究", "如何解释道路？", "targeted", [source["source_id"]], "一页后停止",
        )
        save_reading_note(self.project, job["job_id"], source["source_id"], [1], "道路解释摘要。", True)
        create_historiography_entry(self.project, {
            "work_title": "已读直接研究", "position": "强调道路", "contribution": "解释移动",
            "limitation": "个案有限", "relevance": "直接研究", "source_refs": [source["source_id"]],
        })
        prompts: list[str] = []
        result = run_manuscript_review(
            self.project, self.manuscript["manuscript_id"], "builtin-history-research",
            reviewer=lambda prompt: prompts.append(prompt) or "阻断问题：无。主要问题：覆盖回执显示该研究尚未进入正文。",
        )
        receipt = result["coverage_receipt"]
        self.assertEqual(receipt["project_source_count"], 1)
        self.assertEqual(receipt["read_source_count"], 1)
        self.assertEqual(receipt["historiography_source_count"], 1)
        self.assertEqual(receipt["manuscript_cited_source_count"], 0)
        self.assertEqual(receipt["read_but_unused_direct_research"][0]["source_id"], source["source_id"])
        self.assertTrue(all("不设硬阈值" in prompt for prompt in prompts))

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

    def test_review_ledger_includes_approved_event_fields_and_all_usable_anchor_blocks(self) -> None:
        may_event = self._approved_event_freeze(
            "Sosnovsky-1875", "1875-05-25", "白马河谷到八渡山分水岭",
            "1875年5月25日，考察队从白马河谷行至八渡山分水岭。",
        )
        kreitner_event = self._approved_event_freeze(
            "Kreitner-1879", "1879-04-18", "秦岭山脊向北坡下行",
            "Kreitner记述一行人在秦岭山脊转向北坡下行。",
        )
        manuscript = import_manuscript(
            self.project, "事件锚块评审稿",
            f"# 正文\n\n俄团于5月25日进入所记路线。[EVID:{may_event}] "
            f"Kreitner另有越岭记述。[EVID:{kreitner_event}]",
        )
        prompts: list[str] = []
        run_manuscript_review(
            self.project, manuscript["manuscript_id"], "builtin-history-research",
            reviewer=lambda prompt: prompts.append(prompt) or
            "阻断问题：无。主要问题：证据边界已说明。可保留之处：日期与路线有锚块支持。",
        )
        self.assertTrue(all("event_date=1875-05-25" in prompt for prompt in prompts))
        self.assertTrue(all("route=白马河谷到八渡山分水岭" in prompt for prompt in prompts))
        self.assertTrue(all("1875年5月25日，考察队从白马河谷行至八渡山分水岭。" in prompt for prompt in prompts))
        self.assertTrue(all("Kreitner记述一行人在秦岭山脊转向北坡下行。" in prompt for prompt in prompts))
        self.assertTrue(all("上下文没有支持时，不得凭模型记忆发明替代日期" in prompt for prompt in prompts))

    def test_review_context_losslessly_compacts_claim_links_and_keeps_origin_boundaries(self) -> None:
        source_id = "SRC_compact_review"
        anchor_ids = [f"{source_id}:B{index:03d}" for index in range(1, 100)]
        key_prefixes = {
            0: "20 МАЯ. 考察队从汉中府出发，院内正在组织驮载与护送。",
            1: "22 МАЯ. 队伍经过白马河村落，进入峡谷并沿石阶山路上升。",
            2: "25 МАЯ. 队伍到达八渡山分水岭，辨识汉江与嘉陵江水系。",
            3: "Kreitner 记载 Unsere chinesische Begleitung 在 Sin-ling-Gebirge 下马步行。",
        }
        anchor_texts = [
            (
                key_prefixes.get(index, f"人工核验锚块 {index + 1}。")
                + " "
                + "这是一段经过人工逐字复核的原页锚文本，用于保留道路、移动、参与者与观察语义。" * 12
                + f" 锚块结尾 {index + 1}。"
            )
            for index in range(99)
        ]
        with connect(self.project) as connection:
            project_id = connection.execute("SELECT project_id FROM projects").fetchone()[0]
            connection.execute(
                "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (source_id, project_id, "压缩回归原书", "local_file", "compact.txt",
                 "acquired", "ready", "partial", "2026-01-01"),
            )
            for page_index in range(1, 11):
                connection.execute(
                    "INSERT INTO pages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"{source_id}:P{page_index:03d}", source_id, 200 + page_index,
                     str(600 + page_index), "body", "human_verified",
                     "research_usable", "{}", "{}"),
                )
            for index, (block_id, anchor_text) in enumerate(zip(anchor_ids, anchor_texts)):
                page_index = index // 10 + 1
                connection.execute(
                    "INSERT INTO blocks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (block_id, f"{source_id}:P{page_index:03d}", index % 10 + 1, "paragraph",
                     anchor_text, anchor_text, "human_verified", "research_usable", "{}"),
                )

        anchor_groups = [[] for _ in range(46)]
        for index, block_id in enumerate(anchor_ids):
            anchor_groups[index % len(anchor_groups)].append(block_id)
        event_dates = ["1875-05-20", "1875-05-22", "1875-05-25", "1879-04-18"]
        routes = ["汉中府出发", "白马河峡谷山路", "八渡山分水岭", "秦岭山脊北坡下行"]
        evidence_rows: list[dict[str, object]] = []
        for index, group in enumerate(anchor_groups):
            page_indexes = list(dict.fromkeys((anchor_ids.index(block_id) // 10) + 1 for block_id in group))
            evidence_rows.append({
                "evidence_id": f"EVT_compact_{index:02d}", "relation": "supports",
                "source_id": source_id, "physical_page": 200 + page_indexes[0],
                "physical_pages": [200 + value for value in page_indexes],
                "page_ids": [f"{source_id}:P{value:03d}" for value in page_indexes],
                "printed_pages": [str(600 + value) for value in page_indexes],
                "qualification": "FROZEN_WRITABLE",
                "event_date": event_dates[index] if index < 4 else f"1875-06-{index % 28 + 1:02d}",
                "route": routes[index] if index < 4 else f"核验路线 {index}",
                "note": f"批准事件备注 {index}；只按本项锚块使用。",
                "block_ids": group,
                "field_anchors": {
                    "event_date": [group[0]], "route": group,
                    "original_text": group,
                },
                "quote": anchor_texts[anchor_ids.index(group[0])],
            })

        shared_text = "多组旅行把秦岭实践为通道与调查对象；这一主张只按映射到的事件逐项成立。" * 6
        freeze_one = {
            "freeze_id": "FRZ_compact_one", "title": "压缩冻结一", "status": "approved",
            "payload": {
                "boundary": "冻结一边界：不得把规范化日期、路线或参与者信息外推到其他事件。" * 3,
                "claims": [
                    {"claim_id": "CLM_shared", "text": shared_text,
                     "evidence": evidence_rows},
                    {"claim_id": "CLM_local", "text": "道路与地方协助共同影响移动。" * 4,
                     "does_not_support": "不得将协助写成无条件通行。" * 4,
                     "evidence": [{**row, "relation": "background"} for row in evidence_rows]},
                ],
            },
        }
        freeze_two = {
            "freeze_id": "FRZ_compact_two", "title": "压缩冻结二", "status": "approved",
            "payload": {
                "boundary": "冻结二边界：不得把文本可见度等同于实际在场程度。" * 3,
                "claims": [
                    {"claim_id": "CLM_shared", "text": shared_text,
                     "evidence": [{**row, "relation": "weakens"} for row in evidence_rows]},
                    {"claim_id": "CLM_counter", "text": "不同记录方式会造成参与者可见度差异。" * 4,
                     "does_not_support": "不得据此断言某案没有地方参与者。" * 4,
                     "evidence": [{**row, "relation": "counterevidence"} for row in evidence_rows]},
                ],
            },
        }
        freezes = [freeze_one, freeze_two]
        evidence_ids = [str(row["evidence_id"]) for row in evidence_rows]
        context = authoring._review_evidence_context(self.project, evidence_ids, freezes)

        self.assertLess(len(context), authoring._REVIEW_EVIDENCE_CONTEXT_MAX_CHARS)
        naive_repeated_claim_chars = sum(
            len(str(claim["text"]))
            + len(str(claim.get("does_not_support", "") or freeze["payload"].get("boundary", "")))
            for freeze in freezes for claim in freeze["payload"]["claims"]
            for _evidence in claim["evidence"]
        ) + sum(len(text) for text in anchor_texts)
        self.assertGreater(naive_repeated_claim_chars, authoring._REVIEW_EVIDENCE_CONTEXT_MAX_CHARS)
        self.assertIn("上下文无损压缩回执", context)
        self.assertIn("99 个合格锚块均保留全文，未截断", context)
        for block_id, anchor_text in zip(anchor_ids, anchor_texts):
            self.assertRegex(
                context,
                rf"(?m)^A\d{{3}}=\[ANCHOR {re.escape(block_id)}\] {re.escape(anchor_text)}$",
            )
        self.assertLess(context.index("E01=[EVID:EVT_compact_00]"),
                        context.index("E02=[EVID:EVT_compact_01]"))
        for value in (
            "event_date=1875-05-20｜route=汉中府出发｜note=批准事件备注 0",
            "event_date=1875-05-22｜route=白马河峡谷山路｜note=批准事件备注 1",
            "event_date=1875-05-25｜route=八渡山分水岭｜note=批准事件备注 2",
            "Kreitner 记载 Unsere chinesische Begleitung 在 Sin-ling-Gebirge 下马步行。",
            "原书页 601｜物理页 201",
        ):
            self.assertIn(value, context)

        evidence_by_alias = {
            alias: evidence_id for alias, evidence_id in re.findall(
                r"^(E\d+)=\[EVID:([^]]+)\]$", context, re.MULTILINE,
            )
        }
        freeze_by_alias = {
            alias: freeze_id for alias, freeze_id in re.findall(
                r"^(F\d+)=批准冻结包 ([^：]+)：", context, re.MULTILINE,
            )
        }
        decoded: Counter[tuple[str, str, str, str, str, str]] = Counter()
        for line in context.splitlines():
            match = re.match(
                r"^\[C\d+\] claim_id=(.*?)｜关系映射=(.*?)｜主张=(.*?)｜边界=(.*)$", line,
            )
            if not match:
                continue
            claim_id, mappings, claim_text, boundary = match.groups()
            for relation_group in mappings.split(";"):
                relation_match = re.fullmatch(r"([^[]+)\[(.*)\]", relation_group)
                self.assertIsNotNone(relation_match)
                relation, aliases = relation_match.groups()
                for pair in aliases.split(","):
                    freeze_ref, evidence_ref = pair.split(":", 1)
                    decoded[(freeze_by_alias[freeze_ref], claim_id, claim_text, boundary,
                             evidence_by_alias[evidence_ref], relation)] += 1
        expected: Counter[tuple[str, str, str, str, str, str]] = Counter()
        for freeze in freezes:
            for claim in freeze["payload"]["claims"]:
                boundary = str(
                    claim.get("does_not_support", "") or freeze["payload"].get("boundary", "")
                )
                for evidence in claim["evidence"]:
                    expected[(str(freeze["freeze_id"]), str(claim["claim_id"]),
                              str(claim["text"]), boundary, str(evidence["evidence_id"]),
                              str(evidence["relation"]))] += 1
        self.assertEqual(decoded, expected)
        self.assertIn("主张=" + shared_text + "｜边界=" + freeze_one["payload"]["boundary"], context)
        self.assertIn("主张=" + shared_text + "｜边界=" + freeze_two["payload"]["boundary"], context)

    def test_review_event_context_follows_marker_order_and_keeps_boundaries_local(self) -> None:
        planned = self._approved_event_freeze(
            "Sosnovsky-plan", "1875-05-19", "汉中府驻地",
            "1875年5月19日，考察队拟定下一段行程。",
        )
        departed = self._approved_event_freeze(
            "Sosnovsky-departure", "1875-05-20", "汉中府到白马河谷",
            "1875年5月20日，考察队从汉中府出发。",
        )
        badushan = self._approved_event_freeze(
            "Sosnovsky-Badushan", "1875-05-25", "白马河谷到八渡山分水岭",
            "1875年5月25日，考察队行至八渡山分水岭。",
        )
        uncited = self._approved_event_freeze(
            "Sosnovsky-uncited", "1875-05-26", "八渡山北坡",
            "1875年5月26日，考察队继续向北坡行进。",
        )
        manuscript = import_manuscript(
            self.project, "连续事件评审稿",
            (
                f"# 正文\n\n5月19日拟定行程。[EVID:{planned}] "
                f"5月20日出发。[EVID:{departed}] "
                f"5月25日行至八渡山分水岭。[EVID:{badushan}]"
            ),
        )
        prompts: list[str] = []
        run_manuscript_review(
            self.project, manuscript["manuscript_id"], "builtin-history-research",
            reviewer=lambda prompt: prompts.append(prompt) or
            "阻断问题：无。主要问题：无。可保留之处：三项事件分别有冻结证据。",
        )
        for prompt in prompts:
            ledger = prompt.split("证据台账：\n", 1)[1].split(
                "\n\n本稿实际 CITE 资格回执", 1,
            )[0]
            self.assertLess(ledger.index(f"E01=[EVID:{planned}]"),
                            ledger.index(f"E02=[EVID:{departed}]"))
            self.assertLess(ledger.index(f"E02=[EVID:{departed}]"),
                            ledger.index(f"E03=[EVID:{badushan}]"))
            self.assertIn("event_date=1875-05-19", ledger)
            self.assertIn("event_date=1875-05-20", ledger)
            self.assertIn("event_date=1875-05-25", ledger)
            self.assertNotIn(uncited, ledger)
            self.assertNotIn("event_date=1875-05-26", ledger)
            self.assertRegex(ledger, r"\[C\d+\].*关系映射=supports\[[^]]*F\d+:E01[^]]*\].+主张=.+边界=")
            self.assertRegex(ledger, r"\[C\d+\].*关系映射=supports\[[^]]*F\d+:E03[^]]*\].+主张=.+边界=")
            self.assertIn("定义仅通过映射约束对应 EVID，不得跨 EVID 外推", ledger)
            self.assertIn("不得用某一计划、出发或途中事件的边界", ledger)
            self.assertIn("不得用某个计划事件或出发事件的边界", prompt)

    def test_review_without_evid_markers_does_not_inject_approved_freezes(self) -> None:
        approved = self._approved_event_freeze(
            "Sosnovsky-unused", "1875-05-25", "白马河谷到八渡山分水岭",
            "1875年5月25日，考察队行至八渡山分水岭。",
        )
        manuscript = import_manuscript(
            self.project, "无证据标记评审稿", "# 正文\n\n本段尚未挂接冻结证据。",
        )
        prompts: list[str] = []
        run_manuscript_review(
            self.project, manuscript["manuscript_id"], "builtin-history-research",
            reviewer=lambda prompt: prompts.append(prompt) or
            "阻断问题：正文尚未挂接证据。主要问题：无。建议：回到证据门禁。",
        )
        for prompt in prompts:
            ledger = prompt.split("证据台账：\n", 1)[1].split(
                "\n\n本稿实际 CITE 资格回执", 1,
            )[0]
            self.assertEqual(ledger, "当前正文没有 EVID。")
            self.assertNotIn(approved, ledger)
            self.assertNotIn("event_date=1875-05-25", ledger)

    def test_review_rejects_unsupported_replacement_date_without_persisting_group(self) -> None:
        event_id = self._approved_event_freeze(
            "Sosnovsky-1875", "1875-05-25", "白马河谷到八渡山分水岭",
            "1875年5月25日，考察队从白马河谷行至八渡山分水岭。",
        )
        manuscript = import_manuscript(
            self.project, "无依据日期评审稿",
            f"# 正文\n\n俄团于5月25日进入所记路线。[EVID:{event_id}]",
        )
        calls = 0

        def introduce_unsupported_date(_prompt: str) -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                return "主要问题：5月25日虽有事件锚块，仍需检查正文是否准确复述路线。"
            return "主要问题：原日期有误，应将5月25日改为5月23日后再审。"

        with self.assertRaisesRegex(ValueError, "ungrounded date/page locator.*month-day:5-23"):
            run_manuscript_review(
                self.project, manuscript["manuscript_id"], "builtin-history-research",
                reviewer=introduce_unsupported_date,
            )
        self.assertEqual(calls, 2)
        self.assertEqual(
            manuscript_detail(self.project, manuscript["manuscript_id"])["review_groups"], [],
        )

    def test_review_allows_date_already_present_in_grounded_context(self) -> None:
        event_id = self._approved_event_freeze(
            "Sosnovsky-1875", "1875-05-25", "白马河谷到八渡山分水岭",
            "1875年5月25日，考察队从白马河谷行至八渡山分水岭。",
        )
        manuscript = import_manuscript(
            self.project, "已有日期评审稿",
            f"# 正文\n\n俄团于5月25日进入所记路线。[EVID:{event_id}]",
        )
        result = run_manuscript_review(
            self.project, manuscript["manuscript_id"], "builtin-history-research",
            reviewer=lambda _prompt: "可保留之处：5月25日已有批准事件和原页锚块支持，可以保留。",
        )
        self.assertEqual(len(result["reports"]), 3)
        self.assertEqual(
            len(manuscript_detail(self.project, manuscript["manuscript_id"])["review_groups"]), 1,
        )

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
        export_previews = [
            prompt.split("期刊导出预览：\n", 1)[1] for prompt in prompts
        ]
        self.assertTrue(all("[EVID:EVT_formal]" not in preview for preview in export_previews))
        self.assertTrue(all("E01=[EVID:EVT_formal]" in prompt for prompt in prompts))
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
        self.assertTrue(all("DIRECT_PAGE_CITABLE｜[CITE:SRC_book@PAGE_book_20]" in prompt for prompt in prompts))
        self.assertTrue(all("不要因为 CITE 未进入冻结包" in prompt for prompt in prompts))
        self.assertTrue(all("道路事实。[1]12" in prompt for prompt in prompts))

    def test_review_context_recognizes_only_cited_approved_historiography(self) -> None:
        source_file = Path(self.temporary.name) / "approved-study.pdf"
        source_file.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
        source = register_source(self.project, source_file, "道路研究")
        import_structure(
            self.project, source["source_id"], Path(__file__).parent / "fixtures" / "m1_structure.json",
        )
        page_id = f"{source['source_id']}:P1"
        with connect(self.project) as connection:
            connection.execute(
                "UPDATE pages SET verification_state = 'human_spot_checked', "
                "use_state = 'research_usable', printed_page = '12' WHERE page_id = ?", (page_id,),
            )
        save_source_citation_metadata(self.project, source["source_id"], {
            "author": "李四", "title": "道路研究", "journal": "史学月刊",
            "year": "2020", "issue": "2", "page_range": "10-20", "type_code": "J",
            "verified_by": "Professor",
        })
        job = create_reading_job(
            self.project, "学术史阅读", "道路研究如何解释移动？", "targeted",
            [source["source_id"]], "读完选定页停止",
        )
        save_reading_note(
            self.project, job["job_id"], source["source_id"], [1],
            "作者将道路条件与旅行活动联系起来。", complete=True,
        )
        entry = create_historiography_entry(self.project, {
            "work_title": "道路研究", "position": "道路与移动", "contribution": "解释旅行条件",
            "limitation": "个案区域有限", "relevance": "用于学术史对话",
            "source_refs": [source["source_id"]],
        })
        authoring.decide_historiography_entry(
            self.project, entry["entry_id"], True, "Professor", "已核书目、阅读札记和原页。",
        )
        unused_file = Path(self.temporary.name) / "unused-study.pdf"
        unused_file.write_bytes(b"%PDF-1.4\nunused fixture\n%%EOF\n")
        unused = register_source(self.project, unused_file, "外围研究")
        import_structure(
            self.project, unused["source_id"], Path(__file__).parent / "fixtures" / "m1_structure.json",
        )
        with connect(self.project) as connection:
            connection.execute(
                "UPDATE pages SET verification_state = 'human_spot_checked', "
                "use_state = 'research_usable', printed_page = '30' "
                "WHERE source_id = ? AND physical_page = 1", (unused["source_id"],),
            )
        save_source_citation_metadata(self.project, unused["source_id"], {
            "author": "王五", "title": "外围研究", "journal": "史学集刊", "year": "2021",
            "issue": "3", "page_range": "25-40", "type_code": "J", "verified_by": "Professor",
        })
        unused_job = create_reading_job(
            self.project, "外围阅读", "外围研究说明什么？", "targeted",
            [unused["source_id"]], "读完选定页停止",
        )
        save_reading_note(
            self.project, unused_job["job_id"], unused["source_id"], [1],
            "该文处理另一区域。", complete=True,
        )
        unused_entry = create_historiography_entry(self.project, {
            "work_title": "外围研究", "position": "邻近区域", "contribution": "提供区域比较",
            "limitation": "不讨论本案", "relevance": "仅作外围参照",
            "source_refs": [unused["source_id"]],
        })
        authoring.decide_historiography_entry(
            self.project, unused_entry["entry_id"], True, "Professor", "已核但本稿没有引用。",
        )
        manuscript = import_manuscript(
            self.project, "学术史引证评审稿",
            f"# 正文\n\n已有研究解释了道路条件。[CITE:{source['source_id']}@{page_id}]",
        )
        prompts: list[str] = []
        result = run_manuscript_review(
            self.project, manuscript["manuscript_id"], "builtin-tangdu-current",
            reviewer=lambda prompt: prompts.append(prompt) or "阻断问题：无。主要问题：无。建议：保留。",
        )
        expected = f"APPROVED_HISTORIOGRAPHY_CITABLE｜[CITE:{source['source_id']}@{page_id}]"
        self.assertTrue(all(expected in prompt for prompt in prompts), prompts[0])
        self.assertTrue(all(f"已批准学术史 {entry['entry_id']}" in prompt for prompt in prompts))
        self.assertTrue(all("书目状态 HUMAN_VERIFIED" in prompt for prompt in prompts))
        self.assertTrue(all("页状态 human_spot_checked｜用途 research_usable" in prompt for prompt in prompts))
        self.assertTrue(all("EVID 支撑正文事实，CITE 用于学术史对话" in prompt for prompt in prompts))
        citation_receipts = [
            prompt.split("本稿实际 CITE 资格回执（只列正文已出现的 CITE）：\n", 1)[1]
            .split("\n\n期刊导出预览：", 1)[0]
            for prompt in prompts
        ]
        self.assertTrue(all(unused_entry["entry_id"] not in receipt for receipt in citation_receipts))
        self.assertTrue(all(unused["source_id"] not in receipt for receipt in citation_receipts))
        self.assertEqual(result["citation_context"][0]["citation_qualification"],
                         "APPROVED_HISTORIOGRAPHY_CITABLE")
        self.assertEqual(len(result["citation_context"]), 1)
        self.assertEqual(result["citation_context"][0]["approved_historiography"][0]["entry_id"],
                         entry["entry_id"])

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
