from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget


class ChatInput(QWidget):
    message_submitted = Signal(str)

    def __init__(self) -> None:
        """初始化悬浮聊天输入框及发送控件。"""
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setStyleSheet(
            """
            QWidget { background: #fff8ee; border: 1px solid #d9b47d; border-radius: 14px; }
            QLineEdit { border: none; background: transparent; padding: 8px; color: #3d2a1b; }
            QPushButton { border: none; background: #ffcf8b; color: #5a3715; padding: 8px 12px; border-radius: 10px; }
            QPushButton:hover { background: #ffc16a; }
            """
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        self.input = QLineEdit(self)
        self.input.setPlaceholderText("想和小胡说点什么？")
        self.input.returnPressed.connect(self._submit)
        layout.addWidget(self.input)

        self.send_button = QPushButton("发送", self)
        self.send_button.clicked.connect(self._submit)
        layout.addWidget(self.send_button)

        self.close_button = QPushButton("×", self)
        self.close_button.setFixedWidth(32)
        self.close_button.setToolTip("关闭输入框")
        self.close_button.clicked.connect(self.hide)
        layout.addWidget(self.close_button)
        self.resize(300, 52)
        self._last_anchor_rect = QRect()
        self._always_on_top = True

    def set_always_on_top(self, enabled: bool) -> None:
        """同步输入框窗口的置顶状态与主窗口一致。"""
        if self._always_on_top == enabled:
            return
        self._always_on_top = enabled
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if self.isVisible():
            self.hide()
        self.show()

    def show_near(self, anchor_rect: QRect) -> None:
        """把输入框显示在宠物附近，并聚焦到文本框。"""
        self._last_anchor_rect = QRect(anchor_rect)
        self.reposition(anchor_rect)
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()
        self.input.selectAll()

    def reposition(self, anchor_rect: QRect | None = None) -> None:
        """根据角色当前位置重新摆放输入框。"""
        if anchor_rect is not None:
            self._last_anchor_rect = QRect(anchor_rect)
        if self._last_anchor_rect.isNull():
            return

        x = self._last_anchor_rect.x() + (self._last_anchor_rect.width() - self.width()) // 2
        y = self._last_anchor_rect.y() + self._last_anchor_rect.height() + 4
        self.move(x, max(0, y))

    def _submit(self) -> None:
        """提交输入内容；为空时仅关闭输入框。"""
        text = self.input.text().strip()
        if not text:
            self.hide()
            return
        self.input.clear()
        self.hide()
        self.message_submitted.emit(text)
