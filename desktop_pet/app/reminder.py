from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QObject, QRect, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from storage.reminder_store import ReminderStore
from utils.logger import get_logger
from utils.time_utils import now_local


logger = get_logger(__name__)


class ReminderInputDialog(QDialog):
    """使用桌宠气泡配色的提醒输入框。"""

    def __init__(
        self,
        title: str,
        prompt: str,
        anchor_rect: QRect,
        position_service: object,
        *,
        value: str | int = "",
        input_kind: str = "text",
        minimum: int = 0,
        maximum: int = 999999,
    ) -> None:
        """初始化提醒输入控件，并把窗口放到人物周围的空位。"""
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(
            """
            ReminderInputDialog { background: transparent; }
            QWidget#reminder_surface { background: #fff3d7; border: 1px solid #d8b27a; border-radius: 16px; }
            QLabel#reminder_title { color: #5a3e28; font-size: 14px; font-weight: 600; background: transparent; }
            QLabel#reminder_prompt { color: #795b3d; font-size: 12px; background: transparent; }
            QLineEdit, QSpinBox { color: #3d2a1b; background: #fffaf0; border: 1px solid #d8b27a; border-radius: 9px; padding: 6px 9px; font-size: 13px; }
            QLineEdit:focus, QSpinBox:focus { border-color: #c98d52; }
            QDialogButtonBox QPushButton { color: #5a3e28; background: #f8dfb8; border: 1px solid #d5a66d; border-radius: 8px; padding: 5px 14px; min-width: 58px; }
            QDialogButtonBox QPushButton:hover { background: #ffe9c9; }
            """
        )
        surface = QWidget(self)
        surface.setObjectName("reminder_surface")
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)
        title_label = QLabel(title, surface)
        title_label.setObjectName("reminder_title")
        prompt_label = QLabel(prompt, surface)
        prompt_label.setObjectName("reminder_prompt")
        layout.addWidget(title_label)
        layout.addWidget(prompt_label)
        if input_kind == "int":
            field = QSpinBox(surface)
            field.setRange(minimum, maximum)
            field.setValue(int(value))
            field.setSuffix(" 分钟")
            self.input_field = field
        else:
            field = QLineEdit(str(value), surface)
            field.setClearButtonEnabled(True)
            self.input_field = field
        layout.addWidget(field)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=surface,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(surface)
        self.adjustSize()
        positioner = getattr(position_service, "speech_bubble_position", None)
        if callable(positioner):
            self.move(positioner((self.width(), self.height()), anchor_rect))
        self.input_field.setFocus()
        if isinstance(self.input_field, QLineEdit):
            self.input_field.selectAll()

    @classmethod
    def get_text(
        cls,
        title: str,
        prompt: str,
        anchor_rect: QRect,
        position_service: object,
    ) -> tuple[str, bool]:
        """显示文字提醒输入框，并返回文本与确认状态。"""
        dialog = cls(title, prompt, anchor_rect, position_service)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return dialog.input_field.text(), accepted

    @classmethod
    def get_int(
        cls,
        title: str,
        prompt: str,
        anchor_rect: QRect,
        position_service: object,
        *,
        value: int,
        minimum: int,
        maximum: int,
    ) -> tuple[int, bool]:
        """显示数字提醒输入框，并返回数值与确认状态。"""
        dialog = cls(
            title,
            prompt,
            anchor_rect,
            position_service,
            value=value,
            input_kind="int",
            minimum=minimum,
            maximum=maximum,
        )
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return dialog.input_field.value(), accepted


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
        self.completed_retention_days = self._normalized_retention_days(
            completed_retention_days
        )
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
        self.completed_retention_days = self._normalized_retention_days(
            completed_retention_days
        )
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
        due_reminders = self.reminder_store.claim_due_reminders(
            now,
            self.ack_repeat_minutes,
        )
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
            logger.info(
                "Reminder auto cleanup removed completed reminders: count=%s",
                removed_count,
            )
        return removed_count
