from __future__ import annotations

from typing import Any


DEFAULT_CONTEXT_BUDGET = {
    "max_prompt_chars": 12000,
    "max_history_messages": 12,
    "max_user_message_chars": 1200,
    "max_history_message_chars": 600,
    "max_summary_chars": 1200,
    "max_memory_chars": 1200,
    "max_mem0_chars": 1000,
    "summary_max_input_chars": 5000,
    "memory_extract_max_input_chars": 3500,
}


# 根据 config 读取预算配置，返回当前流程使用的限制值。
def read_context_budget(config: dict[str, Any] | None) -> dict[str, int]:
    """根据 config 读取预算配置，返回当前流程使用的限制值。"""
    api_config = (config or {}).get("api", {})
    budget: dict[str, int] = {}
    for key, default in DEFAULT_CONTEXT_BUDGET.items():
        budget[key] = _safe_positive_int(api_config.get(key), default)
    return budget


# 根据 text、limit 整理clip 文本，并把结果交给调用方或写回状态。
def clip_text(text: Any, limit: int) -> str:
    """根据 text、limit 整理clip 文本，并把结果交给调用方或写回状态。"""
    content = str(text or "").strip()
    if limit <= 0 or len(content) <= limit:
        return content
    if limit <= 3:
        return content[:limit]
    head = max(1, limit - 3)
    return content[:head] + "..."


# 根据 value、default 转换为正整数，失败或小于等于零时返回默认值。
def _safe_positive_int(value: Any, default: int) -> int:
    """根据 value、default 转换为正整数，失败或小于等于零时返回默认值。"""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
