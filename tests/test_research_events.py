from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from research_workbench.db import connect
from research_workbench.research_events import (
    _qualified_block_id,
    create_event_candidates,
    decide_event,
    event_anchor_text,
    event_chronicle,
    event_coverage,
    event_state,
    export_event_register,
    export_event_chronicle,
)
from research_workbench.scholarship import (
    approve_freeze,
    create_event_freeze,
    draft_from_freeze,
    review_artifact,
)
from research_workbench.service import (
    correct_printed_page,
    import_structure,
    initialize_project,
    correct_block,
    register_source,
    verify_block,
)


FIXTURE = Path(__file__).parent / "fixtures" / "m1_structure.json"


class ResearchEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.project = root / "project"
        initialize_project(self.project, "Event table test")
        original = root / "source.txt"
        original.write_text("immutable original", encoding="utf-8")
        self.source = register_source(self.project, original, "Test source")
        import_structure(self.project, self.source["source_id"], FIXTURE)
        self.block_id = f"{self.source['source_id']}:B2"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_local_human_repair_block_id_is_qualified_by_source(self) -> None:
        source_id = self.source["source_id"]
        self.assertEqual(
            _qualified_block_id(source_id, "P0231:H005"),
            f"{source_id}:P0231:H005",
        )
        full_id = f"{source_id}:P0231:H005"
        self.assertEqual(_qualified_block_id(source_id, full_id), full_id)

    def _create(self) -> dict[str, object]:
        return create_event_candidates(
            self.project,
            [{
                "case_id": "Richthofen-1871",
                "event_date": "1871-10-01",
                "source_id": self.source["source_id"],
                "block_ids": [self.block_id],
                "field_anchors": {
                    "event_date": [self.block_id],
                    "route": [self.block_id],
                    "investigation_object": [self.block_id],
                    "recording_technique": [self.block_id],
                    "movement_mode": [self.block_id],
                    "genre": [self.block_id],
                    "participant_visibility": [self.block_id],
                    "institutional_task": [self.block_id],
                    "outcome_destination": [self.block_id],
                    "original_text": [self.block_id],
                },
                "original_text": "The sentence continues toward the page boundary",
                "route": "Qinling route",
                "investigation_object": "road",
                "recording_technique": "diary observation",
                "movement_mode": "on foot",
                "genre": "travel diary",
                "participant_visibility": "unnamed participants described by role",
                "institutional_task": "journey record",
                "outcome_destination": "published diary",
                "missing_reason": "Chinese participants PND in this block scope",
            }],
            "test-model",
            model_snapshot={"model": "test-model"},
        )[0]

    def test_candidate_requires_page_verification_before_approval(self) -> None:
        candidate = self._create()
        self.assertEqual(candidate["status"], "draft")
        self.assertEqual(candidate["qualification"], "PAGE_LINKED_EVENT_NOT_FROZEN")
        self.assertEqual(candidate["field_anchors"]["original_text"], [self.block_id])
        self.assertEqual(candidate["movement_mode"], "on foot")
        self.assertEqual(candidate["genre"], "travel diary")
        self.assertEqual(candidate["participant_visibility"], "unnamed participants described by role")
        self.assertEqual(candidate["outcome_destination"], "published diary")
        with self.assertRaisesRegex(
            ValueError,
            f"human verification before approval: {self.block_id}",
        ):
            decide_event(
                self.project, str(candidate["event_id"]), True,
                "Professor", "核对原页后决定",
            )

        verify_block(self.project, self.block_id, "Professor", "Exact against the source page")
        approved = decide_event(
            self.project, str(candidate["event_id"]), True,
            "Professor", "已逐字核对原页",
            {"notes": "人工确认后保留"},
        )
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["qualification"], "PAGE_LINKED_EVENT_NOT_FROZEN")
        self.assertEqual(approved["notes"], "人工确认后保留")

    def test_approved_events_can_form_a_pending_freeze_without_duplicate_evidence_rows(self) -> None:
        candidate = self._create()
        verify_block(self.project, self.block_id, "Professor", "Exact against the source page")
        approved = decide_event(
            self.project, str(candidate["event_id"]), True,
            "Professor", "已逐字核对原页",
        )

        freeze = create_event_freeze(
            self.project,
            "Approved event freeze",
            [{
                "text": "The route was recorded as an object of investigation.",
                "does_not_support": "This does not prove a complete survey.",
                "evidence": [{"event_id": approved["event_id"], "relation": "supports"}],
            }],
            unresolved=["The wider chronology remains unresolved."],
            prohibited_claims=["Do not call this a complete survey."],
        )
        self.assertEqual(freeze["status"], "pending")
        self.assertEqual(freeze["payload"]["freeze_kind"], "approved_research_events")
        evidence = freeze["payload"]["claims"][0]["evidence"][0]
        self.assertEqual(evidence["evidence_id"], approved["event_id"])
        self.assertEqual(evidence["block_ids"], [self.block_id])
        self.assertEqual(evidence["qualification_before_freeze"], "PAGE_LINKED_EVENT_NOT_FROZEN")
        self.assertEqual(evidence["qualification"], "FROZEN_WRITABLE")
        self.assertEqual(
            freeze["payload"]["classifications"]["PROHIBITED_CLAIM"],
            ["Do not call this a complete survey."],
        )
        with connect(self.project) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0], 0)

        approved_freeze = approve_freeze(
            self.project, freeze["freeze_id"], "Professor", "Checked event anchors and boundaries",
        )
        artifact = draft_from_freeze(self.project, approved_freeze["freeze_id"], "Event-backed draft")
        review = review_artifact(self.project, artifact["versions"][0]["version_id"])
        self.assertEqual(review["status"], "passed")

    def test_unapproved_event_cannot_enter_an_event_freeze(self) -> None:
        candidate = self._create()
        with self.assertRaisesRegex(ValueError, "not approved"):
            create_event_freeze(
                self.project,
                "Rejected pending event",
                [{"text": "Unsafe claim", "evidence": [{"event_id": candidate["event_id"]}]}],
            )

    def test_approval_refreshes_printed_page_snapshot_after_page_repair(self) -> None:
        candidate = self._create()
        page_id = f"{self.source['source_id']}:P1"
        correct_printed_page(
            self.project, page_id, "225", "Professor", "Corrected against the printed page footer",
        )
        verify_block(self.project, self.block_id, "Professor", "Exact against the source page")

        approved = decide_event(
            self.project, str(candidate["event_id"]), True,
            "Professor", "Approved after the page metadata correction",
        )

        self.assertEqual(candidate["printed_pages"], ["1"])
        self.assertEqual(approved["printed_pages"], ["225"])

    def test_quote_must_match_verified_blocks(self) -> None:
        candidate = self._create()
        verify_block(self.project, self.block_id, "Professor", "Exact against the source page")
        with self.assertRaisesRegex(ValueError, "must occur"):
            decide_event(
                self.project, str(candidate["event_id"]), True,
                "Professor", "核对原页后决定", {"original_text": "not in the source"},
            )

        with self.assertRaisesRegex(ValueError, "require case_id and original_text"):
            decide_event(
                self.project, str(candidate["event_id"]), True,
                "Professor", "核对原页后决定", {"original_text": ""},
            )

    def test_rejection_is_retained_in_event_history(self) -> None:
        candidate = self._create()
        rejected = decide_event(
            self.project, str(candidate["event_id"]), False,
            "Professor", "不符合比较口径",
        )
        self.assertEqual(rejected["status"], "rejected")
        state = event_state(self.project)
        self.assertEqual(state["counts"]["rejected"], 1)
        self.assertEqual(state["events"][0]["decision_reason"], "不符合比较口径")

    def test_coverage_uses_an_exact_case_allowlist_and_separates_other_cases(self) -> None:
        selected = self._create()
        verify_block(self.project, self.block_id, "Professor", "Exact against the source page")
        decide_event(
            self.project, str(selected["event_id"]), True,
            "Professor", "Approved selected comparison event",
        )
        other = create_event_candidates(
            self.project,
            [{
                "case_id": "Misclassified-case",
                "source_id": self.source["source_id"],
                "block_ids": [self.block_id],
                "field_anchors": {"original_text": [self.block_id]},
                "missing_reason": "Comparison fields not coded.",
            }],
            "test-model",
        )[0]
        decide_event(
            self.project, str(other["event_id"]), True,
            "Professor", "Approved but outside the selected comparison cases",
        )

        coverage = event_coverage(self.project, ["Richthofen-1871"])

        self.assertEqual(coverage["selected_approved_total"], 1)
        self.assertEqual(coverage["combined"]["fields"]["route"]["anchored"], 1)
        self.assertEqual(coverage["combined"]["fields"]["route"]["percent"], 100.0)
        self.assertEqual(coverage["combined"]["movement_cost_any"]["anchored"], 0)
        self.assertEqual(
            coverage["other_approved_cases"],
            [{"case_id": "Misclassified-case", "approved_events": 1}],
        )

    def test_event_state_can_return_a_filtered_summary_without_long_text(self) -> None:
        selected = self._create()
        verify_block(self.project, self.block_id, "Professor", "Exact against the source page")
        decide_event(
            self.project, str(selected["event_id"]), True,
            "Professor", "Approved selected comparison event",
        )
        create_event_candidates(
            self.project,
            [{
                "case_id": "Other-case",
                "source_id": self.source["source_id"],
                "block_ids": [self.block_id],
                "field_anchors": {"original_text": [self.block_id]},
            }],
            "test-model",
        )

        state = event_state(
            self.project,
            case_ids=["Richthofen-1871"],
            statuses=["approved"],
            detail="summary",
        )

        self.assertEqual(state["counts"], {"draft": 0, "approved": 1, "rejected": 0})
        self.assertEqual(state["filters"]["detail"], "summary")
        self.assertEqual(len(state["events"]), 1)
        self.assertEqual(state["events"][0]["route"], "Qinling route")
        self.assertEqual(state["events"][0]["field_anchors"]["route"], [self.block_id])
        self.assertNotIn("original_text", state["events"][0])
        self.assertNotIn("translation", state["events"][0])
        self.assertNotIn("model_snapshot", state["events"][0])

    def test_approved_event_register_exports_source_linkage_and_utf8_csv(self) -> None:
        selected = self._create()
        verify_block(self.project, self.block_id, "Professor", "Exact against the source page")
        decide_event(
            self.project, str(selected["event_id"]), True,
            "Professor", "Approved for the event register",
        )
        create_event_candidates(
            self.project,
            [{
                "case_id": "draft-case",
                "source_id": self.source["source_id"],
                "block_ids": [self.block_id],
                "field_anchors": {"original_text": [self.block_id]},
            }],
            "test-model",
        )

        result = export_event_register(self.project)
        target = self.project / result["project_path"]
        exported = target.read_text(encoding="utf-8-sig")

        self.assertEqual(result["row_count"], 1)
        self.assertTrue(target.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertIn("source_title", exported)
        self.assertIn("Test source", exported)
        self.assertIn(str(selected["event_id"]), exported)
        self.assertNotIn("draft-case", exported)

        chronicle = event_chronicle(self.project, year="1871", query="Qinling")
        self.assertEqual(chronicle["total_count"], 1)
        self.assertEqual(chronicle["entries"][0]["source_title"], "Test source")
        self.assertIn("路线：Qinling route", chronicle["entries"][0]["summary"])
        self.assertEqual(chronicle["entries"][0]["physical_pages"], [1])
        exported_chronicle = export_event_chronicle(self.project, year="1871")
        chronicle_text = (self.project / exported_chronicle["project_path"]).read_text(encoding="utf-8")
        self.assertIn("# 史料长编", chronicle_text)
        self.assertIn("Test source", chronicle_text)
        self.assertIn(str(selected["event_id"]), chronicle_text)
        self.assertNotIn("draft-case", chronicle_text)

    def test_every_source_derived_field_requires_its_own_anchors(self) -> None:
        with self.assertRaisesRegex(ValueError, "event_date requires explicit block anchors"):
            create_event_candidates(
                self.project,
                [{
                    "case_id": "Richthofen-1871", "event_date": "1871-10-01",
                    "source_id": self.source["source_id"], "block_ids": [self.block_id],
                    "original_text": "The sentence continues toward the page boundary",
                    "field_anchors": {"original_text": [self.block_id]},
                }],
                "test-model",
            )

    def test_missing_codes_cannot_masquerade_as_source_field_values(self) -> None:
        for value in ("NR", "UNC：尚不能确认", "PND（待核页）"):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "leave chinese_participants blank.*missing_reason"
            ):
                create_event_candidates(
                    self.project,
                    [{
                        "case_id": "Richthofen-1871",
                        "source_id": self.source["source_id"],
                        "block_ids": [self.block_id],
                        "chinese_participants": value,
                        "field_anchors": {
                            "chinese_participants": [self.block_id],
                            "original_text": [self.block_id],
                        },
                    }],
                    "test-model",
                )

        candidate = self._create()
        verify_block(self.project, self.block_id, "Professor", "Exact against the source page")
        with self.assertRaisesRegex(ValueError, "leave institutional_task blank.*missing_reason"):
            decide_event(
                self.project, str(candidate["event_id"]), True,
                "Professor", "尝试把缺失代码写入来源字段",
                {"institutional_task": "NR", "missing_reason": ""},
            )

    def test_original_text_can_be_copied_exactly_from_its_anchors(self) -> None:
        candidate = create_event_candidates(
            self.project,
            [{
                "case_id": "Richthofen-1871",
                "source_id": self.source["source_id"],
                "block_ids": [self.block_id],
                "field_anchors": {"original_text": [self.block_id]},
                "missing_reason": "Other fields PND in this block scope",
            }],
            "test-model",
        )[0]
        self.assertEqual(
            candidate["original_text"],
            "The sentence continues toward the page boundary",
        )

    def test_original_text_defaults_to_the_explicit_event_blocks(self) -> None:
        candidate = create_event_candidates(
            self.project,
            [{
                "case_id": "Richthofen-1871",
                "source_id": self.source["source_id"],
                "block_ids": [self.block_id],
                "missing_reason": "Other fields PND in this block scope",
            }],
            "test-model",
        )[0]
        self.assertEqual(
            candidate["original_text"],
            "The sentence continues toward the page boundary",
        )
        self.assertEqual(candidate["field_anchors"]["original_text"], [self.block_id])

    def test_one_historical_event_may_span_more_than_twelve_blocks(self) -> None:
        root = self.project.parent
        original = root / "long-event.txt"
        original.write_text("immutable long event", encoding="utf-8")
        source = register_source(self.project, original, "Long event source")
        structure = root / "long-event-structure.json"
        structure.write_text(json.dumps({
            "schema_version": 1,
            "pages": [{
                "id": "P_LONG", "physical_page": 10, "printed_page": "10", "page_type": "body",
                "blocks": [
                    {"id": f"B_LONG_{index:02d}", "order": index, "type": "paragraph",
                     "text": f"Observation segment {index}.", "region": [10, index * 10, 500, index * 10 + 8]}
                    for index in range(1, 14)
                ],
            }],
            "relations": [],
            "anomalies": [],
        }), encoding="utf-8")
        import_structure(self.project, source["source_id"], structure)
        block_ids = [f"{source['source_id']}:B_LONG_{index:02d}" for index in range(1, 14)]

        candidate = create_event_candidates(
            self.project,
            [{
                "case_id": "continuous-two-day-observation",
                "source_id": source["source_id"],
                "block_ids": block_ids,
                "field_anchors": {"original_text": block_ids},
                "missing_reason": "Other fields are outside this boundary test.",
            }],
            "test-model",
        )[0]

        self.assertEqual(candidate["block_ids"], block_ids)
        self.assertEqual(len(candidate["field_anchors"]["original_text"]), 13)

    def test_source_relative_block_ids_are_resolved_with_the_explicit_source(self) -> None:
        candidate = create_event_candidates(
            self.project,
            [{
                "case_id": "source-relative-id",
                "source_id": self.source["source_id"],
                "block_ids": ["B2"],
                "field_anchors": {"original_text": ["B2"]},
                "missing_reason": "Other fields are outside this identifier test.",
            }],
            "test-model",
        )[0]

        self.assertEqual(candidate["block_ids"], [self.block_id])
        self.assertEqual(candidate["field_anchors"]["original_text"], [self.block_id])

    def test_current_anchor_text_can_refill_a_draft_after_a_human_repair(self) -> None:
        candidate = self._create()
        initial = event_anchor_text(self.project, str(candidate["event_id"]))
        self.assertFalse(initial["changed"])

        corrected = "The sentence continues across the page boundary"
        correct_block(self.project, self.block_id, corrected, "Professor", "Checked against the page")
        refreshed = event_anchor_text(self.project, str(candidate["event_id"]))

        self.assertTrue(refreshed["changed"])
        self.assertEqual(refreshed["original_text"], corrected)
        self.assertEqual(refreshed["block_ids"], [self.block_id])

    def test_event_editor_exposes_all_approved_comparison_fields(self) -> None:
        script = (
            Path(__file__).parents[1] / "src" / "research_workbench" / "web_assets" / "app.js"
        ).read_text(encoding="utf-8")
        for field, label in (
            ("movement_mode", "移动方式"),
            ("genre", "体裁"),
            ("participant_visibility", "参与者可见度"),
            ("end_place", "行程终点"),
            ("outcome_destination", "成果/知识产出去向（非行程终点）"),
        ):
            with self.subTest(field=field):
                self.assertIn(f"{field}:'{label}'", script)
        self.assertIn("保存人工修订", script)
        self.assertIn("item.status!=='rejected'&&sourceFields.has(key)", script)
        self.assertIn("field_anchors:approved?field_anchors:undefined", script)

    def test_verified_local_block_can_approve_event_while_page_remains_open(self) -> None:
        local_original = Path(self.temporary.name) / "local-source.txt"
        local_original.write_text("separate local source", encoding="utf-8")
        local_source = register_source(self.project, local_original, "Local partial source")
        packet = Path(self.temporary.name) / "local-page.json"
        packet.write_text(json.dumps({
            "pages": [{
                "id": "P_LOCAL", "physical_page": 3, "page_type": "body",
                "blocks": [{"id": "B_LOCAL", "order": 1, "type": "paragraph", "text": "Bad OCR."}],
            }],
            "anomalies": [{
                "id": "A_LOCAL_PAGE", "scope_type": "page", "target_id": "P_LOCAL",
                "severity": "local", "category": "content", "message": "Other page content remains unchecked.",
            }],
        }), encoding="utf-8")
        import_structure(self.project, local_source["source_id"], packet)
        block_id = f"{local_source['source_id']}:B_LOCAL"
        correct_block(self.project, block_id, "Verified local text.", "Professor", "Checked against the image")
        candidate = create_event_candidates(
            self.project,
            [{
                "case_id": "Local-partial-page",
                "source_id": local_source["source_id"],
                "block_ids": [block_id],
                "field_anchors": {"original_text": [block_id]},
            }],
            "test-model",
        )[0]

        approved = decide_event(
            self.project, str(candidate["event_id"]), True,
            "Professor", "The cited block alone was checked against the page",
        )
        self.assertEqual(approved["status"], "approved")
        with connect(self.project) as connection:
            page_state = connection.execute(
                "SELECT use_state FROM pages WHERE page_id = ?",
                (f"{local_source['source_id']}:P_LOCAL",),
            ).fetchone()[0]
            anomaly_state = connection.execute(
                "SELECT status FROM anomalies WHERE anomaly_id = ?",
                (f"{local_source['source_id']}:A_LOCAL_PAGE",),
            ).fetchone()[0]
        self.assertEqual(page_state, "blocked")
        self.assertEqual(anomaly_state, "open")

    def test_approved_event_can_be_revised_with_explicit_new_field_anchors(self) -> None:
        candidate = create_event_candidates(
            self.project,
            [{
                "case_id": "Richthofen-1871",
                "source_id": self.source["source_id"],
                "block_ids": [self.block_id],
                "field_anchors": {"original_text": [self.block_id]},
                "missing_reason": "Comparison fields were not yet coded.",
            }],
            "test-model",
        )[0]
        verify_block(self.project, self.block_id, "Professor", "Exact against the source page")
        decide_event(
            self.project, str(candidate["event_id"]), True,
            "Professor", "Initial page-linked approval",
        )

        with self.assertRaisesRegex(ValueError, "movement_mode requires explicit block anchors"):
            decide_event(
                self.project, str(candidate["event_id"]), True,
                "Professor", "Attempted unanchored backfill", {"movement_mode": "on foot"},
            )

        revised = decide_event(
            self.project, str(candidate["event_id"]), True,
            "Professor", "Backfilled against the already verified block",
            {"movement_mode": "on foot"}, {"movement_mode": [self.block_id]},
        )
        self.assertEqual(revised["status"], "approved")
        self.assertEqual(revised["movement_mode"], "on foot")
        self.assertEqual(revised["field_anchors"]["movement_mode"], [self.block_id])
        with connect(self.project) as connection:
            audit = connection.execute(
                """SELECT event_type, payload_json FROM audit_events
                   WHERE entity_id = ? ORDER BY event_id DESC LIMIT 1""",
                (candidate["event_id"],),
            ).fetchone()
        self.assertEqual(audit["event_type"], "research_event_revised")
        self.assertEqual(json.loads(audit["payload_json"])["edited_fields"], ["movement_mode"])


if __name__ == "__main__":
    unittest.main()
