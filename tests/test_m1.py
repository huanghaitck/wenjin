from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from research_workbench.db import connect
from research_workbench.service import (
    correct_block,
    correct_printed_page,
    import_structure,
    initialize_project,
    list_anomalies,
    list_blocks,
    project_status,
    register_source,
    submit_block_repair,
    submit_page_repair,
    verify_block,
    verify_page,
)


FIXTURES = Path(__file__).parent / "fixtures"


class M1KernelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        initialize_project(self.project, "M1 test project")
        self.source_file = self.root / "sample.pdf"
        self.source_file.write_bytes(b"%PDF-1.4\nsynthetic-m1-fixture\n%%EOF\n")
        self.original_hash = hashlib.sha256(self.source_file.read_bytes()).hexdigest()
        self.source = register_source(self.project, self.source_file, "Synthetic source")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def import_default(self) -> dict:
        return import_structure(self.project, self.source["source_id"], FIXTURES / "m1_structure.json")

    def test_project_and_source_are_initialized_without_modifying_original(self) -> None:
        self.assertTrue((self.project / "project.sqlite3").is_file())
        self.assertTrue((self.project / "project.yaml").is_file())
        copied = self.project / self.source["project_path"]
        self.assertTrue(copied.is_file())
        self.assertEqual(hashlib.sha256(copied.read_bytes()).hexdigest(), self.original_hash)
        self.assertEqual(hashlib.sha256(self.source_file.read_bytes()).hexdigest(), self.original_hash)

    def test_structure_import_is_idempotent_and_audited(self) -> None:
        first = self.import_default()
        second = self.import_default()
        self.assertEqual(first["status"], "applied")
        self.assertEqual(second["status"], "already_applied")
        with connect(self.project) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM pages").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM blocks").fetchone()[0], 3)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM page_relations").fetchone()[0], 1)
            event_types = [row[0] for row in connection.execute("SELECT event_type FROM audit_events")]
        self.assertIn("structure_imported", event_types)

    def test_local_anomalies_only_block_affected_regions(self) -> None:
        self.import_default()
        blocks = list_blocks(self.project, self.source["source_id"])
        states = {row["block_id"].rsplit(":", 1)[-1]: row["use_state"] for row in blocks}
        self.assertEqual(states["B1"], "blocked")
        self.assertEqual(states["B2"], "research_usable")
        self.assertEqual(states["B3"], "blocked")
        self.assertEqual(project_status(self.project)["sources"][0]["use_state"], "partial")

    def test_block_repair_resolves_only_its_anomaly(self) -> None:
        self.import_default()
        anomaly = next(row for row in list_anomalies(self.project) if row["anomaly_id"].endswith(":A_BLOCK"))
        result = submit_block_repair(
            self.project,
            anomaly["anomaly_id"],
            "The expedition left the staging station in spring.",
            "human-reviewer",
            "Corrected the mistranscribed word against the page image.",
        )
        self.assertEqual(result["scope_type"], "block")
        blocks = {row["block_id"]: row for row in list_blocks(self.project, self.source["source_id"])}
        repaired = blocks[anomaly["target_id"]]
        self.assertEqual(repaired["effective_text"], "The expedition left the staging station in spring.")
        self.assertEqual(repaired["use_state"], "research_usable")
        page_anomaly = next(row for row in list_anomalies(self.project) if row["anomaly_id"].endswith(":A_PAGE"))
        self.assertEqual(page_anomaly["status"], "open")
        self.assertEqual(project_status(self.project)["sources"][0]["use_state"], "partial")

    def test_page_repair_updates_page_blocks_and_relation(self) -> None:
        self.import_default()
        anomalies = list_anomalies(self.project)
        block_anomaly = next(row for row in anomalies if row["anomaly_id"].endswith(":A_BLOCK"))
        submit_block_repair(self.project, block_anomaly["anomaly_id"], "Corrected first paragraph.",
                            "human-reviewer", "Page image check")
        page_anomaly = next(row for row in anomalies if row["anomaly_id"].endswith(":A_PAGE"))
        relation_id = f"{self.source['source_id']}:R1"
        result = submit_page_repair(
            self.project,
            page_anomaly["anomaly_id"],
            {
                "blocks": [
                    {"order": 1, "type": "paragraph", "text": "and ends correctly on the following page."}
                ],
                "relation_updates": [{"relation_id": relation_id, "value": True}],
            },
            "human-reviewer",
            "Rebuilt the complete second page against the PDF.",
        )
        self.assertEqual(result["scope_type"], "page")
        status = project_status(self.project)
        self.assertEqual(status["sources"][0]["use_state"], "research_usable")
        self.assertEqual(status["repair_count"], 2)
        block3 = next(row for row in list_blocks(self.project, self.source["source_id"])
                      if row["block_id"].endswith(":B3"))
        self.assertEqual(block3["effective_text"], "and ends correctly on the following page.")
        with connect(self.project) as connection:
            relation = connection.execute(
                "SELECT human_value, verification_state FROM page_relations WHERE relation_id = ?",
                (relation_id,),
            ).fetchone()
        self.assertEqual(json.loads(relation["human_value"]), True)
        self.assertEqual(relation["verification_state"], "human_repaired")

    def test_systemic_anomaly_blocks_the_whole_source(self) -> None:
        second_source_file = self.root / "systemic.pdf"
        second_source_file.write_bytes(b"%PDF-1.4\nsystemic\n%%EOF\n")
        second = register_source(self.project, second_source_file, "Systemic source")
        import_structure(self.project, second["source_id"], FIXTURES / "m1_systemic_structure.json")
        status = project_status(self.project)
        source = next(item for item in status["sources"] if item["source_id"] == second["source_id"])
        self.assertEqual(source["use_state"], "blocked")
        blocks = list_blocks(self.project, second["source_id"])
        self.assertTrue(blocks)
        self.assertTrue(all(item["use_state"] == "blocked" for item in blocks))

    def test_state_changes_create_repair_and_audit_records(self) -> None:
        self.import_default()
        anomaly = next(row for row in list_anomalies(self.project) if row["anomaly_id"].endswith(":A_BLOCK"))
        submit_block_repair(self.project, anomaly["anomaly_id"], "Corrected.", "human-reviewer", "Checked")
        with connect(self.project) as connection:
            repair_count = connection.execute("SELECT COUNT(*) FROM repair_records").fetchone()[0]
            audit_types = [row[0] for row in connection.execute("SELECT event_type FROM audit_events")]
        self.assertEqual(repair_count, 1)
        self.assertIn("block_repaired", audit_types)

    def test_clean_page_requires_explicit_human_verification(self) -> None:
        packet = self.root / "clean-structure.json"
        packet.write_text(json.dumps({"pages": [{
            "id": "P1", "physical_page": 1, "page_type": "body",
            "blocks": [{"id": "B1", "order": 1, "type": "paragraph", "text": "Verified text."}],
        }]}), encoding="utf-8")
        import_structure(self.project, self.source["source_id"], packet)
        page_id = f"{self.source['source_id']}:P1"
        result = verify_page(self.project, page_id, "Professor", "Compared every line with the rendered page")
        self.assertEqual(result["verification_state"], "human_verified")
        with connect(self.project) as connection:
            page_state = connection.execute("SELECT verification_state FROM pages WHERE page_id = ?", (page_id,)).fetchone()[0]
            block_state = connection.execute("SELECT verification_state FROM blocks WHERE page_id = ?", (page_id,)).fetchone()[0]
        self.assertEqual(page_state, "human_verified")
        self.assertEqual(block_state, "human_verified")

    def test_single_block_verification_marks_only_a_page_spot_check(self) -> None:
        packet = self.root / "spot-check.json"
        packet.write_text(json.dumps({"pages": [{
            "id": "P1", "physical_page": 1, "page_type": "body",
            "blocks": [
                {"id": "B1", "order": 1, "type": "paragraph", "text": "Checked paragraph."},
                {"id": "B2", "order": 2, "type": "paragraph", "text": "Unchecked paragraph."},
            ],
        }]}), encoding="utf-8")
        import_structure(self.project, self.source["source_id"], packet)
        result = verify_block(self.project, f"{self.source['source_id']}:B1", "Professor", "Checked this paragraph")
        self.assertEqual(result["verification_state"], "human_verified")
        with connect(self.project) as connection:
            page_state = connection.execute("SELECT verification_state FROM pages WHERE page_id = ?", (result["page_id"],)).fetchone()[0]
            states = [row[0] for row in connection.execute("SELECT verification_state FROM blocks ORDER BY block_order")]
        self.assertEqual(page_state, "human_spot_checked")
        self.assertEqual(states, ["human_verified", "machine_parsed"])

    def test_user_can_correct_an_undetected_block_error(self) -> None:
        packet = self.root / "manual-correction.json"
        packet.write_text(json.dumps({"pages": [{
            "id": "P1", "physical_page": 1, "page_type": "body",
            "blocks": [{"id": "B1", "order": 1, "type": "paragraph", "text": "The rode was busy."}],
        }]}), encoding="utf-8")
        import_structure(self.project, self.source["source_id"], packet)
        block_id = f"{self.source['source_id']}:B1"
        result = correct_block(
            self.project, block_id, "The road was busy.", "Professor", "Corrected against the image",
            block_type="heading",
        )
        self.assertTrue(result["repair_id"].startswith("REP_"))
        with connect(self.project) as connection:
            block = connection.execute(
                "SELECT machine_text, human_text, block_type, verification_state FROM blocks WHERE block_id = ?", (block_id,)
            ).fetchone()
        self.assertEqual(block["machine_text"], "The rode was busy.")
        self.assertEqual(block["human_text"], "The road was busy.")
        self.assertEqual(block["block_type"], "heading")
        self.assertEqual(block["verification_state"], "human_repaired")

    def test_user_can_reconstruct_a_missing_printed_page_label(self) -> None:
        packet = self.root / "missing-printed-page.json"
        packet.write_text(json.dumps({"pages": [{
            "id": "P310", "physical_page": 310, "page_type": "body",
            "blocks": [{"id": "B1", "order": 1, "type": "paragraph", "text": "Page text."}],
        }]}), encoding="utf-8")
        import_structure(self.project, self.source["source_id"], packet)
        page_id = f"{self.source['source_id']}:P310"
        result = correct_printed_page(
            self.project, page_id, "300", "Professor", "Read the printed header on the rendered page"
        )
        self.assertEqual(result["printed_page"], "300")
        with connect(self.project) as connection:
            page = connection.execute(
                "SELECT printed_page, verification_state FROM pages WHERE page_id = ?", (page_id,)
            ).fetchone()
            audit = connection.execute(
                "SELECT event_type FROM audit_events WHERE entity_id = ? ORDER BY event_id DESC", (page_id,)
            ).fetchone()[0]
        self.assertEqual(tuple(page), ("300", "human_spot_checked"))
        self.assertEqual(audit, "printed_page_corrected")


if __name__ == "__main__":
    unittest.main()
