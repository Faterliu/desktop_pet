from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QMouseEvent, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from utils.dwm_border import suppress_dwm_border


class FormalAnswerPanel(QWidget):
    # 初始化可拖动、可复制、可关闭的正式问答面板。
    def __init__(self, title: str = "正式问答") -> None:
        """初始化可拖动、可复制、可关闭的正式问答面板。"""
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setStyleSheet(
            """
            QWidget {
                background: #fff8ee;
                border: 1px solid #d9b47d;
                border-radius: 16px;
            }
            QLabel {
                background: transparent;
                border: none;
                color: #5a3715;
                font-weight: 600;
            }
            QTextEdit {
                background: #fffdf8;
                border: 1px solid #edd5ac;
                border-radius: 12px;
                color: #3d2a1b;
                padding: 8px;
            }
            QPushButton {
                background: #ffcf8b;
                border: none;
                border-radius: 10px;
                color: #5a3715;
                padding: 6px 10px;
            }
            QPushButton:hover {
                background: #ffc16a;
            }
            """
        )

        self._drag_offset = QPoint()
        self._dragging = False

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(8)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        self.title_label = QLabel(title, self)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)

        self.close_button = QPushButton("关闭", self)
        self.close_button.clicked.connect(self.close)
        header_layout.addWidget(self.close_button)
        root_layout.addLayout(header_layout)

        self.text_edit = QTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setAcceptRichText(False)
        self.text_edit.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        root_layout.addWidget(self.text_edit)

        self.resize(420, 320)

    # 设置问答标题和正文，并初始显示在角色旁边。
    def set_content(
        self,
        title: str,
        text: str,
        anchor_rect: QRect,
        offset_index: int = 0,
    ) -> None:
        """设置问答标题和正文，并初始显示在角色旁边。"""
        self.title_label.setText(title)
        self.text_edit.setPlainText(text)
        self._place_near(anchor_rect, offset_index)
        self.show()
        self.raise_()

    # 移除 Windows DWM 在透明无边框窗口周围绘制的细线边框。
    def nativeEvent(self, eventType, message) -> tuple:  # noqa: N802
        """移除 Windows DWM 在透明无边框窗口周围绘制的细线边框。"""
        ok, result = suppress_dwm_border(eventType, message)
        if ok:
            return True, result
        return super().nativeEvent(eventType, message)

    # 把新的正式回答追加到现有面板中，不覆盖旧内容。
    def append_entry(self, question: str, answer: str) -> None:
        """把新的正式回答追加到现有面板中，不覆盖旧内容。"""
        entry = self.format_entry(question, answer)
        existing_text = self.text_edit.toPlainText().strip()
        self.text_edit.setPlainText(f"{existing_text}\n\n{entry}" if existing_text else entry)
        self.text_edit.moveCursor(QTextCursor.MoveOperation.End)
        self.show()
        self.raise_()

    # 把正式回答格式化为适合直接阅读和复制的纯文本。
    @staticmethod
    def format_entry(question: str, answer: str) -> str:
        """把正式回答格式化为适合直接阅读和复制的纯文本。"""
        _ = question
        return answer.strip()

    # 把正式问答面板初始摆放在角色附近，并错开多个面板。
    def _place_near(self, anchor_rect: QRect, offset_index: int = 0) -> None:
        """把正式问答面板初始摆放在角色附近，并错开多个面板。"""
        stagger = min(max(offset_index, 0), 5) * 28
        x = anchor_rect.x() + anchor_rect.width() + 16 + stagger
        y = max(0, anchor_rect.y() - 20 + stagger)
        self.move(x, y)

    # 按下非文本区域时开始拖动面板。
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """按下非文本区域时开始拖动面板。"""
        if event.button() == Qt.MouseButton.LeftButton and not self.text_edit.geometry().contains(
            event.position().toPoint()
        ):
            self._dragging = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    # 拖动正式问答面板到任意位置。
    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """拖动正式问答面板到任意位置。"""
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    # 结束面板拖动。
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """结束面板拖动。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
        super().mouseReleaseEvent(event)
