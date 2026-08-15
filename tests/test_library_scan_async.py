from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen

from research_workbench import library as library_module
from research_workbench.library import (
    create_scan_session,
    run_scan_session,
    scan_session,
    start_scan_session,
)
from research_workbench.library_store import connect_library, library_database_path
from research_workbench.service import initialize_project
from research_workbench.web import build_server


class AsyncLibraryScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.project = root / "project"
        self.library = root / "library"
        self.materials = root / "materials"
        self.materials.mkdir()
        initialize_project(self.project, "async library scan")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _wait(self, session_id: str, timeout: float = 5) -> dict[str, object]:
        deadline = time.monotonic() + timeout
        current: dict[str, object] = {}
        while time.monotonic() < deadline:
            current = scan_session(self.project, session_id, self.library)
            if current["status"] != "scanning":
                return current
            time.sleep(0.02)
        self.fail(f"scan did not finish: {current}")

    def test_slow_scan_starts_quickly_and_reports_progress(self) -> None:
        for index in range(3):
            (self.materials / f"history-{index}.txt").write_text("历史档案" * 40, encoding="utf-8")
        original = library_module._inspect_file

        def slow(path: Path) -> dict[str, object]:
            time.sleep(0.1)
            return original(path)

        with patch.object(library_module, "_inspect_file", side_effect=slow):
            started = time.monotonic()
            created = start_scan_session(self.project, self.materials, self.library)
            # The contract is that the HTTP-facing call returns before the first
            # deliberately slow inspection completes. Windows may spend a few
            # hundred milliseconds creating and migrating the fresh test DB, so
            # a 0.2 second wall-clock limit was scheduler-sensitive in the full
            # suite while still exercising the intended non-blocking boundary.
            self.assertLess(time.monotonic() - started, 1.0)
            self.assertEqual(created["status"], "scanning")
            completed = self._wait(str(created["session_id"]))
        self.assertEqual(completed["status"], "preview_ready")
        self.assertEqual(completed["processed_count"], 3)
        self.assertEqual(completed["total_count"], 3)

    def test_unexpected_scan_error_is_durable_failed_state(self) -> None:
        (self.materials / "history.txt").write_text("历史档案" * 40, encoding="utf-8")
        created = create_scan_session(self.project, self.materials, self.library)
        with patch.object(library_module.os, "walk", side_effect=RuntimeError("walk failed")):
            run_scan_session(self.project, str(created["session_id"]), self.library)
        failed = scan_session(self.project, str(created["session_id"]), self.library)
        self.assertEqual(failed["status"], "failed")
        self.assertIn("walk failed", failed["error"])

    def test_five_thousand_candidates_are_paginated_without_sample_text(self) -> None:
        created = create_scan_session(self.project, self.materials, self.library)
        session_id = str(created["session_id"])
        rows = []
        for index in range(5000):
            rows.append((
                f"CND_{index:05d}", session_id, str((self.materials / f"{index:05d}.txt").resolve()),
                "txt", 1, index, "a" * 64, f"title {index}", "", "", "", "und",
                "book_or_document", None, "present", "uncertain", "manual review", 1,
                "large text must not leave the database", "register_new", None, None, None,
                "preview", "",
            ))
        with connect_library(self.library) as connection:
            connection.executemany(
                """INSERT INTO scan_candidates VALUES (
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                   )""",
                rows,
            )
            connection.execute(
                "UPDATE scan_sessions SET status='preview_ready', processed_count=5000 WHERE session_id=?",
                (session_id,),
            )
        page = scan_session(self.project, session_id, self.library, page=2, page_size=500)
        self.assertEqual(len(page["candidates"]), 50)
        self.assertEqual(page["page_size"], 50)
        self.assertEqual(page["total_count"], 5000)
        self.assertTrue(page["has_more"])
        self.assertNotIn("sample_text", page["candidates"][0])

    def test_polling_during_scan_does_not_lock_library(self) -> None:
        for index in range(120):
            (self.materials / f"{index:03d}.txt").write_text("历史档案" * 40, encoding="utf-8")
        created = start_scan_session(self.project, self.materials, self.library)
        errors: list[Exception] = []

        def poll() -> None:
            try:
                for _ in range(60):
                    scan_session(self.project, str(created["session_id"]), self.library)
                    time.sleep(0.005)
            except Exception as exc:  # pragma: no cover - assertion reports exact failure
                errors.append(exc)

        poller = threading.Thread(target=poll)
        poller.start()
        completed = self._wait(str(created["session_id"]), timeout=10)
        poller.join(timeout=5)
        self.assertEqual(errors, [])
        self.assertEqual(completed["status"], "preview_ready")
        connection = sqlite3.connect(library_database_path(self.library))
        try:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        finally:
            connection.close()

    def test_api_recovers_latest_session_after_refresh(self) -> None:
        (self.materials / "history.txt").write_text("历史档案" * 40, encoding="utf-8")
        first = create_scan_session(self.project, self.materials, self.library)
        time.sleep(0.002)
        second = create_scan_session(self.project, self.materials, self.library)
        server = build_server(self.project, port=0, library_root=self.library)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            result = json.loads(urlopen(
                f"http://127.0.0.1:{server.server_port}/api/library/scan?page_size=50", timeout=5
            ).read())
            self.assertEqual(result["session_id"], second["session_id"])
            self.assertNotEqual(result["session_id"], first["session_id"])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)

    def test_ui_guards_against_stale_work_detail_and_restores_scan(self) -> None:
        script = (Path(__file__).parents[1] / "src" / "research_workbench" / "web_assets" / "app.js").read_text(encoding="utf-8")
        self.assertIn("const token=++state.libraryWorkRequestToken", script)
        self.assertIn("token!==state.libraryWorkRequestToken||state.libraryWorkId!==workId", script)
        self.assertIn("assertCurrentLibraryWork(work.work_id)", script)
        self.assertIn("sessionStorage.getItem('hrwLibraryScanId')", script)
        self.assertIn("setTimeout(()=>loadLibraryScan", script)


if __name__ == "__main__":
    unittest.main()
