from __future__ import annotations

from pathlib import Path
from typing import Any

from storage.json_store import load_json, save_json
from storage.memory_lock import MEMORY_IO_LOCK
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
    def __init__(self, path: str | Path, vector_store: Any | None = None) -> None:
        self.path = Path(path)
        self.vector_store = vector_store

    def load(self) -> dict[str, Any]:
        with MEMORY_IO_LOCK:
            return load_json(self.path, DEFAULT_MEMORY)

    def save(self, data: dict[str, Any]) -> None:
        with MEMORY_IO_LOCK:
            data["last_updated"] = now_iso()
            save_json(self.path, data)
        self._sync_vectors(data)

    def merge(self, updates: dict[str, Any]) -> dict[str, Any]:
        with MEMORY_IO_LOCK:
            current = load_json(self.path, DEFAULT_MEMORY)
            self._merge_lists(current, updates)
            current["last_updated"] = now_iso()
            save_json(self.path, current)
        self._sync_vectors(current)
        return current

    def _sync_vectors(self, data: dict[str, Any]) -> None:
        if self.vector_store is None:
            return
        try:
            self.vector_store.sync_memory(data)
        except Exception:
            return

    def _merge_lists(self, current: dict[str, Any], updates: dict[str, Any]) -> None:
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
