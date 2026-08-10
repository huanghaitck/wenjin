from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document

from research_workbench.authoring import import_manuscript
from research_workbench.desktop_runtime import bootstrap_desktop
from research_workbench.document_model import ensure_document, reimport_docx
from research_workbench.model_settings import public_settings, save_role
from research_workbench.service import initialize_project


class D5DesktopPackagingTests(unittest.TestCase):
    def test_first_run_creates_stable_local_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = bootstrap_desktop(Path(directory))
            second = bootstrap_desktop(Path(directory))
            self.assertEqual(first["project_root"], second["project_root"])
            self.assertTrue((Path(first["project_root"]) / "project.sqlite3").is_file())
            self.assertTrue((Path(first["workspace_root"]) / "workspace.json").is_file())
            self.assertTrue(Path(first["library_root"]).is_dir())

    def test_ollama_role_settings_are_applied_without_a_secret_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=False):
            root = Path(directory)
            result = save_role(root, "main_reasoning", {
                "provider": "ollama", "model": "local-history-model",
                "base_url": "http://127.0.0.1:11434", "timeout_seconds": 120,
            })
            text = (root / "model-settings.json").read_text(encoding="utf-8")
            self.assertNotIn("api_key", text.lower())
            self.assertEqual(os.environ["HRW_AGENT_MODEL"], "local-history-model")
            self.assertEqual(os.environ["HRW_AGENT_BASE_URL"], "http://127.0.0.1:11434")
            self.assertEqual(len(result["roles"]), 3)
            self.assertEqual(public_settings(root)["credential_backend"], "windows_credential_manager")

    def test_word_reimport_creates_a_new_revision_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            initialize_project(project, "Word 往返测试")
            manuscript = import_manuscript(project, "测试稿", "# 导言\n\n原始段落。")
            before = ensure_document(project, manuscript["manuscript_id"])
            word = Document()
            word.add_heading("导言", level=1)
            word.add_paragraph("在 Microsoft Word 中人工修改后的段落。")
            payload = io.BytesIO()
            word.save(payload)
            after = reimport_docx(project, manuscript["manuscript_id"], payload.getvalue())
            self.assertNotEqual(before["current_revision_id"], after["current_revision_id"])
            self.assertEqual(after["revisions"][0]["source_format"], "docx_reimport")
            self.assertIn("人工修改", after["document"]["children"][0]["children"][0]["text"])
            self.assertGreaterEqual(len(after["revisions"]), 2)

    def test_ui_exposes_desktop_word_and_model_bridges(self) -> None:
        root = Path(__file__).parents[1] / "src" / "research_workbench" / "web_assets"
        html = (root / "index.html").read_text(encoding="utf-8")
        script = (root / "app.js").read_text(encoding="utf-8")
        for identifier in ("chooseFolder", "choosePdf", "chooseDocx", "openInWord", "reimportWord"):
            self.assertIn(f'id="{identifier}"', html)
        self.assertIn("/api/model-settings/save", script)
        self.assertIn("Windows 凭据管理器", script)

    def test_desktop_sidecar_bundles_https_runtime(self) -> None:
        build_script = (Path(__file__).parents[1] / "scripts" / "build_desktop.ps1").read_text(encoding="utf-8")
        self.assertIn("libssl-3-x64.dll", build_script)
        self.assertIn("libcrypto-3-x64.dll", build_script)
        self.assertIn("--collect-data certifi", build_script)


if __name__ == "__main__":
    unittest.main()
