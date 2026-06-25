from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QScreen

from storage.json_store import load_json, save_json
from utils.logger import get_logger


logger = get_logger(__name__)


class ScreenProvider(Protocol):
    # 返回测试替身或应用对象记录的主屏幕对象。
    def primaryScreen(self) -> QScreen | None:  # noqa: N802
        """返回测试替身或应用对象记录的主屏幕对象。"""
        ...

    # 返回测试替身或应用对象记录的屏幕列表。
    def screens(self) -> list[QScreen]:
        """返回测试替身或应用对象记录的屏幕列表。"""
        ...


class WindowPositionService:
    """读取、校验、恢复并保存桌宠窗口位置。"""

    # 初始化当前对象及其依赖。
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

    # 根据 window_size、base_size、remember_last_position 计算窗口或气泡位置，保证结果落在可见屏幕内。
    def restore_position(
        self,
        window_size: QSize,
        base_size: tuple[int, int],
        remember_last_position: bool = True,
    ) -> QPoint:
        """根据 window_size、base_size、remember_last_position 计算窗口或气泡位置，保证结果落在可见屏幕内。"""
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

    # 读取状态并返回 dict[str, Any]。
    def load_state(self) -> dict[str, Any]:
        """读取状态并返回 dict[str, Any]。"""
        return load_json(self.state_path, {"x": None, "y": None})

    # 根据 position 把位置写入持久化存储并保持数据可恢复。
    def save_position(self, position: QPoint) -> None:
        """根据 position 把位置写入持久化存储并保持数据可恢复。"""
        save_json(self.state_path, {"x": position.x(), "y": position.y()})

    # 根据 position、window_size 计算窗口或气泡位置，保证结果落在可见屏幕内。
    def position_visible_on_any_screen(self, position: QPoint, window_size: QSize) -> bool:
        """根据 position、window_size 计算窗口或气泡位置，保证结果落在可见屏幕内。"""
        window_rect = QRect(position, window_size)
        for screen in self.screen_provider.screens():
            if screen.availableGeometry().intersects(window_rect):
                return True
        return False

    # 根据 base_size 计算窗口或气泡位置，保证结果落在可见屏幕内。
    def default_position(self, base_size: tuple[int, int]) -> QPoint:
        """根据 base_size 计算窗口或气泡位置，保证结果落在可见屏幕内。"""
        screen = self.screen_provider.primaryScreen()
        if screen is None:
            return QPoint(self.fallback_position)
        available = screen.availableGeometry()
        width, height = base_size
        return QPoint(
            available.right() - width - self.default_margin,
            available.bottom() - height - self.default_margin,
        )

    # 根据 state 计算窗口或气泡位置，保证结果落在可见屏幕内。
    def _saved_position(self, state: dict[str, Any]) -> QPoint | None:
        """根据 state 计算窗口或气泡位置，保证结果落在可见屏幕内。"""
        if state.get("x") is None or state.get("y") is None:
            return None
        try:
            return QPoint(int(state["x"]), int(state["y"]))
        except (TypeError, ValueError):
            return None