from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PySide6.QtCore import QRect


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from app.bubble_position_service import BubblePositionService  # noqa: E402


class FakeScreen:
    def __init__(self, available: QRect) -> None:
        """初始化当前对象及其依赖。"""
        self.available = available

    def availableGeometry(self) -> QRect:  # noqa: N802
        """处理 `availableGeometry` 对应的业务逻辑。"""
        return QRect(self.available)


class FakeApplication:
    def __init__(self, available: QRect) -> None:
        """初始化当前对象及其依赖。"""
        self.screen = FakeScreen(available)

    def screenAt(self, _point):  # noqa: N802
        """处理 `screenAt` 对应的业务逻辑。"""
        return self.screen

    def primaryScreen(self):  # noqa: N802
        """处理 `primaryScreen` 对应的业务逻辑。"""
        return self.screen


class BubblePositionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        """准备当前测试所需的环境和数据。"""
        self.available = QRect(0, 0, 800, 600)
        self.service = BubblePositionService(FakeApplication(self.available))

    def assert_inside_screen(self, position, size: tuple[int, int]) -> None:
        """处理 `assert_inside_screen` 对应的业务逻辑。"""
        rect = QRect(position.x(), position.y(), size[0], size[1])
        self.assertTrue(self.available.contains(rect), rect)

    def test_speech_bubble_stays_on_screen_around_edges(self) -> None:
        """验证 `test_speech_bubble_stays_on_screen_around_edges` 对应的行为。"""
        bubble_size = (220, 80)
        anchors = [
            QRect(350, 260, 100, 120),
            QRect(0, 260, 100, 120),
            QRect(700, 260, 100, 120),
            QRect(350, 520, 100, 80),
        ]

        for anchor in anchors:
            with self.subTest(anchor=anchor):
                position = self.service.speech_bubble_position(bubble_size, anchor)
                self.assert_inside_screen(position, bubble_size)

    def test_reply_bubble_stays_on_screen_around_edges(self) -> None:
        """验证 `test_reply_bubble_stays_on_screen_around_edges` 对应的行为。"""
        bubble_size = (160, 48)
        anchors = [
            QRect(350, 260, 100, 120),
            QRect(0, 260, 100, 120),
            QRect(700, 260, 100, 120),
            QRect(350, 520, 100, 80),
        ]

        for anchor in anchors:
            with self.subTest(anchor=anchor):
                position = self.service.reply_bubble_position(bubble_size, anchor)
                self.assert_inside_screen(position, bubble_size)

    def test_speech_bubble_avoids_visible_reply_bubble(self) -> None:
        """验证 `test_speech_bubble_avoids_visible_reply_bubble` 对应的行为。"""
        anchor = QRect(350, 260, 100, 120)
        bubble_size = (220, 80)
        first_choice = QRect(250, 170, 220, 80)

        position = self.service.speech_bubble_position(
            bubble_size,
            anchor,
            exclusion_rects=[first_choice],
        )

        bubble_rect = QRect(position.x(), position.y(), bubble_size[0], bubble_size[1])
        self.assertFalse(bubble_rect.intersects(first_choice))


if __name__ == "__main__":
    unittest.main()
