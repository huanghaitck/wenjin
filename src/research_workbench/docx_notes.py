from __future__ import annotations

import re
import tempfile
import zipfile
from pathlib import Path

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
FOOTNOTE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes"
FOOTNOTE_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"


def add_footnote_reference(paragraph, note_number: int) -> None:
    run = paragraph.add_run()
    reference = OxmlElement("w:footnoteReference")
    reference.set(qn("w:id"), str(note_number))
    run._r.append(reference)


def _xml(root) -> bytes:
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone="yes")


def _footnotes(notes: list[str]) -> bytes:
    root = etree.Element(f"{{{W}}}footnotes", nsmap={"w": W, "r": R})
    for note_id, element_name in (("-1", "separator"), ("0", "continuationSeparator")):
        note = etree.SubElement(root, f"{{{W}}}footnote")
        note.set(f"{{{W}}}id", note_id)
        run = etree.SubElement(etree.SubElement(note, f"{{{W}}}p"), f"{{{W}}}r")
        etree.SubElement(run, f"{{{W}}}{element_name}")
    for number, text in enumerate(notes, start=1):
        note = etree.SubElement(root, f"{{{W}}}footnote")
        note.set(f"{{{W}}}id", str(number))
        paragraph = etree.SubElement(note, f"{{{W}}}p")
        marker_run = etree.SubElement(paragraph, f"{{{W}}}r")
        etree.SubElement(marker_run, f"{{{W}}}footnoteRef")
        text_run = etree.SubElement(paragraph, f"{{{W}}}r")
        properties = etree.SubElement(text_run, f"{{{W}}}rPr")
        etree.SubElement(properties, f"{{{W}}}rFonts", {
            f"{{{W}}}ascii": "FangSong", f"{{{W}}}hAnsi": "FangSong", f"{{{W}}}eastAsia": "仿宋",
        })
        etree.SubElement(properties, f"{{{W}}}sz", {f"{{{W}}}val": "21"})
        value = etree.SubElement(text_run, f"{{{W}}}t")
        value.text = " " + text
    return _xml(root)


def attach_footnotes(path: Path, notes: list[str], restart_each_page: bool = True) -> None:
    if not notes:
        return
    with tempfile.NamedTemporaryFile(suffix=".docx", dir=path.parent, delete=False) as temporary:
        target = Path(temporary.name)
    try:
        with zipfile.ZipFile(path, "r") as source:
            content_types = etree.fromstring(source.read("[Content_Types].xml"))
            if not content_types.xpath("./ct:Override[@PartName='/word/footnotes.xml']", namespaces={"ct": CT}):
                override = etree.SubElement(content_types, f"{{{CT}}}Override")
                override.set("PartName", "/word/footnotes.xml")
                override.set("ContentType", FOOTNOTE_CT)

            relationships = etree.fromstring(source.read("word/_rels/document.xml.rels"))
            if not relationships.xpath("./r:Relationship[@Type=$kind]", namespaces={"r": PKG_REL}, kind=FOOTNOTE_REL):
                numbers = [int(match.group(1)) for node in relationships
                           if (match := re.fullmatch(r"rId(\d+)", node.get("Id", "")))]
                relation = etree.SubElement(relationships, f"{{{PKG_REL}}}Relationship")
                relation.set("Id", f"rId{max(numbers, default=0) + 1}")
                relation.set("Type", FOOTNOTE_REL)
                relation.set("Target", "footnotes.xml")

            document = etree.fromstring(source.read("word/document.xml"))
            if restart_each_page:
                for section in document.xpath(".//w:sectPr", namespaces={"w": W}):
                    properties = section.find(f"{{{W}}}footnotePr")
                    if properties is None:
                        properties = etree.Element(f"{{{W}}}footnotePr")
                        section.insert(0, properties)
                    restart = properties.find(f"{{{W}}}numRestart")
                    if restart is None:
                        restart = etree.SubElement(properties, f"{{{W}}}numRestart")
                    restart.set(f"{{{W}}}val", "eachPage")

            overrides = {
                "[Content_Types].xml": _xml(content_types),
                "word/_rels/document.xml.rels": _xml(relationships),
                "word/document.xml": _xml(document),
                "word/footnotes.xml": _footnotes(notes),
            }
            existing = set(source.namelist())
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as output:
                for item in source.infolist():
                    output.writestr(item, overrides.get(item.filename, source.read(item.filename)))
                for name, data in overrides.items():
                    if name not in existing:
                        output.writestr(name, data)
        target.replace(path)
    finally:
        target.unlink(missing_ok=True)
