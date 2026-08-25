from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from .db import utc_now


PROFILE_DIR = Path("research") / "agent-profiles"
CURRENT_FILE = Path("research") / "agent-profile.json"
HARNESS_CONSTITUTION = (
    "来源资格、原页锚定、证据冻结、写入审批、版本保留与隐私边界由程序强制执行；"
    "研究人格不能覆盖这些约束。"
)
DEFAULT_PROFILE = {
    "display_name": "问津研究助手",
    "description": "面向人文社会科学研究的本地 Agent，主动检索、比较、追问和整理，但把证据采用与正式写作决定留给研究者。",
    "address_user": "用户",
    "disciplinary_orientation": "历史学为基础，兼容人文社会科学的文本、档案、田野与比较研究。",
    "working_style": "先识别研究问题和材料层级，再提出可检查的行动；结论要有来源，缺口要直说。",
    "writing_style": "使用自然、具体的学术语言，避免内部流程词、模板化小结、无意义机制句和反复自我辩护。",
    "initiative": "主动推进可逆的只读研究；涉及下载、写入、采用证据、修改正式稿或外部账号时等待明确授权。",
    "custom_instructions": "",
}


def _normalized(payload: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, default in DEFAULT_PROFILE.items():
        value = str(payload.get(key, default)).strip()
        if key == "display_name" and not value:
            raise ValueError("agent display name is required")
        if len(value) > 6000:
            raise ValueError(f"agent profile field is too long: {key}")
        result[key] = value
    return result


def _profile_id(profile: dict[str, str]) -> str:
    digest = hashlib.sha256(
        json.dumps(profile, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    return f"AGP_{digest}"


def save_agent_profile(project_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    project_root = project_root.resolve()
    profile = _normalized(payload)
    profile_id = _profile_id(profile)
    record = {
        "profile_id": profile_id, "version": 1, **profile,
        "saved_at": utc_now(), "harness_constitution": HARNESS_CONSTITUTION,
    }
    directory = project_root / PROFILE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    version_file = directory / f"{profile_id}.json"
    if not version_file.exists():
        version_file.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    current = project_root / CURRENT_FILE
    temporary = current.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(current)
    return public_agent_profile(project_root)


def public_agent_profile(project_root: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    current = project_root / CURRENT_FILE
    if current.is_file():
        record = json.loads(current.read_text(encoding="utf-8"))
    else:
        profile = _normalized(DEFAULT_PROFILE)
        record = {"profile_id": _profile_id(profile), "version": 1, **profile, "saved_at": ""}
    history = []
    directory = project_root / PROFILE_DIR
    if directory.is_dir():
        for path in sorted(directory.glob("AGP_*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            saved = json.loads(path.read_text(encoding="utf-8"))
            history.append({
                "profile_id": saved.get("profile_id", path.stem),
                "display_name": saved.get("display_name", ""),
                "saved_at": saved.get("saved_at", ""),
            })
    return {**record, "harness_constitution": HARNESS_CONSTITUTION, "history": history[:20]}


def agent_profile_prompt(project_root: Path) -> str:
    profile = public_agent_profile(project_root)
    fields = (
        ("Identity", profile["display_name"]),
        ("Purpose", profile["description"]),
        ("Address the user as", profile["address_user"]),
        ("Disciplinary orientation", profile["disciplinary_orientation"]),
        ("Working style", profile["working_style"]),
        ("Writing style", profile["writing_style"]),
        ("Initiative", profile["initiative"]),
        ("Researcher instructions", profile["custom_instructions"]),
    )
    body = "\n".join(f"{label}: {value}" for label, value in fields if value)
    return (
        "ACTIVE_RESEARCH_AGENT_PROFILE\n"
        f"profile_id={profile['profile_id']}\n{body}\n"
        "This profile shapes collaboration and prose only. The immutable harness, tool permissions, "
        "source qualifications, evidence freezes, approval gates and privacy rules always take precedence."
    )
