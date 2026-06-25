from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PySide6.QtCore import QRect


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from app.bubble_position_service import BubblePositionService  # noqa: E402


class FakeScreen:
    # 初始化当前对象及其依赖。
    def __init__(self, available: QRect) -> None:
        """初始化当前对象及其依赖。"""
        self.available = available

    # 为 FakeScreen 测试替身提供available屏幕区域行为。
    def availableGeometry(self) -> QRect:  # noqa: N802
        """为 FakeScreen 测试替身提供available屏幕区域行为。"""
        return QRect(self.available)


class FakeApplication:
    # 初始化当前对象及其依赖。
    def __init__(self, available: QRect) -> None:
        """初始化当前对象及其依赖。"""
        self.screen = FakeScreen(available)

    # 为 FakeApplication 测试替身提供屏幕at行为。
    def screenAt(self, _point):  # noqa: N802
        """为 FakeApplication 测试替身提供屏幕at行为。"""
        return self.screen

    # 为 FakeApplication 测试替身提供primary屏幕行为。
    def primaryScreen(self):  # noqa: N802
        """为 FakeApplication 测试替身提供primary屏幕行为。"""
        return self.screen


class BubblePositionServiceTests(unittest.TestCase):
    # 准备当前测试所需的环境和数据。
    def setUp(self) -> None:
        """准备当前测试所需的环境和数据。"""
        self.available = QRect(0, 0, 800, 600)
        self.service = BubblePositionService(FakeApplication(self.available))

    # 为测试准备assertinside屏幕数据或断言辅助结果。
    def assert_inside_screen(self, position, size: tuple[int, int]) -> None:
        """为测试准备assertinside屏幕数据或断言辅助结果。"""
        rect = QRect(position.x(), position.y(), size[0], size[1])
        self.assertTrue(self.available.contains(rect), rect)

    # 验证speech 气泡 stays on 屏幕 around edges场景下的预期结果。
    def test_speech_bubble_stays_on_screen_around_edges(self) -> None:
        """验证speech 气泡 stays on 屏幕 around edges场景下的预期结果。"""
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

    # 验证回复 气泡 stays on 屏幕 around edges场景下的预期结果。
    def test_reply_bubble_stays_on_screen_around_edges(self) -> None:
        """验证回复 气泡 stays on 屏幕 around edges场景下的预期结果。"""
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

    # 验证speech 气泡 avoids visible 回复 气泡场景下的预期结果。
    def test_speech_bubble_avoids_visible_reply_bubble(self) -> None:
        """验证speech 气泡 avoids visible 回复 气泡场景下的预期结果。"""
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
