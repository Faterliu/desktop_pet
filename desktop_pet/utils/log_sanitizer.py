from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


DEFAULT_TEXT_LIMIT = 300


# 根据 value、visible_prefix、visible_suffix 脱敏或截断API密钥，避免日志暴露敏感内容。
def mask_api_key(value: Any, visible_prefix: int = 4, visible_suffix: int = 4) -> str:
    """根据 value、visible_prefix、visible_suffix 脱敏或截断API密钥，避免日志暴露敏感内容。"""
    text = str(value or "").strip()
    if not text:
        return ""

    min_masked_length = visible_prefix + visible_suffix + 3
    if len(text) <= min_masked_length:
        return "***"

    return f"{text[:visible_prefix]}...{text[-visible_suffix:]}"


# 根据 value 脱敏或截断secrets，避免日志暴露敏感内容。
def redact_secrets(value: Any) -> str:
    """根据 value 脱敏或截断secrets，避免日志暴露敏感内容。"""
    text = str(value or "")

    # 根据 match 脱敏或截断bearer，避免日志暴露敏感内容。
    def mask_bearer(match: re.Match[str]) -> str:
        """根据 match 脱敏或截断bearer，避免日志暴露敏感内容。"""
        return f"{match.group(1)}{mask_api_key(match.group(2))}"

    # 根据 match 脱敏或截断named密钥，避免日志暴露敏感内容。
    def mask_named_key(match: re.Match[str]) -> str:
        """根据 match 脱敏或截断named密钥，避免日志暴露敏感内容。"""
        return f"{match.group(1)}{mask_api_key(match.group(2))}"

    text = re.sub(r"(Bearer\s+)([A-Za-z0-9._\-]{8,})", mask_bearer, text)
    text = re.sub(
        r"((?:api[_-]?key|dashscope_api_key|authorization)\s*[=:]\s*)([^\s,;'\"]{8,})",
        mask_named_key,
        text,
        flags=re.IGNORECASE,
    )
    return text


# 根据 value、max_chars 脱敏或截断文本，避免日志暴露敏感内容。
def truncate_text(value: Any, max_chars: int = DEFAULT_TEXT_LIMIT) -> str:
    """根据 value、max_chars 脱敏或截断文本，避免日志暴露敏感内容。"""
    text = redact_secrets(value)
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text

    marker = "...[truncated]"
    if max_chars <= len(marker):
        return marker[:max_chars]
    return f"{text[: max_chars - len(marker)]}{marker}"


# 把异常类型和消息脱敏后截断为可安全写入日志的文本。
def safe_exception(exc: BaseException, max_chars: int = DEFAULT_TEXT_LIMIT) -> str:
    """把异常类型和消息脱敏后截断为可安全写入日志的文本。"""
    return truncate_text(f"{exc.__class__.__name__}: {exc}", max_chars=max_chars)


# 提取 API 响应的键、choices 和 message 结构，避免记录原始内容。
def response_shape(data: Any) -> dict[str, Any]:
    """提取 API 响应的键、choices 和 message 结构，避免记录原始内容。"""
    if not isinstance(data, Mapping):
        return {"type": type(data).__name__}

    choices = data.get("choices")
    shape: dict[str, Any] = {
        "keys": sorted(str(key) for key in data.keys()),
        "choices_type": type(choices).__name__,
    }
    if isinstance(choices, Sequence) and not isinstance(choices, (str, bytes, bytearray)):
        shape["choices_count"] = len(choices)
        if choices and isinstance(choices[0], Mapping):
            first_choice = choices[0]
            message = first_choice.get("message")
            shape["first_choice_keys"] = sorted(str(key) for key in first_choice.keys())
            if isinstance(message, Mapping):
                shape["message_keys"] = sorted(str(key) for key in message.keys())
                content = message.get("content")
                shape["content_type"] = type(content).__name__
                if isinstance(content, str):
                    shape["content_chars"] = len(content)
    return shape


# 统计消息数量、角色分布和内容长度，返回隐私安全的结构摘要。
def messages_shape(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """统计消息数量、角色分布和内容长度，返回隐私安全的结构摘要。"""
    role_counts: dict[str, int] = {}
    total_chars = 0
    for message in messages:
        role = str(message.get("role", "unknown"))
        role_counts[role] = role_counts.get(role, 0) + 1
        total_chars += len(str(message.get("content", "")))

    return {
        "message_count": len(messages),
        "role_counts": role_counts,
        "content_chars": total_chars,
    }
