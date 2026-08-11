from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from research_workbench.authoring import ensure_journal_templates, import_manuscript
from research_workbench.citations import create_note, decide_note, note_detail, revise_note
from research_workbench.db import connect
from research_workbench.document_model import ensure_document, export_document, save_document
from research_workbench.scholarship import create_claim, create_evidence
from research_workbench.service import import_structure, initialize_project, register_source


FIXTURES = Path(__file__).parent / "fixtures"


class D4PracticalAuthoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.project = root / "project"
        initialize_project(self.project, "D4 project")
        source_file = root / "source.pdf"
        source_file.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
        source = register_source(self.project, source_file, "Expedition source")
        import_structure(self.project, source["source_id"], FIXTURES / "m1_structure.json")
        with connect(self.project) as connection:
            connection.execute("UPDATE pages SET use_state = 'research_usable', verification_state = 'human_verified'")
            connection.execute("UPDATE blocks SET use_state = 'research_usable', verification_state = 'human_verified'")
            block = connection.execute("SELECT block_id, machine_text FROM blocks ORDER BY block_order LIMIT 1").fetchone()
        claim = create_claim(self.project, "考察队发生了移动")
        self.evidence = create_evidence(self.project, claim["claim_id"], block["block_id"], block["machine_text"], "原页核对")
        self.evidence_id = self.evidence["evidence"][0]["evidence_id"]
        self.manuscript = import_manuscript(self.project, "注释测试", "# 导言\n\n1908年，材料称队伍进入草原。")
        self.document = ensure_document(self.project, self.manuscript["manuscript_id"])
        self.node = self.document["document"]["children"][0]["children"][0]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _propose(self):
        return create_note(
            self.project, self.manuscript["manuscript_id"], self.node["node_id"], len(self.node["text"]),
            "队伍进入草原。", "builtin-history-research", "VERIFY_AND_INSERT",
            {"source_type": "book", "author": "张三", "title": "考察记", "place": "北京",
             "publisher": "史学出版社", "year": "1908", "original_page": "12", "digital_page": "17"},
            self.evidence_id,
        )

    def test_two_versioned_builtin_templates_are_visible(self) -> None:
        templates = [item for item in ensure_journal_templates(self.project) if item["origin"] == "builtin"]
        self.assertEqual({item["name"] for item in templates}, {"《历史研究》", "《中国社会科学》"})
        self.assertTrue(all(item["source_url"] and item["verified_at"] for item in templates))
        history = next(item for item in templates if item["name"] == "《历史研究》")
        self.assertEqual(history["verification_status"], "REFERENCE_NEEDS_PRE_SUBMISSION_RECHECK")

    def test_page_verified_note_requires_evidence_and_human_approval(self) -> None:
        with self.assertRaisesRegex(ValueError, "evidence item"):
            create_note(
                self.project, self.manuscript["manuscript_id"], self.node["node_id"], len(self.node["text"]),
                "队伍进入草原。", "builtin-history-research", "VERIFY_AND_INSERT",
                {"title": "考察记", "original_page": "12"}, "",
            )
        proposed = self._propose()
        self.assertEqual(proposed["status"], "pending")
        approved = decide_note(self.project, proposed["note_version_id"], True, "human-reviewer")
        self.assertEqual(approved["status"], "active")
        self.assertEqual(approved["current"]["source_refs"][0]["evidence_id"], self.evidence_id)

    def test_note_versions_are_immutable_and_anchor_change_blocks_use(self) -> None:
        proposed = self._propose()
        approved = decide_note(self.project, proposed["note_version_id"], True, "human-reviewer")
        revision = revise_note(self.project, approved["note_id"], "REFORMAT_EXISTING", {
            "user_supplied_text": "张三：《考察记》，北京：史学出版社，1908年，第12页。",
        })
        self.assertEqual(revision["status"], "active")
        self.assertEqual(revision["pending"]["verification_state"], "PAGE_VERIFIED_REFORMATTED")
        during_review = export_document(self.project, self.manuscript["manuscript_id"], "markdown")
        self.assertIn("[^note1]", (self.project / during_review["project_path"]).read_text(encoding="utf-8"))
        decide_note(self.project, revision["pending"]["note_version_id"], True, "human-reviewer")
        self.assertEqual(len(note_detail(self.project, approved["note_id"])["versions"]), 2)
        tree = self.document["document"]
        tree["children"][0]["children"][0]["text"] = "1908年，材料称队伍抵达草原。"
        saved = save_document(self.project, self.manuscript["manuscript_id"], tree)
        self.assertEqual(saved["notes"][0]["status"], "anchor_needs_review")

    def test_markdown_and_docx_export_approved_true_footnote(self) -> None:
        proposed = self._propose()
        decide_note(self.project, proposed["note_version_id"], True, "human-reviewer")
        markdown = export_document(self.project, self.manuscript["manuscript_id"], "markdown")
        markdown_text = (self.project / markdown["project_path"]).read_text(encoding="utf-8")
        self.assertIn("[^note1]", markdown_text)
        self.assertIn("张三：《考察记》", markdown_text)
        word = export_document(self.project, self.manuscript["manuscript_id"], "docx", "builtin-chinese-social-sciences-2026")
        self.assertEqual(word["fidelity"]["approved_note_count"], 1)
        with zipfile.ZipFile(self.project / word["project_path"]) as package:
            self.assertIn("word/footnotes.xml", package.namelist())
            self.assertIn("考察记", package.read("word/footnotes.xml").decode("utf-8"))
            self.assertIn("footnoteReference", package.read("word/document.xml").decode("utf-8"))
            self.assertIn("eachPage", package.read("word/document.xml").decode("utf-8"))

    def test_article_ui_exposes_note_and_template_controls(self) -> None:
        root = Path(__file__).parents[1] / "src" / "research_workbench" / "web_assets"
        html = (root / "index.html").read_text(encoding="utf-8")
        script = (root / "app.js").read_text(encoding="utf-8")
        for marker in ('data-authoring="notes"', 'id="insertNote"', 'id="insertSection"', 'id="insertTable"', 'id="exportTemplate"', 'id="manuscriptStats"', 'id="manuscriptTitleEdit"'):
            self.assertIn(marker, html)
        self.assertIn("/api/note/create", script)
        self.assertIn("humanStates.has(item.block.verification_state)", script)
        self.assertIn("const shownEvidence=new Set()", script)
        self.assertIn("proposal.proposed_content.length", script)


if __name__ == "__main__":
    unittest.main()
