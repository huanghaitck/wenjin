from __future__ import annotations

import tempfile
import json
import sqlite3
import threading
import unittest
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from research_workbench.document_model import export_document

from research_workbench.authoring import (
    add_style_profile_sample,
    add_external_style_profile_sample,
    create_historiography_entry,
    create_journal_template,
    create_reading_job,
    reading_job_batch,
    save_reading_note,
    style_profile_detail,
    create_style_profile,
    create_external_style_profile,
    create_writing_proposal,
    decide_historiography_entry,
    decide_writing_proposal,
    decide_style_profile,
    export_manuscript,
    import_manuscript,
    manuscript_detail,
)
from research_workbench.db import SCHEMA_VERSION, _migrate, connect, database_path
from research_workbench.document_model import document_detail
from research_workbench.scholarship import approve_freeze, create_claim, create_evidence, create_freeze
from research_workbench.service import (
    import_structure, initialize_project, list_anomalies, register_source, save_source_citation_metadata,
    submit_block_repair, verify_page,
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

    def test_polish_proposal_rejects_unchanged_output(self) -> None:
        section = self.manuscript["sections"][1]
        proposal = create_writing_proposal(
            self.project, section["section_id"], "polish", "调整表达",
            writer=lambda _prompt: section["content"],
        )
        self.assertTrue(proposal["validation"]["no_change"])
        self.assertFalse(proposal["validation"]["valid"])
        with self.assertRaisesRegex(ValueError, "evidence contract"):
            decide_writing_proposal(
                self.project, proposal["proposal_id"], True, "Professor", reason="No revision made",
            )

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

    def test_manual_sync_rejects_stale_section_version(self) -> None:
        from research_workbench.document_model import sync_approved_section

        section = self.manuscript["sections"][1]
        proposal = create_writing_proposal(
            self.project, section["section_id"], "polish", "补入一段",
            writer=lambda prompt: section["content"] + "\n\n新增一段。",
        )
        decision = decide_writing_proposal(
            self.project, proposal["proposal_id"], True, "Professor", reason="Checked",
        )
        detail = document_detail(self.project, self.manuscript["manuscript_id"])
        synced = next(
            item for item in detail["document"]["children"]
            if item["section_id"] == section["section_id"]
        )
        self.assertIn("新增一段", synced["children"][-1]["text"])
        self.assertEqual(decision["document_revision_id"], detail["current_revision_id"])
        with self.assertRaisesRegex(ValueError, "stale"):
            sync_approved_section(
                self.project, self.manuscript["manuscript_id"], section["section_id"],
                section["content"], section["current_version_id"],
            )

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
        for index in range(2):
            extra = import_manuscript(
                self.project, f"作者认可样本{index + 2}",
                "# 样本\n\n" + "\n\n".join(paragraph.replace("1908年", f"190{index + 9}年") for _ in range(10)),
            )
            profile = add_style_profile_sample(self.project, profile["profile_id"], extra["manuscript_id"])
        profile = decide_style_profile(
            self.project, profile["profile_id"], True, "Professor", "这是我认可的三篇完整样本",
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

    def test_external_verified_articles_are_separate_style_sources_and_need_human_stability_decision(self) -> None:
        def external_article(index: int) -> dict[str, object]:
            path = self.root / f"style-{index}.pdf"
            path.write_bytes(f"%PDF-1.4\nstyle {index}\n%%EOF\n".encode())
            source = register_source(self.project, path, f"史红帅论文{index}")
            import_structure(self.project, source["source_id"], FIXTURES / "m1_structure.json")
            with connect(self.project) as connection:
                connection.execute(
                    "UPDATE pages SET verification_state = 'human_verified', use_state = 'research_usable' "
                    "WHERE source_id = ?", (source["source_id"],),
                )
                connection.execute(
                    "UPDATE blocks SET verification_state = 'human_verified', use_state = 'research_usable', "
                    "human_text = ? WHERE page_id IN (SELECT page_id FROM pages WHERE source_id = ?)",
                    ((f"18{index}年，材料记录了地方社会的具体行动。" * 60), source["source_id"]),
                )
                connection.execute(
                    "UPDATE sources SET use_state = 'research_usable' WHERE source_id = ?", (source["source_id"],),
                )
                connection.execute(
                    "UPDATE anomalies SET status = 'resolved', resolved_at = '2026-01-01' WHERE source_id = ?",
                    (source["source_id"],),
                )
            save_source_citation_metadata(self.project, source["source_id"], {
                "author": "史红帅", "title": f"史红帅论文{index}", "journal": "史学集刊",
                "year": f"202{index}", "type_code": "J", "verified_by": "Professor",
            })
            return source

        sources = [external_article(index) for index in range(1, 4)]
        profile = create_external_style_profile(
            self.project, sources[0]["source_id"], "史红帅论文文风", "史红帅",
        )
        self.assertEqual(profile["samples"][0]["sample_role"], "external_verified_article")
        self.assertIsNone(profile["samples"][0]["manuscript_id"])
        profile = add_external_style_profile_sample(self.project, profile["profile_id"], sources[1]["source_id"])
        profile = add_external_style_profile_sample(self.project, profile["profile_id"], sources[2]["source_id"])
        self.assertEqual(profile["status"], "REVIEW_READY")
        self.assertIn("5 篇", profile["sample_count_warning"])
        with self.assertRaisesRegex(ValueError, "author approved"):
            create_writing_proposal(
                self.project, self.manuscript["sections"][1]["section_id"], "historical_humanize", "材料先行",
                style_profile_id=profile["profile_id"], writer=lambda prompt: "原有论述。",
            )
        profile = decide_style_profile(
            self.project, profile["profile_id"], True, "Professor", "三篇全文已逐篇核验，批准高层特征",
        )
        self.assertEqual(profile["status"], "STABLE_PROFILE")
        self.assertTrue(all(sample["source_id"] for sample in profile["samples"]))
        with self.assertRaisesRegex(ValueError, "remain separate"):
            add_style_profile_sample(self.project, profile["profile_id"], self.manuscript["manuscript_id"])

    def test_external_style_source_rejects_unverified_or_open_full_text(self) -> None:
        path = self.root / "unverified-style.pdf"
        path.write_bytes(b"%PDF-1.4\nstyle\n%%EOF\n")
        source = register_source(self.project, path, "未核论文")
        import_structure(self.project, source["source_id"], FIXTURES / "m1_structure.json")
        with self.assertRaisesRegex(ValueError, "HUMAN_VERIFIED bibliography"):
            create_external_style_profile(self.project, source["source_id"], "候选画像", "史红帅")
        save_source_citation_metadata(self.project, source["source_id"], {
            "author": "史红帅", "title": "未核论文", "journal": "史学集刊", "year": "2020",
            "type_code": "J", "verified_by": "Professor",
        })
        with self.assertRaisesRegex(ValueError, "every page"):
            create_external_style_profile(self.project, source["source_id"], "候选画像", "史红帅")

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

    def test_explicit_character_budget_and_internal_prose_block_approval(self) -> None:
        section = self.manuscript["sections"][1]
        short = create_writing_proposal(
            self.project, section["section_id"], "polish", "严格控制在1000—1200个中文字符",
            writer=lambda _prompt: "材料先行。" * 20,
        )
        self.assertEqual(short["validation"]["character_budget_status"], "OUT_OF_RANGE")
        with self.assertRaisesRegex(ValueError, "outside the requested character budget"):
            decide_writing_proposal(
                self.project, short["proposal_id"], True, "Professor", reason="Checked length",
            )
        approximate = create_writing_proposal(
            self.project, section["section_id"], "polish",
            "目标约1000—1200个中文字符。必须保留既有材料标记，不得新增事实。",
            writer=lambda _prompt: "材料先行。" * 20,
        )
        self.assertEqual(approximate["validation"]["character_budget_status"], "OUT_OF_RANGE")
        self.assertEqual(approximate["validation"]["character_budget_enforcement"], "ADVISORY")
        decision = decide_writing_proposal(
            self.project, approximate["proposal_id"], True, "Professor", reason="Author approved concise version",
        )
        self.assertEqual(decision["status"], "approved")
        internal = create_writing_proposal(
            self.project, section["section_id"], "polish", "保留史学表达",
            writer=lambda _prompt: "这只是核心个案之一。",
        )
        with self.assertRaisesRegex(ValueError, "research-process"):
            decide_writing_proposal(
                self.project, internal["proposal_id"], True, "Professor", reason="Checked prose",
            )

    def test_defensive_cluster_warns_without_blocking_historical_qualification(self) -> None:
        section = self.manuscript["sections"][1]
        proposal = create_writing_proposal(
            self.project, section["section_id"], "polish", "保留证据边界",
            writer=lambda _prompt: "材料不能证明全程连续，也不等于当地活动从此中断。",
        )
        self.assertEqual(proposal["validation"]["prose_risk_warnings"], ["defensive_cluster"])
        decision = decide_writing_proposal(
            self.project, proposal["proposal_id"], True, "Professor", reason="Necessary qualification",
        )
        self.assertEqual(decision["status"], "approved")

    def test_approval_strips_model_echoed_section_heading(self) -> None:
        section = self.manuscript["sections"][1]
        proposal = create_writing_proposal(
            self.project, section["section_id"], "polish", "只润色正文",
            writer=lambda _prompt: f"{section['heading']}\n\n材料先行。",
        )
        decision = decide_writing_proposal(
            self.project, proposal["proposal_id"], True, "Professor", reason="Checked body",
        )
        self.assertEqual(decision["status"], "approved")
        current = manuscript_detail(self.project, self.manuscript["manuscript_id"])
        revised = next(item for item in current["sections"] if item["section_id"] == section["section_id"])
        self.assertEqual(revised["content"], "材料先行。")

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
        with connect(self.project) as connection:
            stored = json.loads(connection.execute(
                "SELECT page_refs_json FROM reading_notes WHERE note_id = ?", (note["note_id"],),
            ).fetchone()[0])
        self.assertEqual(len(stored), len(batch["pages"]))
        self.assertEqual(
            [ref["physical_page"] for ref in stored],
            [page["physical_page"] for page in batch["pages"]],
        )
        self.assertEqual(stored[0]["source_version_id"], self.source["source_version_id"])
        self.assertEqual(stored[0]["page_id"], batch["pages"][0]["page_id"])
        self.assertEqual(stored[0]["block_id"], batch["pages"][0]["blocks"][0]["block_id"])
        entry = create_historiography_entry(self.project, {
            "work_title": "Expedition source", "position": "强调知识生产", "contribution": "提出中介问题",
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

    def test_verified_bibliography_accepts_canonical_title_or_full_citation(self) -> None:
        save_source_citation_metadata(self.project, self.source["source_id"], {
            "author": "赵维玺", "title": "索思诺福斯齐考察团来华及左宗棠的应对",
            "journal": "近代史研究", "year": "2021", "type_code": "J",
            "verified_by": "Professor",
        })
        job = create_reading_job(
            self.project, "直接研究", "作者如何解释考察？", "targeted",
            [self.source["source_id"]], "读完选定页停止",
        )
        save_reading_note(
            self.project, job["job_id"], self.source["source_id"], [1],
            "作者说明考察团的来华过程。", complete=True,
        )
        entry = create_historiography_entry(self.project, {
            "work_title": "赵维玺：《索思诺福斯齐考察团来华及左宗棠的应对》，《近代史研究》2021年第1期，第1—20页",
            "position": "考察史", "contribution": "重建过程", "limitation": "个案研究",
            "relevance": "直接研究", "source_refs": [self.source["source_id"]],
        })
        self.assertEqual(entry["work_title"], "索思诺福斯齐考察团来华及左宗棠的应对")
        self.assertEqual(
            decide_historiography_entry(
                self.project, entry["entry_id"], True, "Professor", "核对作者、题名和原页。",
            )["status"],
            "approved",
        )

    def test_verified_bibliography_rejects_author_conflict_and_fuzzy_title(self) -> None:
        save_source_citation_metadata(self.project, self.source["source_id"], {
            "author": "赵维玺", "title": "索思诺福斯齐考察团来华及左宗棠的应对",
            "journal": "近代史研究", "year": "2021", "type_code": "J",
            "verified_by": "Professor",
        })
        job = create_reading_job(
            self.project, "直接研究", "作者如何解释考察？", "targeted",
            [self.source["source_id"]], "读完选定页停止",
        )
        save_reading_note(
            self.project, job["job_id"], self.source["source_id"], [1],
            "作者说明考察团的来华过程。", complete=True,
        )
        common = {
            "position": "考察史", "contribution": "重建过程", "limitation": "个案研究",
            "relevance": "直接研究", "source_refs": [self.source["source_id"]],
        }
        with self.assertRaisesRegex(ValueError, "author does not match"):
            create_historiography_entry(self.project, {
                **common,
                "work_title": "史红帅：《索思诺福斯齐考察团来华及左宗棠的应对》，《近代史研究》2021年第1期",
            })
        with self.assertRaisesRegex(ValueError, "title does not match"):
            create_historiography_entry(self.project, {
                **common, "work_title": "《索思诺福斯齐考察团来华及左宗棠的应对再研究》",
            })
        with self.assertRaisesRegex(ValueError, "title does not match"):
            create_historiography_entry(self.project, {
                **common, "work_title": "评《索思诺福斯齐考察团来华及左宗棠的应对》",
            })
        with self.assertRaisesRegex(ValueError, "title does not match"):
            create_historiography_entry(self.project, {
                **common,
                "work_title": "赵维玺：《索思诺福斯齐考察团来华及左宗棠的应对再研究》，《近代史研究》2021年第1期",
            })

    def test_unverified_bibliography_keeps_strict_project_title_match(self) -> None:
        job = create_reading_job(
            self.project, "直接研究", "作者如何解释考察？", "targeted",
            [self.source["source_id"]], "读完选定页停止",
        )
        save_reading_note(
            self.project, job["job_id"], self.source["source_id"], [1],
            "作者说明考察过程。", complete=True,
        )
        with self.assertRaisesRegex(ValueError, "title does not match"):
            create_historiography_entry(self.project, {
                "work_title": "2021_Expedition source", "position": "考察史",
                "contribution": "重建过程", "limitation": "个案研究",
                "relevance": "直接研究", "source_refs": [self.source["source_id"]],
            })

    def test_approved_historiography_is_explicitly_bridged_through_cite_whitelist(self) -> None:
        job = create_reading_job(
            self.project, "直接研究", "作者如何解释移动？", "targeted",
            [self.source["source_id"]], "读完选定页面停止",
        )
        save_reading_note(
            self.project, job["job_id"], self.source["source_id"], [1],
            "该研究把道路条件与知识生产联系起来。", complete=True,
        )
        entry = create_historiography_entry(self.project, {
            "work_title": "Expedition source", "position": "道路塑造观察", "contribution": "连接移动与知识",
            "limitation": "只分析单一区域", "relevance": "用于导言对话", "source_refs": [self.source["source_id"]],
        })
        section = self.manuscript["sections"][1]
        with self.assertRaisesRegex(ValueError, "not approved"):
            create_writing_proposal(
                self.project, section["section_id"], "polish", "加入学术史对话",
                historiography_entry_ids=[entry["entry_id"]], writer=lambda prompt: section["content"],
            )
        decide_historiography_entry(
            self.project, entry["entry_id"], True, "Professor", "确认该条目可进入文章学术史对话",
        )
        with self.assertRaisesRegex(ValueError, "bibliography is not HUMAN_VERIFIED"):
            create_writing_proposal(
                self.project, section["section_id"], "polish", "加入学术史对话",
                historiography_entry_ids=[entry["entry_id"]], writer=lambda prompt: section["content"],
            )
        save_source_citation_metadata(self.project, self.source["source_id"], {
            "author": "Smith", "title": "A Study", "place": "London", "publisher": "Press",
            "year": "2020", "type_code": "M", "verified_by": "Professor",
        })
        with connect(self.project) as connection:
            connection.execute(
                "UPDATE pages SET printed_page = '12' WHERE source_id = ? AND physical_page = 1",
                (self.source["source_id"],),
            )
        page_id = f"{self.source['source_id']}:P1"
        marker = f"[CITE:{self.source['source_id']}@{page_id}]"
        prompts: list[str] = []
        proposal = create_writing_proposal(
            self.project, section["section_id"], "polish", "加入学术史对话",
            historiography_entry_ids=[entry["entry_id"]],
            writer=lambda prompt: prompts.append(prompt) or f"已有研究强调道路条件。{marker}",
        )
        self.assertIn(entry["entry_id"], prompts[0])
        self.assertIn("该研究把道路条件与知识生产联系起来", prompts[0])
        self.assertIn(marker, prompts[0])
        self.assertEqual(proposal["validation"]["invalid_citation_markers"], [])
        self.assertEqual(proposal["validation"]["missing_historiography_entry_ids"], [])
        self.assertEqual(proposal["model_snapshot"]["historiography_context"]["entry_ids"], [entry["entry_id"]])
        stored_refs = proposal["model_snapshot"]["historiography_context"]["reading_notes"][0]["page_refs"]
        self.assertEqual(len(stored_refs), 1)
        self.assertEqual(stored_refs[0]["source_version_id"], self.source["source_version_id"])
        with self.assertRaisesRegex(ValueError, "outside the approved historiography whitelist"):
            create_writing_proposal(
                self.project, section["section_id"], "polish", "加入学术史对话",
                historiography_entry_ids=[entry["entry_id"]],
                writer=lambda prompt: "错误引证。[CITE:SRC_other@PAGE_other]",
            )

        missing = create_writing_proposal(
            self.project, section["section_id"], "polish", "加入学术史对话",
            historiography_entry_ids=[entry["entry_id"]],
            writer=lambda _prompt: section["content"] + "\n\n只增加文字而未落实所选研究。",
        )
        self.assertFalse(missing["validation"]["valid"])
        self.assertFalse(missing["validation"]["historiography_coverage_valid"])
        self.assertEqual(
            missing["validation"]["missing_historiography_entry_ids"], [entry["entry_id"]],
        )
        with self.assertRaisesRegex(ValueError, "evidence contract"):
            decide_writing_proposal(
                self.project, missing["proposal_id"], True, "Professor", reason="Missing selected study",
            )

    def test_current_schema_version_is_installed(self) -> None:
        with connect(self.project) as connection:
            self.assertEqual(
                connection.execute("SELECT MAX(version) FROM schema_meta").fetchone()[0],
                SCHEMA_VERSION,
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(style_profile_samples)")}
            self.assertTrue({"sample_role", "source_id", "source_version_id"} <= columns)

    def test_snapshot_exposes_parsed_reading_refs_without_raw_json(self) -> None:
        job = create_reading_job(
            self.project, "快照札记", "作者如何解释移动？", "targeted",
            [self.source["source_id"]], "读完选定页停止",
        )
        save_reading_note(
            self.project, job["job_id"], self.source["source_id"], [1], "作者强调移动。",
        )
        server = build_server(
            self.project, port=0, library_root=self.root / "library-snapshot",
            workspace_root=self.root / "workspace-snapshot",
        )
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            snapshot = json.loads(urlopen(
                f"http://127.0.0.1:{server.server_port}/api/snapshot", timeout=5,
            ).read())
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
        note = next(
            item for reading_job in snapshot["authoring"]["reading_jobs"]
            if reading_job["job_id"] == job["job_id"] for item in reading_job["notes"]
        )
        self.assertNotIn("page_refs_json", note)
        self.assertEqual(len(note["page_refs"]), 1)
        self.assertEqual(note["page_refs"][0]["source_version_id"], self.source["source_version_id"])

    def test_legacy_reading_refs_compact_idempotently_and_leave_invalid_rows_untouched(self) -> None:
        job = create_reading_job(
            self.project, "旧页块札记", "作者如何解释移动？", "targeted",
            [self.source["source_id"]], "读完选定页停止",
        )
        page_id = f"{self.source['source_id']}:P1"
        first_block = f"{self.source['source_id']}:B1"
        second_block = f"{self.source['source_id']}:B2"
        legacy_refs = [
            {"page_id": page_id, "physical_page": 1, "block_id": first_block},
            {"page_id": page_id, "physical_page": 1, "block_id": second_block},
        ]
        malformed_refs = [
            {"page_id": "SRC_foreign:P1", "physical_page": 1, "block_id": first_block},
        ]
        with connect(self.project) as connection:
            connection.execute(
                """INSERT INTO reading_notes(note_id, job_id, source_id, page_refs_json, content,
                   qualification, created_at) VALUES ('RDN_legacy_compact', ?, ?, ?, ?,
                   'READING_NOTE_NOT_EVIDENCE', '2026-01-01')""",
                (job["job_id"], self.source["source_id"], json.dumps(legacy_refs), "旧札记。"),
            )
            connection.execute(
                """INSERT INTO reading_notes(note_id, job_id, source_id, page_refs_json, content,
                   qualification, created_at) VALUES ('RDN_legacy_invalid', ?, ?, ?, ?,
                   'READING_NOTE_NOT_EVIDENCE', '2026-01-02')""",
                (job["job_id"], self.source["source_id"], json.dumps(malformed_refs), "异常旧札记。"),
            )
            before = {
                row["note_id"]: dict(row)
                for row in connection.execute(
                    "SELECT * FROM reading_notes WHERE note_id LIKE 'RDN_legacy_%' ORDER BY note_id"
                )
            }
            connection.execute("DELETE FROM schema_meta WHERE version = 21")
        raw_connection = sqlite3.connect(database_path(self.project))
        raw_connection.row_factory = sqlite3.Row
        try:
            _migrate(raw_connection)
            _migrate(raw_connection)
            raw_connection.commit()
        finally:
            raw_connection.close()
        with connect(self.project) as connection:
            compacted = json.loads(connection.execute(
                "SELECT page_refs_json FROM reading_notes WHERE note_id = 'RDN_legacy_compact'"
            ).fetchone()[0])
            untouched = connection.execute(
                "SELECT page_refs_json FROM reading_notes WHERE note_id = 'RDN_legacy_invalid'"
            ).fetchone()[0]
            audits = connection.execute(
                """SELECT event_type, entity_id, COUNT(*) AS count FROM audit_events
                   WHERE entity_id IN ('RDN_legacy_compact', 'RDN_legacy_invalid')
                   GROUP BY event_type, entity_id ORDER BY entity_id"""
            ).fetchall()
            after = {
                row["note_id"]: dict(row)
                for row in connection.execute(
                    "SELECT * FROM reading_notes WHERE note_id LIKE 'RDN_legacy_%' ORDER BY note_id"
                )
            }
        self.assertEqual(compacted, [{
            "source_version_id": self.source["source_version_id"],
            "page_id": page_id,
            "physical_page": 1,
            "block_id": first_block,
        }])
        self.assertEqual(untouched, json.dumps(malformed_refs))
        for note_id in before:
            self.assertEqual(
                {key: value for key, value in after[note_id].items() if key != "page_refs_json"},
                {key: value for key, value in before[note_id].items() if key != "page_refs_json"},
            )
        self.assertEqual(
            [(row["event_type"], row["entity_id"], row["count"]) for row in audits],
            [
                ("reading_note_page_refs_compacted", "RDN_legacy_compact", 1),
                ("reading_note_page_refs_compaction_skipped", "RDN_legacy_invalid", 1),
            ],
        )

    def test_compact_page_refs_still_complete_a_full_reading_job(self) -> None:
        with connect(self.project) as connection:
            connection.execute(
                "UPDATE anomalies SET status = 'resolved' WHERE source_id = ?",
                (self.source["source_id"],),
            )
            connection.execute(
                "UPDATE pages SET use_state = 'research_usable' WHERE source_id = ?",
                (self.source["source_id"],),
            )
            connection.execute(
                """UPDATE blocks SET use_state = 'research_usable'
                   WHERE page_id IN (SELECT page_id FROM pages WHERE source_id = ?)""",
                (self.source["source_id"],),
            )
        job = create_reading_job(
            self.project, "全文阅读", "作者如何解释移动？", "full",
            [self.source["source_id"]], "读完全部可用页停止",
        )
        note = save_reading_note(
            self.project, job["job_id"], self.source["source_id"], [1, 2],
            "作者按页展开移动论述。", complete=True,
        )
        self.assertEqual(note["status"], "completed")
        with connect(self.project) as connection:
            refs = json.loads(connection.execute(
                "SELECT page_refs_json FROM reading_notes WHERE note_id = ?", (note["note_id"],),
            ).fetchone()[0])
        self.assertEqual([ref["physical_page"] for ref in refs], [1, 2])
        self.assertEqual(len(refs), 2)

    def test_schema_20_preserves_existing_manuscript_style_samples(self) -> None:
        paragraph = "1908年，材料记录了行动次序；这一材料只能支持有限判断。"
        manuscript = import_manuscript(
            self.project, "旧画像样本", "# 正文\n\n" + "\n\n".join(paragraph for _ in range(30)),
        )
        profile = create_style_profile(self.project, manuscript["manuscript_id"], "旧画像", "本人")
        with connect(self.project) as connection:
            connection.execute("DELETE FROM schema_meta WHERE version >= 20")
        migrated = style_profile_detail(self.project, profile["profile_id"])
        self.assertEqual(migrated["samples"][0]["sample_role"], "manuscript")
        self.assertEqual(migrated["samples"][0]["manuscript_id"], manuscript["manuscript_id"])

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
