from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from research_workbench.backups import backup_project, list_backups, restore_backup
from research_workbench.service import initialize_project


class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "workspace" / "projects" / "original"
        initialize_project(self.project, "可恢复项目")
        self.backups = self.root / "backups"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_online_backup_is_integrity_checked_and_unchanged_run_is_deduplicated(self) -> None:
        first = backup_project(self.project, self.backups, "test")
        second = backup_project(self.project, self.backups, "test")
        self.assertEqual(first["backup_id"], second["backup_id"])
        self.assertEqual(second["status"], "unchanged")
        self.assertEqual(len(list_backups(self.backups)), 1)

    def test_restore_creates_a_new_project_without_overwriting_original(self) -> None:
        backup = backup_project(self.project, self.backups, "test")
        restored = restore_backup(self.backups, self.root / "workspace", backup["backup_id"])
        restored_root = Path(restored["restored_project_root"])
        self.assertNotEqual(restored_root, self.project)
        self.assertTrue((restored_root / "project.sqlite3").is_file())
        self.assertTrue((self.project / "project.sqlite3").is_file())


if __name__ == "__main__":
    unittest.main()
