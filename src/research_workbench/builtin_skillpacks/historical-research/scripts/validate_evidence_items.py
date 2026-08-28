#!/usr/bin/env python3
"""Validate page-anchored historical evidence items."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


REQUIRED = {
    "evidence_id", "source_id", "witness_id", "independence_group", "content_type",
    "locator_type", "original_page", "digital_page", "anchor", "excerpt_or_description",
    "context_scope", "material_statement", "author_interpretation", "researcher_inference",
    "supports", "does_not_support", "contradicts", "verification_status", "verified_by",
    "verified_at", "notes",
}
CONTENT_TYPES = {"TEXT", "ARCHIVAL_PAGE", "MAP", "IMAGE", "TABLE", "MATERIAL_OBJECT", "OTHER"}
VERIFY = {"DRAFT", "TARGETED_READ", "PAGE_VERIFIED", "CITABLE", "REJECTED"}


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
            eid = row["evidence_id"].strip()
            if not eid:
                errors.append(f"line {line}: evidence_id is empty")
            elif eid in seen:
                errors.append(f"line {line}: duplicate evidence_id {eid}")
            seen.add(eid)
            if not row["source_id"].strip():
                errors.append(f"line {line}: source_id is empty")
            if row["content_type"] not in CONTENT_TYPES:
                errors.append(f"line {line}: invalid content_type")
            if row["verification_status"] not in VERIFY:
                errors.append(f"line {line}: invalid verification_status")
            if row["verification_status"] in {"PAGE_VERIFIED", "CITABLE"}:
                if not any(row[field].strip() for field in ("original_page", "digital_page", "anchor")):
                    errors.append(f"line {line}: verified evidence lacks locator")
                if not row["supports"].strip() or not row["does_not_support"].strip():
                    errors.append(f"line {line}: verified evidence boundary is incomplete")
                if not row["verified_by"].strip() or not row["verified_at"].strip():
                    errors.append(f"line {line}: verified evidence lacks audit identity or date")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_items", type=Path)
    args = parser.parse_args()
    try:
        errors = validate(args.evidence_items)
    except Exception as exc:
        errors = [str(exc)]
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
