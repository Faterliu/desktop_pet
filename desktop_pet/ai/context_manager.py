from __future__ import annotations

from pathlib import Path
from typing import Any

from ai.context_budget import clip_text, read_context_budget
from storage.chat_store import ChatStore
from storage.json_store import load_json_prefer_primary


class ContextManager:
    # 初始化上下文管理器，关联主配置、示例配置与正式/非正式聊天记录存储。
    def __init__(
        self,
        config_path: str | Path,
        chat_store_formal: ChatStore,
        chat_store_informal: ChatStore,
        fallback_config_path: str | Path | None = None,
    ) -> None:
        """初始化上下文管理器，关联主配置、示例配置与正式/非正式聊天记录存储。"""
        self.config_path = Path(config_path)
        self.fallback_config_path = Path(fallback_config_path) if fallback_config_path else self.config_path
        self.chat_store_formal = chat_store_formal
        self.chat_store_informal = chat_store_informal

    # 读取应用配置内容。
    def _config(self) -> dict[str, Any]:
        """读取应用配置内容。"""
        return load_json_prefer_primary(self.config_path, self.fallback_config_path, {})

    # 按配置限制返回最近上下文消息，按模式选择存储。
    def recent_messages(self, formal_qa_mode: bool = False) -> list[dict[str, Any]]:
        """按配置限制返回最近上下文消息，按模式选择存储。"""
        budget = read_context_budget(self._config())
        store = self.chat_store_formal if formal_qa_mode else self.chat_store_informal
        messages = store.get_recent_messages(budget["max_history_messages"])
        return [
            {
                **item,
                "content": clip_text(item.get("content", ""), budget["max_history_message_chars"]),
            }
            for item in messages
            if str(item.get("content", "")).strip()
        ]
