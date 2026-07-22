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

from ai.llm_client import LlmClient, LlmError  # noqa: E402


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


class InvalidJsonResponse(FakeResponse):
    # 模拟成功状态下返回非 JSON 内容的响应。
    def json(self) -> dict:
        """模拟成功状态下返回非 JSON 内容的响应。"""
        raise ValueError("invalid json")


class LlmClientToolTests(unittest.TestCase):
    # 构建不依赖配置文件的已配置客户端替身。
    def setUp(self) -> None:
        """构建不依赖配置文件的已配置客户端替身。"""
        self.client = LlmClient("unused.json")
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
        with patch("ai.llm_client.requests.post", return_value=response) as post:
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
        with patch("ai.llm_client.requests.post", side_effect=[unsupported, fallback]) as post:
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
        with patch("ai.llm_client.requests.post", side_effect=[invalid, plain]):
            invalid_result = self.client.chat_with_reminder_tools(self.messages, self.messages)
            plain_reply = self.client.chat(self.messages)

        self.assertTrue(invalid_result.invalid_tool_calls)
        self.assertEqual(invalid_result.reminder_calls, [])
        self.assertEqual(plain_reply, "普通回复")

    # 验证聊天读取唯一 OpenAI 配置，并复用 Chat Completions 请求路径。
    def test_openai_config_uses_chat_completions_without_temperature(self) -> None:
        """验证聊天读取唯一 OpenAI 配置，并复用 Chat Completions 请求路径。"""
        config = {
            "api": {
                "provider": "openai",
                "openai": {
                    "api_key": "openai-key",
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-5",
                    "timeout_seconds": 15,
                },
            }
        }
        response = FakeResponse({"choices": [{"message": {"content": "GPT 回复"}}]})
        client = LlmClient("unused-openai.json")
        with patch("ai.llm_client.load_json_prefer_primary", return_value=config):
            with patch("ai.llm_client.requests.post", return_value=response) as post:
                self.assertEqual(client.provider_name(), "openai")
                self.assertTrue(client.is_configured())
                self.assertEqual(client.chat(self.messages), "GPT 回复")

        self.assertEqual(post.call_args.args[0], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer openai-key")
        self.assertEqual(post.call_args.kwargs["json"]["model"], "gpt-5")
        self.assertNotIn("temperature", post.call_args.kwargs["json"])

    # 验证 OpenAI Responses 协议使用与连接脚本一致的 instructions 和文本 input。
    def test_openai_responses_provider_uses_responses_endpoint(self) -> None:
        """验证 OpenAI Responses 协议使用与连接脚本一致的 instructions 和文本 input。"""
        config = {
            "api": {
                "provider": "openai",
                "openai": {
                    "api_key": "openai-key",
                    "base_url": "https://provider.test",
                    "wire_api": "responses",
                    "model": "gpt-5.5",
                },
            }
        }
        response = FakeResponse(
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Responses 回复"}],
                    }
                ]
            }
        )
        client = LlmClient("unused-responses.json")
        messages = [
            {"role": "system", "content": "请简短、直接地回答。"},
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好呀"},
            {"role": "user", "content": "再说一句"},
        ]
        with patch("ai.llm_client.load_json_prefer_primary", return_value=config):
            with patch("ai.llm_client.requests.post", return_value=response) as post:
                self.assertEqual(client.chat(messages), "Responses 回复")

        self.assertEqual(post.call_args.args[0], "https://provider.test/responses")
        self.assertEqual(post.call_args.kwargs["json"]["instructions"], "请简短、直接地回答。")
        self.assertEqual(
            post.call_args.kwargs["json"]["input"],
            "用户：你好\n\n助手：你好呀\n\n用户：再说一句",
        )
        self.assertNotIn("messages", post.call_args.kwargs["json"])

    # 构建 KLD 主线路及其 DeepSeek 降级配置。
    def _kldai_config(self, *, with_deepseek: bool = True) -> dict:
        """返回用于线路切换测试的完整嵌套 API 配置。"""
        config = {
            "api": {
                "provider": "openai",
                "openai": {
                    "api_key": "openai-key",
                    "base_url": "https://www.kldai.cc",
                    "wire_api": "responses",
                    "model": "gpt-5.5",
                },
            }
        }
        if with_deepseek:
            config["api"]["deepseek"] = {
                "api_key": "deepseek-key",
                "base_url": "https://api.deepseek.com",
                "model": "deepseek-v4-flash",
            }
        return config

    # 验证 KLD 主线路的可重试故障会使用同参数的备用地址。
    def test_kldai_retryable_failures_fall_back_to_secondary_route(self) -> None:
        """验证超时、连接故障、限流和服务端错误均只切换到 KLD 备用地址。"""
        retryable_failures: list[object] = [
            requests.Timeout("late"),
            requests.exceptions.SSLError("connection reset"),
            requests.ConnectionError("connection reset"),
            FakeResponse({}, status_code=429),
            FakeResponse({}, status_code=503),
        ]
        secondary = FakeResponse({"output_text": "KLD 备用地址回复"})
        client = LlmClient("unused-kldai.json")
        for failure in retryable_failures:
            with self.subTest(failure=type(failure).__name__):
                with patch("ai.llm_client.load_json_prefer_primary", return_value=self._kldai_config()):
                    with patch(
                        "ai.llm_client.requests.post",
                        side_effect=[failure, secondary],
                    ) as post:
                        self.assertEqual(client.chat(self.messages), "KLD 备用地址回复")

                self.assertEqual(post.call_count, 2)
                self.assertEqual(post.call_args_list[0].args[0], "https://www.kldai.cc/responses")
                self.assertEqual(post.call_args_list[1].args[0], "https://www.kldai.vip/responses")
                self.assertEqual(post.call_args_list[0].kwargs["headers"], post.call_args_list[1].kwargs["headers"])
                self.assertEqual(post.call_args_list[0].kwargs["json"], post.call_args_list[1].kwargs["json"])

    # 验证两条 KLD 文本线路均不可用时才使用独立 DeepSeek 配置。
    def test_kldai_routes_fall_back_to_deepseek(self) -> None:
        """验证线路顺序为 KLD 主地址、KLD 备用地址、DeepSeek，且不循环重试。"""
        fallback = FakeResponse({"choices": [{"message": {"content": "DeepSeek 降级回复"}}]})
        client = LlmClient("unused-kldai.json")
        with patch("ai.llm_client.load_json_prefer_primary", return_value=self._kldai_config()):
            with patch(
                "ai.llm_client.requests.post",
                side_effect=[requests.Timeout("late"), FakeResponse({}, status_code=503), fallback],
            ) as post:
                self.assertEqual(client.chat(self.messages), "DeepSeek 降级回复")

        self.assertEqual(post.call_args_list[0].args[0], "https://www.kldai.cc/responses")
        self.assertEqual(post.call_args_list[1].args[0], "https://www.kldai.vip/responses")
        self.assertEqual(post.call_args_list[2].args[0], "https://api.deepseek.com/chat/completions")
        fallback_payload = post.call_args_list[2].kwargs["json"]
        self.assertEqual(fallback_payload["model"], "deepseek-v4-flash")
        self.assertEqual(fallback_payload["messages"], self.messages)
        self.assertEqual(fallback_payload["temperature"], 0.7)

    # 验证两条 KLD 均失败但未配置 DeepSeek 时不会请求不存在的备用服务。
    def test_kldai_routes_report_missing_deepseek_fallback(self) -> None:
        """验证 DeepSeek 缺失时明确失败，且两条 KLD 地址只各请求一次。"""
        client = LlmClient("unused-kldai.json")
        with patch("ai.llm_client.load_json_prefer_primary", return_value=self._kldai_config(with_deepseek=False)):
            with patch(
                "ai.llm_client.requests.post",
                side_effect=[requests.Timeout("late"), requests.Timeout("late")],
            ) as post:
                with self.assertRaisesRegex(LlmError, "DeepSeek 降级服务未配置"):
                    client.chat(self.messages)

        self.assertEqual(post.call_count, 2)

    # 验证 DeepSeek 的最终失败会直接返回，不再重新请求任一 KLD 地址。
    def test_deepseek_failure_does_not_restart_kldai_routes(self) -> None:
        """验证三段式线路至多请求一次，避免故障时形成循环重试。"""
        client = LlmClient("unused-kldai.json")
        with patch("ai.llm_client.load_json_prefer_primary", return_value=self._kldai_config()):
            with patch(
                "ai.llm_client.requests.post",
                side_effect=[requests.Timeout("late"), requests.Timeout("late"), requests.Timeout("late")],
            ) as post:
                with self.assertRaisesRegex(LlmError, "没来得及想好"):
                    client.chat(self.messages)

        self.assertEqual(post.call_count, 3)

    # 验证 KLD 故障后的提醒 tools 请求会在 DeepSeek 继续执行原生协议。
    def test_reminder_tools_fall_back_through_both_kldai_routes_to_deepseek(self) -> None:
        """验证提醒工具调用继承三段式文本线路并保留 tools 载荷。"""
        tool_response = FakeResponse(
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
        client = LlmClient("unused-kldai-tools.json")
        with patch("ai.llm_client.load_json_prefer_primary", return_value=self._kldai_config()):
            with patch(
                "ai.llm_client.requests.post",
                side_effect=[requests.Timeout("late"), requests.Timeout("late"), tool_response],
            ) as post:
                result = client.chat_with_reminder_tools(self.messages, self.messages)

        self.assertEqual(result.protocol, "native")
        self.assertEqual(result.reminder_calls[0].title, "开会")
        self.assertEqual(post.call_args_list[2].args[0], "https://api.deepseek.com/chat/completions")
        self.assertIn("tools", post.call_args_list[2].kwargs["json"])

    # 验证 DeepSeek 不支持 tools 时，严格 JSON 协议仍在 DeepSeek 执行。
    def test_deepseek_tools_json_fallback_stays_on_deepseek(self) -> None:
        """验证工具协议降级不会回跳已不可用的 KLD 地址。"""
        unsupported = FakeResponse({}, status_code=400, text="tools is not supported")
        json_response = FakeResponse(
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
        client = LlmClient("unused-kldai-tools.json")
        with patch("ai.llm_client.load_json_prefer_primary", return_value=self._kldai_config()):
            with patch(
                "ai.llm_client.requests.post",
                side_effect=[requests.Timeout("late"), requests.Timeout("late"), unsupported, json_response],
            ) as post:
                result = client.chat_with_reminder_tools(self.messages, self.messages)

        self.assertEqual(result.protocol, "json")
        self.assertEqual(result.reminder_calls[0].title, "休息")
        self.assertEqual(post.call_count, 4)
        self.assertEqual(post.call_args_list[2].args[0], "https://api.deepseek.com/chat/completions")
        self.assertEqual(post.call_args_list[3].args[0], "https://api.deepseek.com/chat/completions")
        self.assertIn("tools", post.call_args_list[2].kwargs["json"])
        self.assertNotIn("tools", post.call_args_list[3].kwargs["json"])

    # 验证普通客户端错误不会把非服务故障请求切换到备用线路。
    def test_kldai_non_retryable_client_error_does_not_fallback(self) -> None:
        """验证认证、参数等普通 4xx 错误保持原线路错误语义。"""
        client = LlmClient("unused-kldai.json")
        with patch("ai.llm_client.load_json_prefer_primary", return_value=self._kldai_config()):
            with patch("ai.llm_client.requests.post", return_value=FakeResponse({}, status_code=400)) as post:
                with self.assertRaisesRegex(LlmError, "稍后再试"):
                    client.chat(self.messages)

        self.assertEqual(post.call_count, 1)

    # 验证其他 OpenAI Responses 地址不参与 KLD 双地址及 DeepSeek 线路切换。
    def test_non_kldai_timeout_does_not_fallback(self) -> None:
        """验证非 KLD 地址超时后保持原有单线路错误行为。"""
        config = self._kldai_config()
        config["api"]["openai"]["base_url"] = "https://provider.test"
        client = LlmClient("unused-openai.json")
        with patch("ai.llm_client.load_json_prefer_primary", return_value=config):
            with patch("ai.llm_client.requests.post", side_effect=requests.Timeout("late")) as post:
                with self.assertRaisesRegex(LlmError, "没来得及想好"):
                    client.chat(self.messages)

        self.assertEqual(post.call_count, 1)

    # 验证 Responses 协议会将函数调用规范为现有提醒工具参数。
    def test_responses_provider_parses_function_call(self) -> None:
        """验证 Responses 协议会将函数调用规范为现有提醒工具参数。"""
        config = {
            "api": {
                "provider": "openai",
                "openai": {
                    "api_key": "openai-key",
                    "base_url": "https://provider.test",
                    "wire_api": "responses",
                    "model": "gpt-5.5",
                },
            }
        }
        response = FakeResponse(
            {
                "output": [
                    {
                        "type": "function_call",
                        "name": "create_reminder",
                        "arguments": '{"title":"开会","due_at":"2026-07-11T09:00:00"}',
                    }
                ]
            }
        )
        client = LlmClient("unused-responses-tools.json")
        with patch("ai.llm_client.load_json_prefer_primary", return_value=config):
            with patch("ai.llm_client.requests.post", return_value=response) as post:
                result = client.chat_with_reminder_tools(self.messages, self.messages)

        self.assertEqual(result.reminder_calls[0].title, "开会")
        tools = post.call_args.kwargs["json"]["tools"]
        self.assertEqual(tools[0]["type"], "function")
        self.assertEqual(tools[0]["name"], "create_reminder")
        self.assertTrue(tools[0]["strict"])

    # 验证 DeepSeek 提供商只读取嵌套配置。
    def test_deepseek_provider_uses_nested_config(self) -> None:
        """验证 DeepSeek 提供商只读取嵌套配置。"""
        config = {
            "api": {
                "provider": "deepseek",
                "deepseek": {
                    "api_key": "deepseek-key",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-v4-flash",
                    "timeout_seconds": 20,
                },
            }
        }
        response = FakeResponse({"choices": [{"message": {"content": "DeepSeek 回复"}}]})
        client = LlmClient("unused-deepseek.json")
        with patch("ai.llm_client.load_json_prefer_primary", return_value=config):
            with patch("ai.llm_client.requests.post", return_value=response) as post:
                self.assertEqual(client.provider_name(), "deepseek")
                self.assertEqual(client.chat(self.messages), "DeepSeek 回复")

        self.assertEqual(post.call_args.kwargs["json"]["model"], "deepseek-v4-flash")
        self.assertEqual(post.call_args.kwargs["json"]["temperature"], 0.7)

    # 验证已废弃的 OpenAI 别名不再被识别为 OpenAI 提供商。
    def test_openai_provider_aliases_are_not_supported(self) -> None:
        """验证 gpt 与 gpt_openai 不再作为 OpenAI 的配置别名。"""
        for alias in ("gpt", "gpt_openai"):
            with self.subTest(alias=alias):
                client = LlmClient("unused-provider-alias.json")
                with patch(
                    "ai.llm_client.load_json_prefer_primary",
                    return_value={"api": {"provider": alias, "openai": {"api_key": "openai-key"}}},
                ):
                    self.assertEqual(client.provider_name(), "deepseek")
                    self.assertFalse(client.is_configured())

    # 验证旧版扁平 API 字段不再作为 DeepSeek 连接配置读取。
    def test_flat_deepseek_api_config_is_not_supported(self) -> None:
        """验证客户端只读取 api.deepseek 的嵌套配置。"""
        client = LlmClient("unused-flat-api.json")
        with patch(
            "ai.llm_client.load_json_prefer_primary",
            return_value={"api": {"provider": "deepseek", "api_key": "legacy-key"}},
        ):
            self.assertFalse(client.is_configured())

    # 验证非 JSON 响应会归类为可识别的模型服务响应错误。
    def test_invalid_json_response_raises_specific_error(self) -> None:
        """验证非 JSON 响应会归类为可识别的模型服务响应错误。"""
        with patch(
            "ai.llm_client.requests.post",
            return_value=InvalidJsonResponse({}),
        ):
            with self.assertRaisesRegex(LlmError, "无法解析"):
                self.client.chat(self.messages)

    # 验证视觉请求使用唯一 OpenAI 配置并构建已验证的 Responses 图片载荷。
    def test_vision_request_uses_openai_responses_payload(self) -> None:
        """验证视觉请求使用唯一 OpenAI 配置和 Responses。"""
        config = {
            "api": {
                "openai": {
                    "api_key": "openai-key",
                    "base_url": "https://vision.test/v1",
                    "model": "gpt-5.5",
                    "timeout_seconds": 45,
                },
            }
        }
        response = FakeResponse({"output_text": "截图里是一个设置页面。"})
        client = LlmClient("unused-vision.json")
        with patch("ai.llm_client.load_json_prefer_primary", return_value=config):
            with patch("ai.llm_client.requests.post", return_value=response) as post:
                self.assertTrue(client.is_vision_configured())
                reply = client.analyze_image(
                    b"\x89PNG\r\n",
                    "image/png",
                    "请解析截图",
                    detail="auto",
                    max_output_tokens=80,
                )

        self.assertEqual(reply, "截图里是一个设置页面。")
        self.assertEqual(post.call_args.args[0], "https://vision.test/v1/responses")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer openai-key")
        self.assertEqual(post.call_args.kwargs["timeout"], 45)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "gpt-5.5")
        self.assertEqual(payload["max_output_tokens"], 80)
        self.assertEqual(
            [part["type"] for part in payload["input"][0]["content"]],
            ["input_text", "input_image"],
        )
        image_part = payload["input"][0]["content"][1]
        self.assertEqual(image_part["detail"], "auto")
        self.assertEqual(image_part["image_url"], "data:image/png;base64,iVBORw0K")

    # 验证视觉 Responses 的嵌套 output 文本仍能复用统一解析逻辑。
    def test_vision_request_parses_nested_output_text(self) -> None:
        """验证没有 output_text 快捷字段时提取 output 内容。"""
        config = {
            "api": {
                "openai": {
                    "api_key": "openai-key",
                    "base_url": "https://vision.test/v1",
                    "model": "gpt-5.5",
                },
            }
        }
        response = FakeResponse(
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "嵌套回复"}],
                    }
                ]
            }
        )
        client = LlmClient("unused-vision.json")
        with patch("ai.llm_client.load_json_prefer_primary", return_value=config):
            with patch("ai.llm_client.requests.post", return_value=response):
                self.assertEqual(
                    client.analyze_image(b"jpeg", "image/jpeg", "解析"),
                    "嵌套回复",
                )

    # 验证视觉请求拒绝空图片并把超时转换为安全错误。
    def test_vision_request_validates_empty_image_and_handles_timeout(self) -> None:
        """验证视觉请求的输入校验和超时错误。"""
        client = LlmClient("unused-vision.json")
        with self.assertRaisesRegex(LlmError, "截图内容为空"):
            client.analyze_image(b"", "image/png", "解析")

        config = {
            "api": {
                "openai": {
                    "api_key": "openai-key",
                    "base_url": "https://vision.test/v1",
                    "model": "gpt-5.5",
                }
            }
        }
        with patch("ai.llm_client.load_json_prefer_primary", return_value=config):
            with patch("ai.llm_client.requests.post", side_effect=requests.Timeout("late")) as post:
                with self.assertRaisesRegex(LlmError, "超时"):
                    client.analyze_image(b"png", "image/png", "解析")

        self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
