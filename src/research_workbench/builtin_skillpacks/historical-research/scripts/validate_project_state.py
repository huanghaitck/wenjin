#!/usr/bin/env python3
"""Validate the top-level fields of a historical-research project state file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED = {
    "schema_version",
    "project_type",
    "mode",
    "title",
    "language",
    "citation_style",
    "source_roots",
    "memory_backend",
    "current_stage",
    "full_workflow_authorized",
    "multi_agent_authorized",
    "stop_gate",
}


def scalar(value: str):
    value = value.strip()
    if value in {"true", "false"}:
        return value == "true"
    if value == "[]":
        return []
    if value.startswith(('"', "'")) and value.endswith(('"', "'")):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value


def load_state(path: Path) -> dict:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8-sig"))
    result: dict = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if raw[:1].isspace() or ":" not in line:
            raise ValueError(f"line {number}: only top-level key/value YAML is supported")
        key, value = line.split(":", 1)
        result[key.strip()] = scalar(value)
    return result


def validate(state: dict) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED - state.keys())
    if missing:
        errors.append("missing fields: " + ", ".join(missing))
    if state.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if state.get("project_type") != "historical_research":
        errors.append("project_type must be historical_research")
    if state.get("mode") not in {"module", "project"}:
        errors.append("mode must be module or project")
    stage = state.get("current_stage")
    if not isinstance(stage, int) or not 0 <= stage <= 8:
        errors.append("current_stage must be an integer from 0 to 8")
    for field in ("full_workflow_authorized", "multi_agent_authorized"):
        if not isinstance(state.get(field), bool):
            errors.append(f"{field} must be true or false")
    if state.get("memory_backend") not in {"none", "historian-memory", "custom"}:
        errors.append("memory_backend must be none, historian-memory, or custom")
    if not isinstance(state.get("source_roots"), list):
        errors.append("source_roots must be a list")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("state_file", type=Path)
    args = parser.parse_args()
    try:
        errors = validate(load_state(args.state_file))
    except Exception as exc:
        errors = [str(exc)]
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"valid": True, "file": str(args.state_file)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
