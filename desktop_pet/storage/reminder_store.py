from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from storage.json_store import load_json, save_json
from storage.path_lock import lock_for_path
from utils.time_utils import now_iso, now_local


DEFAULT_REMINDERS = {"reminders": []}
_VALID_STATUSES = {"active", "done", "cancelled"}


class ReminderStore:
    """管理本地提醒的持久化数据，并保证同一路径写入串行化。"""

    # 初始化提醒存储，并绑定目标 JSON 文件路径。
    def __init__(self, path: str | Path) -> None:
        """初始化提醒存储，并绑定目标 JSON 文件路径。"""
        self.path = Path(path)
        self._lock = lock_for_path(self.path)

    # 新建一条 active 提醒并返回写入后的记录。
    def add_reminder(
        self,
        title: str,
        due_at: datetime | str,
        source: str = "manual",
    ) -> dict[str, str]:
        """新建一条 active 提醒并返回写入后的记录。"""
        normalized_title = str(title).strip()
        if not normalized_title:
            raise ValueError("提醒内容不能为空")

        reminder = {
            "id": uuid4().hex,
            "title": normalized_title,
            "due_at": self._normalize_datetime(due_at),
            "created_at": now_iso(),
            "status": "active",
            "source": str(source).strip() or "manual",
        }
        with self._lock:
            payload = self._load_payload()
            payload["reminders"].append(reminder)
            save_json(self.path, payload)
        return dict(reminder)

    # 返回全部提醒；可按状态筛选，结果按到期时间和创建时间排序。
    def list_reminders(self, status: str | None = None) -> list[dict[str, str]]:
        """返回全部提醒；可按状态筛选，结果按到期时间和创建时间排序。"""
        if status is not None and status not in _VALID_STATUSES:
            raise ValueError("提醒状态无效")
        with self._lock:
            reminders = self._normalized_reminders(self._load_payload())
        if status is not None:
            reminders = [item for item in reminders if item["status"] == status]
        return sorted(reminders, key=lambda item: (item["due_at"], item["created_at"], item["id"]))

    # 按 ID 查询单条提醒；不存在时返回 None。
    def get_reminder(self, reminder_id: str) -> dict[str, str] | None:
        """按 ID 查询单条提醒；不存在时返回 None。"""
        with self._lock:
            for reminder in self._normalized_reminders(self._load_payload()):
                if reminder["id"] == reminder_id:
                    return reminder
        return None

    # 更新一条提醒的可编辑字段，并返回更新后的记录。
    def update_reminder(
        self,
        reminder_id: str,
        *,
        title: str | None = None,
        due_at: datetime | str | None = None,
        status: str | None = None,
        source: str | None = None,
    ) -> dict[str, str] | None:
        """更新一条提醒的可编辑字段，并返回更新后的记录。"""
        if status is not None and status not in _VALID_STATUSES:
            raise ValueError("提醒状态无效")
        if title is not None and not str(title).strip():
            raise ValueError("提醒内容不能为空")

        with self._lock:
            payload = self._load_payload()
            reminders = payload["reminders"]
            for raw_reminder in reminders:
                if not isinstance(raw_reminder, dict) or str(raw_reminder.get("id", "")) != reminder_id:
                    continue
                if title is not None:
                    raw_reminder["title"] = str(title).strip()
                if due_at is not None:
                    raw_reminder["due_at"] = self._normalize_datetime(due_at)
                if status is not None:
                    raw_reminder["status"] = status
                if source is not None:
                    raw_reminder["source"] = str(source).strip() or "manual"
                normalized = self._normalize_reminder(raw_reminder)
                raw_reminder.clear()
                raw_reminder.update(normalized)
                save_json(self.path, payload)
                return normalized
        return None

    # 将指定提醒标记为完成。
    def mark_done(self, reminder_id: str) -> dict[str, str] | None:
        """将指定提醒标记为完成。"""
        return self.update_reminder(reminder_id, status="done")

    # 将指定提醒标记为取消。
    def cancel_reminder(self, reminder_id: str) -> dict[str, str] | None:
        """将指定提醒标记为取消。"""
        return self.update_reminder(reminder_id, status="cancelled")

    # 删除指定提醒并返回是否实际删除。
    def delete_reminder(self, reminder_id: str) -> bool:
        """删除指定提醒并返回是否实际删除。"""
        with self._lock:
            payload = self._load_payload()
            reminders = payload["reminders"]
            retained = [
                item
                for item in reminders
                if not isinstance(item, dict) or str(item.get("id", "")) != reminder_id
            ]
            if len(retained) == len(reminders):
                return False
            payload["reminders"] = retained
            save_json(self.path, payload)
        return True

    # 原子领取所有已到期 active 提醒，并在同次写入中标记为 done。
    def claim_due_reminders(self, current_time: datetime | None = None) -> list[dict[str, str]]:
        """原子领取所有已到期 active 提醒，并在同次写入中标记为 done。"""
        now = current_time or now_local()
        claimed: list[dict[str, str]] = []
        with self._lock:
            payload = self._load_payload()
            changed = False
            for raw_reminder in payload["reminders"]:
                if not isinstance(raw_reminder, dict):
                    continue
                reminder = self._normalize_reminder(raw_reminder)
                if reminder["status"] != "active" or not self._is_due(reminder["due_at"], now):
                    continue
                raw_reminder.update(reminder)
                raw_reminder["status"] = "done"
                claimed.append(dict(raw_reminder))
                changed = True
            if changed:
                save_json(self.path, payload)
        return sorted(claimed, key=lambda item: (item["due_at"], item["created_at"], item["id"]))

    # 清除所有已完成提醒，并返回清除数量；active 提醒保持不变。
    def clear_completed_reminders(self) -> int:
        """清除所有已完成提醒，并返回清除数量；active 提醒保持不变。"""
        with self._lock:
            payload = self._load_payload()
            reminders = payload["reminders"]
            retained = [
                item
                for item in reminders
                if not isinstance(item, dict) or str(item.get("status", "active")) != "done"
            ]
            removed_count = len(reminders) - len(retained)
            if removed_count:
                payload["reminders"] = retained
                save_json(self.path, payload)
        return removed_count

    # 读取并规范化提醒载荷，兼容缺失或格式异常的旧数据。
    def _load_payload(self) -> dict[str, list[dict[str, Any]]]:
        """读取并规范化提醒载荷，兼容缺失或格式异常的旧数据。"""
        raw_payload = load_json(self.path, DEFAULT_REMINDERS)
        if not isinstance(raw_payload, dict):
            raw_payload = {}
        raw_reminders = raw_payload.get("reminders", [])
        return {"reminders": list(raw_reminders) if isinstance(raw_reminders, list) else []}

    # 将提醒列表中的有效字典规范为对外返回的字段结构。
    def _normalized_reminders(self, payload: dict[str, list[dict[str, Any]]]) -> list[dict[str, str]]:
        """将提醒列表中的有效字典规范为对外返回的字段结构。"""
        return [self._normalize_reminder(item) for item in payload["reminders"] if isinstance(item, dict)]

    # 规范单条提醒字段，缺失字段以安全默认值补齐。
    def _normalize_reminder(self, reminder: dict[str, Any]) -> dict[str, str]:
        """规范单条提醒字段，缺失字段以安全默认值补齐。"""
        status = str(reminder.get("status", "active"))
        return {
            "id": str(reminder.get("id", "")),
            "title": str(reminder.get("title", "")).strip(),
            "due_at": str(reminder.get("due_at", "")),
            "created_at": str(reminder.get("created_at", "")),
            "status": status if status in _VALID_STATUSES else "active",
            "source": str(reminder.get("source", "manual")) or "manual",
        }

    # 将 datetime 或 ISO 文本规范为精确到秒的本地时间文本。
    def _normalize_datetime(self, value: datetime | str) -> str:
        """将 datetime 或 ISO 文本规范为精确到秒的本地时间文本。"""
        if isinstance(value, datetime):
            return value.isoformat(timespec="seconds")
        try:
            return datetime.fromisoformat(str(value)).isoformat(timespec="seconds")
        except (TypeError, ValueError) as exc:
            raise ValueError("提醒时间格式无效") from exc

    # 判断 ISO 到期时间是否已不晚于当前时间；异常数据不会被误触发。
    def _is_due(self, due_at: str, current_time: datetime) -> bool:
        """判断 ISO 到期时间是否已不晚于当前时间；异常数据不会被误触发。"""
        try:
            return datetime.fromisoformat(due_at) <= current_time
        except (TypeError, ValueError):
            return False
