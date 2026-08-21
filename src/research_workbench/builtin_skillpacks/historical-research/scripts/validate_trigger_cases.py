#!/usr/bin/env python3
"""Validate the static positive and negative routing evaluation set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", type=Path)
    parser.add_argument("skills_dir", type=Path)
    args = parser.parse_args()
    data = json.loads(args.cases.read_text(encoding="utf-8-sig"))
    installed = {p.name for p in args.skills_dir.iterdir() if p.is_dir()}
    errors: list[str] = []
    ids: set[str] = set()
    covered: set[str] = set()
    negative = 0
    for case in data.get("cases", []):
        cid = case.get("id", "")
        if not cid or cid in ids:
            errors.append(f"invalid or duplicate case id: {cid}")
        ids.add(cid)
        expected = set(case.get("expected", []))
        unknown = expected - installed
        if unknown:
            errors.append(f"{cid}: unknown skills {sorted(unknown)}")
        if expected:
            covered.update(expected)
        else:
            negative += 1
        if not case.get("prompt", "").strip():
            errors.append(f"{cid}: empty prompt")
    missing = installed - covered
    if missing:
        errors.append(f"skills without a positive case: {sorted(missing)}")
    if negative < 5:
        errors.append("at least five negative isolation cases are required")
    print(json.dumps({"valid": not errors, "cases": len(ids), "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
