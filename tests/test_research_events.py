from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from research_workbench.research_events import (
    create_event_candidates,
    decide_event,
    event_anchor_text,
    event_state,
)
from research_workbench.service import (
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
                    "institutional_task": [self.block_id],
                    "original_text": [self.block_id],
                },
                "original_text": "The sentence continues toward the page boundary",
                "route": "Qinling route",
                "investigation_object": "road",
                "recording_technique": "diary observation",
                "institutional_task": "journey record",
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


if __name__ == "__main__":
    unittest.main()
