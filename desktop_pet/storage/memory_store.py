from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from storage.json_store import load_json, save_json
from storage.memory_lock import MEMORY_IO_LOCK
from utils.time_utils import now_iso


DEFAULT_RELATIONSHIP_MEMORY = {
    "communication_style": {
        "preferred_response_style": "",
        "detail_level": "",
        "confirmation_preference": "",
        "tone_preference": "",
        "avoid_styles": [],
        "evidence": [],
        "last_updated": "",
    },
    "companionship_style": {
        "preferred_companion_role": "",
        "proactive_boundary": "",
        "encouragement_style": "",
        "addressing_preference": "",
        "avoid_behaviors": [],
        "evidence": [],
        "last_updated": "",
    },
    "interaction_patterns": {
        "task_focus": [],
        "recent_interaction_mode": "",
        "interruption_tolerance": "",
        "response_to_proactive_greetings": "",
        "last_observed_at": "",
    },
}

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
    "relationship_memory": copy.deepcopy(DEFAULT_RELATIONSHIP_MEMORY),
    "memory_meta": {
        "schema_version": 2,
        "last_updated": "",
    },
    "last_updated": "",
}


def normalize_memory_schema(data: dict[str, Any] | None) -> dict[str, Any]:
    """Fill missing memory v2 fields while preserving unknown existing fields."""
    if not isinstance(data, dict):
        data = {}
    normalized = copy.deepcopy(data)
    _merge_defaults(normalized, DEFAULT_MEMORY)
    normalized.setdefault("memory_meta", {})
    if not isinstance(normalized["memory_meta"], dict):
        normalized["memory_meta"] = {}
    normalized["memory_meta"]["schema_version"] = 2
    _merge_defaults(normalized["relationship_memory"], DEFAULT_RELATIONSHIP_MEMORY)
    return normalized


def _merge_defaults(target: dict[str, Any], defaults: dict[str, Any]) -> None:
    for key, value in defaults.items():
        if key not in target:
            target[key] = copy.deepcopy(value)
            continue
        if isinstance(value, dict):
            if isinstance(target[key], dict):
                _merge_defaults(target[key], value)
            else:
                target[key] = copy.deepcopy(value)
        elif isinstance(value, list) and not isinstance(target[key], list):
            target[key] = copy.deepcopy(value)


class MemoryStore:
    def __init__(self, path: str | Path, vector_store: Any | None = None) -> None:
        self.path = Path(path)
        self.vector_store = vector_store

    def load(self) -> dict[str, Any]:
        with MEMORY_IO_LOCK:
            return normalize_memory_schema(load_json(self.path, DEFAULT_MEMORY))

    def save(self, data: dict[str, Any]) -> None:
        with MEMORY_IO_LOCK:
            data = normalize_memory_schema(data)
            self._touch_memory(data)
            save_json(self.path, data)
        self._sync_vectors(data)

    def merge(self, updates: dict[str, Any]) -> dict[str, Any]:
        with MEMORY_IO_LOCK:
            current = normalize_memory_schema(load_json(self.path, DEFAULT_MEMORY))
            self._merge_lists(current, updates)
            current = normalize_memory_schema(current)
            self._touch_relationship_sections(current, updates)
            self._touch_memory(current)
            save_json(self.path, current)
        self._sync_vectors(current)
        return current

    def _touch_memory(self, data: dict[str, Any]) -> None:
        timestamp = now_iso()
        data["last_updated"] = timestamp
        data.setdefault("memory_meta", {})
        data["memory_meta"]["schema_version"] = 2
        data["memory_meta"]["last_updated"] = timestamp

    def _touch_relationship_sections(
        self, current: dict[str, Any], updates: dict[str, Any]
    ) -> None:
        relationship_updates = updates.get("relationship_memory", {})
        if not isinstance(relationship_updates, dict):
            return
        relationship = current.setdefault("relationship_memory", {})
        timestamp = now_iso()
        for section, time_key in (
            ("communication_style", "last_updated"),
            ("companionship_style", "last_updated"),
            ("interaction_patterns", "last_observed_at"),
        ):
            section_updates = relationship_updates.get(section, {})
            if not isinstance(section_updates, dict):
                continue
            if self._has_update_content(section_updates):
                relationship.setdefault(section, {})[time_key] = timestamp

    def _has_update_content(self, value: Any) -> bool:
        if isinstance(value, dict):
            return any(
                key not in {"last_updated", "last_observed_at"}
                and self._has_update_content(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(self._has_update_content(item) for item in value)
        return value not in (None, "")

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
