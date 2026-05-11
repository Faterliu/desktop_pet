from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QLabel, QWidget


class SpeechBubble(QWidget):
    def __init__(self) -> None:
        """初始化悬浮气泡窗口与自动关闭计时器。"""
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self.label = QLabel(self)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(
            "QLabel { color: #3d2a1b; font-size: 13px; background: transparent; }"
        )
        self.label.move(16, 12)

        self.close_timer = QTimer(self)
        self.close_timer.setSingleShot(True)
        self.close_timer.timeout.connect(self.hide)

        self.source = "system"
        self._last_anchor_rect = QRect()
        self._always_on_top = True

    def set_always_on_top(self, enabled: bool) -> None:
        """同步气泡窗口的置顶状态与主窗口一致。"""
        if self._always_on_top == enabled:
            return
        self._always_on_top = enabled
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if self.isVisible():
            self.hide()
        self.show()

    def show_message(
        self,
        text: str,
        anchor_rect: QRect,
        duration_ms: int,
        source: str = "system",
    ) -> None:
        """在宠物附近显示一条气泡消息，并按时自动关闭。"""
        self.source = source
        self.label.setText(text)
        self.label.adjustSize()
        width = min(max(self.label.sizeHint().width() + 32, 180), 360)
        self.label.setFixedWidth(width - 32)
        self.label.adjustSize()
        height = self.label.height() + 28
        self.resize(width, height)
        self._last_anchor_rect = QRect(anchor_rect)
        self.reposition(anchor_rect)
        self.show()
        self.raise_()
        self.close_timer.start(duration_ms)

    def reposition(self, anchor_rect: QRect | None = None) -> None:
        """根据角色当前位置重新摆放气泡。"""
        if anchor_rect is not None:
            self._last_anchor_rect = QRect(anchor_rect)
        if self._last_anchor_rect.isNull():
            return

        width = self.width()
        height = self.height()
        x = self._last_anchor_rect.x() + self._last_anchor_rect.width() - width + 20
        y = self._last_anchor_rect.y() - height - 10
        if y < 0:
            y = self._last_anchor_rect.y() + 12
        self.move(QPoint(max(0, x), max(0, y)))

    def paintEvent(self, event) -> None:  # noqa: N802
        """绘制圆角气泡背景和底部小尾巴。"""
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height() - 8, 18, 18)
        path.moveTo(self.width() - 44, self.height() - 8)
        path.lineTo(self.width() - 32, self.height())
        path.lineTo(self.width() - 20, self.height() - 8)
        path.closeSubpath()
        painter.fillPath(path, QColor("#fff3d7"))
        painter.setPen(QColor("#d8b27a"))
        painter.drawPath(path)
