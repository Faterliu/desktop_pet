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


def read_context_budget(config: dict[str, Any] | None) -> dict[str, int]:
    """读取 `read_context_budget` 所需的数据。"""
    api_config = (config or {}).get("api", {})
    budget: dict[str, int] = {}
    for key, default in DEFAULT_CONTEXT_BUDGET.items():
        budget[key] = _safe_positive_int(api_config.get(key), default)
    return budget


def clip_text(text: Any, limit: int) -> str:
    """整理 `clip_text` 对应的文本或数据。"""
    content = str(text or "").strip()
    if limit <= 0 or len(content) <= limit:
        return content
    if limit <= 3:
        return content[:limit]
    head = max(1, limit - 3)
    return content[:head] + "..."


def _safe_positive_int(value: Any, default: int) -> int:
    """处理 `_safe_positive_int` 对应的业务逻辑。"""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
