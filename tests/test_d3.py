from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from docx import Document

from research_workbench.agent_runtime import create_thread, send_message
from research_workbench.authoring import import_manuscript, manuscript_detail
from research_workbench.db import connect
from research_workbench.document_model import (
    ensure_document,
    export_document,
    import_docx,
    save_document,
)
from research_workbench.service import initialize_project


class D3ResearchObjectWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        initialize_project(self.project, "D3 project")
        self.manuscript = import_manuscript(
            self.project, "页面关系论文", "# 导言\n\n1908年，材料称“队伍北行”。[^1]\n\n# 第一节\n\n原有论述。",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_legacy_sections_become_structured_document_without_losing_text(self) -> None:
        detail = ensure_document(self.project, self.manuscript["manuscript_id"])
        self.assertEqual([item["heading"] for item in detail["document"]["children"]], ["导言", "第一节"])
        self.assertIn("1908年", detail["document"]["children"][0]["children"][0]["text"])
        self.assertEqual(detail["source_format"], "legacy_sections")

    def test_save_creates_immutable_revision_and_updates_legacy_read(self) -> None:
        first = ensure_document(self.project, self.manuscript["manuscript_id"])
        tree = first["document"]
        tree["children"][0]["children"][0]["text"] += " 人工补充一句。"
        second = save_document(self.project, self.manuscript["manuscript_id"], tree)
        self.assertNotEqual(first["current_revision_id"], second["current_revision_id"])
        self.assertEqual(len(second["revisions"]), 2)
        with connect(self.project) as connection:
            original = connection.execute(
                "SELECT document_json FROM document_revisions WHERE revision_id = ?",
                (first["current_revision_id"],),
            ).fetchone()[0]
        self.assertNotIn("人工补充一句", original)
        self.assertIn("人工补充一句", manuscript_detail(self.project, self.manuscript["manuscript_id"])["sections"][0]["content"])
        with connect(self.project) as connection:
            counts = [row[0] for row in connection.execute(
                "SELECT COUNT(*) FROM section_versions GROUP BY section_id ORDER BY section_id"
            )]
        self.assertEqual(sorted(counts), [1, 2])

    def test_context_dialogue_freezes_revision_section_and_selection_hash(self) -> None:
        detail = ensure_document(self.project, self.manuscript["manuscript_id"])
        section = detail["document"]["children"][0]
        node = section["children"][0]
        thread = create_thread(self.project, "稿件讨论")
        result = send_message(self.project, thread["thread_id"], "这句话的证据边界如何？", {
            "manuscript_id": self.manuscript["manuscript_id"],
            "revision_id": detail["current_revision_id"],
            "section_id": section["section_id"],
            "node_id": node["node_id"],
            "selection_text": "队伍北行",
            "attached_refs": [],
        })
        binding = result["messages"][0]["context_binding"]
        self.assertEqual(binding["revision_id"], detail["current_revision_id"])
        self.assertEqual(binding["selection_text"], "队伍北行")
        self.assertEqual(len(binding["selection_hash"]), 64)

    def test_docx_and_markdown_adapters_return_fidelity_receipts(self) -> None:
        package = io.BytesIO()
        docx = Document()
        docx.add_heading("导言", level=1)
        docx.add_paragraph("正文段落。")
        table = docx.add_table(rows=3, cols=3)
        for column, value in enumerate(("比较项", "谭卫道", "李希霍芬")):
            table.cell(0, column).text = value
        table.cell(1, 0).text, table.cell(1, 1).text, table.cell(1, 2).text = "旅行年份", "1873", "1872"
        table.cell(2, 0).text, table.cell(2, 1).text, table.cell(2, 2).text = "停驻点", "12", "9"
        docx.save(package)
        imported = import_docx(self.project, "DOCX 稿件", package.getvalue())
        self.assertEqual(imported["import_fidelity"]["level"], "limited")
        self.assertEqual(imported["document"]["children"][0]["children"][1]["type"], "table")
        markdown = export_document(self.project, imported["manuscript_id"], "markdown")
        word = export_document(self.project, imported["manuscript_id"], "docx")
        self.assertTrue((self.project / markdown["project_path"]).is_file())
        self.assertTrue((self.project / word["project_path"]).is_file())
        self.assertIn("| 比较项 | 谭卫道 | 李希霍芬 |", (self.project / markdown["project_path"]).read_text(encoding="utf-8"))
        self.assertEqual(len(Document(self.project / word["project_path"]).tables), 1)
        self.assertEqual(word["fidelity"]["level"], "structured_with_true_footnotes")

    def test_ui_has_four_permanent_workspaces_and_nested_repair(self) -> None:
        html = (Path(__file__).parents[1] / "src" / "research_workbench" / "web_assets" / "index.html").read_text(encoding="utf-8")
        for label in ("研究对话", "研究图书馆", "文章工作台", "项目设置"):
            self.assertIn(label, html)
        self.assertIn("研究者意图基线", html)
        app = (Path(__file__).parents[1] / "src" / "research_workbench" / "web_assets" / "app.js").read_text(encoding="utf-8")
        self.assertIn("研究认知轨迹", app)
        self.assertIn("不是心理画像或来源证据", app)
        self.assertIn("$('pageJump').value = page?.physical_page || '';", app)
        self.assertNotIn('id="sourceMode"', html)
        self.assertIn('id="openSourceRepair"', html)
        self.assertIn('id="documentCanvas"', html)
        self.assertIn('id="browserWorkbench"', html)


if __name__ == "__main__":
    unittest.main()
