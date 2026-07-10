from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import requests

from storage.json_store import load_json_prefer_primary
from utils.log_sanitizer import messages_shape, response_shape, safe_exception
from utils.logger import get_logger


logger = get_logger(__name__)


class DeepSeekError(RuntimeError):
    pass


class ToolCallingUnsupportedError(DeepSeekError):
    """当前 OpenAI 兼容端点明确不支持 tools 参数。"""


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


class DeepSeekClient:
    # 初始化当前对象及其依赖。
    def __init__(self, config_path: str | Path, fallback_config_path: str | Path | None = None) -> None:
        """初始化当前对象及其依赖。"""
        self.config_path = Path(config_path)
        self.fallback_config_path = Path(fallback_config_path) if fallback_config_path else self.config_path

    # 读取配置片段，缺失时返回安全默认配置。
    def _api_config(self) -> dict[str, Any]:
        """读取配置片段，缺失时返回安全默认配置。"""
        config = load_json_prefer_primary(self.config_path, self.fallback_config_path, {})
        return config.get("api", {})

    # 判断必需配置是否完整，并返回客户端是否可以调用。
    def is_configured(self) -> bool:
        """判断必需配置是否完整，并返回客户端是否可以调用。"""
        return bool(self._api_config().get("api_key", "").strip())

    # 根据 messages 处理聊天消息流程，更新上下文和展示状态。
    def chat(self, messages: list[dict[str, str]]) -> str:
        """根据 messages 处理聊天消息流程，更新上下文和展示状态。"""
        message = self._request_message(messages)
        return self._message_content(message)

    # 优先使用原生工具调用；端点不支持时用严格 JSON 协议降级。
    def chat_with_reminder_tools(
        self,
        messages: list[dict[str, str]],
        json_fallback_messages: list[dict[str, str]],
    ) -> ToolChatResponse:
        """优先使用原生工具调用；端点不支持时用严格 JSON 协议降级。"""
        try:
            message = self._request_message(
                messages,
                tools=[REMINDER_TOOL_DEFINITION],
                tool_choice="auto",
            )
        except ToolCallingUnsupportedError:
            return self._parse_json_reminder_response(self.chat(json_fallback_messages))

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

    # 发送一次 Chat Completions 请求并返回首个 message 对象。
    def _request_message(
        self,
        messages: list[dict[str, str]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> dict[str, Any]:
        """发送一次 Chat Completions 请求并返回首个 message 对象。"""
        api = self._api_config()
        api_key = api.get("api_key", "").strip()
        if not api_key:
            raise DeepSeekError("DeepSeek API key is empty.")

        base_url = api.get("base_url", "https://api.deepseek.com").rstrip("/")
        timeout_seconds = api.get("timeout_seconds", 30)
        payload = {
            "model": api.get("model", "deepseek-chat"),
            "messages": messages,
            "temperature": 0.7,
        }
        if tools is not None:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except requests.Timeout as exc:
            logger.error(
                "DeepSeek request timed out: %s request=%s",
                safe_exception(exc),
                messages_shape(messages),
            )
            raise DeepSeekError("我刚刚没来得及想好。") from exc
        except requests.HTTPError as exc:
            if tools is not None and self._tools_are_unsupported(exc):
                raise ToolCallingUnsupportedError("Tool calling is unsupported.") from exc
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            logger.error(
                "DeepSeek request failed: %s status_code=%s request=%s",
                safe_exception(exc),
                status_code,
                messages_shape(messages),
            )
            raise DeepSeekError("稍后再试试好不好。") from exc
        except requests.RequestException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            logger.error(
                "DeepSeek request failed: %s status_code=%s request=%s",
                safe_exception(exc),
                status_code,
                messages_shape(messages),
            )
            raise DeepSeekError("稍后再试试好不好。") from exc
        except ValueError as exc:
            status_code = getattr(response, "status_code", None) if "response" in locals() else None
            logger.error(
                "DeepSeek returned invalid JSON: %s status_code=%s request=%s",
                safe_exception(exc),
                status_code,
                messages_shape(messages),
            )
            raise DeepSeekError("我收到了一段看不懂的回复。") from exc

        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.error(
                "DeepSeek response structure mismatch: %s response=%s",
                safe_exception(exc),
                response_shape(data),
            )
            raise DeepSeekError("回复有点奇怪，我再缓一缓。") from exc
        if not isinstance(message, dict):
            logger.error("DeepSeek message structure mismatch: response=%s", response_shape(data))
            raise DeepSeekError("回复有点奇怪，我再缓一缓。")
        return message

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
