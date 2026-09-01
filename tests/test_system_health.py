from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_workbench.service import initialize_project
from research_workbench.system_health import diagnose_system, repair_system


class SystemHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.config = self.root / "config"
        initialize_project(self.project, "system health")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_diagnosis_is_read_only_and_reports_integrity(self) -> None:
        before = (self.project / "project.sqlite3").read_bytes()
        with patch("research_workbench.system_health.runtime_status", return_value={"wenjin_backend": {"available": True}}), patch(
            "research_workbench.system_health.plugin_state", return_value={"count": 0, "plugins": []}
        ):
            result = diagnose_system(self.project, self.config)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["project_database"]["status"], "ok")
        self.assertEqual((self.project / "project.sqlite3").read_bytes(), before)

    def test_safe_repair_backs_up_then_repairs_recorded_plugin_only(self) -> None:
        source = self.root / "plugin.zip"
        source.write_bytes(b"package")
        broken = {"name": "sample", "status": "runtime_missing", "package_changed": False, "source_path": str(source)}
        healthy = {"name": "healthy", "status": "ready", "package_changed": False, "source_path": str(source)}
        with patch("research_workbench.system_health.runtime_status", return_value={}), patch(
            "research_workbench.system_health.plugin_state", side_effect=[{"plugins": [broken, healthy]}, {"plugins": [healthy]}]
        ), patch("research_workbench.system_health.repair_domain_plugin") as repair:
            result = repair_system(self.project, self.config)
        repair.assert_called_once_with(self.config, "sample")
        self.assertEqual(result["repaired_plugins"], ["sample"])
        self.assertTrue(result["backup_id"].startswith("BKP_"))


if __name__ == "__main__":
    unittest.main()
