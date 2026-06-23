from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QScreen

from storage.json_store import load_json, save_json
from utils.logger import get_logger


logger = get_logger(__name__)


class ScreenProvider(Protocol):
    def primaryScreen(self) -> QScreen | None:  # noqa: N802
        """处理 `primaryScreen` 对应的业务逻辑。"""
        ...

    def screens(self) -> list[QScreen]:
        """处理 `screens` 对应的业务逻辑。"""
        ...


class WindowPositionService:
    """读取、校验、恢复并保存桌宠窗口位置。"""

    def __init__(
        self,
        state_path: Path,
        screen_provider: ScreenProvider,
        default_margin: int = 30,
        fallback_position: QPoint | None = None,
    ) -> None:
        """初始化当前对象及其依赖。"""
        self.state_path = state_path
        self.screen_provider = screen_provider
        self.default_margin = default_margin
        self.fallback_position = fallback_position or QPoint(50, 50)

    def restore_position(
        self,
        window_size: QSize,
        base_size: tuple[int, int],
        remember_last_position: bool = True,
    ) -> QPoint:
        """处理 `restore_position` 对应的业务逻辑。"""
        state = self.load_state()
        if remember_last_position:
            saved_position = self._saved_position(state)
            if saved_position is not None:
                if self.position_visible_on_any_screen(saved_position, window_size):
                    return saved_position
                logger.warning(
                    "Saved window position is outside visible screens: x=%s, y=%s. Falling back.",
                    state.get("x"),
                    state.get("y"),
                )
        return self.default_position(base_size)

    def load_state(self) -> dict[str, Any]:
        """读取 `load_state` 所需的数据。"""
        return load_json(self.state_path, {"x": None, "y": None})

    def save_position(self, position: QPoint) -> None:
        """保存 `save_position` 产生的数据。"""
        save_json(self.state_path, {"x": position.x(), "y": position.y()})

    def position_visible_on_any_screen(self, position: QPoint, window_size: QSize) -> bool:
        """处理 `position_visible_on_any_screen` 对应的业务逻辑。"""
        window_rect = QRect(position, window_size)
        for screen in self.screen_provider.screens():
            if screen.availableGeometry().intersects(window_rect):
                return True
        return False

    def default_position(self, base_size: tuple[int, int]) -> QPoint:
        """处理 `default_position` 对应的业务逻辑。"""
        screen = self.screen_provider.primaryScreen()
        if screen is None:
            return QPoint(self.fallback_position)
        available = screen.availableGeometry()
        width, height = base_size
        return QPoint(
            available.right() - width - self.default_margin,
            available.bottom() - height - self.default_margin,
        )

    def _saved_position(self, state: dict[str, Any]) -> QPoint | None:
        """处理 `_saved_position` 对应的业务逻辑。"""
        if state.get("x") is None or state.get("y") is None:
            return None
        try:
            return QPoint(int(state["x"]), int(state["y"]))
        except (TypeError, ValueError):
            return None