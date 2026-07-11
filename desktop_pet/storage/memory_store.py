from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from storage.json_store import load_json, save_json
from storage.memory_lock import MEMORY_IO_LOCK
from utils.time_utils import now_iso, parse_iso_datetime, utc_iso


MEMORY_FIELDS: dict[str, str] = {
    "user_profile.preferences": "preferences",
    "user_profile.communication_style": "communication_style",
    "user_profile.important_personal_notes": "notes",
    "work_study.current_learning_topics": "topics",
    "work_study.current_projects": "projects",
    "work_study.useful_context": "context",
    "relationship_memory.communication_style.preferred_response_style": "preferred_response_style",
    "relationship_memory.communication_style.detail_level": "detail_level",
    "relationship_memory.communication_style.confirmation_preference": "confirmation_preference",
    "relationship_memory.communication_style.tone_preference": "tone_preference",
    "relationship_memory.communication_style.avoid_styles": "avoid_styles",
    "relationship_memory.communication_style.evidence": "communication_evidence",
    "relationship_memory.companionship_style.preferred_companion_role": "preferred_companion_role",
    "relationship_memory.companionship_style.proactive_boundary": "proactive_boundary",
    "relationship_memory.companionship_style.encouragement_style": "encouragement_style",
    "relationship_memory.companionship_style.addressing_preference": "addressing_preference",
    "relationship_memory.companionship_style.avoid_behaviors": "avoid_behaviors",
    "relationship_memory.companionship_style.evidence": "companionship_evidence",
    "relationship_memory.interaction_patterns.task_focus": "task_focus",
    "relationship_memory.interaction_patterns.recent_interaction_mode": "recent_interaction_mode",
    "relationship_memory.interaction_patterns.interruption_tolerance": "interruption_tolerance",
    "relationship_memory.interaction_patterns.response_to_proactive_greetings": "response_to_proactive_greetings",
}


DEFAULT_RELATIONSHIP_MEMORY = {
    "communication_style": {
        "preferred_response_style": {},
        "detail_level": {},
        "confirmation_preference": {},
        "tone_preference": {},
        "avoid_styles": {},
        "evidence": {},
    },
    "companionship_style": {
        "preferred_companion_role": {},
        "proactive_boundary": {},
        "encouragement_style": {},
        "addressing_preference": {},
        "avoid_behaviors": {},
        "evidence": {},
    },
    "interaction_patterns": {
        "task_focus": {},
        "recent_interaction_mode": {},
        "interruption_tolerance": {},
        "response_to_proactive_greetings": {},
    },
}

DEFAULT_MEMORY = {
    "schema_version": "2.0",
    "user_profile": {
        "preferences": {},
        "communication_style": {},
        "important_personal_notes": {},
    },
    "work_study": {
        "current_learning_topics": {},
        "current_projects": {},
        "useful_context": {},
    },
    "relationship_memory": copy.deepcopy(DEFAULT_RELATIONSHIP_MEMORY),
    "memory_meta": {
        "schema_version": 3,
        "last_updated": "",
        "summary_batches": {},
    },
    "last_updated": "",
}


# 把旧版记忆文件补齐为当前 schema，同时保留已有字段。
def normalize_memory_schema(data: dict[str, Any] | None) -> dict[str, Any]:
    """把旧版记忆文件补齐为当前 schema，同时保留已有字段。"""
    if not isinstance(data, dict):
        data = {}
    normalized = copy.deepcopy(data)
    fallback_timestamp = _normalized_timestamp(normalized.get("last_updated"))
    for path, prefix in MEMORY_FIELDS.items():
        container = _get_path(normalized, path)
        _set_path(
            normalized,
            path,
            _normalize_record_collection(container, prefix, fallback_timestamp),
        )
    _merge_defaults(normalized, DEFAULT_MEMORY)
    normalized.setdefault("memory_meta", {})
    if not isinstance(normalized["memory_meta"], dict):
        normalized["memory_meta"] = {}
    normalized["schema_version"] = "2.0"
    normalized["memory_meta"]["schema_version"] = 3
    if not isinstance(normalized["memory_meta"].get("summary_batches"), dict):
        normalized["memory_meta"]["summary_batches"] = {}
    _merge_defaults(normalized["relationship_memory"], DEFAULT_RELATIONSHIP_MEMORY)
    normalized["last_updated"] = _normalized_timestamp(normalized.get("last_updated"))
    return normalized


# 返回字段内的编号记录，按最近更新时间优先排序。
def memory_records(memory: dict[str, Any], field_path: str) -> list[tuple[str, dict[str, Any]]]:
    """返回字段内的编号记录，按最近更新时间优先排序。"""
    if field_path not in MEMORY_FIELDS:
        return []
    collection = _get_path(memory, field_path)
    if not isinstance(collection, dict):
        return []
    records = [
        (record_id, dict(record))
        for record_id, record in collection.items()
        if isinstance(record_id, str) and _is_memory_record(record)
    ]
    records.sort(key=lambda item: str(item[1].get("timestamp", "")), reverse=True)
    return records


# 返回一个字段所有编号记录中的描述文本。
def memory_descriptions(memory: dict[str, Any], field_path: str) -> list[str]:
    """返回一个字段所有编号记录中的描述文本。"""
    texts: list[str] = []
    for _, record in memory_records(memory, field_path):
        for text in record.get("description", []):
            cleaned = str(text).strip()
            if cleaned and cleaned not in texts:
                texts.append(cleaned)
    return texts


# 安全读取点路径，缺失时返回 None。
def _get_path(data: dict[str, Any], path: str) -> Any:
    """安全读取点路径，缺失时返回 None。"""
    node: Any = data
    for key in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


# 安全写入点路径，必要时创建中间对象。
def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    """安全写入点路径，必要时创建中间对象。"""
    keys = path.split(".")
    node = data
    for key in keys[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[keys[-1]] = value


# 判断对象是否为新结构的单条记忆记录。
def _is_memory_record(value: Any) -> bool:
    """判断对象是否为新结构的单条记忆记录。"""
    return isinstance(value, dict) and "description" in value and (
        "timestamp" in value or "data" in value
    )


# 规范化单条描述为非空字符串列表。
def _description_list(value: Any) -> list[str]:
    """规范化单条描述为非空字符串列表。"""
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    texts: list[str] = []
    for item in values:
        if item is None:
            continue
        text = str(item).strip()
        if text and text not in texts:
            texts.append(text)
    return texts


# 把旧值或部分新值转换为按序号保存的记录集合。
def _normalize_record_collection(value: Any, prefix: str, fallback_timestamp: str) -> dict[str, dict[str, Any]]:
    """把旧值或部分新值转换为按序号保存的记录集合。"""
    candidates: list[tuple[str | None, Any, Any]] = []
    if isinstance(value, dict) and any(_is_memory_record(item) for item in value.values()):
        for key, record in value.items():
            if _is_memory_record(record):
                candidates.append((str(key), record.get("description"), record.get("timestamp", record.get("data"))))
    elif isinstance(value, list):
        candidates = [(None, item, fallback_timestamp) for item in value]
    elif value not in (None, "", {}):
        candidates = [(None, value, fallback_timestamp)]

    normalized: dict[str, dict[str, Any]] = {}
    next_number = 1
    for record_id, description, timestamp in candidates:
        texts = _description_list(description)
        if not texts:
            continue
        if record_id and record_id.startswith(f"{prefix}_") and record_id not in normalized:
            target_id = record_id
            try:
                next_number = max(next_number, int(record_id.rsplit("_", 1)[1]) + 1)
            except (IndexError, ValueError):
                pass
        else:
            while f"{prefix}_{next_number}" in normalized:
                next_number += 1
            target_id = f"{prefix}_{next_number}"
            next_number += 1
        normalized[target_id] = {
            "description": texts,
            "timestamp": _normalized_timestamp(timestamp or fallback_timestamp),
        }
    return normalized


# 把旧版或新值时间统一为带时区的 UTC ISO 字符串。
def _normalized_timestamp(value: Any) -> str:
    """把旧版或新值时间统一为带时区的 UTC ISO 字符串。"""
    parsed = parse_iso_datetime(value)
    return utc_iso(parsed) if parsed is not None else utc_iso()


# 根据 target、defaults 递归补齐缺失字段，保留已有记忆内容。
def _merge_defaults(target: dict[str, Any], defaults: dict[str, Any]) -> None:
    """根据 target、defaults 递归补齐缺失字段，保留已有记忆内容。"""
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
    # 初始化当前对象及其依赖。
    def __init__(self, path: str | Path, vector_store: Any | None = None) -> None:
        """初始化当前对象及其依赖。"""
        self.path = Path(path)
        self.vector_store = vector_store

    # 读取load并返回 dict[str, Any]。
    def load(self) -> dict[str, Any]:
        """读取load并返回 dict[str, Any]。"""
        with MEMORY_IO_LOCK:
            raw = load_json(self.path, DEFAULT_MEMORY)
            normalized = normalize_memory_schema(raw)
            if raw != normalized:
                save_json(self.path, normalized)
            return normalized

    # 根据 data 把save写入持久化存储并保持数据可恢复。
    def save(self, data: dict[str, Any]) -> None:
        """根据 data 把save写入持久化存储并保持数据可恢复。"""
        with MEMORY_IO_LOCK:
            data = normalize_memory_schema(data)
            self._touch_memory(data)
            save_json(self.path, data)
        self._sync_vectors(data)

    # 根据 updates 整理merge，并把结果交给调用方或写回状态。
    def merge(self, updates: dict[str, Any]) -> dict[str, Any]:
        """兼容旧调用方：把旧结构更新转换为新增编号记录。"""
        operations: list[dict[str, Any]] = []
        for path in MEMORY_FIELDS:
            value = _get_path(updates, path)
            for text in _description_list(value):
                operations.append({"action": "add", "field": path, "description": [text]})
        self.apply_summary_operations("legacy_merge", 0, operations)
        return self.load()

    # 应用模型返回的编号记忆增量，并在同一次写入中标记摘要批次。
    def apply_summary_operations(
        self,
        mode: str,
        sequence: int,
        operations: list[dict[str, Any]],
    ) -> dict[str, int]:
        """应用模型返回的编号记忆增量，并在同一次写入中标记摘要批次。"""
        if not isinstance(operations, list):
            raise ValueError("Memory operations must be a list")
        with MEMORY_IO_LOCK:
            current = normalize_memory_schema(load_json(self.path, DEFAULT_MEMORY))
            stats = {"added": 0, "updated": 0, "unchanged": 0}
            for operation in operations:
                self._apply_operation(current, operation, stats)

            meta = current.setdefault("memory_meta", {})
            batches = meta.setdefault("summary_batches", {})
            if not isinstance(batches, dict):
                batches = {}
                meta["summary_batches"] = batches
            if sequence > 0:
                batches[str(mode)] = int(sequence)
            meta["last_memory_summary"] = {
                "mode": str(mode),
                "sequence": int(sequence),
                "added": stats["added"],
                "updated": stats["updated"],
                "unchanged": stats["unchanged"],
                "completed_at": utc_iso(),
            }
            self._touch_memory(current)
            save_json(self.path, current)
        self._sync_vectors(current)
        return stats

    # 校验并应用模型的一条结构化记忆操作。
    def _apply_operation(
        self,
        memory: dict[str, Any],
        operation: Any,
        stats: dict[str, int],
    ) -> None:
        """校验并应用模型的一条结构化记忆操作。"""
        if not isinstance(operation, dict):
            raise ValueError("Memory operation must be an object")
        action = str(operation.get("action", "")).strip().lower()
        field = str(operation.get("field", "")).strip()
        if action not in {"add", "update", "unchanged"} or field not in MEMORY_FIELDS:
            raise ValueError("Unsupported memory operation")
        collection = _get_path(memory, field)
        if not isinstance(collection, dict):
            raise ValueError("Memory field is not a record collection")
        if action == "unchanged":
            stats["unchanged"] += 1
            return

        description = _description_list(operation.get("description", []))
        if not description:
            raise ValueError("Memory operation requires description")
        timestamp = utc_iso()
        if action == "add":
            record_id = self._next_record_id(collection, MEMORY_FIELDS[field])
            collection[record_id] = {"description": description, "timestamp": timestamp}
            stats["added"] += 1
            return

        record_id = str(operation.get("record_id", "")).strip()
        if record_id not in collection or not _is_memory_record(collection.get(record_id)):
            raise ValueError("Memory update target does not exist")
        collection[record_id] = {"description": description, "timestamp": timestamp}
        stats["updated"] += 1

    # 读取字段已有最大序号并生成下一个记录键。
    @staticmethod
    def _next_record_id(collection: dict[str, Any], prefix: str) -> str:
        """读取字段已有最大序号并生成下一个记录键。"""
        maximum = 0
        for key in collection:
            if not isinstance(key, str) or not key.startswith(f"{prefix}_"):
                continue
            try:
                maximum = max(maximum, int(key.rsplit("_", 1)[1]))
            except (IndexError, ValueError):
                continue
        return f"{prefix}_{maximum + 1}"

    # 根据 data 处理记忆数据，保持本地记忆和外部索引一致。
    def _touch_memory(self, data: dict[str, Any]) -> None:
        """根据 data 处理记忆数据，保持本地记忆和外部索引一致。"""
        timestamp = utc_iso()
        data["last_updated"] = timestamp
        data.setdefault("memory_meta", {})
        data["memory_meta"]["schema_version"] = 3
        data["memory_meta"]["last_updated"] = timestamp

    # 根据 current、updates 合并关系记忆分区，并为新增条目补充时间戳。
    def _touch_relationship_sections(
        self, current: dict[str, Any], updates: dict[str, Any]
    ) -> None:
        """根据 current、updates 合并关系记忆分区，并为新增条目补充时间戳。"""
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

    # 根据 value 判断updatecontent是否满足条件并返回布尔结果。
    def _has_update_content(self, value: Any) -> bool:
        """根据 value 判断updatecontent是否满足条件并返回布尔结果。"""
        if isinstance(value, dict):
            return any(
                key not in {"last_updated", "last_observed_at"}
                and self._has_update_content(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(self._has_update_content(item) for item in value)
        return value not in (None, "")

    # 根据 data 把记忆变更同步到向量索引，失败时仅记录日志。
    def _sync_vectors(self, data: dict[str, Any]) -> None:
        """根据 data 把记忆变更同步到向量索引，失败时仅记录日志。"""
        if self.vector_store is None:
            return
        try:
            self.vector_store.sync_memory(data)
        except Exception:
            return

    # 根据 current、updates 合并列表并按文本去重，保留原有顺序。
    def _merge_lists(self, current: dict[str, Any], updates: dict[str, Any]) -> None:
        """根据 current、updates 合并列表并按文本去重，保留原有顺序。"""
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
