#!/usr/bin/env python3
"""Validate bounded historical-search and acquisition records."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


REQUIRED = {
    "search_id", "trigger", "query", "language", "provider", "provider_type",
    "source_scope", "search_date", "result_rank", "title", "author", "year",
    "identifier", "result_url", "open_copy_url", "access_state",
    "acquisition_status", "local_path", "http_status", "rights_or_license",
    "relevance_reason", "expected_claim", "negative_result", "stop_condition",
    "user_action", "status", "notes",
}
PROVIDER_TYPES = {"LOCAL", "OPEN_API", "PUBLIC_WEB", "DISCOVERY_INDEX", "RESTRICTED_DATABASE", "OTHER"}
ACCESS_STATES = {
    "OPEN_FULLTEXT", "OPEN_WEB_TEXT", "METADATA_ONLY", "AUTH_REQUIRED",
    "INSTITUTIONAL_ACCESS_REQUIRED", "PAYWALLED", "CAPTCHA_OR_READER_BLOCKED",
    "OPEN_COPY_NOT_FOUND", "USER_SELECTION_REQUIRED", "UNKNOWN",
}
ACQUISITION = {"NOT_ATTEMPTED", "DOWNLOADED_UNVERIFIED", "FILE_VERIFIED", "FAILED", "NOT_APPLICABLE"}
STATUS = {"ACTIVE", "STOPPED", "RESOLVED", "DEFERRED", "REJECTED"}


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
            sid = row["search_id"].strip()
            if not sid:
                errors.append(f"line {line}: search_id is empty")
            elif sid in seen:
                errors.append(f"line {line}: duplicate search_id {sid}")
            seen.add(sid)
            if row["provider_type"] not in PROVIDER_TYPES:
                errors.append(f"line {line}: invalid provider_type")
            if row["access_state"] not in ACCESS_STATES:
                errors.append(f"line {line}: invalid access_state")
            if row["acquisition_status"] not in ACQUISITION:
                errors.append(f"line {line}: invalid acquisition_status")
            if row["status"] not in STATUS:
                errors.append(f"line {line}: invalid status")
            if row["acquisition_status"] == "FILE_VERIFIED" and not row["local_path"].strip():
                errors.append(f"line {line}: verified file lacks local_path")
            if row["access_state"] == "USER_SELECTION_REQUIRED" and not row["user_action"].strip():
                errors.append(f"line {line}: user selection lacks requested action")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("search_log", type=Path)
    args = parser.parse_args()
    try:
        errors = validate(args.search_log)
    except Exception as exc:
        errors = [str(exc)]
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
