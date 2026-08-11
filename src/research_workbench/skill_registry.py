from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any


BUILTIN_SKILLS = Path(__file__).parent / "builtin_skills"
HARNESS_POLICY_SKILLS = {
    "historical-research-router",
    "historical-project-workflow",
    "historical-drafting",
}
INTEGRATION_SKILLS = {
    "agent-browser", "codex-memory", "historian-memory", "json-canvas",
    "obsidian-bases", "obsidian-cli", "obsidian-markdown",
}


def _placement(name: str) -> tuple[str, list[str]]:
    if name in HARNESS_POLICY_SKILLS:
        return "harness_policy", []
    if name in INTEGRATION_SKILLS:
        return "integration", []
    if name == "historical-material-intake":
        return "user_action", ["library_intake"]
    if name in {"historical-humanizer-zh", "historical-prose-revision-zh"}:
        return "user_action", ["writing_revision"]
    return "user_action", ["research_dialogue"]


def _skill_roots(extra_roots: list[Path] | None = None) -> list[Path]:
    roots = [BUILTIN_SKILLS]
    shared = Path(__file__).resolve().parents[3] / "codex-skills"
    if shared.is_dir():
        roots.append(shared)
    plugin_cache = Path.home() / ".codex" / "plugins" / "cache" / "historical-research" / "historical-research"
    if plugin_cache.is_dir():
        roots.extend(path / "skills" for path in sorted(plugin_cache.iterdir()) if (path / "skills").is_dir())
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


def _agent_program(skill_root: Path) -> dict[str, Any] | None:
    path = skill_root / "agents" / "openai.yaml"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    def value(key: str) -> str:
        match = re.search(rf"^\s*{re.escape(key)}:\s*[\"']?(.*?)[\"']?\s*$", text, re.MULTILINE)
        return match.group(1).strip().strip("\"'") if match else ""
    return {
        "display_name": value("display_name") or skill_root.name,
        "short_description": value("short_description"),
        "default_prompt": value("default_prompt"),
        "allow_implicit_invocation": value("allow_implicit_invocation").lower() == "true",
        "program_file": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


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
            placement, compatible_actions = _placement(name)
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
                "placement": placement,
                "compatible_actions": compatible_actions,
                "invocation": f"/{name}",
                "agent_program": _agent_program(path.parent),
            }
    return sorted(skills.values(), key=lambda item: item["name"])


def get_skill(name: str, extra_roots: list[Path] | None = None) -> dict[str, Any]:
    for skill in discover_skills(extra_roots):
        if skill["name"] == name:
            return skill
    raise KeyError(f"unknown skill: {name}")
