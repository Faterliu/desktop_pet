from __future__ import annotations

import random
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal

from storage.json_store import load_json
from storage.usage_store import UsageStore
from utils.time_utils import now_local


class BehaviorController(QObject):
    speak_requested = Signal(str, int, str)

    def __init__(
        self,
        app_config_path: str | Path,
        local_lines_path: str | Path,
        usage_store: UsageStore,
        config_loader: Callable[[], dict[str, Any]],
    ) -> None:
        """初始化主动行为控制器，并启动空闲检测计时器。"""
        super().__init__()
        self.app_config_path = Path(app_config_path)
        self.local_lines_path = Path(local_lines_path)
        self.usage_store = usage_store
        self.config_loader = config_loader

        self.last_user_interaction = now_local()
        self.last_proactive_at = None
        self.awaiting_user_reply = False

        self.idle_check_timer = QTimer(self)
        self.idle_check_timer.timeout.connect(self._maybe_idle_prompt)
        self.idle_check_timer.start(60_000)

    def start(self) -> None:
        """在应用启动后延迟触发一次启动问候。"""
        QTimer.singleShot(1200, self._startup_greeting)

    def reload(self) -> None:
        """重置行为状态，供重新加载配置后继续使用。"""
        self.last_user_interaction = now_local()
        self.awaiting_user_reply = False

    def notify_user_interaction(self) -> None:
        """记录用户刚刚发生过交互，并取消等待回复状态。"""
        self.last_user_interaction = now_local()
        self.awaiting_user_reply = False

    def notify_proactive_shown(self) -> None:
        """记录刚展示过主动消息，并标记等待用户回应。"""
        self.last_proactive_at = now_local()
        self.awaiting_user_reply = True

    def set_do_not_disturb(self, enabled: bool) -> None:
        """更新内存中的免打扰开关状态。"""
        config = self.config_loader()
        config.setdefault("behavior", {})["do_not_disturb"] = enabled

    def _startup_greeting(self) -> None:
        """满足条件时发送启动问候。"""
        config = self.config_loader()
        behavior = config.get("behavior", {})
        if behavior.get("do_not_disturb") or not behavior.get("startup_greeting", True):
            return
        max_daily = int(behavior.get("max_local_lines_per_day", 10))
        if not self.usage_store.can_use_local(max_daily):
            return
        line = self._random_line("startup")
        if line:
            self.usage_store.increment_local_line()
            self.notify_proactive_shown()
            self.speak_requested.emit(line, 7000, "waving")

    def _maybe_idle_prompt(self) -> None:
        """在用户空闲足够久时尝试发送一条主动陪伴消息。"""
        config = self.config_loader()
        behavior = config.get("behavior", {})
        if behavior.get("do_not_disturb") or not behavior.get("proactive_chat", True):
            return

        max_daily = int(behavior.get("max_local_lines_per_day", 10))
        if not self.usage_store.can_use_local(max_daily):
            return

        min_minutes = int(behavior.get("min_proactive_interval_minutes", 20))
        now = now_local()
        if now - self.last_user_interaction < timedelta(minutes=min_minutes):
            return
        if self.awaiting_user_reply:
            return
        if self.last_proactive_at and now - self.last_proactive_at < timedelta(minutes=min_minutes):
            return

        line_type = random.choice(["idle", "quiet", "encourage"])
        line = self._random_line(line_type)
        if not line:
            return
        self.usage_store.increment_local_line()
        self.notify_proactive_shown()
        self.speak_requested.emit(line, 6000, "waving")

    def trigger_test_speak(self) -> bool:
        """立即触发一次测试主动说话，不受冷却时间限制。"""
        line_type = random.choice(["startup", "idle", "quiet", "encourage"])
        line = self._random_line(line_type)
        if not line:
            return False
        self.speak_requested.emit(line, 6000, "waving")
        return True

    def _random_line(self, group_name: str) -> str:
        """从指定话术分组中随机抽取一句文本。"""
        payload = load_json(self.local_lines_path, {})
        lines = payload.get(group_name, [])
        if not lines:
            return ""
        return random.choice(lines)
