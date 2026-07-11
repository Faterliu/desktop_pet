from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from storage.reminder_store import ReminderStore
from utils.time_utils import now_local
from utils.logger import get_logger


logger = get_logger(__name__)


class ReminderController(QObject):
    """使用主线程定时器检查本地提醒，并把到期事件交给界面层展示。"""

    reminder_due = Signal(dict)

    # 初始化提醒定时检查器，并绑定存储和运行配置。
    def __init__(
        self,
        reminder_store: ReminderStore,
        *,
        enabled: bool = True,
        check_interval_seconds: int = 30,
        auto_cleanup_enabled: bool = True,
        completed_retention_days: int = 7,
        ack_repeat_minutes: int = 5,
        can_deliver: Callable[[], bool] | None = None,
        now_provider: Callable[[], datetime] = now_local,
        parent: QObject | None = None,
    ) -> None:
        """初始化提醒定时检查器，并绑定存储和运行配置。"""
        super().__init__(parent)
        self.reminder_store = reminder_store
        self.enabled = bool(enabled)
        self.check_interval_seconds = self._normalized_interval(check_interval_seconds)
        self.auto_cleanup_enabled = bool(auto_cleanup_enabled)
        self.completed_retention_days = self._normalized_retention_days(completed_retention_days)
        self.ack_repeat_minutes = self._normalized_ack_repeat_minutes(ack_repeat_minutes)
        self.can_deliver = can_deliver or (lambda: True)
        self.now_provider = now_provider
        self._started = False
        self.check_timer = QTimer(self)
        self.check_timer.timeout.connect(self.check_due_reminders)

    # 启动检查器，并立刻补查一次启动前已过期的 active 提醒。
    def start(self) -> None:
        """启动检查器，并立刻补查一次启动前已过期的 active 提醒。"""
        self._started = True
        if not self.enabled:
            self.check_timer.stop()
            return
        self.check_due_reminders()
        self.check_timer.start(self.check_interval_seconds * 1000)

    # 停止提醒定时检查。
    def stop(self) -> None:
        """停止提醒定时检查。"""
        self._started = False
        self.check_timer.stop()

    # 更新提醒配置，并在已启动状态下立即按新配置生效。
    def configure(
        self,
        enabled: bool,
        check_interval_seconds: int,
        auto_cleanup_enabled: bool = True,
        completed_retention_days: int = 7,
        ack_repeat_minutes: int = 5,
    ) -> None:
        """更新提醒配置，并在已启动状态下立即按新配置生效。"""
        self.enabled = bool(enabled)
        self.check_interval_seconds = self._normalized_interval(check_interval_seconds)
        self.auto_cleanup_enabled = bool(auto_cleanup_enabled)
        self.completed_retention_days = self._normalized_retention_days(completed_retention_days)
        self.ack_repeat_minutes = self._normalized_ack_repeat_minutes(ack_repeat_minutes)
        if self._started:
            self.start()

    # 检查并发出所有到期提醒；无法展示时保留 active 状态以便稍后补发。
    def check_due_reminders(self) -> list[dict]:
        """检查并发出所有到期提醒；无法展示时保留 active 状态以便稍后补发。"""
        if not self.enabled:
            return []
        now = self.now_provider()
        self._auto_cleanup_completed_reminders(now)
        if not self.can_deliver():
            return []
        due_reminders = self.reminder_store.claim_due_reminders(now, self.ack_repeat_minutes)
        for reminder in due_reminders:
            self.reminder_due.emit(reminder)
        return due_reminders

    # 规范检查间隔，避免异常配置导致高频轮询。
    def _normalized_interval(self, value: int) -> int:
        """规范检查间隔，避免异常配置导致高频轮询。"""
        try:
            interval = int(value)
        except (TypeError, ValueError):
            interval = 30
        return max(1, interval)

    # 规范完成提醒保留天数，异常值回退到默认 7 天。
    def _normalized_retention_days(self, value: int) -> int:
        """规范完成提醒保留天数，异常值回退到默认 7 天。"""
        try:
            days = int(value)
        except (TypeError, ValueError):
            days = 7
        return max(0, days)

    # 规范待确认提醒重复提示间隔，异常配置回退到默认 5 分钟。
    def _normalized_ack_repeat_minutes(self, value: int) -> int:
        """规范待确认提醒重复提示间隔，异常配置回退到默认 5 分钟。"""
        try:
            minutes = int(value)
        except (TypeError, ValueError):
            minutes = 5
        return max(1, minutes)

    # 清理超过保留期的完成提醒，并记录安全的数量日志。
    def _auto_cleanup_completed_reminders(self, current_time: datetime) -> int:
        """清理超过保留期的完成提醒，并记录安全的数量日志。"""
        if not self.auto_cleanup_enabled:
            return 0
        removed_count = self.reminder_store.delete_expired_completed_reminders(
            self.completed_retention_days,
            current_time,
        )
        if removed_count:
            logger.info("Reminder auto cleanup removed completed reminders: count=%s", removed_count)
        return removed_count
