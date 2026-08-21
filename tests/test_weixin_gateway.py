from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_workbench.service import initialize_project
from research_workbench.weixin_gateway import WeixinGateway, _headers, _load, _message_text


class FakeApi:
    def __init__(self, responses: list[dict] | None = None):
        self.responses = list(responses or [])
        self.calls: list[dict] = []

    def request(self, method, base_url, endpoint, payload=None, token="", timeout=35):
        self.calls.append({"method": method, "base_url": base_url, "endpoint": endpoint,
                           "payload": payload, "token": token, "timeout": timeout})
        return self.responses.pop(0) if self.responses else {"ret": 0}


class WeixinGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.config = root / "config"
        self.project = root / "project"
        initialize_project(self.project, "Weixin gateway test")
        self.secrets: dict[str, str] = {}
        self.patches = [
            patch("research_workbench.weixin_gateway.save_credential", side_effect=lambda key, value, *_: self.secrets.__setitem__(key, value)),
            patch("research_workbench.weixin_gateway.read_credential", side_effect=lambda key: self.secrets.get(key, "")),
            patch("research_workbench.weixin_gateway.delete_credential", side_effect=lambda key: self.secrets.pop(key, None)),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def test_login_uses_ilink_qr_and_saves_only_token_in_credential_store(self) -> None:
        api = FakeApi([
            {"qrcode": "opaque-code", "qrcode_img_content": "https://example.invalid/qr"},
            {"status": "confirmed", "bot_token": "secret-token", "ilink_bot_id": "bot-1",
             "ilink_user_id": "user-1", "baseurl": "https://api.example.invalid"},
        ])
        gateway = WeixinGateway(self.config, self.project, api)
        started = gateway.start_login()
        self.assertTrue(started["qrcode_data_url"].startswith("data:image/svg+xml;base64,"))
        with patch.object(gateway, "start"):
            result = gateway.poll_login(started["session_id"])
        self.assertTrue(result["connected"])
        self.assertIn("bot_type=3", api.calls[0]["endpoint"])
        self.assertEqual(set(self.secrets.values()), {"secret-token"})
        persisted = (self.config / "weixin-gateway.json").read_text(encoding="utf-8")
        self.assertNotIn("secret-token", persisted)
        self.assertEqual(_load(self.config)["allowed_user_ids"], ["user-1"])

    def test_private_allowlisted_text_routes_to_agent_and_replies_with_context_token(self) -> None:
        api = FakeApi()
        gateway = WeixinGateway(self.config, self.project, api)
        settings = _load(self.config)
        settings.update({"allowed_user_ids": ["user-1"], "base_url": "https://api.example.invalid",
                         "access_mode": "ask", "thread_map": {}})
        view = {"messages": [{"role": "assistant", "content": {"text": "已完成核对。"}}],
                "runs": [{"status": "COMPLETED"}]}
        message = {"message_id": 10, "from_user_id": "user-1", "context_token": "context-1",
                   "item_list": [{"type": 1, "text_item": {"text": "核对这条材料"}}]}
        with patch("research_workbench.weixin_gateway.send_message", return_value=view) as sent:
            gateway._handle_message(message, settings, "bot-token")
        self.assertEqual(sent.call_args.args[2], "核对这条材料")
        reply = api.calls[-1]["payload"]["msg"]
        self.assertEqual(reply["context_token"], "context-1")
        self.assertEqual(reply["item_list"][0]["text_item"]["text"], "已完成核对。")
        self.assertNotIn("bot-token", str(api.calls[-1]["payload"]))

    def test_group_unlisted_duplicate_and_non_text_messages_are_ignored(self) -> None:
        api = FakeApi()
        gateway = WeixinGateway(self.config, self.project, api)
        settings = _load(self.config)
        settings["allowed_user_ids"] = ["user-1"]
        messages = [
            {"group_id": "g", "from_user_id": "user-1", "context_token": "c", "item_list": [{"type": 1, "text_item": {"text": "group"}}]},
            {"from_user_id": "other", "context_token": "c", "item_list": [{"type": 1, "text_item": {"text": "other"}}]},
            {"from_user_id": "user-1", "context_token": "c", "item_list": [{"type": 2}]},
        ]
        with patch("research_workbench.weixin_gateway.send_message") as sent:
            for message in messages:
                gateway._handle_message(message, settings, "token")
        sent.assert_not_called()
        self.assertEqual(api.calls, [])

    def test_common_headers_do_not_expose_secrets_without_token(self) -> None:
        headers = _headers()
        self.assertEqual(headers["AuthorizationType"], "ilink_bot_token")
        self.assertEqual(headers["iLink-App-Id"], "bot")
        self.assertNotIn("Authorization", headers)
        self.assertEqual(_message_text({"item_list": [{"type": 1, "text_item": {"text": " A "}}]}), "A")


if __name__ == "__main__":
    unittest.main()
