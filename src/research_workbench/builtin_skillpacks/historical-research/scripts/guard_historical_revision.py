#!/usr/bin/env python3
"""Check protected literals, footnotes, and media across a DOCX revision."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path


TEXT_RE = re.compile(rb"<w:t(?:\s[^>]*)?>(.*?)</w:t>", re.DOTALL)


def xml_text(data: bytes) -> str:
    parts = TEXT_RE.findall(data)
    return b"".join(parts).decode("utf-8", errors="replace")


def docx_data(path: Path) -> tuple[str, str, dict[str, str]]:
    with zipfile.ZipFile(path) as archive:
        document = xml_text(archive.read("word/document.xml"))
        footnotes = xml_text(archive.read("word/footnotes.xml")) if "word/footnotes.xml" in archive.namelist() else ""
        media = {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist()
            if name.startswith("word/media/")
        }
    return document, footnotes, media


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("revised", type=Path)
    parser.add_argument("protection_file", type=Path)
    parser.add_argument("--require-same-footnotes", action="store_true")
    parser.add_argument("--require-same-media", action="store_true")
    args = parser.parse_args()

    protection = json.loads(args.protection_file.read_text(encoding="utf-8-sig"))
    before, before_notes, before_media = docx_data(args.baseline)
    after, after_notes, after_media = docx_data(args.revised)
    errors: list[str] = []
    for literal in protection.get("protected_literals", []):
        if before.count(literal) != after.count(literal):
            errors.append(f"protected literal count changed: {literal}")
    if args.require_same_footnotes and before_notes != after_notes:
        errors.append("footnote text changed")
    if args.require_same_media and before_media != after_media:
        errors.append("embedded media changed")
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
