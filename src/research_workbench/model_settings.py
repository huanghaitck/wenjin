from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SETTINGS_FILE = "model-settings.json"
PROVIDERS = {"disabled", "ollama", "openai_compatible"}
ROLES = {
    "main_reasoning": {"label": "主推理模型", "prefix": "HRW_AGENT"},
    "vision_ocr": {"label": "视觉 / OCR 模型", "prefix": "HRW_OCR"},
    "translation_helper": {"label": "翻译模型", "prefix": "HRW_TRANSLATION"},
}
CREDENTIAL_PREFIX = "HistoricalResearchWorkbench"


class _FileTime(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]


class _Credential(ctypes.Structure):
    _fields_ = [
        ("flags", wintypes.DWORD), ("type", wintypes.DWORD),
        ("target_name", wintypes.LPWSTR), ("comment", wintypes.LPWSTR),
        ("last_written", _FileTime), ("blob_size", wintypes.DWORD),
        ("blob", ctypes.POINTER(ctypes.c_ubyte)), ("persist", wintypes.DWORD),
        ("attribute_count", wintypes.DWORD), ("attributes", ctypes.c_void_p),
        ("target_alias", wintypes.LPWSTR), ("user_name", wintypes.LPWSTR),
    ]


def _target(role: str) -> str:
    return f"{CREDENTIAL_PREFIX}/{role}"


def _credential_api() -> Any:
    if os.name != "nt":
        raise RuntimeError("Windows Credential Manager is only available on Windows")
    return ctypes.WinDLL("Advapi32.dll", use_last_error=True)


def save_secret(role: str, secret: str) -> None:
    if role not in ROLES:
        raise KeyError(f"unknown model role: {role}")
    encoded = secret.encode("utf-16-le")
    blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
    credential = _Credential()
    credential.type = 1
    credential.target_name = _target(role)
    credential.blob_size = len(encoded)
    credential.blob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
    credential.persist = 2
    credential.user_name = "Historical Research Workbench"
    api = _credential_api()
    api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    if not api.CredWriteW(ctypes.byref(credential), 0):
        raise ctypes.WinError(ctypes.get_last_error())


def read_secret(role: str) -> str:
    if role not in ROLES or os.name != "nt":
        return ""
    api = _credential_api()
    pointer = ctypes.POINTER(_Credential)()
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(ctypes.POINTER(_Credential))]
    api.CredReadW.restype = wintypes.BOOL
    if not api.CredReadW(_target(role), 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:
            return ""
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        value = ctypes.string_at(pointer.contents.blob, pointer.contents.blob_size)
        return value.decode("utf-16-le")
    finally:
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredFree(pointer)


def delete_secret(role: str) -> None:
    if role not in ROLES or os.name != "nt":
        return
    api = _credential_api()
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL
    if not api.CredDeleteW(_target(role), 1, 0) and ctypes.get_last_error() != 1168:
        raise ctypes.WinError(ctypes.get_last_error())


def _defaults() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "roles": {
            role: {"provider": "disabled", "model": "", "base_url": "", "timeout_seconds": 90}
            for role in ROLES
        },
    }


def load_settings(config_root: Path) -> dict[str, Any]:
    path = config_root.resolve() / SETTINGS_FILE
    if not path.is_file():
        return _defaults()
    saved = json.loads(path.read_text(encoding="utf-8"))
    result = _defaults()
    for role in ROLES:
        if isinstance(saved.get("roles", {}).get(role), dict):
            result["roles"][role].update(saved["roles"][role])
    return result


def public_settings(config_root: Path) -> dict[str, Any]:
    settings = load_settings(config_root)
    roles = []
    for role, definition in ROLES.items():
        item = settings["roles"][role]
        roles.append({
            "role": role, "label": definition["label"], "provider": item["provider"],
            "model": item["model"], "base_url": item["base_url"],
            "timeout_seconds": item["timeout_seconds"],
            "credential_ref": f"windows-credential:{_target(role)}" if item["provider"] == "openai_compatible" else "none",
            "has_secret": bool(read_secret(role)) if item["provider"] == "openai_compatible" else False,
        })
    return {"schema_version": settings["schema_version"], "roles": roles,
            "credential_backend": "windows_credential_manager" if os.name == "nt" else "unavailable"}


def save_role(config_root: Path, role: str, payload: dict[str, Any]) -> dict[str, Any]:
    if role not in ROLES:
        raise KeyError(f"unknown model role: {role}")
    provider = str(payload.get("provider", "disabled")).strip().lower()
    model = str(payload.get("model", "")).strip()
    base_url = str(payload.get("base_url", "")).strip().rstrip("/")
    timeout = int(payload.get("timeout_seconds", 90))
    if provider not in PROVIDERS:
        raise ValueError(f"unsupported model provider: {provider}")
    if provider != "disabled" and (not model or not base_url):
        raise ValueError("model and base URL are required for an enabled role")
    if not 5 <= timeout <= 600:
        raise ValueError("timeout_seconds must be between 5 and 600")
    secret = str(payload.get("api_key", ""))
    if secret:
        save_secret(role, secret)
    if bool(payload.get("clear_secret", False)):
        delete_secret(role)
    config_root = config_root.resolve()
    config_root.mkdir(parents=True, exist_ok=True)
    settings = load_settings(config_root)
    settings["roles"][role] = {
        "provider": provider, "model": model, "base_url": base_url, "timeout_seconds": timeout,
    }
    temporary = config_root / f"{SETTINGS_FILE}.tmp"
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(config_root / SETTINGS_FILE)
    apply_settings(config_root)
    return public_settings(config_root)


def apply_settings(config_root: Path) -> None:
    settings = load_settings(config_root)
    for role, definition in ROLES.items():
        prefix = definition["prefix"]
        for suffix in ("PROVIDER", "MODEL", "BASE_URL", "API_KEY", "TIMEOUT_SECONDS"):
            os.environ.pop(f"{prefix}_{suffix}", None)
        item = settings["roles"][role]
        if item["provider"] == "disabled":
            continue
        os.environ[f"{prefix}_PROVIDER"] = str(item["provider"])
        os.environ[f"{prefix}_MODEL"] = str(item["model"])
        os.environ[f"{prefix}_BASE_URL"] = str(item["base_url"])
        os.environ[f"{prefix}_TIMEOUT_SECONDS"] = str(item["timeout_seconds"])
        secret = read_secret(role)
        if secret:
            os.environ[f"{prefix}_API_KEY"] = secret


def probe_role(config_root: Path, role: str) -> dict[str, Any]:
    item = load_settings(config_root)["roles"].get(role)
    if item is None:
        raise KeyError(f"unknown model role: {role}")
    if item["provider"] == "disabled":
        return {"role": role, "available": False, "detail": "该角色尚未启用"}
    url = str(item["base_url"]).rstrip("/") + ("/api/tags" if item["provider"] == "ollama" else "/models")
    headers = {"Accept": "application/json"}
    secret = read_secret(role)
    if item["provider"] == "openai_compatible":
        if not secret:
            return {"role": role, "available": False, "detail": "尚未保存 API Key"}
        headers["Authorization"] = f"Bearer {secret}"
    try:
        with urlopen(Request(url, headers=headers), timeout=min(int(item["timeout_seconds"]), 15)) as response:
            available = 200 <= response.status < 300
    except HTTPError as error:
        return {"role": role, "available": False, "detail": f"接口返回 HTTP {error.code}"}
    except (URLError, TimeoutError):
        return {"role": role, "available": False, "detail": "无法连接模型接口"}
    return {"role": role, "available": available, "detail": f"已连接 {item['provider']} / {item['model']}"}

