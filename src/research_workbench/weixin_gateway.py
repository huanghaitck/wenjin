from __future__ import annotations

import base64
import io
import json
import secrets
import threading
import time
import ssl
import uuid
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

import certifi
import qrcode
import qrcode.image.svg

from .agent_runtime import create_thread, send_message
from .credential_store import delete_credential, read_credential, save_credential


FIXED_BASE_URL = "https://ilinkai.weixin.qq.com"
SETTINGS_FILE = "weixin-gateway.json"
CHANNEL_VERSION = "0.1.1"
APP_ID = "bot"
CLIENT_VERSION = 257
TOKEN_TARGET = "Wenjin/Weixin/iLinkBotToken"
LOGIN_TTL_SECONDS = 300
WELCOME_TEXT = (
    "你好，我是问津，一套本地优先的人文社会科学研究工作台。"
    "我可以协助整理文献、核对PDF原页、处理表格与图片、调用领域 Agent、管理证据和推进写作。"
    "你可以直接发问题或文件；文件会按指纹归入研究图书馆，同一内容不会重复登记。"
    "涉及写文件、运行程序或其他敏感动作时，我会按照你在客户端选择的权限请求确认。"
)


def _base_info() -> dict[str, Any]:
    return {"channel_version": CHANNEL_VERSION, "bot_agent": "Wenjin/0.1.1"}


def _headers(token: str = "") -> dict[str, str]:
    random_uin = base64.b64encode(str(secrets.randbits(32)).encode("ascii")).decode("ascii")
    headers = {
        "Content-Type": "application/json", "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": random_uin, "iLink-App-Id": APP_ID,
        "iLink-App-ClientVersion": str(CLIENT_VERSION),
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class WeixinApi:
    def request(self, method: str, base_url: str, endpoint: str, payload: dict[str, Any] | None = None,
                token: str = "", timeout: float = 35) -> dict[str, Any]:
        url = base_url.rstrip("/") + "/" + endpoint.lstrip("/")
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = Request(url, data=data, headers=_headers(token), method=method)
        with urlopen(request, timeout=timeout, context=ssl.create_default_context(cafile=certifi.where())) as response:
            return json.loads(response.read().decode("utf-8"))


def _defaults() -> dict[str, Any]:
    return {
        "schema_version": 1, "enabled": False, "account_id": "", "user_id": "",
        "base_url": FIXED_BASE_URL, "allowed_user_ids": [], "access_mode": "ask",
        "thread_map": {}, "get_updates_buf": "", "last_error": "", "last_event_at": "",
        "welcome_pending": False,
    }


def _load(config_root: Path) -> dict[str, Any]:
    path = config_root.resolve() / SETTINGS_FILE
    result = _defaults()
    if path.is_file():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            result.update(saved)
    return result


def _save(config_root: Path, value: dict[str, Any]) -> None:
    config_root = config_root.resolve()
    config_root.mkdir(parents=True, exist_ok=True)
    path = config_root / SETTINGS_FILE
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _message_text(message: dict[str, Any]) -> str:
    parts = []
    for item in message.get("item_list") or []:
        if item.get("type") == 1 and isinstance(item.get("text_item"), dict):
            text = str(item["text_item"].get("text", "")).strip()
            if text:
                parts.append(text)
    return "\n".join(parts)


def _qr_data_url(value: str) -> str:
    image = qrcode.make(value, image_factory=qrcode.image.svg.SvgPathImage)
    stream = io.BytesIO()
    image.save(stream)
    return "data:image/svg+xml;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def _latest_assistant_text(view: dict[str, Any]) -> str:
    for message in reversed(view.get("messages") or []):
        if message.get("role") == "assistant":
            content = message.get("content") or message.get("content_json") or {}
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except json.JSONDecodeError:
                    return content
            if isinstance(content, dict):
                return str(content.get("text", "")).strip()
    return ""


class WeixinGateway:
    def __init__(self, config_root: Path, project_root: Path, api: WeixinApi | None = None):
        self.config_root = config_root.resolve()
        self.project_root = project_root.resolve()
        self.api = api or WeixinApi()
        self._login: dict[str, Any] | None = None
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._seen: deque[str] = deque(maxlen=1000)
        self._lock = threading.RLock()

    def status(self) -> dict[str, Any]:
        settings = _load(self.config_root)
        return {
            "configured": bool(settings.get("account_id") and read_credential(TOKEN_TARGET)),
            "running": bool(self._worker and self._worker.is_alive()),
            "enabled": bool(settings.get("enabled")), "account_id": settings.get("account_id", ""),
            "user_id": settings.get("user_id", ""), "allowed_user_ids": settings.get("allowed_user_ids", []),
            "access_mode": settings.get("access_mode", "ask"), "last_error": settings.get("last_error", ""),
            "last_event_at": settings.get("last_event_at", ""), "private_chat_only": True,
            "proactive_messages": False, "welcome_on_first_message": True,
            "credential_backend": "windows_credential_manager",
            "implementation": "wenjin_native_ilink_gateway",
        }

    def start_login(self) -> dict[str, Any]:
        response = self.api.request(
            "POST", FIXED_BASE_URL, "ilink/bot/get_bot_qrcode?bot_type=3",
            {"local_token_list": []}, timeout=15,
        )
        qrcode = str(response.get("qrcode", ""))
        qrcode_url = str(response.get("qrcode_img_content", ""))
        if not qrcode or not qrcode_url:
            raise RuntimeError("微信接口没有返回可用二维码")
        session_id = uuid.uuid4().hex
        with self._lock:
            self._login = {
                "session_id": session_id, "qrcode": qrcode, "qrcode_url": qrcode_url,
                "created_at": time.time(), "poll_base_url": FIXED_BASE_URL,
            }
        return {"session_id": session_id, "qrcode_url": qrcode_url,
                "qrcode_data_url": _qr_data_url(qrcode_url), "status": "wait"}

    def poll_login(self, session_id: str, verify_code: str = "") -> dict[str, Any]:
        with self._lock:
            login = dict(self._login or {})
        if not login or login.get("session_id") != session_id:
            raise KeyError("微信登录会话不存在")
        if time.time() - float(login["created_at"]) > LOGIN_TTL_SECONDS:
            raise ValueError("微信二维码已经过期，请重新生成")
        endpoint = "ilink/bot/get_qrcode_status?qrcode=" + quote(str(login["qrcode"]))
        if verify_code.strip():
            endpoint += "&verify_code=" + quote(verify_code.strip())
        response = self.api.request("GET", str(login["poll_base_url"]), endpoint, timeout=35)
        status = str(response.get("status", "wait"))
        if status == "scaned_but_redirect" and response.get("redirect_host"):
            with self._lock:
                if self._login:
                    self._login["poll_base_url"] = str(response["redirect_host"])
            return {"connected": False, "status": status, "message": "已扫码，正在切换登录节点"}
        if status == "confirmed":
            token = str(response.get("bot_token", ""))
            account_id = str(response.get("ilink_bot_id", ""))
            user_id = str(response.get("ilink_user_id", ""))
            if not token or not account_id:
                raise RuntimeError("微信已确认，但没有返回完整账号凭据")
            save_credential(TOKEN_TARGET, token, "Wenjin Weixin Gateway")
            settings = _load(self.config_root)
            settings.update({
                "enabled": True, "account_id": account_id, "user_id": user_id,
                "base_url": str(response.get("baseurl") or FIXED_BASE_URL),
                "allowed_user_ids": [user_id] if user_id else [], "last_error": "",
                "welcome_pending": True,
            })
            _save(self.config_root, settings)
            with self._lock:
                self._login = None
            self.start()
            return {"connected": True, "status": status, "account_id": account_id,
                    "user_id": user_id,
                    "message": "微信已连接。请发送任意一条消息，问津会在首条回复中自我介绍。"}
        return {"connected": False, "status": status,
                "requires_verify_code": status == "need_verifycode", "message": "等待微信确认"}

    def update_config(self, allowed_user_ids: list[str], access_mode: str, enabled: bool) -> dict[str, Any]:
        if access_mode not in {"ask", "research_assist", "full_computer"}:
            raise ValueError("unknown agent access mode")
        settings = _load(self.config_root)
        settings["allowed_user_ids"] = list(dict.fromkeys(value.strip() for value in allowed_user_ids if value.strip()))
        settings["access_mode"] = access_mode
        settings["enabled"] = bool(enabled)
        _save(self.config_root, settings)
        if enabled:
            self.start()
        else:
            self.stop()
        return self.status()

    def disconnect(self) -> dict[str, Any]:
        self.stop()
        delete_credential(TOKEN_TARGET)
        settings = _defaults()
        _save(self.config_root, settings)
        return self.status()

    def start(self) -> None:
        settings = _load(self.config_root)
        if not settings.get("enabled") or not read_credential(TOKEN_TARGET):
            return
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            self._stop.clear()
            self._worker = threading.Thread(target=self._run, name="wenjin-weixin", daemon=True)
            self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        worker = self._worker
        if worker and worker.is_alive():
            worker.join(timeout=1)

    def _run(self) -> None:
        while not self._stop.is_set():
            settings = _load(self.config_root)
            token = read_credential(TOKEN_TARGET)
            if not settings.get("enabled") or not token:
                return
            try:
                response = self.api.request(
                    "POST", str(settings.get("base_url") or FIXED_BASE_URL), "ilink/bot/getupdates",
                    {"get_updates_buf": settings.get("get_updates_buf", ""), "base_info": _base_info()},
                    token=token, timeout=38,
                )
                if int(response.get("ret", 0) or 0) != 0 or int(response.get("errcode", 0) or 0) != 0:
                    raise RuntimeError(str(response.get("errmsg") or "微信长轮询返回错误"))
                if response.get("get_updates_buf"):
                    settings["get_updates_buf"] = response["get_updates_buf"]
                settings["last_event_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                settings["last_error"] = ""
                _save(self.config_root, settings)
                for message in response.get("msgs") or []:
                    self._handle_message(message, settings, token)
            except Exception as error:
                settings["last_error"] = str(error)[:500]
                _save(self.config_root, settings)
                self._stop.wait(3)

    def _handle_message(self, message: dict[str, Any], settings: dict[str, Any], token: str) -> None:
        if message.get("group_id"):
            return
        sender = str(message.get("from_user_id", ""))
        allowed = set(settings.get("allowed_user_ids") or [])
        if not sender or sender not in allowed:
            return
        message_key = str(message.get("message_id") or message.get("client_id") or "")
        if message_key and message_key in self._seen:
            return
        if message_key:
            self._seen.append(message_key)
        text = _message_text(message)
        context_token = str(message.get("context_token", ""))
        if not text or not context_token:
            return
        mapping = settings.setdefault("thread_map", {})
        thread_id = str(mapping.get(sender, ""))
        if not thread_id:
            thread_id = create_thread(self.project_root, "微信研究对话")["thread_id"]
            mapping[sender] = thread_id
            _save(self.config_root, settings)
        try:
            view = send_message(
                self.project_root, thread_id, text, planning_mode="guided_execution",
                access_mode=str(settings.get("access_mode", "ask")),
            )
            runs = view.get("runs") or []
            if runs and runs[0].get("status") == "WAITING_FOR_APPROVAL":
                reply = "这一步需要你在问津客户端审核。批准或拒绝后，再从微信继续。"
            else:
                reply = _latest_assistant_text(view) or "问津已处理，但没有形成可发送的文字答复。"
        except Exception as error:
            reply = "问津暂时无法处理这条消息。请在客户端查看运行状态。"
            settings["last_error"] = str(error)[:500]
            _save(self.config_root, settings)
        if settings.get("welcome_pending"):
            reply = WELCOME_TEXT + "\n\n" + reply
            settings["welcome_pending"] = False
            _save(self.config_root, settings)
        self.api.request(
            "POST", str(settings.get("base_url") or FIXED_BASE_URL), "ilink/bot/sendmessage",
            {"msg": {"from_user_id": "", "to_user_id": sender,
                     "client_id": "wenjin-" + uuid.uuid4().hex, "message_type": 2,
                     "message_state": 2, "item_list": [{"type": 1, "text_item": {"text": reply}}],
                     "context_token": context_token}, "base_info": _base_info()},
            token=token, timeout=15,
        )


_GATEWAYS: dict[tuple[str, str], WeixinGateway] = {}


def gateway(config_root: Path, project_root: Path) -> WeixinGateway:
    key = (str(config_root.resolve()), str(project_root.resolve()))
    instance = _GATEWAYS.get(key)
    if instance is None:
        instance = WeixinGateway(config_root, project_root)
        _GATEWAYS[key] = instance
    return instance


def start_configured_gateway(config_root: Path, project_root: Path) -> None:
    gateway(config_root, project_root).start()
