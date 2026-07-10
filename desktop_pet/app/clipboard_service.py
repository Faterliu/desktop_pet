from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import QApplication


class ClipboardService:
    """仅在调用方主动请求时读取系统剪贴板文本。"""

    # 初始化剪贴板访问器；测试时可注入替身，运行时使用 QApplication 剪贴板。
    def __init__(self, clipboard_provider: Callable[[], Any] | None = None) -> None:
        """初始化剪贴板访问器；测试时可注入替身，运行时使用 QApplication 剪贴板。"""
        self._clipboard_provider = clipboard_provider or QApplication.clipboard

    # 读取当前剪贴板中的纯文本；不可用或为空时返回空字符串。
    def read_text(self) -> str:
        """读取当前剪贴板中的纯文本；不可用或为空时返回空字符串。"""
        try:
            clipboard = self._clipboard_provider()
            if clipboard is None:
                return ""
            text = clipboard.text()
        except RuntimeError:
            return ""
        return text if isinstance(text, str) else ""
