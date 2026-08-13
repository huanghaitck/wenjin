from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from research_workbench.authoring import (
    create_writing_proposal,
    decide_writing_proposal,
    import_manuscript,
    manuscript_detail,
)
from research_workbench.document_model import document_detail, save_document
from research_workbench.db import connect, utc_now
from research_workbench.service import initialize_project
from research_workbench.web import build_server


class SelectionPolishTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        initialize_project(self.project, "Selection polish")
        self.manuscript = import_manuscript(
            self.project, "选区返修",
            "# 正文\n\n1908年，材料称“队伍进入草原”。[^1][EVID:EVI_keep]"
            "[CITE:SRC_keep@SRC_keep:P1]\n\n末尾需要调整。",
        )
        self.section = self.manuscript["sections"][0]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def selection(base: str, text: str, kind: str = "text", node_id: str = "NOD_last") -> dict[str, object]:
        start = base.index(text)
        return {
            "start": start, "end": start + len(text), "text": text,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "node_ids": [node_id], "kind": kind,
        }

    def approved_freeze(self, evidence_id: str = "EVI_1879", status: str = "approved") -> str:
        freeze_id = "FRZ_table_supplement"
        evidence = {
            "evidence_id": evidence_id, "relation": "supports",
            "quote": "1879年，考察者沿秦岭南坡行进，随后北下关中。",
            "physical_page": 79, "physical_pages": [79],
            "page_id": "SRC_1879:P79", "source_version_id": "SVR_1879",
        }
        other_evidence = {
            "evidence_id": "EVI_other", "relation": "background",
            "quote": "1878年，另一份记录仍提到沿线活动。",
            "physical_page": 78, "physical_pages": [78],
            "page_id": "SRC_1878:P78", "source_version_id": "SVR_1878",
        }
        payload = {
            "claims": [{"claim_id": "CLM_1879", "text": "1879年行程", "evidence": [evidence, other_evidence]}],
            "boundary": "只补充1879年行程。",
        }
        with connect(self.project) as connection:
            connection.execute(
                """INSERT INTO evidence_freezes(freeze_id, title, status, payload_json,
                   approved_by, approved_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (freeze_id, "1879年行程", status, json.dumps(payload, ensure_ascii=False),
                 "Professor" if status == "approved" else None,
                 utc_now() if status == "approved" else None, utc_now()),
            )
        return freeze_id

    def test_complete_table_may_add_only_selected_approved_frozen_evidence(self) -> None:
        freeze_id = self.approved_freeze()
        table = (
            "| 年份 | 行程 |\n"
            "| --- | --- |\n"
            "| 1872 | 越岭 [EVID:EVT_1872] |"
        )
        manuscript = import_manuscript(
            self.project, "冻结补表",
            "# 正文\n\n表前保留。[CITE:SRC_before@SRC_before:P1]\n\n" + table + "\n\n表后保留。",
        )
        section = manuscript["sections"][0]
        replacement = table + "\n| 1879 | 沿南坡行进后北下关中 [EVID:EVI_1879] |"
        prompts: list[str] = []
        proposal = create_writing_proposal(
            self.project, section["section_id"], "polish", "补入1879年行程",
            freeze_id, writer=lambda prompt: prompts.append(prompt) or replacement,
            evidence_ids=["EVI_1879"], selection_only=True,
            base_version_id=section["current_version_id"],
            selection=self.selection(section["content"], table, "table", "NOD_table"),
        )
        self.assertIn("允许补充的冻结证据", prompts[0])
        self.assertIn("1879年，考察者沿秦岭南坡行进", prompts[0])
        self.assertNotIn("表前保留", prompts[0])
        self.assertEqual(proposal["validation"]["new_evidence_ids"], ["EVI_1879"])
        self.assertTrue(proposal["validation"]["supplemental_evidence_valid"])
        self.assertTrue(proposal["validation"]["valid"])
        self.assertEqual(proposal["evidence_refs"][0]["evidence_id"], "EVI_1879")
        self.assertEqual(
            proposal["model_snapshot"]["evidence_contract"]["selection_supplement"]["freeze_id"],
            freeze_id,
        )
        decision = decide_writing_proposal(
            self.project, proposal["proposal_id"], True, "Professor", reason="逐格核对新增行及原页",
        )
        self.assertEqual(decision["status"], "approved")

    def test_text_selection_may_add_only_selected_approved_frozen_evidence(self) -> None:
        freeze_id = self.approved_freeze()
        base = self.section["content"]
        selected = "末尾需要调整。"
        replacement = "末尾还可补充1879年的行程记录。[EVID:EVI_1879]"
        prompts: list[str] = []
        proposal = create_writing_proposal(
            self.project, self.section["section_id"], "polish", "只补充获准证据",
            freeze_id, writer=lambda prompt: prompts.append(prompt) or replacement,
            evidence_ids=["EVI_1879"], selection_only=True,
            base_version_id=self.section["current_version_id"],
            selection=self.selection(base, selected),
        )
        self.assertIn("当前选区", prompts[0])
        self.assertIn("1879年，考察者沿秦岭南坡行进", prompts[0])
        self.assertNotIn("队伍进入草原", prompts[0])
        self.assertEqual(proposal["validation"]["new_evidence_ids"], ["EVI_1879"])
        self.assertTrue(proposal["validation"]["supplemental_evidence_valid"])
        self.assertTrue(proposal["validation"]["valid"])
        self.assertEqual(
            proposal["proposed_content"],
            base[:base.index(selected)] + replacement + base[base.index(selected) + len(selected):],
        )
        decision = decide_writing_proposal(
            self.project, proposal["proposal_id"], True, "Professor",
            reason="逐句核对选区、冻结证据与原页",
        )
        self.assertEqual(decision["status"], "approved")

    def test_text_supplement_blocks_unselected_or_missing_new_evidence(self) -> None:
        freeze_id = self.approved_freeze()
        base = self.section["content"]
        selected = "末尾需要调整。"
        invalid = create_writing_proposal(
            self.project, self.section["section_id"], "polish", "补充选定证据",
            freeze_id, writer=lambda _prompt: "末尾新增记录。[EVID:EVI_other]",
            evidence_ids=["EVI_1879"], selection_only=True,
            base_version_id=self.section["current_version_id"],
            selection=self.selection(base, selected),
        )
        self.assertEqual(invalid["validation"]["invalid_new_evidence_ids"], ["EVI_other"])
        self.assertFalse(invalid["validation"]["valid"])
        with self.assertRaisesRegex(ValueError, "evidence contract"):
            decide_writing_proposal(
                self.project, invalid["proposal_id"], True, "Professor", reason="不应批准",
            )

        missing = create_writing_proposal(
            self.project, self.section["section_id"], "polish", "补充选定证据",
            freeze_id, writer=lambda _prompt: "末尾表述已调整。",
            evidence_ids=["EVI_1879"], selection_only=True,
            base_version_id=self.section["current_version_id"],
            selection=self.selection(base, selected),
        )
        self.assertFalse(missing["validation"]["supplemental_evidence_linked"])
        self.assertFalse(missing["validation"]["valid"])
        with self.assertRaisesRegex(ValueError, "evidence contract"):
            decide_writing_proposal(
                self.project, missing["proposal_id"], True, "Professor", reason="不应批准",
            )

    def test_text_supplement_preserves_existing_markers_and_selection_boundary(self) -> None:
        freeze_id = self.approved_freeze()
        base = self.section["content"]
        selected = "1908年，材料称“队伍进入草原”。[^1][EVID:EVI_keep][CITE:SRC_keep@SRC_keep:P1]"
        dropped = create_writing_proposal(
            self.project, self.section["section_id"], "polish", "补充选定证据",
            freeze_id, writer=lambda _prompt: "材料称队伍进入草原。[EVID:EVI_keep][EVID:EVI_1879]",
            evidence_ids=["EVI_1879"], selection_only=True,
            base_version_id=self.section["current_version_id"],
            selection=self.selection(base, selected),
        )
        self.assertIn("1908", dropped["validation"]["selection_missing_protected_counts"])
        self.assertIn("[^1]", dropped["validation"]["selection_missing_protected_counts"])
        self.assertFalse(dropped["validation"]["valid"])

        replacement = selected + "另有1879年行程记录。[EVID:EVI_1879]"
        valid = create_writing_proposal(
            self.project, self.section["section_id"], "polish", "补充选定证据",
            freeze_id, writer=lambda _prompt: replacement,
            evidence_ids=["EVI_1879"], selection_only=True,
            base_version_id=self.section["current_version_id"],
            selection=self.selection(base, selected),
        )
        outside_edit = valid["proposed_content"].replace("末尾需要调整。", "篡改选区外文字。")
        with self.assertRaisesRegex(ValueError, "outside the selected passage"):
            decide_writing_proposal(
                self.project, valid["proposal_id"], True, "Professor",
                edited_content=outside_edit, reason="不应批准",
            )

    def test_table_supplement_rejects_unselected_evidence_and_protects_existing_counts(self) -> None:
        freeze_id = self.approved_freeze()
        table = (
            "| 年份 | 行程 |\n"
            "| --- | --- |\n"
            "| 1872 | 越岭 [EVID:EVT_1872] [EVID:EVT_1872] |"
        )
        manuscript = import_manuscript(self.project, "冻结补表", "# 正文\n\n" + table)
        section = manuscript["sections"][0]
        replacement = (
            "| 年份 | 行程 |\n| --- | --- |\n"
            "| 1872 | 越岭 [EVID:EVT_1872] |\n"
            "| 1879 | 北下关中 [EVID:EVI_1879] [EVID:EVI_unselected] |"
        )
        proposal = create_writing_proposal(
            self.project, section["section_id"], "polish", "补表", freeze_id,
            writer=lambda _prompt: replacement, evidence_ids=["EVI_1879"],
            selection_only=True, base_version_id=section["current_version_id"],
            selection=self.selection(section["content"], table, "table", "NOD_table"),
        )
        self.assertEqual(proposal["validation"]["invalid_new_evidence_ids"], ["EVI_unselected"])
        self.assertIn("[EVID:EVT_1872]", proposal["validation"]["selection_missing_protected_counts"])
        self.assertFalse(proposal["validation"]["valid"])
        with self.assertRaisesRegex(ValueError, "evidence contract"):
            decide_writing_proposal(
                self.project, proposal["proposal_id"], True, "Professor", reason="不应批准",
            )

    def test_supplement_freeze_scope_and_status_are_rechecked_at_approval(self) -> None:
        freeze_id = self.approved_freeze()
        with self.assertRaisesRegex(ValueError, "not part of the approved freeze"):
            create_writing_proposal(
                self.project, self.section["section_id"], "polish", "补证", freeze_id,
                writer=lambda _prompt: "末尾已改。[EVID:EVI_missing]", evidence_ids=["EVI_missing"],
                selection_only=True, base_version_id=self.section["current_version_id"],
                selection=self.selection(self.section["content"], "末尾需要调整。"),
            )

        table = "| 年份 | 行程 |\n| --- | --- |\n| 1872 | 越岭 |"
        manuscript = import_manuscript(self.project, "冻结补表", "# 正文\n\n" + table)
        section = manuscript["sections"][0]
        replacement = table + "\n| 1879 | 北下关中 [EVID:EVI_1879] |"
        proposal = create_writing_proposal(
            self.project, section["section_id"], "polish", "补表", freeze_id,
            writer=lambda _prompt: replacement, evidence_ids=["EVI_1879"],
            selection_only=True, base_version_id=section["current_version_id"],
            selection=self.selection(section["content"], table, "table", "NOD_table"),
        )
        with connect(self.project) as connection:
            connection.execute(
                "UPDATE evidence_freezes SET status = 'rejected' WHERE freeze_id = ?", (freeze_id,),
            )
        with self.assertRaisesRegex(ValueError, "approved evidence freeze"):
            decide_writing_proposal(
                self.project, proposal["proposal_id"], True, "Professor", reason="冻结已失效",
            )

    def test_complete_table_selection_returns_a_table_and_preserves_adjacent_markers(self) -> None:
        table = (
            "| 年份 | 事件 | 来源 |\n"
            "| --- | --- | --- |\n"
            "| 1872 | 越岭 | [EVID:EVT_1872] |\n"
            "| 1879 | 再次越岭 | [CITE:SRC_1879@SRC_1879:P1] |"
        )
        manuscript = import_manuscript(
            self.project, "表格返修",
            "# 正文\n\n前段保留。[EVID:EVT_before]\n\n" + table
            + "\n\n后段保留1908年。[EVID:EVT_after]",
        )
        section = manuscript["sections"][0]
        replacement = table.replace("再次越岭", "越岭活动延续")
        prompts: list[str] = []
        proposal = create_writing_proposal(
            self.project, section["section_id"], "polish", "调整表格措辞",
            writer=lambda prompt: prompts.append(prompt) or replacement,
            selection_only=True, base_version_id=section["current_version_id"],
            selection=self.selection(section["content"], table, "table", "NOD_table"),
        )
        self.assertIn("只返回一张完整 Markdown 表", prompts[0])
        self.assertNotIn("前段保留", prompts[0])
        self.assertTrue(proposal["validation"]["table_structure_valid"])
        self.assertEqual(proposal["validation"]["selection_kind"], "table")
        self.assertTrue(proposal["validation"]["valid"])
        self.assertIn("前段保留。[EVID:EVT_before]", proposal["proposed_content"])
        self.assertIn("后段保留1908年。[EVID:EVT_after]", proposal["proposed_content"])
        self.assertIn(replacement, proposal["proposed_content"])

        decision = decide_writing_proposal(
            self.project, proposal["proposal_id"], True, "Professor", reason="整表逐格核对通过",
        )
        self.assertEqual(decision["status"], "approved")
        current = document_detail(self.project, manuscript["manuscript_id"])
        current_section = next(
            item for item in current["document"]["children"]
            if item["section_id"] == section["section_id"]
        )
        table_nodes = [item for item in current_section["children"] if item["type"] == "table"]
        self.assertEqual(len(table_nodes), 1)
        self.assertEqual(table_nodes[0]["rows"][2][1], "越岭活动延续")

    def test_paragraph_after_table_uses_its_exact_range_and_keeps_adjacent_markers(self) -> None:
        table = (
            "| 年份 | 事件 |\n"
            "| --- | --- |\n"
            "| 1872 | 越岭 [EVID:EVT_table] |"
        )
        selected = (
            "其后材料继续记录1879年的行程。[EVID:EVT_1879]"
            "[CITE:SRC_diary@SRC_diary:P79]"
        )
        previous = "表前判断保留。[EVID:EVT_before]"
        following = "下一段也须保留。[CITE:SRC_after@SRC_after:P1]"
        manuscript = import_manuscript(
            self.project, "表后段落返修",
            "# 正文\n\n" + previous + "\n\n" + table + "\n\n" + selected + "\n\n" + following,
        )
        section = manuscript["sections"][0]
        base = section["content"]
        replacement = (
            "此后材料仍记录1879年的行程。[EVID:EVT_1879]"
            "[CITE:SRC_diary@SRC_diary:P79]"
        )
        prompts: list[str] = []
        proposal = create_writing_proposal(
            self.project, section["section_id"], "polish", "压缩这一整段",
            writer=lambda prompt: prompts.append(prompt) or replacement,
            selection_only=True, base_version_id=section["current_version_id"],
            selection=self.selection(base, selected, "text", "NOD_after_table"),
        )

        self.assertIn(selected, prompts[0])
        self.assertNotIn(table, prompts[0])
        self.assertNotIn(previous, prompts[0])
        self.assertEqual(
            proposal["proposed_content"],
            base[:base.index(selected)] + replacement + base[base.index(selected) + len(selected):],
        )
        self.assertIn(previous, proposal["proposed_content"])
        self.assertIn("[EVID:EVT_table]", proposal["proposed_content"])
        self.assertIn(following, proposal["proposed_content"])
        self.assertNotIn(selected, proposal["proposed_content"])
        self.assertTrue(proposal["validation"]["valid"])

    def test_table_selection_rejects_partial_or_malformed_replacement(self) -> None:
        table = "| 年份 | 事件 |\n| --- | --- |\n| 1872 | 越岭 [EVID:EVT_1872] |"
        manuscript = import_manuscript(self.project, "表格返修", "# 正文\n\n" + table)
        section = manuscript["sections"][0]
        partial = self.selection(section["content"], "| 1872 | 越岭 [EVID:EVT_1872] |", "table", "NOD_table")
        with self.assertRaisesRegex(ValueError, "complete Markdown table"):
            create_writing_proposal(
                self.project, section["section_id"], "polish", "修改", writer=lambda _: "修改",
                selection_only=True, base_version_id=section["current_version_id"], selection=partial,
            )

        selection = self.selection(section["content"], table, "table", "NOD_table")
        malformed = create_writing_proposal(
            self.project, section["section_id"], "polish", "修改表格",
            writer=lambda _: "1872年越岭。[EVID:EVT_1872]",
            selection_only=True, base_version_id=section["current_version_id"], selection=selection,
        )
        self.assertFalse(malformed["validation"]["table_structure_valid"])
        self.assertFalse(malformed["validation"]["valid"])
        with self.assertRaisesRegex(ValueError, "evidence contract"):
            decide_writing_proposal(
                self.project, malformed["proposal_id"], True, "Professor", reason="不应批准",
            )

    def test_table_approval_cannot_edit_outside_selection_or_drop_table_marker(self) -> None:
        table = "| 年份 | 事件 |\n| --- | --- |\n| 1872 | 越岭 [EVID:EVT_1872] |"
        manuscript = import_manuscript(
            self.project, "表格返修", "# 正文\n\n前段。[EVID:EVT_before]\n\n" + table + "\n\n后段。",
        )
        section = manuscript["sections"][0]
        proposal = create_writing_proposal(
            self.project, section["section_id"], "polish", "修改表格",
            writer=lambda _: table.replace("越岭", "翻越秦岭"),
            selection_only=True, base_version_id=section["current_version_id"],
            selection=self.selection(section["content"], table, "table", "NOD_table"),
        )
        outside_edit = proposal["proposed_content"].replace("前段。", "篡改前段。")
        with self.assertRaisesRegex(ValueError, "outside the selected passage"):
            decide_writing_proposal(
                self.project, proposal["proposal_id"], True, "Professor",
                edited_content=outside_edit, reason="不应批准",
            )
        dropped = proposal["proposed_content"].replace(" [EVID:EVT_1872]", "")
        with self.assertRaisesRegex(ValueError, "protected markers"):
            decide_writing_proposal(
                self.project, proposal["proposal_id"], True, "Professor",
                edited_content=dropped, reason="不应批准",
            )

    def test_selection_polish_returns_a_full_proposal_and_approves_a_full_version(self) -> None:
        base = self.section["content"]
        prompts: list[str] = []
        proposal = create_writing_proposal(
            self.project, self.section["section_id"], "polish", "压缩末段",
            writer=lambda prompt: prompts.append(prompt) or "末尾表述已经调整。",
            selection_only=True, base_version_id=self.section["current_version_id"],
            selection=self.selection(base, "末尾需要调整。"),
        )
        self.assertNotIn("队伍进入草原", prompts[0])
        self.assertEqual(
            proposal["proposed_content"],
            base.replace("末尾需要调整。", "末尾表述已经调整。"),
        )
        self.assertIn("[EVID:EVI_keep]", proposal["proposed_content"])
        self.assertIn("[CITE:SRC_keep@SRC_keep:P1]", proposal["proposed_content"])
        self.assertIn("[^1]", proposal["proposed_content"])
        self.assertTrue(proposal["validation"]["valid"])
        self.assertTrue(proposal["validation"]["selection_only"])
        decision = decide_writing_proposal(
            self.project, proposal["proposal_id"], True, "Professor", reason="逐段核对通过",
        )
        self.assertEqual(decision["status"], "approved")
        current = manuscript_detail(self.project, self.manuscript["manuscript_id"])["sections"][0]
        self.assertEqual(current["content"], proposal["proposed_content"])

    def test_selection_character_budget_uses_replacement_when_approved(self) -> None:
        base = self.section["content"]
        replacement = "甲" * 250
        proposal = create_writing_proposal(
            self.project, self.section["section_id"], "polish",
            "严格控制在200—300个中文字符",
            writer=lambda _prompt: replacement, selection_only=True,
            base_version_id=self.section["current_version_id"],
            selection=self.selection(base, "末尾需要调整。"),
        )
        self.assertEqual(proposal["validation"]["actual_character_count"], 250)
        self.assertEqual(proposal["validation"]["character_budget_status"], "PASS")

        decision = decide_writing_proposal(
            self.project, proposal["proposal_id"], True, "Professor", reason="选区长度符合要求",
        )
        self.assertEqual(decision["status"], "approved")
        self.assertEqual(decision["validation"]["actual_character_count"], 250)
        current = manuscript_detail(self.project, self.manuscript["manuscript_id"])["sections"][0]
        self.assertTrue(current["content"].endswith(replacement))

    def test_selection_character_budget_still_rejects_long_replacement(self) -> None:
        base = self.section["content"]
        replacement = "乙" * 350
        proposal = create_writing_proposal(
            self.project, self.section["section_id"], "polish",
            "严格控制在200—300个中文字符",
            writer=lambda _prompt: replacement, selection_only=True,
            base_version_id=self.section["current_version_id"],
            selection=self.selection(base, "末尾需要调整。"),
        )
        self.assertEqual(proposal["validation"]["actual_character_count"], 350)
        self.assertEqual(proposal["validation"]["character_budget_status"], "OUT_OF_RANGE")
        with self.assertRaisesRegex(ValueError, r"350 not in 200–300"):
            decide_writing_proposal(
                self.project, proposal["proposal_id"], True, "Professor", reason="选区过长，不应批准",
            )

    def test_selection_with_legal_cite_evid_and_footnote_is_not_internal_process(self) -> None:
        base = self.section["content"]
        selected = "1908年，材料称“队伍进入草原”。[^1][EVID:EVI_keep][CITE:SRC_keep@SRC_keep:P1]"
        replacement = "1908年，材料记载“队伍进入草原”。[^1][EVID:EVI_keep][CITE:SRC_keep@SRC_keep:P1]"
        proposal = create_writing_proposal(
            self.project, self.section["section_id"], "polish", "调整选句表达",
            writer=lambda _prompt: replacement, selection_only=True,
            base_version_id=self.section["current_version_id"],
            selection=self.selection(base, selected),
        )
        self.assertTrue(proposal["validation"]["valid"])
        self.assertFalse(proposal["validation"]["selection_internal_process"])
        self.assertIn(replacement, proposal["proposed_content"])

        real_internal = create_writing_proposal(
            self.project, self.section["section_id"], "polish", "调整选句表达",
            writer=lambda _prompt: replacement + "这是核心个案之一。", selection_only=True,
            base_version_id=self.section["current_version_id"],
            selection=self.selection(base, selected),
        )
        self.assertFalse(real_internal["validation"]["valid"])
        self.assertTrue(real_internal["validation"]["selection_internal_process"])

    def test_selection_requires_text_unique_range_hash_and_current_version(self) -> None:
        base = self.section["content"]
        with self.assertRaisesRegex(ValueError, "requires a text selection"):
            create_writing_proposal(
                self.project, self.section["section_id"], "polish", "修改", writer=lambda _: "修改",
                selection_only=True, base_version_id=self.section["current_version_id"], selection=None,
            )
        with self.assertRaisesRegex(ValueError, "stale"):
            create_writing_proposal(
                self.project, self.section["section_id"], "polish", "修改", writer=lambda _: "修改",
                selection_only=True, base_version_id="SEV_stale",
                selection=self.selection(base, "末尾需要调整。"),
            )
        bad_hash = self.selection(base, "末尾需要调整。")
        bad_hash["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            create_writing_proposal(
                self.project, self.section["section_id"], "polish", "修改", writer=lambda _: "修改",
                selection_only=True, base_version_id=self.section["current_version_id"], selection=bad_hash,
            )

        repeated = import_manuscript(self.project, "重复选区", "# 正文\n\n相同一句。\n\n相同一句。")
        duplicate = repeated["sections"][0]
        with self.assertRaisesRegex(ValueError, "not unique"):
            create_writing_proposal(
                self.project, duplicate["section_id"], "polish", "修改", writer=lambda _: "修改",
                selection_only=True, base_version_id=duplicate["current_version_id"],
                selection=self.selection(duplicate["content"], "相同一句。"),
            )

    def test_selection_internal_work_language_and_stale_approval_are_blocked(self) -> None:
        base = self.section["content"]
        internal = create_writing_proposal(
            self.project, self.section["section_id"], "polish", "修改末段",
            writer=lambda _: "这是核心个案之一。", selection_only=True,
            base_version_id=self.section["current_version_id"],
            selection=self.selection(base, "末尾需要调整。"),
        )
        self.assertTrue(internal["validation"]["selection_internal_process"])
        self.assertFalse(internal["validation"]["valid"])
        with self.assertRaisesRegex(ValueError, "research-process"):
            decide_writing_proposal(
                self.project, internal["proposal_id"], True, "Professor", reason="不应批准",
            )

        valid = create_writing_proposal(
            self.project, self.section["section_id"], "polish", "修改末段",
            writer=lambda _: "末尾已经修改。", selection_only=True,
            base_version_id=self.section["current_version_id"],
            selection=self.selection(base, "末尾需要调整。"),
        )
        from research_workbench.document_model import ensure_document
        tree = ensure_document(self.project, self.manuscript["manuscript_id"])["document"]
        tree["children"][0]["children"].append({
            "type": "paragraph", "node_id": "NOD_manual_stale", "text": "另加一句。",
        })
        save_document(self.project, self.manuscript["manuscript_id"], tree)
        with self.assertRaisesRegex(ValueError, "stale section version"):
            decide_writing_proposal(
                self.project, valid["proposal_id"], True, "Professor", reason="旧选区提案",
            )

    def test_loopback_api_accepts_version_bound_selection(self) -> None:
        server = build_server(
            self.project, port=0, library_root=self.root / "library",
            workspace_root=self.root / "workspace",
        )
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base_url = f"http://127.0.0.1:{server.server_port}"

        def post(payload: dict[str, object]) -> dict[str, object]:
            request = Request(
                base_url + "/api/writing/propose", data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            return json.loads(urlopen(request, timeout=5).read())

        base = self.section["content"]
        payload = {
            "section_id": self.section["section_id"], "operation": "polish",
            "instruction": "修改末段", "selection_only": True,
            "base_version_id": self.section["current_version_id"],
            "selection": self.selection(base, "末尾需要调整。"),
        }
        try:
            with patch("research_workbench.authoring._model_capability", return_value={"available": True}), \
                    patch("research_workbench.authoring._model_write", return_value="末尾已经调整。"):
                result = post(payload)
            self.assertTrue(result["validation"]["selection_only"])
            self.assertIn("[EVID:EVI_keep]", result["proposed_content"])
            payload["selection"] = None
            with self.assertRaises(HTTPError) as raised:
                post(payload)
            self.assertEqual(raised.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
