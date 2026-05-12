from __future__ import annotations

from pathlib import Path
from typing import Any

from storage.json_store import load_json, save_json
from utils.time_utils import now_iso


DEFAULT_CHAT_HISTORY = {"messages": [], "last_cleaned_at": ""}


class ChatStore:
    def __init__(self, path: str | Path) -> None:
        """初始化聊天记录存储，并绑定目标 JSON 文件路径。"""
        self.path = Path(path)

    def all_messages(self) -> list[dict[str, Any]]:
        """读取全部聊天消息列表。"""
        payload = load_json(self.path, DEFAULT_CHAT_HISTORY)
        return list(payload.get("messages", []))

    def append_message(
        self,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """追加一条聊天消息并返回最终写入的消息对象。"""
        payload = load_json(self.path, DEFAULT_CHAT_HISTORY)
        message = {
            "role": role,
            "content": content,
            "timestamp": now_iso(),
            "metadata": metadata or {},
        }
        payload.setdefault("messages", []).append(message)
        save_json(self.path, payload)
        return message

    def get_recent_messages(self, max_messages: int = 8) -> list[dict[str, Any]]:
        """读取最近若干条消息，用于构建上下文。"""
        messages = self.all_messages()
        return messages[-max_messages:]

    def round_count(self) -> int:
        """按用户消息数量估算当前对话轮数。"""
        user_messages = [msg for msg in self.all_messages() if msg.get("role") == "user"]
        return len(user_messages)

    def should_trigger_summary(
        self, trigger_rounds: int = 12, covered_message_count: int = 0
    ) -> bool:
        """判断聊天记录是否已经达到需要生成摘要的条件。"""
        messages = self.all_messages()
        return self.round_count() >= trigger_rounds and len(messages) > covered_message_count

    def update_last_cleaned_at(self, timestamp: str) -> None:
        """更新上次清理时间戳。"""
        payload = load_json(self.path, DEFAULT_CHAT_HISTORY)
        payload["last_cleaned_at"] = timestamp
        save_json(self.path, payload)

    def clear_history(self) -> None:
        """清空聊天记录文件。"""
        save_json(self.path, DEFAULT_CHAT_HISTORY)
