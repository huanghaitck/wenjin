from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any


BUILTIN_SKILLS = Path(__file__).parent / "builtin_skills"


def _skill_roots(extra_roots: list[Path] | None = None) -> list[Path]:
    roots = [BUILTIN_SKILLS]
    configured = os.getenv("HRW_SKILL_ROOTS", "")
    roots.extend(Path(item) for item in configured.split(os.pathsep) if item.strip())
    roots.extend(extra_roots or [])
    return roots


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    values: dict[str, str] = {}
    for line in text[4:end].splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip().strip('"\'')
    return values, text[end + 5 :].strip()


def discover_skills(extra_roots: list[Path] | None = None) -> list[dict[str, Any]]:
    skills: dict[str, dict[str, Any]] = {}
    for root in _skill_roots(extra_roots):
        root = root.expanduser()
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*/SKILL.md")):
            raw = path.read_bytes()
            text = raw.decode("utf-8")
            metadata, instructions = _frontmatter(text.replace("\r\n", "\n"))
            name = metadata.get("name") or path.parent.name
            resources = sorted(
                str(item.relative_to(path.parent)).replace("\\", "/")
                for item in path.parent.rglob("*")
                if item.is_file() and item != path
            )
            skills[name] = {
                "name": name,
                "description": metadata.get("description", ""),
                "instructions": instructions,
                "skill_file": str(path.resolve()),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "resources": resources,
                "execution": "instructions_only",
            }
    return sorted(skills.values(), key=lambda item: item["name"])


def get_skill(name: str, extra_roots: list[Path] | None = None) -> dict[str, Any]:
    for skill in discover_skills(extra_roots):
        if skill["name"] == name:
            return skill
    raise KeyError(f"unknown skill: {name}")
