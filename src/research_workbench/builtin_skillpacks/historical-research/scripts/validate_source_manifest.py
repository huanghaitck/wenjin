#!/usr/bin/env python3
"""Validate a CSV source manifest and its evidence-state invariants."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


REQUIRED = {
    "source_id", "path_or_url", "sha256", "bytes", "pages", "author", "title",
    "version", "date", "language", "source_type", "carrier", "text_layer",
    "witness_relation", "rights_scope", "reading_status", "verification_status",
    "citable", "notes",
}
READING = {"NOT_READ", "METADATA_READ", "TARGETED_READ", "FULL_READ"}
VERIFY = {"DISCOVERED", "ACQUIRED_UNVERIFIED", "FILE_VERIFIED", "PAGE_VERIFIED", "CITABLE"}
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def validate(path: Path) -> list[str]:
    errors: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing = sorted(REQUIRED - fields)
        if missing:
            return ["missing columns: " + ", ".join(missing)]
        seen: set[str] = set()
        for line, row in enumerate(reader, 2):
            sid = row["source_id"].strip()
            if not sid:
                errors.append(f"line {line}: source_id is empty")
            elif sid in seen:
                errors.append(f"line {line}: duplicate source_id {sid}")
            seen.add(sid)
            if row["reading_status"] not in READING:
                errors.append(f"line {line}: invalid reading_status")
            if row["verification_status"] not in VERIFY:
                errors.append(f"line {line}: invalid verification_status")
            if row["sha256"] and not SHA256.fullmatch(row["sha256"]):
                errors.append(f"line {line}: sha256 must contain 64 hexadecimal characters")
            if row["citable"].lower() not in {"true", "false"}:
                errors.append(f"line {line}: citable must be true or false")
            if row["citable"].lower() == "true":
                if row["verification_status"] not in {"PAGE_VERIFIED", "CITABLE"}:
                    errors.append(f"line {line}: citable source is not page verified")
                if row["reading_status"] not in {"TARGETED_READ", "FULL_READ"}:
                    errors.append(f"line {line}: citable source has not been substantively read")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        errors = validate(args.manifest)
    except Exception as exc:
        errors = [str(exc)]
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
