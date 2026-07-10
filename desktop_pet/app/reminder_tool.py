from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from storage.reminder_store import ReminderStore
from utils.time_utils import now_local


@dataclass(frozen=True)
class ReminderToolRequest:
    """模型请求创建的单条本地提醒。"""

    title: str
    due_at: str


@dataclass(frozen=True)
class ReminderToolResult:
    """本地提醒工具的标准调用结果。"""

    success: bool
    code: str
    reminder: dict[str, str] | None = None


class ReminderTool:
    """供模型调用的纯本地提醒工具，不依赖任何 QWidget。"""

    # 初始化提醒工具，并绑定存储、配置读取和当前时间来源。
    def __init__(
        self,
        reminder_store: ReminderStore,
        *,
        enabled_provider: Callable[[], bool],
        max_active_provider: Callable[[], int],
        now_provider: Callable[[], datetime] = now_local,
    ) -> None:
        """初始化提醒工具，并绑定存储、配置读取和当前时间来源。"""
        self.reminder_store = reminder_store
        self.enabled_provider = enabled_provider
        self.max_active_provider = max_active_provider
        self.now_provider = now_provider

    # 判断当前配置是否允许模型创建本地提醒。
    def is_enabled(self) -> bool:
        """判断当前配置是否允许模型创建本地提醒。"""
        return bool(self.enabled_provider())

    # 创建单条提醒，并返回不含用户原文日志的标准结果。
    def create_reminder(
        self,
        title: str,
        due_at: str,
        *,
        source: str = "model_tool_native",
    ) -> ReminderToolResult:
        """创建单条提醒，并返回不含用户原文日志的标准结果。"""
        results = self.create_reminders(
            [ReminderToolRequest(title=str(title), due_at=str(due_at))],
            source=source,
        )
        return results[0]

    # 批量创建最多三条提醒，先整体校验以避免可预见的部分写入。
    def create_reminders(
        self,
        requests: Sequence[ReminderToolRequest],
        *,
        source: str,
    ) -> list[ReminderToolResult]:
        """批量创建最多三条提醒，先整体校验以避免可预见的部分写入。"""
        items = list(requests)
        if not items:
            return []
        if len(items) > 3:
            return [ReminderToolResult(False, "too_many_reminders") for _ in items]
        if not self.is_enabled():
            return [ReminderToolResult(False, "reminders_disabled") for _ in items]

        normalized: list[tuple[str, datetime]] = []
        for item in items:
            title = item.title.strip()
            if not title:
                return [ReminderToolResult(False, "empty_title") for _ in items]
            due_at = self._parse_future_local_time(item.due_at)
            if due_at is None:
                return [ReminderToolResult(False, "invalid_or_past_due_at") for _ in items]
            normalized.append((title, due_at))

        max_active = self._max_active_reminders()
        if len(self.reminder_store.list_reminders("active")) + len(normalized) > max_active:
            return [ReminderToolResult(False, "active_reminder_limit") for _ in items]

        created: list[ReminderToolResult] = []
        for title, due_at in normalized:
            reminder = self.reminder_store.add_reminder(title, due_at, source=source)
            created.append(ReminderToolResult(True, "created", reminder))
        return created

    # 将无时区 ISO 文本解析为未来的本地时间，异常或过期时返回 None。
    def _parse_future_local_time(self, due_at: str) -> datetime | None:
        """将无时区 ISO 文本解析为未来的本地时间，异常或过期时返回 None。"""
        try:
            parsed = datetime.fromisoformat(due_at)
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is not None or parsed <= self.now_provider():
            return None
        return parsed

    # 读取并规范 active 提醒数量上限。
    def _max_active_reminders(self) -> int:
        """读取并规范 active 提醒数量上限。"""
        try:
            return max(1, int(self.max_active_provider()))
        except (TypeError, ValueError):
            return 20
