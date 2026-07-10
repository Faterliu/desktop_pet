from __future__ import annotations

import sys
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from app.clipboard_service import ClipboardService  # noqa: E402


class FakeClipboard:
    # 初始化用于测试的剪贴板文本。
    def __init__(self, text: object) -> None:
        """初始化用于测试的剪贴板文本。"""
        self._text = text

    # 返回模拟的剪贴板文本内容。
    def text(self) -> object:
        """返回模拟的剪贴板文本内容。"""
        return self._text


class ClipboardServiceTests(unittest.TestCase):
    # 验证服务仅在 read_text 被调用时向提供方读取当前文本。
    def test_read_text_reads_provider_on_demand(self) -> None:
        """验证服务仅在 read_text 被调用时向提供方读取当前文本。"""
        calls = 0

        def provider() -> FakeClipboard:
            nonlocal calls
            calls += 1
            return FakeClipboard("待处理文本")

        service = ClipboardService(provider)

        self.assertEqual(calls, 0)
        self.assertEqual(service.read_text(), "待处理文本")
        self.assertEqual(calls, 1)

    # 验证没有剪贴板对象或文本类型异常时安全返回空字符串。
    def test_read_text_returns_empty_for_unavailable_or_non_text_clipboard(self) -> None:
        """验证没有剪贴板对象或文本类型异常时安全返回空字符串。"""
        self.assertEqual(ClipboardService(lambda: None).read_text(), "")
        self.assertEqual(ClipboardService(lambda: FakeClipboard(None)).read_text(), "")


if __name__ == "__main__":
    unittest.main()
