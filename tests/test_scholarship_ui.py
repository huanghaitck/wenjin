from __future__ import annotations

import unittest
import json
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from urllib.request import Request, urlopen

from research_workbench.db import connect
from research_workbench.service import initialize_project
from research_workbench.web import build_server


ROOT = Path(__file__).parents[1]
APP = ROOT / "src" / "research_workbench" / "web_assets" / "app.js"
WEB = ROOT / "src" / "research_workbench" / "web.py"


class ScholarshipUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = APP.read_text(encoding="utf-8")
        cls.web = WEB.read_text(encoding="utf-8")

    def test_creating_reading_job_does_not_claim_it_was_executed(self) -> None:
        self.assertIn("建立有界阅读任务", self.app)
        self.assertIn("尚未读取材料，也未生成札记", self.app)
        self.assertNotIn("建立并执行有界阅读", self.app)
        self.assertNotIn("阅读札记已生成；它们不是证据", self.app)

    def test_section_historiography_is_approved_only_and_sent_to_authoring(self) -> None:
        self.assertIn("本节选用学术史", self.app)
        self.assertIn("候选，需批准后方可选", self.app)
        self.assertIn("check.disabled=!approved", self.app)
        self.assertIn("historiography_entry_ids", self.app)
        self.assertIn('"historiography_entry_ids" in supported', self.web)
        self.assertIn('/api/historiography/decide', self.app)
        self.assertIn('decide_historiography_entry', self.web)

    def test_rejected_selected_proposal_does_not_shadow_a_new_proposal(self) -> None:
        self.assertIn("else state.proposalId = '';", self.app)

    def test_writing_decision_locks_editor_until_refresh_finishes(self) -> None:
        self.assertIn("function setAuthoringRefreshBusy(busy)", self.app)
        self.assertIn("workbench.inert=busy", self.app)
        self.assertIn("workbench.setAttribute('aria-busy',busy?'true':'false')", self.app)
        decision = self.app.split(
            "const decide=async(approved)=>{const reviewer=$('writingReviewer')", 1,
        )[1].split("const approve=actionButton", 1)[0]
        self.assertLess(
            decision.index("setAuthoringRefreshBusy(true)"),
            decision.index("await request('/api/writing/decide'"),
        )
        self.assertIn("finally{setAuthoringRefreshBusy(false);}", decision)
        self.assertIn("完成前暂不可编辑或重新选区", self.app)

    def test_selecting_historiography_does_not_reset_writing_instruction(self) -> None:
        selection_handler = self.app.split("check.onchange=()=>", 1)[1].split(";", 1)[0]
        self.assertNotIn("renderAuthoringControl", selection_handler)

    def test_review_template_selection_survives_review_refresh(self) -> None:
        self.assertIn("template.onchange=()=>{$('exportTemplate').value=template.value;};", self.app)

    def test_writing_contract_failures_are_visible_to_the_researcher(self) -> None:
        self.assertIn("所选学术史未进入正文", self.app)
        self.assertIn("模型原样返回，未形成实际修改", self.app)

    def test_selection_polish_is_version_bound_and_keeps_sidebar_state(self) -> None:
        self.assertIn("仅返修当前选区", self.app)
        self.assertIn("base_version_id:section.current_version_id", self.app)
        self.assertIn("selection_only:selectionOnly.checked", self.app)
        self.assertIn("sha256Text(selection.text)", self.app)
        self.assertIn("选区返修并已回填完整章节", self.app)
        selection_handlers = self.app.split("$('documentCanvas').onmouseup", 1)[1].split(";", 2)[0]
        self.assertNotIn("renderAuthoringControl", selection_handlers)

    def test_text_selection_can_choose_approved_frozen_evidence(self) -> None:
        self.assertIn("selectionSupplementAllowed", self.app)
        self.assertIn("Boolean(state.writingSelection?.text)", self.app)
        self.assertIn("当前选区允许补充的冻结证据（可多选）", self.app)
        self.assertIn("请为当前选区补充至少选择一条已冻结证据", self.app)
        self.assertNotIn("tableSupplementAllowed", self.app)

    def test_complete_table_selection_uses_canonical_offsets_and_rejects_mixed_ranges(self) -> None:
        self.assertIn("function canonicalNodeText(node)", self.app)
        self.assertIn("function canonicalNodeStart(nodes,index)", self.app)
        self.assertIn("completeTableSelected(range,startElement)", self.app)
        self.assertIn("kind:'table'", self.app)
        self.assertIn("表格返修必须完整选择一张表", self.app)
        self.assertIn("canonicalNodeStart(nodes,startIndex)", self.app)
        self.assertNotIn("nodes.slice(startIndex,endIndex+1).some((node)=>node.type==='table')", self.app)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the browser offset contract")
    def test_canonical_offset_counts_a_preceding_table_and_all_source_markers(self) -> None:
        helper = "function canonicalNodeText" + self.app.split(
            "function canonicalNodeText", 1,
        )[1].split("function textOffsetWithin", 1)[0]
        nodes = [
            {"type": "paragraph", "node_id": "NOD_before",
             "text": "表前判断。[EVID:EVT_before]"},
            {"type": "table", "node_id": "NOD_table", "rows": [
                ["年份", "事件"], ["1872", "越岭 [EVID:EVT_table]"],
            ]},
            {"type": "paragraph", "node_id": "NOD_selected",
             "text": "1879年继续行程。[EVID:EVT_1879][CITE:SRC_diary@SRC_diary:P79]"},
            {"type": "paragraph", "node_id": "NOD_after",
             "text": "后段。[CITE:SRC_after@SRC_after:P1]"},
        ]
        javascript = helper + "\n" + (
            f"const nodes={json.dumps(nodes, ensure_ascii=False)};"
            "const base=nodes.map(canonicalNodeText).join('\\n\\n');"
            "const start=canonicalNodeStart(nodes,2);"
            "const end=start+canonicalNodeText(nodes[2]).length;"
            "process.stdout.write(JSON.stringify({start,end,text:base.slice(start,end),base}));"
        )
        completed = subprocess.run(
            [shutil.which("node") or "node", "-e", javascript],
            check=True, capture_output=True, text=True, encoding="utf-8",
        )
        result = json.loads(completed.stdout)
        selected = nodes[2]["text"]
        self.assertEqual(result["start"], result["base"].index(selected))
        self.assertEqual(result["end"], result["start"] + len(selected))
        self.assertEqual(result["text"], selected)

    def test_explicit_context_references_replace_empty_hard_code(self) -> None:
        self.assertIn("attached_refs:explicitResearchRefs(authoring)", self.app)
        self.assertIn("kind:'historiography_entry'", self.app)
        self.assertIn("kind:'source_page'", self.app)
        self.assertNotIn("attached_refs:[]", self.app)

    def test_material_closure_style_sample_and_lock_guidance_are_visible(self) -> None:
        for label in ("已读研究：", "学术史：", "正文引用：", "书目核验："):
            self.assertIn(label, self.app)
        self.assertIn("最低 3 篇，建议 5 篇", self.app)
        self.assertIn("/api/style-profile/create-external", self.app)
        self.assertIn("/api/style-profile/add-external-sample", self.app)
        self.assertIn("create_external_style_profile", self.web)
        self.assertIn("至少 3 篇同作者已核全文的稳定文风画像", self.app)
        self.assertIn("研究来源用于支持论断，不能充作文风样本", self.app)
        self.assertIn("database locked", self.app)
        self.assertIn("关闭重复打开的工作台再重试", self.app)

    def test_readiness_copy_separates_formal_drafting_from_submission(self) -> None:
        self.assertIn("正式写作条件已满足｜投稿仍待检查", self.app)
        self.assertIn("继续研究｜尚未达到正式写作条件", self.app)
        self.assertIn("这不是投稿就绪结论", self.app)
        self.assertNotIn("当前可进入正式成稿与投稿导出", self.app)

    def test_long_page_blocks_are_grouped_without_removing_page_gates(self) -> None:
        self.assertIn("function appendGroupedBlocks", self.app)
        self.assertIn("正文与标题", self.app)
        self.assertIn("脚注", self.app)
        self.assertIn("页眉、页脚与页码", self.app)
        self.assertIn("details.open=hasIssue", self.app)
        self.assertIn("确认本页与原图一致", self.app)
        self.assertIn("renderRelations(); renderAnomalies();", self.app)
        self.assertIn("orderedBlockCards(container)", self.app)

    def test_internal_model_tool_output_is_not_rendered_verbatim(self) -> None:
        self.assertIn("function publicMessageText", self.app)
        self.assertIn("模型返回了内部工具格式内容，未直接展示", self.app)
        self.assertIn("模型操作格式未通过；系统最多自动重试一次", self.app)
        self.assertIn("text.textContent = publicMessageText(message)", self.app)

    def test_historiography_decision_route_records_a_human_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            initialize_project(project, "Scholarship UI")
            server = build_server(
                project, port=0, library_root=root / "library", workspace_root=root / "workspace",
            )
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"

            def post(path: str, payload: dict[str, object]) -> dict[str, object]:
                request = Request(
                    base + path, data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                return json.loads(urlopen(request, timeout=5).read())

            try:
                with connect(project) as connection:
                    connection.execute(
                        """INSERT INTO historiography_entries(entry_id, work_title, position, contribution,
                           limitation, relevance, source_refs_json, status, created_at)
                           VALUES ('HIS_test', 'A Study', 'Position', 'Contribution', 'Limitation',
                                   'Relevance', '[\"SRC_missing\"]', 'candidate', '2026-01-01')"""
                    )
                decision = post("/api/historiography/decide", {
                    "entry_id": "HIS_test", "approved": False,
                    "reviewer": "Professor", "reason": "Source identity requires recheck",
                })
                self.assertEqual(decision["status"], "rejected")
                self.assertEqual(decision["decision"]["reviewer"], "Professor")
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
