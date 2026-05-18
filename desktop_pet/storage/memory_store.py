from __future__ import annotations

from pathlib import Path
from typing import Any

from storage.json_store import load_json, save_json
from utils.time_utils import now_iso


DEFAULT_MEMORY = {
    "schema_version": "1.0",
    "user_profile": {
        "preferences": [],
        "communication_style": [],
        "important_personal_notes": [],
    },
    "work_study": {
        "current_learning_topics": [],
        "current_projects": [],
        "useful_context": [],
    },
    "last_updated": "",
}


class MemoryStore:
    def __init__(self, path: str | Path) -> None:
        """初始化记忆存储，并绑定目标 JSON 文件路径。"""
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        """读取当前记忆数据。"""
        return load_json(self.path, DEFAULT_MEMORY)

    def save(self, data: dict[str, Any]) -> None:
        """保存完整记忆数据，并更新时间戳。"""
        data["last_updated"] = now_iso()
        save_json(self.path, data)

    def merge(self, updates: dict[str, Any]) -> dict[str, Any]:
        """把新增记忆合并到现有记忆中，并返回合并结果。"""
        current = self.load()
        self._merge_lists(current, updates)
        current["last_updated"] = now_iso()
        save_json(self.path, current)
        return current

    def _merge_lists(self, current: dict[str, Any], updates: dict[str, Any]) -> None:
        """递归合并字典和列表，避免重复写入相同记忆项。"""
        for key, value in updates.items():
            if isinstance(value, dict):
                node = current.setdefault(key, {})
                self._merge_lists(node, value)
            elif isinstance(value, list):
                existing = current.setdefault(key, [])
                for item in value:
                    if item and item not in existing:
                        existing.append(item)
            elif value not in (None, ""):
                current[key] = value
