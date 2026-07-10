from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from storage.reminder_store import ReminderStore
from utils.time_utils import now_local


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
        can_deliver: Callable[[], bool] | None = None,
        now_provider: Callable[[], datetime] = now_local,
        parent: QObject | None = None,
    ) -> None:
        """初始化提醒定时检查器，并绑定存储和运行配置。"""
        super().__init__(parent)
        self.reminder_store = reminder_store
        self.enabled = bool(enabled)
        self.check_interval_seconds = self._normalized_interval(check_interval_seconds)
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
    def configure(self, enabled: bool, check_interval_seconds: int) -> None:
        """更新提醒配置，并在已启动状态下立即按新配置生效。"""
        self.enabled = bool(enabled)
        self.check_interval_seconds = self._normalized_interval(check_interval_seconds)
        if self._started:
            self.start()

    # 检查并发出所有到期提醒；无法展示时保留 active 状态以便稍后补发。
    def check_due_reminders(self) -> list[dict]:
        """检查并发出所有到期提醒；无法展示时保留 active 状态以便稍后补发。"""
        if not self.enabled or not self.can_deliver():
            return []
        due_reminders = self.reminder_store.claim_due_reminders(self.now_provider())
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
