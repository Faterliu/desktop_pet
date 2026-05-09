from __future__ import annotations

from pathlib import Path
from typing import Any

from storage.chat_store import ChatStore
from storage.json_store import load_json_prefer_primary


class ContextManager:
    def __init__(
        self,
        config_path: str | Path,
        chat_store: ChatStore,
        fallback_config_path: str | Path | None = None,
    ) -> None:
        """初始化上下文管理器，关联主配置、示例配置与聊天记录存储。"""
        self.config_path = Path(config_path)
        self.fallback_config_path = Path(fallback_config_path) if fallback_config_path else self.config_path
        self.chat_store = chat_store

    def _config(self) -> dict[str, Any]:
        """读取应用配置内容。"""
        return load_json_prefer_primary(self.config_path, self.fallback_config_path, {})

    def recent_messages(self) -> list[dict[str, Any]]:
        """按照配置限制返回最近的上下文消息。"""
        api_config = self._config().get("api", {})
        max_recent = int(api_config.get("max_recent_messages", 8))
        return self.chat_store.get_recent_messages(max_recent)

    def should_trigger_summary(self, covered_message_count: int) -> bool:
        """根据配置和已覆盖消息数判断是否需要触发摘要。"""
        api_config = self._config().get("api", {})
        trigger_rounds = int(api_config.get("summary_trigger_rounds", 12))
        return self.chat_store.should_trigger_summary(trigger_rounds, covered_message_count)
