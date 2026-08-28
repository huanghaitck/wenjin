#!/usr/bin/env python3
"""Validate claim-to-citation mappings before evidence freeze or submission."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


REQUIRED = {
    "claim_id", "claim_text", "claim_strength", "evidence_id", "source_id",
    "source_role", "original_page", "digital_page", "locator_verified",
    "witness_independence", "supports", "does_not_support", "citation_full",
    "citation_short", "status", "notes",
}
STRENGTH = {"DESCRIPTIVE", "INTERPRETIVE", "CAUSAL", "COMPARATIVE"}
STATUS = {"DRAFT", "NEEDS_REVIEW", "VERIFIED", "FROZEN", "REJECTED"}


def validate(path: Path) -> list[str]:
    errors: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing = sorted(REQUIRED - fields)
        if missing:
            return ["missing columns: " + ", ".join(missing)]
        seen: set[tuple[str, str]] = set()
        for line, row in enumerate(reader, 2):
            key = (row["claim_id"].strip(), row["evidence_id"].strip())
            if not all(key):
                errors.append(f"line {line}: claim_id and evidence_id are required")
            elif key in seen:
                errors.append(f"line {line}: duplicate claim/evidence pair {key}")
            seen.add(key)
            if row["claim_strength"] not in STRENGTH:
                errors.append(f"line {line}: invalid claim_strength")
            if row["status"] not in STATUS:
                errors.append(f"line {line}: invalid status")
            if row["locator_verified"].lower() not in {"true", "false"}:
                errors.append(f"line {line}: locator_verified must be true or false")
            if row["status"] in {"VERIFIED", "FROZEN"}:
                if row["locator_verified"].lower() != "true":
                    errors.append(f"line {line}: verified or frozen claim lacks a verified locator")
                if not row["citation_full"].strip():
                    errors.append(f"line {line}: verified or frozen claim lacks a full citation")
                if not row["supports"].strip() or not row["does_not_support"].strip():
                    errors.append(f"line {line}: evidence boundary is incomplete")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("claim_map", type=Path)
    args = parser.parse_args()
    try:
        errors = validate(args.claim_map)
    except Exception as exc:
        errors = [str(exc)]
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
