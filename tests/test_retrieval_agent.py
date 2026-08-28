from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from research_workbench.agent_runtime import _compact_retrievals
from research_workbench.research import add_authenticated_results, create_authenticated_search_task
from research_workbench.service import initialize_project


class RetrievalAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        initialize_project(self.project, "CNKI recommendations")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_agent_can_inspect_captured_titles_without_raw_or_full_text(self) -> None:
        record = create_authenticated_search_task(self.project, "CNKI", "灾害史 地方志")
        add_authenticated_results(self.project, record["record_id"], [{
            "title": "地方志灾害资料整理研究", "authors": "研究者甲", "year": "2024",
            "container": "史学月刊", "url": "https://example.cn/item/1",
        }])
        index = _compact_retrievals(self.project)
        self.assertEqual(index["records"][0]["result_count"], 1)
        detail = _compact_retrievals(self.project, record["record_id"])
        self.assertEqual(detail["results"][0]["title"], "地方志灾害资料整理研究")
        self.assertNotIn("raw_json", detail["results"][0])
        self.assertIn("discovery leads", detail["boundary"])


if __name__ == "__main__":
    unittest.main()
