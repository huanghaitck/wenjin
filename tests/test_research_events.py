from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from research_workbench.research_events import (
    create_event_candidates,
    decide_event,
    event_state,
)
from research_workbench.service import (
    import_structure,
    initialize_project,
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
                    "chinese_participants": [self.block_id],
                    "institutional_task": [self.block_id],
                    "original_text": [self.block_id],
                },
                "original_text": "The sentence continues toward the page boundary",
                "route": "Qinling route",
                "investigation_object": "road",
                "recording_technique": "diary observation",
                "chinese_participants": "PND",
                "institutional_task": "journey record",
            }],
            "test-model",
            model_snapshot={"model": "test-model"},
        )[0]

    def test_candidate_requires_page_verification_before_approval(self) -> None:
        candidate = self._create()
        self.assertEqual(candidate["status"], "draft")
        self.assertEqual(candidate["qualification"], "PAGE_LINKED_EVENT_NOT_FROZEN")
        self.assertEqual(candidate["field_anchors"]["original_text"], [self.block_id])
        with self.assertRaisesRegex(ValueError, "human verification"):
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


if __name__ == "__main__":
    unittest.main()
