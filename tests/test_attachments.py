from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from research_workbench.agent_runtime import create_thread
from research_workbench.attachments import get_attachment, inspect_attachment, save_attachment
from research_workbench.library import library_assets, library_status, search_library
from research_workbench.service import initialize_project


class AttachmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        initialize_project(self.project, "attachments")
        self.thread = create_thread(self.project, "chat")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_text_attachment_is_versioned_and_readable_without_becoming_evidence(self) -> None:
        record = save_attachment(
            self.project, self.thread["thread_id"], "notes.txt", "source notes".encode(),
        )
        self.assertTrue((self.project / record["project_path"]).is_file())
        self.assertEqual(get_attachment(self.project, record["attachment_id"])["sha256"], record["sha256"])
        inspected = inspect_attachment(self.project, record["attachment_id"])
        self.assertEqual(inspected["kind"], "text")
        self.assertEqual(inspected["preview"], "source notes")

    def test_spreadsheet_attachment_gets_a_bounded_preview(self) -> None:
        path = self.project / "sample.xlsx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("xl/workbook.xml", '<workbook xmlns="x"><sheets><sheet name="Sheet" xmlns:r="r" r:id="rId1"/></sheets></workbook>')
            archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
            archive.writestr("xl/worksheets/sheet1.xml", '<worksheet><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>year</t></is></c><c r="B1" t="inlineStr"><is><t>place</t></is></c></row><row r="2"><c r="A2"><v>1831</v></c><c r="B2" t="inlineStr"><is><t>万载县</t></is></c></row></sheetData></worksheet>')
        record = save_attachment(
            self.project, self.thread["thread_id"], path.name, path.read_bytes(),
        )
        inspected = inspect_attachment(self.project, record["attachment_id"])
        self.assertEqual(inspected["kind"], "spreadsheet")
        self.assertEqual(inspected["sheets"][0]["rows"][1], ["1831", "万载县"])

    def test_unknown_thread_is_rejected_before_writing(self) -> None:
        with self.assertRaises(KeyError):
            save_attachment(self.project, "THR_missing", "notes.txt", b"data")
        self.assertFalse((self.project / "attachments").exists())

    def test_chat_upload_is_archived_once_by_hash_in_the_library(self) -> None:
        library = Path(self.temporary.name) / "library"
        first = save_attachment(
            self.project, self.thread["thread_id"], "notes.txt", b"same source", library,
        )
        second = save_attachment(
            self.project, self.thread["thread_id"], "renamed.txt", b"same source", library,
        )
        self.assertEqual(first["project_path"], second["project_path"])
        self.assertEqual(first["library_work_id"], second["library_work_id"])
        self.assertEqual(library_status(self.project, library)["counts"]["works"], 1)
        works = search_library(self.project, library_root=library)
        self.assertEqual(len(works), 1)
        self.assertEqual(works[0]["canonical_title"], "notes")
        self.assertEqual(len(list((library / "uploads").rglob("*.txt"))), 1)

    def test_library_separates_maps_and_images_without_new_databases(self) -> None:
        library = Path(self.temporary.name) / "library-assets"
        save_attachment(self.project, self.thread["thread_id"], "counties.geojson", b'{"type":"FeatureCollection","features":[]}', library)
        save_attachment(self.project, self.thread["thread_id"], "秦岭地图.png", b"not-a-decoded-map", library)
        save_attachment(self.project, self.thread["thread_id"], "page.png", b"not-a-decoded-image", library)
        self.assertEqual({item["canonical_title"] for item in library_assets(self.project, "maps", library)}, {"counties", "秦岭地图"})
        self.assertEqual(library_assets(self.project, "images", library)[0]["canonical_title"], "page")


if __name__ == "__main__":
    unittest.main()
