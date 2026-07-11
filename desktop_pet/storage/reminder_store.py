from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from storage.json_store import load_json, save_json
from storage.path_lock import lock_for_path
from utils.time_utils import now_iso, now_local


DEFAULT_REMINDERS = {"reminders": []}
_VALID_STATUSES = {"active", "awaiting_ack", "done", "cancelled"}


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
            "completed_at": "",
            "notified_at": "",
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
                    previous_status = str(raw_reminder.get("status", "active"))
                    raw_reminder["status"] = status
                    if status == "done" and previous_status != "done":
                        raw_reminder["completed_at"] = now_iso()
                    elif status == "active":
                        raw_reminder["completed_at"] = ""
                        raw_reminder["notified_at"] = ""
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

    # 原子领取到期或待确认超时的提醒，并在同次写入中标记最近提示时间。
    def claim_due_reminders(
        self,
        current_time: datetime | None = None,
        ack_repeat_minutes: int = 5,
    ) -> list[dict[str, str]]:
        """原子领取到期或待确认超时的提醒，并在同次写入中标记最近提示时间。"""
        try:
            normalized_repeat_minutes = int(ack_repeat_minutes)
        except (TypeError, ValueError) as exc:
            raise ValueError("提醒确认重试间隔无效") from exc
        if normalized_repeat_minutes < 1:
            raise ValueError("提醒确认重试间隔需要大于 0")

        now = current_time or now_local()
        claimed: list[dict[str, str]] = []
        with self._lock:
            payload = self._load_payload()
            changed = False
            for raw_reminder in payload["reminders"]:
                if not isinstance(raw_reminder, dict):
                    continue
                reminder = self._normalize_reminder(raw_reminder)
                is_newly_due = (
                    reminder["status"] == "active" and self._is_due(reminder["due_at"], now)
                )
                is_ack_overdue = (
                    reminder["status"] == "awaiting_ack"
                    and self._should_repeat_ack(
                        reminder["notified_at"],
                        now,
                        normalized_repeat_minutes,
                    )
                )
                if not is_newly_due and not is_ack_overdue:
                    continue
                raw_reminder.update(reminder)
                raw_reminder["status"] = "awaiting_ack"
                raw_reminder["notified_at"] = now.isoformat(timespec="seconds")
                claimed.append(dict(raw_reminder))
                changed = True
            if changed:
                save_json(self.path, payload)
        return sorted(claimed, key=lambda item: (item["due_at"], item["created_at"], item["id"]))

    # 确认一条待回应提醒，并记录完成时间。
    def acknowledge_reminder(
        self,
        reminder_id: str,
        current_time: datetime | None = None,
    ) -> dict[str, str] | None:
        """确认一条待回应提醒，并记录完成时间。"""
        completed_at = (current_time or now_local()).isoformat(timespec="seconds")
        with self._lock:
            payload = self._load_payload()
            for raw_reminder in payload["reminders"]:
                if not isinstance(raw_reminder, dict) or str(raw_reminder.get("id", "")) != reminder_id:
                    continue
                reminder = self._normalize_reminder(raw_reminder)
                if reminder["status"] != "awaiting_ack":
                    return None
                raw_reminder.update(reminder)
                raw_reminder["status"] = "done"
                raw_reminder["completed_at"] = completed_at
                normalized = self._normalize_reminder(raw_reminder)
                raw_reminder.clear()
                raw_reminder.update(normalized)
                save_json(self.path, payload)
                return normalized
        return None

    # 将一条待回应提醒延后指定分钟数，并恢复为 active 状态。
    def snooze_reminder(
        self,
        reminder_id: str,
        minutes: int,
        current_time: datetime | None = None,
    ) -> dict[str, str] | None:
        """将一条待回应提醒延后指定分钟数，并恢复为 active 状态。"""
        try:
            normalized_minutes = int(minutes)
        except (TypeError, ValueError) as exc:
            raise ValueError("提醒延后分钟数无效") from exc
        if normalized_minutes < 1:
            raise ValueError("提醒延后分钟数需要大于 0")

        due_at = (current_time or now_local()) + timedelta(minutes=normalized_minutes)
        with self._lock:
            payload = self._load_payload()
            for raw_reminder in payload["reminders"]:
                if not isinstance(raw_reminder, dict) or str(raw_reminder.get("id", "")) != reminder_id:
                    continue
                reminder = self._normalize_reminder(raw_reminder)
                if reminder["status"] != "awaiting_ack":
                    return None
                raw_reminder.update(reminder)
                raw_reminder["status"] = "active"
                raw_reminder["due_at"] = due_at.isoformat(timespec="seconds")
                raw_reminder["completed_at"] = ""
                raw_reminder["notified_at"] = ""
                normalized = self._normalize_reminder(raw_reminder)
                raw_reminder.clear()
                raw_reminder.update(normalized)
                save_json(self.path, payload)
                return normalized
        return None

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

    # 删除完成时间超过保留期的 done 提醒；active 与 cancelled 保持不变。
    def delete_expired_completed_reminders(
        self,
        retention_days: int,
        current_time: datetime | None = None,
    ) -> int:
        """删除完成时间超过保留期的 done 提醒；active 与 cancelled 保持不变。"""
        try:
            normalized_days = int(retention_days)
        except (TypeError, ValueError) as exc:
            raise ValueError("提醒保留天数无效") from exc
        if normalized_days < 0:
            raise ValueError("提醒保留天数不能小于 0")

        now = current_time or now_local()
        cutoff = now - timedelta(days=normalized_days)
        with self._lock:
            payload = self._load_payload()
            retained: list[dict[str, Any]] = []
            removed_count = 0
            for raw_reminder in payload["reminders"]:
                if not isinstance(raw_reminder, dict):
                    retained.append(raw_reminder)
                    continue
                reminder = self._normalize_reminder(raw_reminder)
                completed_at = self._completed_at_for_cleanup(reminder)
                if (
                    reminder["status"] == "done"
                    and completed_at is not None
                    and completed_at <= cutoff
                ):
                    removed_count += 1
                    continue
                retained.append(raw_reminder)
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
            "completed_at": str(reminder.get("completed_at", "")),
            "notified_at": str(reminder.get("notified_at", "")),
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

    # 判断待回应提醒是否达到再次提示间隔；缺失旧字段时允许立即补提示。
    def _should_repeat_ack(
        self,
        notified_at: str,
        current_time: datetime,
        ack_repeat_minutes: int,
    ) -> bool:
        """判断待回应提醒是否达到再次提示间隔；缺失旧字段时允许立即补提示。"""
        try:
            last_notified_at = datetime.fromisoformat(notified_at)
        except (TypeError, ValueError):
            return True
        return current_time >= last_notified_at + timedelta(minutes=ack_repeat_minutes)

    # 返回自动清理使用的完成时间；兼容旧版 done 提醒时回退到 due_at。
    def _completed_at_for_cleanup(self, reminder: dict[str, str]) -> datetime | None:
        """返回自动清理使用的完成时间；兼容旧版 done 提醒时回退到 due_at。"""
        value = reminder["completed_at"] or reminder["due_at"]
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None
