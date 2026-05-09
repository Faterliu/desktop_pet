from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap

from storage.json_store import load_json
from utils.logger import get_logger


logger = get_logger(__name__)

DEFAULT_SPRITE_CONFIG = {
    "sprite_file": "assets/spritesheet.webp",
    "frame_width": 192,
    "frame_height": 208,
    "rows": 9,
    "columns": 8,
    "default_fps": 8,
    "actions": {
        "idle": {"row": 0, "frames": 1, "fps": 6, "loop": True},
    },
}


class SpritePlayer(QObject):
    frame_changed = Signal(QPixmap)
    action_changed = Signal(str)

    def __init__(self, config_path: str | Path, scale: float = 1.0) -> None:
        """初始化精灵播放器，加载配置并准备动画计时器。"""
        super().__init__()
        self.config_path = Path(config_path)
        self.project_root = self.config_path.resolve().parents[1]
        self.scale = max(scale, 0.2)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._advance_frame)

        self.config: dict[str, Any] = {}
        self.frames_by_action: dict[str, list[QPixmap]] = {}
        self.current_action = "idle"
        self.fallback_action = "idle"
        self.current_index = 0
        self.force_single_cycle = False
        self.load()

    def load(self) -> None:
        """重新读取精灵配置与帧数据，并切回默认动作。"""
        self.config = load_json(self.config_path, DEFAULT_SPRITE_CONFIG)
        self.frames_by_action = self._load_frames()
        self.current_action = "idle" if "idle" in self.frames_by_action else next(
            iter(self.frames_by_action), "idle"
        )
        self.current_index = 0
        self._restart_timer_for_action(self.current_action)
        self.frame_changed.emit(self.current_pixmap())

    def set_scale(self, scale: float) -> None:
        """更新精灵显示缩放比例并立即刷新当前帧。"""
        self.scale = max(scale, 0.2)
        self.frame_changed.emit(self.current_pixmap())

    def set_action(
        self,
        action_name: str,
        fallback_action: str = "idle",
        force_single_cycle: bool = False,
    ) -> None:
        """切换当前动作，并可选择强制只播放一轮后回退。"""
        if action_name not in self.frames_by_action:
            logger.warning("Unknown action requested: %s", action_name)
            action_name = "idle"
        self.current_action = action_name
        self.fallback_action = fallback_action if fallback_action in self.frames_by_action else "idle"
        self.current_index = 0
        self.force_single_cycle = force_single_cycle
        self._restart_timer_for_action(action_name)
        self.action_changed.emit(self.current_action)
        self.frame_changed.emit(self.current_pixmap())

    def current_pixmap(self) -> QPixmap:
        """返回当前动作下应显示的帧图像。"""
        frames = self.frames_by_action.get(self.current_action) or [self._placeholder_frame()]
        frame = frames[min(self.current_index, len(frames) - 1)]
        if self.scale == 1.0:
            return frame
        return frame.scaled(
            int(frame.width() * self.scale),
            int(frame.height() * self.scale),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )

    def base_size(self) -> tuple[int, int]:
        """返回按当前缩放计算后的基础显示尺寸。"""
        width = int(self.config.get("frame_width", 192) * self.scale)
        height = int(self.config.get("frame_height", 208) * self.scale)
        return width, height

    def action_duration_ms(self, action_name: str, force_single_cycle: bool = False) -> int:
        """返回指定动作完整播放一轮大约需要的时间。"""
        action_config = self.config.get("actions", {}).get(action_name, {})
        frame_count = len(self.frames_by_action.get(action_name, [])) or int(action_config.get("frames", 1))
        fps = int(action_config.get("fps", self.config.get("default_fps", 8)))
        interval_ms = max(400, int(1000 / max(fps, 1)))
        if not force_single_cycle and bool(action_config.get("loop", True)):
            return interval_ms
        return max(interval_ms, frame_count * interval_ms)

    def _advance_frame(self) -> None:
        """推进到下一帧；非循环动作结束后自动回退。"""
        frames = self.frames_by_action.get(self.current_action, [])
        if not frames:
            return

        action_config = self.config.get("actions", {}).get(self.current_action, {})
        loop = bool(action_config.get("loop", True)) and not self.force_single_cycle
        if self.current_index >= len(frames) - 1:
            if loop:
                self.current_index = 0
            else:
                self.set_action(self.fallback_action)
                return
        else:
            self.current_index += 1
        self.frame_changed.emit(self.current_pixmap())

    def _restart_timer_for_action(self, action_name: str) -> None:
        """根据动作帧率重新启动播放计时器。"""
        action_config = self.config.get("actions", {}).get(action_name, {})
        fps = int(action_config.get("fps", self.config.get("default_fps", 8)))
        interval_ms = max(400, int(1000 / max(fps, 1)))
        self.timer.start(interval_ms)

    def _load_frames(self) -> dict[str, list[QPixmap]]:
        """从图集裁切出每个动作对应的帧列表。"""
        sprite_rel_path = self.config.get("sprite_file", "assets/spritesheet.webp")
        sprite_path = self.project_root / sprite_rel_path
        sheet = QPixmap(str(sprite_path))
        if sheet.isNull():
            logger.error("Sprite sheet missing or unreadable: %s", sprite_path)
            return self._placeholder_actions()

        frame_width = int(self.config.get("frame_width", 192))
        frame_height = int(self.config.get("frame_height", 208))
        actions = self.config.get("actions", {})
        frames_by_action: dict[str, list[QPixmap]] = {}
        for action_name, action_config in actions.items():
            row = int(action_config.get("row", 0))
            frame_count = int(action_config.get("frames", 1))
            frames: list[QPixmap] = []
            for index in range(frame_count):
                x = index * frame_width
                y = row * frame_height
                frames.append(sheet.copy(x, y, frame_width, frame_height))
            frames_by_action[action_name] = frames or [self._placeholder_frame()]
        return frames_by_action

    def _placeholder_actions(self) -> dict[str, list[QPixmap]]:
        """在素材缺失时，为每个动作生成占位帧。"""
        return {
            action_name: [self._placeholder_frame(action_name)]
            for action_name in self.config.get("actions", {"idle": {}}).keys()
        }

    def _placeholder_frame(self, text: str = "小胡") -> QPixmap:
        """生成一张带文字的占位图，避免素材缺失时界面空白。"""
        width = int(self.config.get("frame_width", 192))
        height = int(self.config.get("frame_height", 208))
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#ffcf8b"))
        painter.setPen(QColor("#7a4b1f"))
        painter.drawRoundedRect(8, 8, width - 16, height - 16, 24, 24)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
        return pixmap
