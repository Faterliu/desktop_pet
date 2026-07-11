from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, ClassVar
from uuid import uuid4

from storage.path_lock import lock_for_path
from utils.logger import get_logger
from utils.time_utils import parse_iso_datetime, utc_iso


logger = get_logger(__name__)


class ChatStore:
    """按模式读写共享 JSONL 对话历史。"""

    VALID_MODES: ClassVar[frozenset[str]] = frozenset(
        {"formal", "informal", "remind", "clipboard", "screenshot"}
    )

    # 初始化共享 JSONL 路径与当前存储实例负责的模式。
    def __init__(self, path: str | Path, mode: str = "informal") -> None:
        """初始化共享 JSONL 路径与当前存储实例负责的模式。"""
        normalized_mode = str(mode).strip().lower()
        if normalized_mode not in self.VALID_MODES:
            raise ValueError(f"Unsupported chat mode: {mode}")
        self.path = Path(path)
        self.mode = normalized_mode
        self._lock = lock_for_path(self.path)

    # 仅在新 JSONL 尚不存在时，把两份旧 JSON 历史迁移为带模式字段的 JSONL。
    @classmethod
    def migrate_legacy_histories(
        cls,
        path: str | Path,
        legacy_paths: dict[str, str | Path],
    ) -> bool:
        """仅在新 JSONL 尚不存在时迁移旧历史。"""
        target = Path(path)
        lock = lock_for_path(target)
        with lock:
            if target.exists():
                return False
            indexed_messages: list[tuple[str, int, str, dict[str, Any]]] = []
            for mode in ("formal", "informal"):
                legacy_path = legacy_paths.get(mode)
                if legacy_path is None:
                    continue
                for index, message in enumerate(cls._legacy_messages(Path(legacy_path))):
                    normalized = cls._normalize_message(message, mode)
                    if normalized is not None:
                        indexed_messages.append((normalized["timestamp"], index, mode, normalized))
            if not indexed_messages:
                return False
            indexed_messages.sort(key=lambda item: (item[0], item[1], item[2]))
            cls._write_records_atomically(target, [item[3] for item in indexed_messages])
            logger.info("Migrated legacy chat histories into shared JSONL: count=%s", len(indexed_messages))
            return True

    # 读取当前模式的全部聊天消息。
    def all_messages(self) -> list[dict[str, Any]]:
        """读取当前模式的全部聊天消息。"""
        with self._lock:
            return [record for record in self._read_records() if record["mode"] == self.mode]

    # 追加一条当前模式的聊天消息并返回最终写入对象。
    def append_message(
        self,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """追加一条当前模式的聊天消息并返回最终写入对象。"""
        message = {
            "id": uuid4().hex,
            "role": str(role),
            "content": str(content),
            "timestamp": utc_iso(),
            "metadata": dict(metadata) if isinstance(metadata, dict) else {},
            "mode": self.mode,
        }
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as file:
                file.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
                file.flush()
                os.fsync(file.fileno())
        return message

    # 删除指定快照中的当前模式记录；运行期间新增的记录保持不变。
    def remove_snapshot(self, snapshot: list[dict[str, Any]]) -> int:
        """删除指定快照中的当前模式记录；运行期间新增的记录保持不变。"""
        expected = Counter(
            self._record_identity(message)
            for message in snapshot
            if isinstance(message, dict) and message.get("mode") == self.mode
        )
        if not expected:
            return 0

        with self._lock:
            records = self._read_records()
            retained: list[dict[str, Any]] = []
            removed = 0
            for record in records:
                identity = self._record_identity(record)
                if record.get("mode") == self.mode and expected.get(identity, 0) > 0:
                    expected[identity] -= 1
                    removed += 1
                    continue
                retained.append(record)
            if removed:
                self._write_records_atomically(self.path, retained)
            return removed

    # 读取当前模式最近若干条消息，用于构建上下文。
    def get_recent_messages(self, max_messages: int = 8) -> list[dict[str, Any]]:
        """读取当前模式最近若干条消息，用于构建上下文。"""
        count = max(0, int(max_messages))
        return self.all_messages()[-count:] if count else []

    # 按当前模式用户消息数量估算对话轮数。
    def round_count(self) -> int:
        """按当前模式用户消息数量估算对话轮数。"""
        return self._user_message_count(self.all_messages())

    # 判断当前模式历史是否达到需要生成摘要的条件。
    def should_trigger_summary(
        self,
        trigger_rounds: int = 12,
        covered_message_count: int = 0,
    ) -> bool:
        """判断当前模式历史是否达到需要生成摘要的条件。"""
        del covered_message_count
        messages = self.all_messages()
        return self._user_message_count(messages) >= max(1, int(trigger_rounds))

    # 兼容旧调用方的清理时间接口；JSONL 仅保存对话行，不额外写入状态行。
    def update_last_cleaned_at(self, timestamp: str) -> None:
        """兼容旧调用方的清理时间接口。"""
        del timestamp

    # 删除当前模式的全部历史，保留另一模式记录。
    def clear_history(self) -> None:
        """删除当前模式的全部历史，保留另一模式记录。"""
        with self._lock:
            retained = [record for record in self._read_records() if record["mode"] != self.mode]
            self._write_records_atomically(self.path, retained)

    # 兼容历史清理工作器，在同一次原子重写中清理当前模式。
    def clear_history_with_timestamp(self, timestamp: str) -> None:
        """兼容历史清理工作器，在同一次原子重写中清理当前模式。"""
        del timestamp
        self.clear_history()

    # 按内部会话标识把当前模式的记录原子改标为目标模式。
    def reassign_conversation(self, conversation_id: str, target_mode: str) -> int:
        """按内部会话标识把当前模式的记录原子改标为目标模式。"""
        normalized_target = str(target_mode).strip().lower()
        if normalized_target not in self.VALID_MODES:
            raise ValueError(f"Unsupported chat mode: {target_mode}")
        normalized_id = str(conversation_id).strip()
        if not normalized_id or normalized_target == self.mode:
            return 0

        with self._lock:
            records = self._read_records()
            changed = 0
            for record in records:
                metadata = record.get("metadata", {})
                if (
                    record.get("mode") == self.mode
                    and isinstance(metadata, dict)
                    and metadata.get("conversation_id") == normalized_id
                ):
                    record["mode"] = normalized_target
                    changed += 1
            if changed:
                self._write_records_atomically(self.path, records)
            return changed

    # 从 JSONL 读取全部合法记录，损坏行仅跳过并记录安全日志。
    def _read_records(self) -> list[dict[str, Any]]:
        """从 JSONL 读取全部合法记录。"""
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        try:
            with self.path.open("r", encoding="utf-8") as file:
                for line_number, line in enumerate(file, start=1):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        raw = json.loads(stripped)
                    except json.JSONDecodeError:
                        logger.warning("Skipped malformed JSONL chat record: path=%s line=%s", self.path, line_number)
                        continue
                    normalized = self._normalize_message(raw)
                    if normalized is None:
                        logger.warning("Skipped invalid JSONL chat record: path=%s line=%s", self.path, line_number)
                        continue
                    records.append(normalized)
        except OSError as exc:
            logger.warning("Failed to read JSONL chat history: path=%s error=%s", self.path, exc)
        return records

    # 把旧 JSON 历史载荷安全转换为消息列表，不创建或修改旧文件。
    @staticmethod
    def _legacy_messages(path: Path) -> list[dict[str, Any]]:
        """把旧 JSON 历史载荷安全转换为消息列表。"""
        if not path.exists():
            return []
        try:
            with path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Skipped unreadable legacy chat history: path=%s error=%s", path, exc)
            return []
        messages = payload.get("messages", []) if isinstance(payload, dict) else []
        return [item for item in messages if isinstance(item, dict)] if isinstance(messages, list) else []

    # 规范化 JSONL 或旧 JSON 的单条消息，非法记录返回 None。
    @classmethod
    def _normalize_message(
        cls,
        message: Any,
        default_mode: str | None = None,
    ) -> dict[str, Any] | None:
        """规范化 JSONL 或旧 JSON 的单条消息。"""
        if not isinstance(message, dict):
            return None
        mode = str(message.get("mode", default_mode or "")).strip().lower()
        if mode not in cls.VALID_MODES:
            return None
        role = str(message.get("role", "")).strip()
        content = str(message.get("content", ""))
        if not role or not content.strip():
            return None
        parsed_timestamp = parse_iso_datetime(message.get("timestamp"))
        timestamp = utc_iso(parsed_timestamp) if parsed_timestamp is not None else utc_iso()
        metadata = message.get("metadata", {})
        return {
            "id": str(message.get("id", "")).strip(),
            "role": role,
            "content": content,
            "timestamp": timestamp,
            "metadata": dict(metadata) if isinstance(metadata, dict) else {},
            "mode": mode,
        }

    # 为快照清理生成稳定标识；新版记录优先使用追加时生成的唯一 id。
    @staticmethod
    def _record_identity(record: dict[str, Any]) -> str:
        """为快照清理生成稳定标识。"""
        record_id = str(record.get("id", "")).strip()
        if record_id:
            return f"id:{record_id}"
        return json.dumps(
            {
                "role": record.get("role", ""),
                "content": record.get("content", ""),
                "timestamp": record.get("timestamp", ""),
                "metadata": record.get("metadata", {}),
                "mode": record.get("mode", ""),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    # 原子重写 JSONL 全部记录，供按模式清理和首次迁移使用。
    @staticmethod
    def _write_records_atomically(path: Path, records: list[dict[str, Any]]) -> None:
        """原子重写 JSONL 全部记录。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp")
        try:
            with tmp.open("w", encoding="utf-8", newline="\n") as file:
                for record in records:
                    file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp, path)
        except Exception:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise

    # 计算用户消息数量。
    @staticmethod
    def _user_message_count(messages: list[dict[str, Any]]) -> int:
        """计算用户消息数量。"""
        return len([message for message in messages if message.get("role") == "user"])
