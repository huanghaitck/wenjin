from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from research_workbench.db import connect
from research_workbench.service import initialize_project, register_source
from research_workbench.source_documents import build_reading_markdown, export_reading_markdown
from research_workbench.web import build_server


class SourceDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        initialize_project(self.project, "Reading markdown")
        source_file = self.root / "source.pdf"
        source_file.write_bytes(b"%PDF fixture")
        self.source = register_source(self.project, source_file, "Chronicle source")
        with connect(self.project) as connection:
            connection.execute(
                """INSERT INTO pages(page_id, source_id, physical_page, printed_page, page_type,
                   verification_state, use_state, machine_payload_json)
                   VALUES ('P1', ?, 1, '10', 'text', 'human_verified', 'research_usable', '{}'),
                          ('P2', ?, 2, '11', 'text', 'human_spot_checked', 'research_usable', '{}')""",
                (self.source["source_id"], self.source["source_id"]),
            )
            connection.executemany(
                """INSERT INTO blocks(block_id, page_id, block_order, block_type, machine_text,
                   human_text, verification_state, use_state, source_region_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
                [
                    ("B1", "P1", 1, "header", "Header", None, "machine_parsed", "research_usable"),
                    ("B2", "P1", 2, "paragraph", "Old first", "Human first，", "human_repaired", "research_usable"),
                    ("B3", "P2", 1, "paragraph", "continued text。", None, "human_verified", "research_usable"),
                    ("B4", "P2", 2, "paragraph", "Unverified detail。", None, "machine_parsed", "research_usable"),
                    ("B5", "P2", 3, "footnote", "Footnote text", None, "human_verified", "research_usable"),
                ],
            )
            connection.execute(
                """INSERT INTO page_relations(relation_id, source_id, from_block_id, to_block_id,
                   relation_type, machine_value, human_value, verification_state)
                   VALUES ('R1', ?, 'B2', 'B3', 'continues_on_next_page', ?, ?, 'human_repaired')""",
                (
                    self.source["source_id"],
                    json.dumps({"continues": None}),
                    json.dumps({"continues": True}),
                ),
            )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_current_reading_markdown_keeps_page_anchors_and_human_text(self) -> None:
        artifact = build_reading_markdown(self.project, self.source["source_id"])
        text = artifact["markdown"]
        self.assertIn("Human first，", text)
        self.assertIn("continued text。", text)
        self.assertIn("confirmed_page_continuation", text)
        self.assertIn("Unverified detail。", text)
        self.assertIn("> 注：Footnote text", text)
        self.assertNotIn("Header", text)
        self.assertEqual(artifact["confirmed_continuation_count"], 1)

    def test_verified_reading_markdown_excludes_unverified_blocks_and_writes_receipt(self) -> None:
        receipt = export_reading_markdown(
            self.project, self.source["source_id"], verified_only=True,
        )
        target = self.project / receipt["project_path"]
        text = target.read_text(encoding="utf-8")
        self.assertIn("Human first，", text)
        self.assertIn("continued text。", text)
        self.assertNotIn("Unverified detail。", text)
        self.assertEqual(receipt["mode"], "verified")
        self.assertTrue(target.is_file())

    def test_loopback_api_exports_reading_markdown(self) -> None:
        server = build_server(
            self.project, host="127.0.0.1", port=0,
            library_root=self.root / "library", workspace_root=self.root / "workspace",
        )
        import threading
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{server.server_port}/api/source/reading-markdown",
                data=json.dumps({"source_id": self.source["source_id"], "verified_only": True}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request) as response:
                result = json.loads(response.read())
            self.assertEqual(result["mode"], "verified")
            self.assertTrue((self.project / result["project_path"]).is_file())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
