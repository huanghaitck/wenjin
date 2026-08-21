from __future__ import annotations

import ctypes
import json
import os
import ssl
from ctypes import wintypes
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi


SETTINGS_FILE = "model-settings.json"
PROVIDERS = {"auto", "disabled", "ollama", "openai_compatible"}
ROLES = {
    "main_reasoning": {"label": "主模型", "label_en": "Main model", "prefix": "HRW_AGENT", "kind": "main"},
    "vision_ocr": {"label": "视觉与 OCR", "label_en": "Vision and OCR", "prefix": "HRW_OCR", "kind": "auxiliary"},
    "translation_helper": {"label": "翻译", "label_en": "Translation", "prefix": "HRW_TRANSLATION", "kind": "auxiliary"},
    "web_research": {"label": "联网材料整理", "label_en": "Web research", "prefix": "HRW_WEB_RESEARCH", "kind": "auxiliary"},
    "context_compression": {"label": "上下文压缩", "label_en": "Context compression", "prefix": "HRW_COMPRESSION", "kind": "auxiliary"},
    "title_generation": {"label": "标题与摘要命名", "label_en": "Title generation", "prefix": "HRW_TITLE", "kind": "auxiliary"},
    "review_secondary": {"label": "交叉评审", "label_en": "Secondary review", "prefix": "HRW_REVIEW", "kind": "auxiliary"},
}
PROVIDER_PRESETS = [
    {"id": "ollama", "label": "Ollama", "provider": "ollama", "base_url": "http://127.0.0.1:11434"},
    {"id": "deepseek", "label": "DeepSeek", "provider": "openai_compatible", "base_url": "https://api.deepseek.com"},
    {"id": "openrouter", "label": "OpenRouter", "provider": "openai_compatible", "base_url": "https://openrouter.ai/api/v1"},
    {"id": "siliconflow", "label": "SiliconFlow", "provider": "openai_compatible", "base_url": "https://api.siliconflow.cn/v1"},
    {"id": "zhipu", "label": "智谱 GLM", "provider": "openai_compatible", "base_url": "https://open.bigmodel.cn/api/paas/v4"},
    {"id": "custom", "label": "自定义兼容接口", "provider": "openai_compatible", "base_url": ""},
]
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
        "schema_version": 2,
        "roles": {
            role: {
                "provider": "disabled" if role == "main_reasoning" else "auto",
                "model": "", "base_url": "", "timeout_seconds": 90,
                "context_window": 0, "preset_id": "custom",
            }
            for role in ROLES
        },
        "moa": {
            "enabled": False,
            "reference_roles": ["review_secondary"],
            "aggregator_role": "main_reasoning",
            "fanout": "user_turn",
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
    if isinstance(saved.get("moa"), dict):
        result["moa"].update(saved["moa"])
    return result


def public_settings(config_root: Path) -> dict[str, Any]:
    settings = load_settings(config_root)
    roles = []
    for role, definition in ROLES.items():
        item = settings["roles"][role]
        roles.append({
            "role": role, "label": definition["label"], "label_en": definition["label_en"],
            "kind": definition["kind"], "provider": item["provider"],
            "model": item["model"], "base_url": item["base_url"],
            "timeout_seconds": item["timeout_seconds"],
            "context_window": int(item.get("context_window", 0) or 0),
            "preset_id": str(item.get("preset_id", "custom")),
            "credential_ref": f"windows-credential:{_target(role)}" if item["provider"] == "openai_compatible" else "none",
            "has_secret": bool(read_secret(role)) if item["provider"] == "openai_compatible" else False,
        })
    return {"schema_version": settings["schema_version"], "roles": roles,
            "provider_presets": PROVIDER_PRESETS, "moa": settings["moa"],
            "credential_backend": "windows_credential_manager" if os.name == "nt" else "unavailable"}


def save_role(config_root: Path, role: str, payload: dict[str, Any]) -> dict[str, Any]:
    if role not in ROLES:
        raise KeyError(f"unknown model role: {role}")
    provider = str(payload.get("provider", "disabled")).strip().lower()
    model = str(payload.get("model", "")).strip()
    base_url = str(payload.get("base_url", "")).strip().rstrip("/")
    timeout = int(payload.get("timeout_seconds", 90))
    context_window = int(payload.get("context_window", 0) or 0)
    preset_id = str(payload.get("preset_id", "custom")).strip() or "custom"
    if provider not in PROVIDERS:
        raise ValueError(f"unsupported model provider: {provider}")
    if role == "main_reasoning" and provider == "auto":
        raise ValueError("the main model cannot use automatic routing")
    if provider not in {"disabled", "auto"} and (not model or not base_url):
        raise ValueError("model and base URL are required for an enabled role")
    if not 5 <= timeout <= 600:
        raise ValueError("timeout_seconds must be between 5 and 600")
    if context_window < 0:
        raise ValueError("context_window cannot be negative")
    secret = str(payload.get("api_key", ""))
    if secret:
        save_secret(role, secret)
    if bool(payload.get("clear_secret", False)):
        delete_secret(role)
    config_root = config_root.resolve()
    config_root.mkdir(parents=True, exist_ok=True)
    settings = load_settings(config_root)
    settings["roles"][role] = {
        "provider": provider, "model": model, "base_url": base_url,
        "timeout_seconds": timeout, "context_window": context_window, "preset_id": preset_id,
    }
    temporary = config_root / f"{SETTINGS_FILE}.tmp"
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(config_root / SETTINGS_FILE)
    apply_settings(config_root)
    return public_settings(config_root)


def apply_settings(config_root: Path) -> None:
    settings = load_settings(config_root)
    main = settings["roles"]["main_reasoning"]
    for role, definition in ROLES.items():
        prefix = definition["prefix"]
        for suffix in ("PROVIDER", "MODEL", "BASE_URL", "API_KEY", "TIMEOUT_SECONDS"):
            os.environ.pop(f"{prefix}_{suffix}", None)
        item = settings["roles"][role]
        if item["provider"] == "auto":
            item = main
        if item["provider"] == "disabled":
            continue
        os.environ[f"{prefix}_PROVIDER"] = str(item["provider"])
        os.environ[f"{prefix}_MODEL"] = str(item["model"])
        os.environ[f"{prefix}_BASE_URL"] = str(item["base_url"])
        os.environ[f"{prefix}_TIMEOUT_SECONDS"] = str(item["timeout_seconds"])
        secret = read_secret(role)
        if not secret and settings["roles"][role]["provider"] == "auto":
            secret = read_secret("main_reasoning")
        if secret:
            os.environ[f"{prefix}_API_KEY"] = secret
    moa = settings["moa"]
    os.environ["HRW_MOA_ENABLED"] = "1" if moa.get("enabled") else "0"
    os.environ["HRW_MOA_REFERENCE_ROLES"] = ",".join(moa.get("reference_roles") or [])
    os.environ["HRW_MOA_AGGREGATOR_ROLE"] = str(moa.get("aggregator_role", "main_reasoning"))
    os.environ["HRW_MOA_FANOUT"] = str(moa.get("fanout", "user_turn"))


def save_moa(config_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    reference_roles = [str(value) for value in payload.get("reference_roles", [])]
    if any(role not in ROLES or role == "main_reasoning" for role in reference_roles):
        raise ValueError("MoA reference roles must be configured auxiliary roles")
    reference_roles = list(dict.fromkeys(reference_roles))
    fanout = str(payload.get("fanout", "user_turn"))
    if fanout not in {"user_turn", "per_iteration"}:
        raise ValueError("unsupported MoA fanout policy")
    enabled = bool(payload.get("enabled", False))
    if enabled and not reference_roles:
        raise ValueError("an enabled MoA preset needs at least one reference role")
    config_root = config_root.resolve()
    config_root.mkdir(parents=True, exist_ok=True)
    settings = load_settings(config_root)
    settings["moa"] = {
        "enabled": enabled, "reference_roles": reference_roles,
        "aggregator_role": "main_reasoning", "fanout": fanout,
    }
    temporary = config_root / f"{SETTINGS_FILE}.tmp"
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(config_root / SETTINGS_FILE)
    apply_settings(config_root)
    return public_settings(config_root)


def probe_role(config_root: Path, role: str) -> dict[str, Any]:
    item = load_settings(config_root)["roles"].get(role)
    if item is None:
        raise KeyError(f"unknown model role: {role}")
    if item["provider"] == "disabled":
        return {"role": role, "available": False, "detail": "该角色尚未启用"}
    secret_role = role
    if item["provider"] == "auto":
        item = load_settings(config_root)["roles"]["main_reasoning"]
        secret_role = "main_reasoning"
        if item["provider"] == "disabled":
            return {"role": role, "available": False, "detail": "自动路由需要先配置主模型"}
    url = str(item["base_url"]).rstrip("/") + ("/api/tags" if item["provider"] == "ollama" else "/models")
    headers = {"Accept": "application/json"}
    secret = read_secret(secret_role)
    if item["provider"] == "openai_compatible":
        if not secret:
            return {"role": role, "available": False, "detail": "尚未保存 API Key"}
        headers["Authorization"] = f"Bearer {secret}"
    try:
        with urlopen(
            Request(url, headers=headers),
            timeout=min(int(item["timeout_seconds"]), 15),
            context=ssl.create_default_context(cafile=certifi.where()),
        ) as response:
            available = 200 <= response.status < 300
    except HTTPError as error:
        return {"role": role, "available": False, "detail": f"接口返回 HTTP {error.code}"}
    except URLError as error:
        return {"role": role, "available": False, "detail": f"无法连接模型接口：{error.reason}"}
    except TimeoutError:
        return {"role": role, "available": False, "detail": "连接模型接口超时"}
    return {"role": role, "available": available, "detail": f"已连接 {item['provider']} / {item['model']}"}


def discover_models(
    config_root: Path, role: str, provider: str, base_url: str, api_key: str = "",
) -> dict[str, Any]:
    if role not in ROLES:
        raise KeyError(f"unknown model role: {role}")
    provider = provider.strip().lower()
    base_url = base_url.strip().rstrip("/")
    if provider not in {"ollama", "openai_compatible"}:
        raise ValueError("model discovery requires Ollama or an OpenAI-compatible endpoint")
    if not base_url:
        raise ValueError("base URL is required for model discovery")
    endpoint = base_url + ("/api/tags" if provider == "ollama" else "/models")
    headers = {"Accept": "application/json"}
    secret = api_key.strip() or read_secret(role)
    if provider == "openai_compatible":
        if not secret:
            raise ValueError("API Key is required to list models for this provider")
        headers["Authorization"] = f"Bearer {secret}"
    try:
        with urlopen(
            Request(endpoint, headers=headers), timeout=20,
            context=ssl.create_default_context(cafile=certifi.where()),
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(f"model list returned HTTP {error.code}") from error
    except URLError as error:
        raise RuntimeError(f"model list endpoint is unavailable: {error.reason}") from error
    if provider == "ollama":
        items = payload.get("models", []) if isinstance(payload, dict) else []
        models = [str(item.get("name", "")).strip() for item in items if isinstance(item, dict)]
    else:
        items = payload.get("data", []) if isinstance(payload, dict) else []
        models = [str(item.get("id", "")).strip() for item in items if isinstance(item, dict)]
    models = sorted(set(value for value in models if value), key=str.casefold)[:500]
    return {
        "role": role, "provider": provider, "base_url": base_url,
        "models": models, "count": len(models),
        "manual_entry_allowed": True,
        "detail": f"发现 {len(models)} 个模型" if models else "接口未返回可选模型，可手工填写",
    }
