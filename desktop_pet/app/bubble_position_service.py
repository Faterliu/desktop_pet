from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPoint, QRect


class BubblePositionService:
    """计算桌宠窗口周围的浮动气泡位置。"""

    # 初始化当前对象及其依赖。
    def __init__(self, application: Any) -> None:
        """初始化当前对象及其依赖。"""
        self.application = application

    # 根据 bubble_size、anchor_rect、exclusion_rects 计算窗口或气泡位置，保证结果落在可见屏幕内。
    def speech_bubble_position(
        self,
        bubble_size: tuple[int, int],
        anchor_rect: QRect,
        exclusion_rects: list[QRect] | None = None,
    ) -> QPoint:
        """根据 bubble_size、anchor_rect、exclusion_rects 计算窗口或气泡位置，保证结果落在可见屏幕内。"""
        bubble_width, bubble_height = bubble_size
        candidates = [
            QPoint(anchor_rect.x() + anchor_rect.width() - bubble_width + 20, anchor_rect.y() - bubble_height - 10),
            QPoint(anchor_rect.x() - 20, anchor_rect.y() - bubble_height - 10),
            QPoint(anchor_rect.x() + anchor_rect.width() - bubble_width + 20, anchor_rect.y() + anchor_rect.height() + 10),
            QPoint(anchor_rect.x() - 20, anchor_rect.y() + anchor_rect.height() + 10),
            QPoint(anchor_rect.x() + anchor_rect.width() + 10, anchor_rect.y() + anchor_rect.height() // 2 - bubble_height // 2),
            QPoint(anchor_rect.x() - bubble_width - 10, anchor_rect.y() + anchor_rect.height() // 2 - bubble_height // 2),
        ]
        return self._find_position(bubble_width, bubble_height, anchor_rect, candidates, exclusion_rects)

    # 根据 bubble_size、anchor_rect、exclusion_rects 计算窗口或气泡位置，保证结果落在可见屏幕内。
    def reply_bubble_position(
        self,
        bubble_size: tuple[int, int],
        anchor_rect: QRect,
        exclusion_rects: list[QRect] | None = None,
    ) -> QPoint:
        """根据 bubble_size、anchor_rect、exclusion_rects 计算窗口或气泡位置，保证结果落在可见屏幕内。"""
        bubble_width, bubble_height = bubble_size
        center_x = anchor_rect.x() + anchor_rect.width() // 2
        center_y = anchor_rect.y() + anchor_rect.height() // 2
        candidates = [
            QPoint(anchor_rect.x() + anchor_rect.width() + 12, center_y - bubble_height // 2),
            QPoint(anchor_rect.x() - bubble_width - 12, center_y - bubble_height // 2),
            QPoint(center_x - bubble_width // 2, anchor_rect.y() - bubble_height - 10),
            QPoint(center_x - bubble_width // 2, anchor_rect.y() + anchor_rect.height() + 10),
        ]
        return self._find_position(bubble_width, bubble_height, anchor_rect, candidates, exclusion_rects)

    # 根据菜单尺寸优先将右键卡片放在桌宠右侧，空间不足时再选择其他方向。
    def context_menu_position(
        self,
        menu_size: tuple[int, int],
        anchor_rect: QRect,
        exclusion_rects: list[QRect] | None = None,
    ) -> QPoint:
        """计算右键微型菜单的右侧优先位置，并确保其留在当前屏幕内。"""
        menu_width, menu_height = menu_size
        center_y = anchor_rect.y() + anchor_rect.height() // 2
        candidates = [
            QPoint(anchor_rect.x() + anchor_rect.width() + 12, center_y - menu_height // 2),
            QPoint(anchor_rect.x() + anchor_rect.width() + 12, anchor_rect.y() - menu_height + 20),
            QPoint(anchor_rect.x() + anchor_rect.width() + 12, anchor_rect.y() + anchor_rect.height() - 20),
            QPoint(anchor_rect.x() - menu_width - 12, center_y - menu_height // 2),
            QPoint(anchor_rect.x() - menu_width - 12, anchor_rect.y() - menu_height + 20),
            QPoint(anchor_rect.x() - menu_width - 12, anchor_rect.y() + anchor_rect.height() - 20),
            QPoint(anchor_rect.x() + anchor_rect.width() - menu_width + 20, anchor_rect.y() - menu_height - 10),
            QPoint(anchor_rect.x() + anchor_rect.width() - menu_width + 20, anchor_rect.y() + anchor_rect.height() + 10),
        ]
        return self._find_position(menu_width, menu_height, anchor_rect, candidates, exclusion_rects)

    # 按候选方向寻找不越界且避开占用区域的气泡位置。
    def _find_position(
        self,
        bubble_width: int,
        bubble_height: int,
        anchor_rect: QRect,
        candidates: list[QPoint],
        exclusion_rects: list[QRect] | None = None,
    ) -> QPoint:
        """按候选方向寻找不越界且避开占用区域的气泡位置。"""
        available = self._available_geometry(anchor_rect)
        if available is None:
            return candidates[0] if candidates else QPoint(0, 0)

        exclusions = exclusion_rects or []
        for position in candidates:
            bubble_rect = QRect(position.x(), position.y(), bubble_width, bubble_height)
            if not available.contains(bubble_rect):
                continue
            if bubble_rect.intersects(anchor_rect):
                continue
            if any(bubble_rect.intersects(exclusion) for exclusion in exclusions):
                continue
            return position

        if not candidates:
            return QPoint(0, 0)

        first = candidates[0]
        x = max(available.x(), min(first.x(), available.x() + available.width() - bubble_width))
        y = max(available.y(), min(first.y(), available.y() + available.height() - bubble_height))
        return QPoint(max(0, x), max(0, y))

    # 根据 anchor_rect 计算窗口或气泡位置，保证结果落在可见屏幕内。
    def _available_geometry(self, anchor_rect: QRect) -> QRect | None:
        """根据 anchor_rect 计算窗口或气泡位置，保证结果落在可见屏幕内。"""
        screen = self.application.screenAt(anchor_rect.center())
        if screen is None:
            screen = self.application.primaryScreen()
        if screen is None:
            return None
        return screen.availableGeometry()
