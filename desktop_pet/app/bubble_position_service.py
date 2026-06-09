from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPoint, QRect


class BubblePositionService:
    """Calculate floating bubble positions around the pet window."""

    def __init__(self, application: Any) -> None:
        self.application = application

    def speech_bubble_position(
        self,
        bubble_size: tuple[int, int],
        anchor_rect: QRect,
        exclusion_rects: list[QRect] | None = None,
    ) -> QPoint:
        """Return the normal speech bubble position near the pet."""
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

    def reply_bubble_position(
        self,
        bubble_size: tuple[int, int],
        anchor_rect: QRect,
        exclusion_rects: list[QRect] | None = None,
    ) -> QPoint:
        """Return the clickable reply bubble position near the pet."""
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

    def _find_position(
        self,
        bubble_width: int,
        bubble_height: int,
        anchor_rect: QRect,
        candidates: list[QPoint],
        exclusion_rects: list[QRect] | None = None,
    ) -> QPoint:
        """Pick the first on-screen candidate that avoids the pet and other bubbles."""
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

    def _available_geometry(self, anchor_rect: QRect) -> QRect | None:
        screen = self.application.screenAt(anchor_rect.center())
        if screen is None:
            screen = self.application.primaryScreen()
        if screen is None:
            return None
        return screen.availableGeometry()
