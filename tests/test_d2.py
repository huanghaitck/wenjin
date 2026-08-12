from __future__ import annotations

import tempfile
import json
import threading
import unittest
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from research_workbench.document_model import export_document

from research_workbench.authoring import (
    add_style_profile_sample,
    create_historiography_entry,
    create_journal_template,
    create_reading_job,
    reading_job_batch,
    save_reading_note,
    create_style_profile,
    create_writing_proposal,
    decide_writing_proposal,
    decide_style_profile,
    export_manuscript,
    import_manuscript,
    manuscript_detail,
)
from research_workbench.db import connect
from research_workbench.document_model import document_detail
from research_workbench.scholarship import approve_freeze, create_claim, create_evidence, create_freeze
from research_workbench.service import (
    import_structure, initialize_project, list_anomalies, register_source, submit_block_repair, verify_page,
)
from research_workbench.web import build_server


FIXTURES = Path(__file__).parent / "fixtures"


class D2AuthoringReadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        initialize_project(self.project, "D2 project")
        source_file = self.root / "source.pdf"
        source_file.write_bytes(b"%PDF-1.4\nD2 fixture\n%%EOF\n")
        self.source = register_source(self.project, source_file, "Expedition source")
        import_structure(self.project, self.source["source_id"], FIXTURES / "m1_structure.json")
        anomaly = next(item for item in list_anomalies(self.project) if item["anomaly_id"].endswith(":A_BLOCK"))
        submit_block_repair(self.project, anomaly["anomaly_id"],
                            "The expedition left the station in spring.", "Professor", "Checked original page")
        verify_page(self.project, f"{self.source['source_id']}:P1", "Professor", "Checked page image and block order")
        self.manuscript = import_manuscript(
            self.project, "考察史论文",
            "# 导言\n\n1908年，材料称“队伍进入草原”。[^1]\n\n# 第一节\n\n原有论述。",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_polish_proposal_cannot_drop_quotes_numbers_or_footnotes(self) -> None:
        section = self.manuscript["sections"][0]
        proposal = create_writing_proposal(
            self.project, section["section_id"], "polish", "压缩表达",
            writer=lambda prompt: "材料称队伍进入草原。",
        )
        self.assertFalse(proposal["validation"]["valid"])
        with self.assertRaisesRegex(ValueError, "protected markers"):
            decide_writing_proposal(self.project, proposal["proposal_id"], True, "Professor", reason="Quote was removed")

        good = create_writing_proposal(
            self.project, section["section_id"], "polish", "调整语序",
            writer=lambda prompt: "材料称：“队伍进入草原”。此事发生于1908年。[^1]",
        )
        decision = decide_writing_proposal(self.project, good["proposal_id"], True, "Professor", reason="Checked wording")
        self.assertEqual(decision["status"], "approved")
        detail = manuscript_detail(self.project, self.manuscript["manuscript_id"])
        self.assertEqual(len(detail["sections"][0]["versions"]), 2)
        self.assertIn("1908", detail["sections"][0]["content"])
        document = document_detail(self.project, self.manuscript["manuscript_id"])
        self.assertIn("1908", document["document"]["children"][0]["children"][0]["text"])
        self.assertEqual(decision["document_revision_id"], document["current_revision_id"])

    def test_placeholder_requires_metadata_draft_and_uses_approved_body(self) -> None:
        manuscript = import_manuscript(
            self.project, "秦岭调查比较",
            "# 摘要与关键词\n\n（待写）\n\n# 正文\n\n1872年，旅行者沿秦岭道路行进。" * 20,
        )
        abstract = manuscript["sections"][0]
        with self.assertRaisesRegex(ValueError, "metadata_draft"):
            create_writing_proposal(
                self.project, abstract["section_id"], "polish", "生成摘要", writer=lambda prompt: "错误摘要",
            )
        prompts = []
        proposal = create_writing_proposal(
            self.project, abstract["section_id"], "metadata_draft", "写300字摘要",
            writer=lambda prompt: prompts.append(prompt) or "本文比较1872年秦岭道路调查。",
        )
        self.assertTrue(proposal["validation"]["valid"])
        self.assertIn("1872年，旅行者沿秦岭道路行进", prompts[0])
        self.assertNotIn("[EVID:", proposal["proposed_content"])

    def test_drafting_flags_internal_process_and_defensive_clusters_as_style_risks(self) -> None:
        manuscript = import_manuscript(
            self.project, "秦岭活跃期", "# 摘要与关键词\n\n（待写）\n\n# 正文\n\n" +
            "1871年至1879年，外国旅行者连续进入秦岭。" * 30,
        )
        abstract = manuscript["sections"][0]
        prompts: list[str] = []
        proposal = create_writing_proposal(
            self.project, abstract["section_id"], "metadata_draft", "写摘要",
            writer=lambda prompt: prompts.append(prompt) or (
                "正式研究门禁已经满足。本文不能外推，也不等于统计抽样，"
                "待补证项另见事件清单；表中称为核心个案之一和时间锚。"
            ),
        )
        self.assertIn("证据门禁、冻结状态、待补证清单", prompts[0])
        self.assertEqual(
            set(proposal["validation"]["prose_risk_warnings"]),
            {"internal_process", "defensive_cluster"},
        )

    def test_approved_section_with_markdown_table_syncs_to_document(self) -> None:
        section = self.manuscript["sections"][1]
        proposal = create_writing_proposal(
            self.project, section["section_id"], "polish", "加入比较表",
            writer=lambda prompt: "| 个案 | 路线 |\n| --- | --- |\n| 甲 | 山路 |",
        )
        decision = decide_writing_proposal(
            self.project, proposal["proposal_id"], True, "Professor",
            edited_content="| 个案 | 路线 |\n| --- | --- |\n| 甲 | 山路 |",
            reason="Table checked",
        )
        detail = document_detail(self.project, self.manuscript["manuscript_id"])
        synced = next(item for item in detail["document"]["children"] if item["section_id"] == section["section_id"])
        self.assertEqual(synced["children"][0]["type"], "table")
        self.assertEqual(decision["document_revision_id"], detail["current_revision_id"])
        word = export_document(
            self.project, self.manuscript["manuscript_id"], "docx", "builtin-tangdu-current",
        )
        with zipfile.ZipFile(self.project / word["project_path"]) as package:
            xml = package.read("word/document.xml").decode("utf-8")
        self.assertIn("w:tblHeader", xml)
        self.assertIn("w:cantSplit", xml)

    def test_historical_humanizer_uses_only_approved_high_level_style_profile(self) -> None:
        paragraph = ("1908年，材料称“队伍进入草原”。[^1]这一记载只能说明队伍当日的位置，"
                     "尚不足以据此判断整个考察季节的路线。随后一封书信补充了行动次序，"
                     "但两项材料不能视为独立见证。")
        sample = import_manuscript(
            self.project, "作者认可样本",
            "# 样本\n\n" + "\n\n".join(paragraph for _ in range(10)),
        )
        section = sample["sections"][0]
        profile = create_style_profile(self.project, sample["manuscript_id"], "我的史学文风", "本人", "环境史")
        self.assertEqual(profile["status"], "OBSERVED_ONCE")
        self.assertNotIn("1908年", json.dumps(profile["features"], ensure_ascii=False))
        with self.assertRaisesRegex(ValueError, "author approved"):
            create_writing_proposal(
                self.project, section["section_id"], "historical_humanize", "材料先行",
                style_profile_id=profile["profile_id"], writer=lambda prompt: section["content"],
            )
        profile = decide_style_profile(
            self.project, profile["profile_id"], True, "Professor", "这是我认可的章节",
        )
        proposal = create_writing_proposal(
            self.project, section["section_id"], "historical_humanize", "材料先行",
            style_profile_id=profile["profile_id"], writer=lambda prompt: "材料称队伍进入草原。",
        )
        self.assertFalse(proposal["validation"]["valid"])
        self.assertEqual(proposal["validation"]["guard_status"], "BLOCKED_PROTECTED_CHANGE")
        self.assertEqual(proposal["model_snapshot"]["skill"]["name"], "historical-humanizer-zh")

    def test_style_profile_requires_three_distinct_manuscripts_for_stable_status(self) -> None:
        manuscripts = []
        for index in range(3):
            paragraph = f"187{index}年，日记记录了第{index + 1}次行程。材料只支持当日行动，不能据此外推整个区域。"
            manuscripts.append(import_manuscript(
                self.project, f"样本{index + 1}", "# 正文\n\n" + "\n\n".join(paragraph for _ in range(24)),
            ))
        profile = create_style_profile(self.project, manuscripts[0]["manuscript_id"], "多人可选画像", "课题组甲", "旅行史")
        with self.assertRaisesRegex(ValueError, "already part"):
            add_style_profile_sample(self.project, profile["profile_id"], manuscripts[0]["manuscript_id"])
        profile = add_style_profile_sample(self.project, profile["profile_id"], manuscripts[1]["manuscript_id"])
        self.assertEqual(profile["status"], "RECURRING")
        profile = add_style_profile_sample(self.project, profile["profile_id"], manuscripts[2]["manuscript_id"])
        profile = decide_style_profile(self.project, profile["profile_id"], True, "Professor", "三篇独立稿件复现且人工批准")
        self.assertEqual(profile["status"], "STABLE_PROFILE")
        self.assertEqual(len(profile["samples"]), 3)

    def test_section_draft_requires_approved_freeze_and_keeps_evidence_refs(self) -> None:
        claim = create_claim(self.project, "页边界记录反映文本连续性。")
        claim = create_evidence(
            self.project, claim["claim_id"], f"{self.source['source_id']}:B2",
            "The sentence continues toward the page boundary", "直接记载", "supports",
        )
        other_claim = create_claim(self.project, "出发时间构成另一项独立主张。")
        other_claim = create_evidence(
            self.project, other_claim["claim_id"], f"{self.source['source_id']}:B1",
            "The expedition left the station in spring.", "另一节使用", "supports",
        )
        freeze = create_freeze(self.project, "章节证据", [claim["claim_id"], other_claim["claim_id"]])
        section = self.manuscript["sections"][1]
        with self.assertRaisesRegex(ValueError, "approved"):
            create_writing_proposal(self.project, section["section_id"], "section_draft", "写一段", freeze["freeze_id"])
        approve_freeze(self.project, freeze["freeze_id"], "Professor", "Checked freeze boundary")
        evidence_id = claim["evidence"][0]["evidence_id"]
        other_id = other_claim["evidence"][0]["evidence_id"]
        with self.assertRaisesRegex(ValueError, "at least one selected"):
            create_writing_proposal(
                self.project, section["section_id"], "section_draft", "形成一段",
                freeze["freeze_id"], evidence_ids=[],
            )
        with self.assertRaisesRegex(ValueError, "not part of the approved freeze"):
            create_writing_proposal(
                self.project, section["section_id"], "section_draft", "形成一段",
                freeze["freeze_id"], evidence_ids=["EVI_not_frozen"],
            )
        captured_prompts: list[str] = []
        translated = create_writing_proposal(
            self.project, section["section_id"], "section_draft", "形成一段", freeze["freeze_id"],
            writer=lambda prompt: captured_prompts.append(prompt) or
            f"材料记载：“远征队在春天离开了站点。”[EVID:{evidence_id}]",
            evidence_ids=[evidence_id],
        )
        self.assertIn(evidence_id, captured_prompts[0])
        self.assertNotIn(other_id, captured_prompts[0])
        self.assertFalse(translated["validation"]["valid"])
        self.assertTrue(translated["validation"]["altered_quotes"])
        with self.assertRaisesRegex(ValueError, "evidence contract"):
            decide_writing_proposal(
                self.project, translated["proposal_id"], True, "Professor", reason="Translated the source quote",
            )
        malformed = create_writing_proposal(
            self.project, section["section_id"], "section_draft", "形成一段", freeze["freeze_id"],
            writer=lambda prompt: f"道路受限。[EVID:{evidence_id}][EVID:EVT_241?]",
            evidence_ids=[evidence_id],
        )
        self.assertFalse(malformed["validation"]["valid"])
        self.assertEqual(malformed["validation"]["malformed_evidence_markers"], ["EVT_241?"])
        german_quotes = create_writing_proposal(
            self.project, section["section_id"], "section_draft", "形成一段", freeze["freeze_id"],
            writer=lambda prompt: f'材料记载：„The expedition left the station in winter." [EVID:{evidence_id}]',
            evidence_ids=[evidence_id],
        )
        self.assertFalse(german_quotes["validation"]["valid"])
        self.assertIn("winter", german_quotes["validation"]["altered_quotes"][0])
        proposal = create_writing_proposal(
            self.project, section["section_id"], "section_draft", "形成一段", freeze["freeze_id"],
            evidence_ids=[evidence_id],
        )
        self.assertEqual(len(proposal["evidence_refs"]), 1)
        decision = decide_writing_proposal(
            self.project, proposal["proposal_id"], True, "Professor", reason="Checked exact quote and evidence link",
        )
        self.assertEqual(decision["status"], "approved")

    def test_section_draft_lists_shared_evidence_once(self) -> None:
        first = create_claim(self.project, "道路是移动条件。")
        first = create_evidence(
            self.project, first["claim_id"], f"{self.source['source_id']}:B2",
            "The sentence continues toward the page boundary", "直接记载", "supports",
        )
        second = create_claim(self.project, "道路也是观察对象。")
        evidence_id = first["evidence"][0]["evidence_id"]
        with connect(self.project) as connection:
            connection.execute(
                "INSERT INTO claim_evidence(link_id, claim_id, evidence_id, relation, created_at) "
                "VALUES ('LNK_shared', ?, ?, 'supports', '2026-01-01')",
                (second["claim_id"], evidence_id),
            )
        freeze = create_freeze(self.project, "共享证据", [first["claim_id"], second["claim_id"]])
        approve_freeze(self.project, freeze["freeze_id"], "Professor", "Checked shared source")
        prompts: list[str] = []
        proposal = create_writing_proposal(
            self.project, self.manuscript["sections"][1]["section_id"], "section_draft", "形成一段",
            freeze["freeze_id"], writer=lambda prompt: prompts.append(prompt) or f"道路受限。[EVID:{evidence_id}]",
        )
        self.assertEqual(prompts[0].count(f"[EVID:{evidence_id}]"), 1)
        self.assertEqual(len(proposal["evidence_refs"]), 1)
        self.assertEqual(set(proposal["evidence_refs"][0]["claim_ids"]), {first["claim_id"], second["claim_id"]})

    def test_bounded_reading_historiography_and_journal_export(self) -> None:
        job = create_reading_job(
            self.project, "定向阅读", "材料如何叙述移动？", "targeted",
            [self.source["source_id"]], "完成当前可用块后停止",
        )
        self.assertEqual(job["status"], "running")
        batch = reading_job_batch(
            self.project, job["job_id"], self.source["source_id"], page_limit=10,
        )
        self.assertTrue(batch["pages"])
        note = save_reading_note(
            self.project, job["job_id"], self.source["source_id"],
            [page["physical_page"] for page in batch["pages"]],
            "当前可用页说明旅行者怎样移动。", complete=True,
        )
        self.assertEqual(note["status"], "completed")
        self.assertEqual(note["qualification"], "READING_NOTE_NOT_EVIDENCE")
        entry = create_historiography_entry(self.project, {
            "work_title": "A Study", "position": "强调知识生产", "contribution": "提出中介问题",
            "limitation": "材料范围有限", "relevance": "可用于对照", "source_refs": [self.source["source_id"]],
        })
        self.assertEqual(entry["status"], "candidate")
        template = create_journal_template(
            self.project, "测试期刊", "页下注", ["导言", "第一节"],
            "2026 投稿规范", "2026-01-01", "https://example.org/rules", "2026-08-11",
            "OFFICIAL_SOURCE_CHECKED", {"notes": ["约一万字"]},
        )
        self.assertEqual(template["version_label"], "2026 投稿规范")
        self.assertEqual(template["source_url"], "https://example.org/rules")
        exported = export_manuscript(self.project, self.manuscript["manuscript_id"], template["template_id"])
        self.assertTrue((self.project / exported["project_path"]).is_file())

    def test_current_schema_version_is_installed(self) -> None:
        with connect(self.project) as connection:
            self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_meta").fetchone()[0], 19)

    def test_loopback_authoring_api_imports_and_proposes_without_overwriting(self) -> None:
        server = build_server(
            self.project, port=0, library_root=self.root / "library",
            workspace_root=self.root / "workspace-api",
        )
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{server.server_port}"

        def post(path: str, payload: dict[str, object]) -> dict[str, object]:
            request = Request(base + path, data=json.dumps(payload).encode(),
                              headers={"Content-Type": "application/json"}, method="POST")
            return json.loads(urlopen(request, timeout=5).read())

        try:
            manuscript = post("/api/manuscript/import", {"title": "API manuscript", "markdown": "# 一\n\n1908年原文。"})
            proposal = post("/api/writing/propose", {
                "section_id": manuscript["sections"][0]["section_id"],
                "operation": "polish", "instruction": "保持事实",
            })
            self.assertEqual(proposal["status"], "pending")
            snapshot = json.loads(urlopen(base + "/api/snapshot", timeout=5).read())
            self.assertGreaterEqual(len(snapshot["authoring"]["manuscripts"]), 2)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
