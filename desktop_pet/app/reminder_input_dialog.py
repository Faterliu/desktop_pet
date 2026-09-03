from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLineEdit, QLabel, QSpinBox, QVBoxLayout, QWidget


class ReminderInputDialog(QDialog):
    """使用桌宠气泡配色的提醒输入框。"""

    def __init__(self, title: str, prompt: str, anchor_rect: QRect, position_service: object, *, value: str | int = "", input_kind: str = "text", minimum: int = 0, maximum: int = 999999) -> None:
        """初始化提醒输入控件，并把窗口放到人物周围的空位。"""
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("""
            ReminderInputDialog { background: transparent; }
            QWidget#reminder_surface { background: #fff3d7; border: 1px solid #d8b27a; border-radius: 16px; }
            QLabel#reminder_title { color: #5a3e28; font-size: 14px; font-weight: 600; background: transparent; }
            QLabel#reminder_prompt { color: #795b3d; font-size: 12px; background: transparent; }
            QLineEdit, QSpinBox { color: #3d2a1b; background: #fffaf0; border: 1px solid #d8b27a; border-radius: 9px; padding: 6px 9px; font-size: 13px; }
            QLineEdit:focus, QSpinBox:focus { border-color: #c98d52; }
            QDialogButtonBox QPushButton { color: #5a3e28; background: #f8dfb8; border: 1px solid #d5a66d; border-radius: 8px; padding: 5px 14px; min-width: 58px; }
            QDialogButtonBox QPushButton:hover { background: #ffe9c9; }
        """)
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
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=surface)
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
    def get_text(cls, title: str, prompt: str, anchor_rect: QRect, position_service: object) -> tuple[str, bool]:
        """显示文字提醒输入框，并返回文本与确认状态。"""
        dialog = cls(title, prompt, anchor_rect, position_service)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return dialog.input_field.text(), accepted

    @classmethod
    def get_int(cls, title: str, prompt: str, anchor_rect: QRect, position_service: object, *, value: int, minimum: int, maximum: int) -> tuple[int, bool]:
        """显示数字提醒输入框，并返回数值与确认状态。"""
        dialog = cls(title, prompt, anchor_rect, position_service, value=value, input_kind="int", minimum=minimum, maximum=maximum)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return dialog.input_field.value(), accepted
