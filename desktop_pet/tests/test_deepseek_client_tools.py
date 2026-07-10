from __future__ import annotations

import logging
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import requests


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))


logger_module = types.ModuleType("utils.logger")
logger_module.get_logger = logging.getLogger
sys.modules.setdefault("utils.logger", logger_module)

from ai.deepseek_client import DeepSeekClient  # noqa: E402


class FakeResponse:
    # 初始化模拟 HTTP 响应。
    def __init__(self, payload: dict, status_code: int = 200, text: str = "") -> None:
        """初始化模拟 HTTP 响应。"""
        self.payload = payload
        self.status_code = status_code
        self.text = text

    # 按状态码模拟 requests 的错误检查。
    def raise_for_status(self) -> None:
        """按状态码模拟 requests 的错误检查。"""
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    # 返回模拟 JSON 载荷。
    def json(self) -> dict:
        """返回模拟 JSON 载荷。"""
        return self.payload


class DeepSeekClientToolTests(unittest.TestCase):
    # 构建不依赖配置文件的已配置客户端替身。
    def setUp(self) -> None:
        """构建不依赖配置文件的已配置客户端替身。"""
        self.client = DeepSeekClient("unused.json")
        self.api_patch = patch.object(
            self.client,
            "_api_config",
            return_value={"api_key": "test-key", "base_url": "https://example.test"},
        )
        self.api_patch.start()
        self.addCleanup(self.api_patch.stop)
        self.messages = [{"role": "user", "content": "明天提醒我开会"}]

    # 验证原生工具调用请求会携带 tools 并严格解析参数。
    def test_native_tool_call_is_parsed(self) -> None:
        """验证原生工具调用请求会携带 tools 并严格解析参数。"""
        response = FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "create_reminder",
                                        "arguments": '{"title":"开会","due_at":"2026-07-11T09:00:00"}',
                                    }
                                }
                            ],
                        }
                    }
                ]
            }
        )
        with patch("ai.deepseek_client.requests.post", return_value=response) as post:
            result = self.client.chat_with_reminder_tools(self.messages, self.messages)

        self.assertEqual(result.protocol, "native")
        self.assertEqual(result.reminder_calls[0].title, "开会")
        payload = post.call_args.kwargs["json"]
        self.assertIn("tools", payload)
        self.assertEqual(payload["tool_choice"], "auto")

    # 验证端点明确拒绝 tools 时会降级解析严格 JSON。
    def test_tools_unsupported_falls_back_to_json_protocol(self) -> None:
        """验证端点明确拒绝 tools 时会降级解析严格 JSON。"""
        unsupported = FakeResponse({}, status_code=400, text="tools is not supported")
        fallback = FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"reply":"已经记下啦","reminders":[{"title":"休息","due_at":"2026-07-10T13:00:00"}]}'
                        }
                    }
                ]
            }
        )
        with patch("ai.deepseek_client.requests.post", side_effect=[unsupported, fallback]) as post:
            result = self.client.chat_with_reminder_tools(self.messages, self.messages)

        self.assertEqual(result.protocol, "json")
        self.assertEqual(result.reminder_calls[0].due_at, "2026-07-10T13:00:00")
        self.assertIn("tools", post.call_args_list[0].kwargs["json"])
        self.assertNotIn("tools", post.call_args_list[1].kwargs["json"])

    # 验证未知工具和多余字段不会产生可执行调用；普通 chat 保持兼容。
    def test_invalid_tool_call_is_rejected_and_plain_chat_still_works(self) -> None:
        """验证未知工具和多余字段不会产生可执行调用；普通 chat 保持兼容。"""
        invalid = FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {"function": {"name": "delete_reminder", "arguments": "{}"}}
                            ],
                        }
                    }
                ]
            }
        )
        plain = FakeResponse({"choices": [{"message": {"content": "普通回复"}}]})
        with patch("ai.deepseek_client.requests.post", side_effect=[invalid, plain]):
            invalid_result = self.client.chat_with_reminder_tools(self.messages, self.messages)
            plain_reply = self.client.chat(self.messages)

        self.assertTrue(invalid_result.invalid_tool_calls)
        self.assertEqual(invalid_result.reminder_calls, [])
        self.assertEqual(plain_reply, "普通回复")


if __name__ == "__main__":
    unittest.main()
