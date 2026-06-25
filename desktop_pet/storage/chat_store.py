from __future__ import annotations

from pathlib import Path
from typing import Any

from storage.json_store import load_json, save_json
from storage.path_lock import lock_for_path
from utils.time_utils import now_iso


DEFAULT_CHAT_HISTORY = {"messages": [], "last_cleaned_at": ""}


class ChatStore:
    # 初始化聊天记录存储，并绑定目标 JSON 文件路径。
    def __init__(self, path: str | Path) -> None:
        """初始化聊天记录存储，并绑定目标 JSON 文件路径。"""
        self.path = Path(path)
        self._lock = lock_for_path(self.path)

    # 读取全部聊天消息列表。
    def all_messages(self) -> list[dict[str, Any]]:
        """读取全部聊天消息列表。"""
        with self._lock:
            payload = load_json(self.path, DEFAULT_CHAT_HISTORY)
            return self._messages_from_payload(payload)

    # 追加一条聊天消息并返回最终写入的消息对象。
    def append_message(
        self,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """追加一条聊天消息并返回最终写入的消息对象。"""
        message = {
            "role": role,
            "content": content,
            "timestamp": now_iso(),
            "metadata": metadata or {},
        }
        with self._lock:
            payload = load_json(self.path, DEFAULT_CHAT_HISTORY)
            messages = payload.setdefault("messages", [])
            if not isinstance(messages, list):
                messages = []
                payload["messages"] = messages
            messages.append(message)
            save_json(self.path, payload)
        return message

    # 读取最近若干条消息，用于构建上下文。
    def get_recent_messages(self, max_messages: int = 8) -> list[dict[str, Any]]:
        """读取最近若干条消息，用于构建上下文。"""
        messages = self.all_messages()
        return messages[-max_messages:]

    # 按用户消息数量估算当前对话轮数。
    def round_count(self) -> int:
        """按用户消息数量估算当前对话轮数。"""
        with self._lock:
            payload = load_json(self.path, DEFAULT_CHAT_HISTORY)
            return self._user_message_count(self._messages_from_payload(payload))

    # 判断聊天记录是否已经达到需要生成摘要的条件。
    def should_trigger_summary(
        self, trigger_rounds: int = 12, covered_message_count: int = 0
    ) -> bool:
        """判断聊天记录是否已经达到需要生成摘要的条件。"""
        with self._lock:
            payload = load_json(self.path, DEFAULT_CHAT_HISTORY)
            messages = self._messages_from_payload(payload)
            return (
                self._user_message_count(messages) >= trigger_rounds
                and len(messages) > covered_message_count
            )

    # 更新上次清理时间戳。
    def update_last_cleaned_at(self, timestamp: str) -> None:
        """更新上次清理时间戳。"""
        with self._lock:
            payload = load_json(self.path, DEFAULT_CHAT_HISTORY)
            payload["last_cleaned_at"] = timestamp
            save_json(self.path, payload)

    # 清空聊天记录文件。
    def clear_history(self) -> None:
        """清空聊天记录文件。"""
        with self._lock:
            save_json(self.path, self._empty_payload())

    # 清空聊天记录，并在同一次写入中记录清理时间。
    def clear_history_with_timestamp(self, timestamp: str) -> None:
        """清空聊天记录，并在同一次写入中记录清理时间。"""
        with self._lock:
            save_json(self.path, self._empty_payload(timestamp))

    # 从存储载荷中读取消息列表，兼容异常旧数据。
    def _messages_from_payload(self, payload: Any) -> list[dict[str, Any]]:
        """从存储载荷中读取消息列表，兼容异常旧数据。"""
        if not isinstance(payload, dict):
            return []
        messages = payload.get("messages", [])
        return list(messages) if isinstance(messages, list) else []

    # 计算用户消息数量。
    def _user_message_count(self, messages: list[dict[str, Any]]) -> int:
        """计算用户消息数量。"""
        return len([msg for msg in messages if isinstance(msg, dict) and msg.get("role") == "user"])

    # 构建空聊天记录载荷。
    def _empty_payload(self, last_cleaned_at: str = "") -> dict[str, Any]:
        """构建空聊天记录载荷。"""
        return {"messages": [], "last_cleaned_at": last_cleaned_at}
