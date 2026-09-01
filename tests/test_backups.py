from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from research_workbench.backups import backup_existing_projects, backup_project, list_backups, restore_backup
from research_workbench.workspace import initialize_workspace
from research_workbench.service import initialize_project


class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "workspace" / "projects" / "original"
        initialize_project(self.project, "可恢复项目")
        (self.project / "research" / "notes").mkdir(parents=True)
        (self.project / "research" / "notes" / "note.md").write_text("项目札记", encoding="utf-8")
        self.backups = self.root / "backups"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_online_backup_is_integrity_checked_and_unchanged_run_is_deduplicated(self) -> None:
        runtime = self.project / "runtime" / "codex_home" / "thread-writer-locks"
        runtime.mkdir(parents=True)
        (runtime / "active.lock").write_text("ephemeral", encoding="utf-8")
        first = backup_project(self.project, self.backups, "test")
        second = backup_project(self.project, self.backups, "test")
        self.assertEqual(first["backup_id"], second["backup_id"])
        self.assertEqual(second["status"], "unchanged")
        self.assertEqual(len(list_backups(self.backups)), 1)
        with zipfile.ZipFile(first["project_archive_path"]) as archive:
            self.assertNotIn("runtime/codex_home/thread-writer-locks/active.lock", archive.namelist())

    def test_restore_creates_a_new_project_without_overwriting_original(self) -> None:
        backup = backup_project(self.project, self.backups, "test")
        restored = restore_backup(self.backups, self.root / "workspace", backup["backup_id"])
        restored_root = Path(restored["restored_project_root"])
        self.assertNotEqual(restored_root, self.project)
        self.assertTrue((restored_root / "project.sqlite3").is_file())
        self.assertTrue((self.project / "project.sqlite3").is_file())
        self.assertEqual(
            (restored_root / "research" / "notes" / "note.md").read_text(encoding="utf-8"),
            "项目札记",
        )

    def test_startup_backup_includes_projects_registered_outside_the_default_workspace(self) -> None:
        data_root = self.root / "data"
        external = self.root / "external-project"
        initialize_project(external, "外置项目")
        initialize_workspace(data_root / "workspace", external)
        result = backup_existing_projects(data_root, "startup-test")
        self.assertFalse(result["failures"])
        self.assertEqual(len(result["receipts"]), 1)
        self.assertEqual(result["receipts"][0]["source_project_root"], str(external.resolve()))
        self.assertTrue(Path(result["receipts"][0]["project_archive_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
