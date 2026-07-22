from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import requests

from storage.json_store import load_json_prefer_primary
from utils.log_sanitizer import messages_shape, response_shape, safe_exception
from utils.logger import get_logger


logger = get_logger(__name__)


class LlmError(RuntimeError):
    pass


class KldaiTextServiceUnavailableError(LlmError):
    """KLD AI 文本线路不可用，可依次切换备用网址和 DeepSeek。"""


class ToolCallingUnsupportedError(LlmError):
    """当前 OpenAI 兼容端点明确不支持 tools 参数。"""

    def __init__(self, message: str, api: dict[str, Any] | None = None) -> None:
        """保存不支持 tools 的当前线路，供严格 JSON 协议继续复用。"""
        super().__init__(message)
        self.api = dict(api) if isinstance(api, dict) else None


@dataclass(frozen=True)
class ReminderToolCall:
    """模型返回的已校验提醒工具调用参数。"""

    title: str
    due_at: str


@dataclass(frozen=True)
class ToolChatResponse:
    """模型普通回复或提醒工具调用的统一结果。"""

    reply: str
    reminder_calls: list[ReminderToolCall]
    protocol: Literal["native", "json", "plain"]
    invalid_tool_calls: bool = False


REMINDER_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "create_reminder",
        "description": "创建一条本机本地时间的提醒。仅在用户明确要求设置提醒且时间和内容完整时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "简短的提醒内容"},
                "due_at": {
                    "type": "string",
                    "description": "本地 ISO 时间，格式 YYYY-MM-DDTHH:MM:SS",
                },
            },
            "required": ["title", "due_at"],
            "additionalProperties": False,
        },
    },
}


class LlmClient:
    # 初始化当前对象及其依赖。
    def __init__(self, config_path: str | Path, fallback_config_path: str | Path | None = None) -> None:
        """初始化当前对象及其依赖。"""
        self.config_path = Path(config_path)
        self.fallback_config_path = Path(fallback_config_path) if fallback_config_path else self.config_path

    # 读取配置片段，缺失时返回安全默认配置。
    def _api_config(self) -> dict[str, Any]:
        """读取当前选择的供应商连接配置。"""
        config = load_json_prefer_primary(self.config_path, self.fallback_config_path, {})
        raw_api = config.get("api", {}) if isinstance(config, dict) else {}
        api = raw_api if isinstance(raw_api, dict) else {}
        if self._provider_name(api) != "openai":
            deepseek = api.get("deepseek")
            if not isinstance(deepseek, dict):
                return {}
            return {
                "api_key": str(deepseek.get("api_key", "")).strip(),
                "base_url": str(deepseek.get("base_url", "https://api.deepseek.com")),
                "model": str(deepseek.get("model", "deepseek-chat")),
                "timeout_seconds": deepseek.get("timeout_seconds", 30),
                "provider": "deepseek",
                "wire_api": "chat_completions",
            }

        return self._openai_api_config(api)

    # 固定读取 DeepSeek 连接配置，供 KLD AI SSL 中断后的降级使用。
    def _deepseek_api_config(self) -> dict[str, Any]:
        """读取独立 DeepSeek 配置，不受当前聊天提供商选择影响。"""
        config = load_json_prefer_primary(self.config_path, self.fallback_config_path, {})
        raw_api = config.get("api", {}) if isinstance(config, dict) else {}
        api = raw_api if isinstance(raw_api, dict) else {}
        deepseek = api.get("deepseek")
        if not isinstance(deepseek, dict):
            return {}
        return {
            "api_key": str(deepseek.get("api_key", "")).strip(),
            "base_url": str(deepseek.get("base_url", "https://api.deepseek.com")),
            "model": str(deepseek.get("model", "deepseek-chat")),
            "timeout_seconds": deepseek.get("timeout_seconds", 30),
            "provider": "deepseek",
            "wire_api": "chat_completions",
        }

    # 固定读取 OpenAI 连接配置，供不跟随聊天提供商的视觉请求使用。
    def _openai_api_config(self, api: dict[str, Any] | None = None) -> dict[str, Any]:
        """读取 OpenAI 连接配置，不受当前聊天提供商选择影响。"""
        if api is None:
            config = load_json_prefer_primary(self.config_path, self.fallback_config_path, {})
            raw_api = config.get("api", {}) if isinstance(config, dict) else {}
            api = raw_api if isinstance(raw_api, dict) else {}
        openai = api.get("openai", {})
        if not isinstance(openai, dict):
            openai = {}
        api_key = str(openai.get("api_key", "")).strip()
        if not api_key:
            api_key = os.getenv(str(openai.get("api_key_env", "OPENAI_API_KEY")), "").strip()
        return {
            "api_key": api_key,
            "base_url": str(openai.get("base_url", "https://api.openai.com/v1")),
            "model": str(openai.get("model", "gpt-5")),
            "timeout_seconds": openai.get("timeout_seconds", 30),
            "provider": "openai",
            "wire_api": self._wire_api(openai.get("wire_api", "chat_completions")),
        }

    # 返回规范化后的聊天模型提供商名称。
    def provider_name(self) -> str:
        """返回规范化后的聊天模型提供商名称。"""
        config = load_json_prefer_primary(self.config_path, self.fallback_config_path, {})
        api = config.get("api", {}) if isinstance(config, dict) else {}
        return self._provider_name(api if isinstance(api, dict) else {})

    # 仅接受精确的 openai 标识；其余值维持 DeepSeek 提供商。
    def _provider_name(self, api: dict[str, Any]) -> str:
        """仅接受精确的 openai 标识；其余值维持 DeepSeek 提供商。"""
        provider = str(api.get("provider", "deepseek")).strip().lower()
        return "openai" if provider == "openai" else "deepseek"

    # 将提供商连接协议规范为当前支持的 Chat Completions 或 Responses API。
    def _wire_api(self, value: Any) -> str:
        """将提供商连接协议规范为当前支持的 Chat Completions 或 Responses API。"""
        return "responses" if str(value).strip().lower() == "responses" else "chat_completions"

    # 判断必需配置是否完整，并返回客户端是否可以调用。
    def is_configured(self) -> bool:
        """判断必需配置是否完整，并返回客户端是否可以调用。"""
        return bool(self._api_config().get("api_key", "").strip())

    # 判断 OpenAI 视觉请求所需配置是否完整。
    def is_vision_configured(self) -> bool:
        """判断 OpenAI 视觉请求所需的 API key、地址和模型是否完整。"""
        api = self._openai_api_config()
        return bool(
            str(api.get("api_key", "")).strip()
            and str(api.get("base_url", "")).strip()
            and str(api.get("model", "")).strip()
        )

    # 将内存图片作为 Data URL 发送给固定 OpenAI Responses API。
    def analyze_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        prompt: str,
        *,
        detail: str = "auto",
        max_output_tokens: int = 80,
    ) -> str:
        """发送单张内存图片并返回 Responses API 提取出的文字结果。"""
        if not image_bytes:
            raise LlmError("截图内容为空，无法解析。")
        normalized_mime = str(mime_type).strip().lower()
        if normalized_mime not in {"image/png", "image/jpeg"}:
            raise LlmError("截图格式不受支持。")
        normalized_prompt = str(prompt).strip()
        if not normalized_prompt:
            raise LlmError("截图解析提示不能为空。")

        api = self._openai_api_config()
        api_key = str(api.get("api_key", "")).strip()
        if not api_key:
            raise LlmError("OpenAI API key 未配置，暂时不能解析截图。")
        base_url = str(api.get("base_url", "https://api.openai.com/v1")).rstrip("/")
        model = str(api.get("model", "")).strip()
        if not model:
            raise LlmError("OpenAI 模型未配置，暂时不能解析截图。")
        timeout_seconds = api.get("timeout_seconds", 30)
        normalized_detail = str(detail).strip().lower()
        if normalized_detail not in {"low", "high", "original", "auto"}:
            normalized_detail = "auto"
        try:
            output_limit = max(1, int(max_output_tokens))
        except (TypeError, ValueError):
            output_limit = 80

        encoded = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "model": model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": normalized_prompt},
                        {
                            "type": "input_image",
                            "image_url": f"data:{normalized_mime};base64,{encoded}",
                            "detail": normalized_detail,
                        },
                    ],
                }
            ],
            "max_output_tokens": output_limit,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(
                f"{base_url}/responses",
                headers=headers,
                json=payload,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except requests.Timeout as exc:
            logger.error("Vision API request timed out: %s", safe_exception(exc))
            raise LlmError("截图解析超时了，请稍后再试。") from exc
        except requests.HTTPError as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            logger.error(
                "Vision API request failed: %s status_code=%s",
                safe_exception(exc),
                status_code,
            )
            raise LlmError("截图解析服务暂时无法完成请求。") from exc
        except ValueError as exc:
            logger.error("Vision API returned invalid JSON: %s", safe_exception(exc))
            raise LlmError("截图解析服务返回了无法解析的响应。") from exc
        except requests.RequestException as exc:
            logger.error("Vision API request failed: %s", safe_exception(exc))
            raise LlmError("截图解析服务暂时无法连接。") from exc

        reply = self._message_content(self._responses_message(data))
        if not reply:
            raise LlmError("截图解析没有返回可显示的文字。")
        return reply

    # 根据 messages 处理聊天消息流程，更新上下文和展示状态。
    def chat(self, messages: list[dict[str, str]]) -> str:
        """根据 messages 处理聊天消息流程，更新上下文和展示状态。"""
        message, _api = self._request_text_message(messages)
        return self._message_content(message)

    # 优先使用原生工具调用；端点不支持时用严格 JSON 协议降级。
    def chat_with_reminder_tools(
        self,
        messages: list[dict[str, str]],
        json_fallback_messages: list[dict[str, str]],
    ) -> ToolChatResponse:
        """优先使用原生工具调用；端点不支持时用严格 JSON 协议降级。"""
        try:
            message, _api = self._request_text_message(
                messages,
                tools=[REMINDER_TOOL_DEFINITION],
                tool_choice="auto",
            )
        except ToolCallingUnsupportedError as exc:
            json_message, _api = self._request_text_message(
                json_fallback_messages,
                initial_api=exc.api,
            )
            return self._parse_json_reminder_response(self._message_content(json_message))

        reply = self._message_content(message)
        raw_calls = message.get("tool_calls") if isinstance(message, dict) else None
        if not raw_calls:
            return ToolChatResponse(reply, [], "native")
        calls = self._parse_native_reminder_calls(raw_calls)
        if calls is None:
            return ToolChatResponse(
                "提醒信息格式不完整，请告诉我准确的日期、时间和提醒内容。",
                [],
                "native",
                invalid_tool_calls=True,
            )
        return ToolChatResponse(reply, calls, "native")

    # 按 KLD 主地址、KLD 备用地址、DeepSeek 的顺序发送一次文本请求。
    def _request_text_message(
        self,
        messages: list[dict[str, str]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        initial_api: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """按文本线路优先级请求消息，并返回消息和实际使用的连接配置。"""
        api = dict(initial_api) if isinstance(initial_api, dict) else self._api_config()
        try:
            return (
                self._request_message(
                    messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    api_override=api,
                ),
                api,
            )
        except KldaiTextServiceUnavailableError:
            route = self._kldai_text_route(api)
            if route == "primary":
                secondary_api = self._kldai_secondary_api(api)
                logger.warning("KLD AI primary text route unavailable; retrying secondary route")
                try:
                    return (
                        self._request_message(
                            messages,
                            tools=tools,
                            tool_choice=tool_choice,
                            api_override=secondary_api,
                        ),
                        secondary_api,
                    )
                except KldaiTextServiceUnavailableError:
                    api = secondary_api
                    route = "secondary"

            if route == "secondary":
                fallback_api = self._deepseek_api_config()
                if not str(fallback_api.get("api_key", "")).strip():
                    logger.warning("KLD AI text routes unavailable; DeepSeek fallback is not configured")
                    raise LlmError("KLD AI 文本服务暂时不可用，DeepSeek 降级服务未配置。") from None
                logger.warning("KLD AI text routes unavailable; retrying through DeepSeek fallback")
                return (
                    self._request_message(
                        messages,
                        tools=tools,
                        tool_choice=tool_choice,
                        api_override=fallback_api,
                    ),
                    fallback_api,
                )
            raise

    # 基于 KLD 主线路配置构建同参数的备用地址连接配置。
    def _kldai_secondary_api(self, primary_api: dict[str, Any]) -> dict[str, Any]:
        """仅替换 KLD 地址，保留主线路的模型、密钥和协议配置。"""
        secondary_api = dict(primary_api)
        secondary_api["base_url"] = "https://www.kldai.vip"
        return secondary_api

    # 按当前提供商协议发送一次请求，并返回统一的助手消息结构。
    def _request_message(
        self,
        messages: list[dict[str, str]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        api_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """按当前提供商协议发送一次请求，并返回统一的助手消息结构。"""
        api = api_override if api_override is not None else self._api_config()
        api_key = api.get("api_key", "").strip()
        if not api_key:
            raise LlmError("当前聊天模型的 API key 未配置。")

        base_url = api.get("base_url", "https://api.deepseek.com").rstrip("/")
        timeout_seconds = api.get("timeout_seconds", 30)
        wire_api = self._wire_api(api.get("wire_api", "chat_completions"))
        is_responses_api = api.get("provider") == "openai" and wire_api == "responses"
        payload = self._request_payload(api, messages, tools, tool_choice, is_responses_api)
        endpoint = "/responses" if is_responses_api else "/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                f"{base_url}{endpoint}",
                headers=headers,
                json=payload,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except requests.Timeout as exc:
            if self._kldai_text_route(api):
                logger.warning(
                    "KLD AI text request timed out; route=%s request=%s",
                    self._kldai_text_route(api),
                    messages_shape(messages),
                )
                raise KldaiTextServiceUnavailableError("KLD AI text request timed out") from exc
            logger.error(
                "Chat API request timed out: %s request=%s",
                safe_exception(exc),
                messages_shape(messages),
            )
            raise LlmError("我刚刚没来得及想好。") from exc
        except requests.exceptions.SSLError as exc:
            if self._kldai_text_route(api):
                logger.warning(
                    "KLD AI text SSL connection interrupted; route=%s request=%s",
                    self._kldai_text_route(api),
                    messages_shape(messages),
                )
                raise KldaiTextServiceUnavailableError("KLD AI text SSL connection interrupted") from exc
            logger.error(
                "Chat API SSL request failed: %s request=%s",
                safe_exception(exc),
                messages_shape(messages),
            )
            raise LlmError("稍后再试试好不好。") from exc
        except requests.HTTPError as exc:
            if tools is not None and self._tools_are_unsupported(exc):
                raise ToolCallingUnsupportedError("Tool calling is unsupported.", api) from exc
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if self._kldai_text_route(api) and self._should_retry_kldai_status(status_code):
                logger.warning(
                    "KLD AI text request failed; route=%s status_code=%s request=%s",
                    self._kldai_text_route(api),
                    status_code,
                    messages_shape(messages),
                )
                raise KldaiTextServiceUnavailableError("KLD AI text service returned a retryable status") from exc
            logger.error(
                "Chat API request failed: %s status_code=%s request=%s",
                safe_exception(exc),
                status_code,
                messages_shape(messages),
            )
            raise LlmError("稍后再试试好不好。") from exc
        except ValueError as exc:
            status_code = getattr(response, "status_code", None) if "response" in locals() else None
            logger.error(
                "Chat API returned invalid JSON: %s status_code=%s request=%s",
                safe_exception(exc),
                status_code,
                messages_shape(messages),
            )
            raise LlmError("模型服务返回了无法解析的响应。") from exc
        except requests.RequestException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if self._kldai_text_route(api):
                logger.warning(
                    "KLD AI text connection failed; route=%s request=%s",
                    self._kldai_text_route(api),
                    messages_shape(messages),
                )
                raise KldaiTextServiceUnavailableError("KLD AI text connection failed") from exc
            logger.error(
                "Chat API request failed: %s status_code=%s request=%s",
                safe_exception(exc),
                status_code,
                messages_shape(messages),
            )
            raise LlmError("稍后再试试好不好。") from exc

        if is_responses_api:
            return self._responses_message(data)

        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.error(
                "Chat API response structure mismatch: %s response=%s",
                safe_exception(exc),
                response_shape(data),
            )
            raise LlmError("回复有点奇怪，我再缓一缓。") from exc
        if not isinstance(message, dict):
            logger.error("Chat API message structure mismatch: response=%s", response_shape(data))
            raise LlmError("回复有点奇怪，我再缓一缓。")
        return message

    # 返回当前 KLD Responses 文本线路角色；非 KLD 地址不参与线路切换。
    def _kldai_text_route(self, api: dict[str, Any]) -> str:
        """识别 KLD 主地址或备用地址，其他文本提供商保持原有行为。"""
        base_url = str(api.get("base_url", "")).rstrip("/").lower()
        is_responses_api = (
            api.get("provider") == "openai"
            and self._wire_api(api.get("wire_api", "chat_completions")) == "responses"
        )
        if not is_responses_api:
            return ""
        if base_url == "https://www.kldai.cc":
            return "primary"
        if base_url == "https://www.kldai.vip":
            return "secondary"
        return ""

    # 判断 KLD 的 HTTP 状态是否应切换到下一条文本线路。
    def _should_retry_kldai_status(self, status_code: Any) -> bool:
        """仅对限流和服务端故障切换线路，避免掩盖请求或认证问题。"""
        try:
            normalized_status = int(status_code)
        except (TypeError, ValueError):
            return False
        return normalized_status == 429 or normalized_status >= 500

    # 构建 Chat Completions 或 Responses API 对应的请求载荷。
    def _request_payload(
        self,
        api: dict[str, Any],
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None,
        tool_choice: str | None,
        is_responses_api: bool,
    ) -> dict[str, Any]:
        """构建 Chat Completions 或 Responses API 对应的请求载荷。"""
        if is_responses_api:
            instructions, input_text = self._responses_instruction_and_input(messages)
            payload: dict[str, Any] = {
                "model": api.get("model", "gpt-5"),
                "input": input_text,
            }
            if instructions:
                payload["instructions"] = instructions
            if tools is not None:
                payload["tools"] = self._responses_tools(tools)
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
            return payload

        payload = {
            "model": api.get("model", "deepseek-chat"),
            "messages": messages,
        }
        if api.get("provider") != "openai":
            payload["temperature"] = 0.7
        if tools is not None:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        return payload

    # 将既有聊天消息拆分为 Responses API 的 instructions 和文本 input。
    def _responses_instruction_and_input(self, messages: list[dict[str, str]]) -> tuple[str, str]:
        """将 system 提示放入 instructions，其余历史整理为可兼容的文本输入。"""
        instructions: list[str] = []
        input_lines: list[str] = []
        role_names = {
            "user": "用户",
            "assistant": "助手",
            "tool": "工具",
        }
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role", "user")).strip().lower()
            content = message.get("content", "")
            if not isinstance(content, str) or not content.strip():
                continue
            text = content.strip()
            if role == "system":
                instructions.append(text)
                continue
            input_lines.append(f"{role_names.get(role, role)}：{text}")
        return "\n\n".join(instructions), "\n\n".join(input_lines)

    # 将 Chat Completions 风格函数定义转换为 Responses API 的函数工具结构。
    def _responses_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """将 Chat Completions 风格函数定义转换为 Responses API 的函数工具结构。"""
        converted: list[dict[str, Any]] = []
        for tool in tools:
            function = tool.get("function") if isinstance(tool, dict) else None
            if not isinstance(function, dict):
                continue
            converted.append(
                {
                    "type": "function",
                    "name": function.get("name", ""),
                    "description": function.get("description", ""),
                    "parameters": function.get("parameters", {}),
                    "strict": True,
                }
            )
        return converted

    # 将 Responses API 的 output 规范为现有聊天流程可消费的消息结构。
    def _responses_message(self, data: Any) -> dict[str, Any]:
        """将 Responses API 的 output 规范为现有聊天流程可消费的消息结构。"""
        if not isinstance(data, dict):
            logger.error("Responses API response structure mismatch: response=%s", response_shape(data))
            raise LlmError("回复有点奇怪，我再缓一缓。")
        if data.get("error"):
            logger.error("Responses API returned an error: response=%s", response_shape(data))
            raise LlmError("模型服务暂时无法完成请求。")

        texts: list[str] = []
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            texts.append(output_text.strip())
        tool_calls: list[dict[str, Any]] = []
        output = data.get("output", [])
        if not isinstance(output, list):
            output = []
        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "function_call":
                tool_calls.append(
                    {
                        "function": {
                            "name": item.get("name", ""),
                            "arguments": item.get("arguments", ""),
                        }
                    }
                )
                continue
            if item.get("type") != "message" or texts:
                continue
            content = item.get("content", [])
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "output_text":
                    continue
                text = part.get("text", "")
                if isinstance(text, str) and text.strip():
                    texts.append(text.strip())
        return {"content": "".join(texts), "tool_calls": tool_calls}

    # 从模型 message 中提取兼容字符串或多段文本内容。
    def _message_content(self, message: dict[str, Any]) -> str:
        """从模型 message 中提取兼容字符串或多段文本内容。"""
        content = message.get("content", "")
        if isinstance(content, list):
            parts = [part.get("text", "") for part in content if isinstance(part, dict)]
            return "".join(parts).strip()
        return str(content or "").strip()

    # 严格解析原生 create_reminder 调用；任一异常调用都会整体拒绝。
    def _parse_native_reminder_calls(self, raw_calls: Any) -> list[ReminderToolCall] | None:
        """严格解析原生 create_reminder 调用；任一异常调用都会整体拒绝。"""
        if not isinstance(raw_calls, list) or not raw_calls or len(raw_calls) > 3:
            return None
        calls: list[ReminderToolCall] = []
        for raw_call in raw_calls:
            if not isinstance(raw_call, dict):
                return None
            function = raw_call.get("function")
            if not isinstance(function, dict) or function.get("name") != "create_reminder":
                return None
            try:
                arguments = json.loads(str(function.get("arguments", "")))
            except (TypeError, ValueError):
                return None
            call = self._parse_reminder_arguments(arguments)
            if call is None:
                return None
            calls.append(call)
        return calls

    # 解析严格 JSON 回退协议；普通非 JSON 回复保持为普通聊天内容。
    def _parse_json_reminder_response(self, raw_reply: str) -> ToolChatResponse:
        """解析严格 JSON 回退协议；普通非 JSON 回复保持为普通聊天内容。"""
        try:
            payload = json.loads(raw_reply)
        except (TypeError, ValueError):
            return ToolChatResponse(raw_reply, [], "plain")
        if not isinstance(payload, dict) or set(payload) != {"reply", "reminders"}:
            return ToolChatResponse(
                "提醒信息格式不完整，请告诉我准确的日期、时间和提醒内容。",
                [],
                "json",
                invalid_tool_calls=True,
            )
        reply = payload.get("reply")
        reminders = payload.get("reminders")
        if not isinstance(reply, str) or not isinstance(reminders, list) or len(reminders) > 3:
            return ToolChatResponse(
                "提醒信息格式不完整，请告诉我准确的日期、时间和提醒内容。",
                [],
                "json",
                invalid_tool_calls=True,
            )
        calls = [self._parse_reminder_arguments(item) for item in reminders]
        if any(call is None for call in calls):
            return ToolChatResponse(
                "提醒信息格式不完整，请告诉我准确的日期、时间和提醒内容。",
                [],
                "json",
                invalid_tool_calls=True,
            )
        return ToolChatResponse(reply.strip(), [call for call in calls if call is not None], "json")

    # 验证提醒参数只包含标题和标准到期时间。
    def _parse_reminder_arguments(self, arguments: Any) -> ReminderToolCall | None:
        """验证提醒参数只包含标题和标准到期时间。"""
        if not isinstance(arguments, dict) or set(arguments) != {"title", "due_at"}:
            return None
        title = arguments.get("title")
        due_at = arguments.get("due_at")
        if not isinstance(title, str) or not isinstance(due_at, str):
            return None
        return ReminderToolCall(title.strip(), due_at.strip())

    # 识别端点对 tools/tool_choice 的明确不支持响应，不吞掉其他网络或 API 错误。
    def _tools_are_unsupported(self, exc: requests.HTTPError) -> bool:
        """识别端点对 tools/tool_choice 的明确不支持响应，不吞掉其他网络或 API 错误。"""
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code not in {400, 404, 422}:
            return False
        text = str(getattr(response, "text", "")).lower()
        return "tool" in text or "function" in text
