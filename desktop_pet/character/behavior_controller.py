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
        self._last_time_key = self._time_greeting_key()
        self._last_season_key = self._season_key()

        self.idle_check_timer = QTimer(self)
        self.idle_check_timer.timeout.connect(self._maybe_idle_prompt)
        self.idle_check_timer.start(60_000)

        self.period_check_timer = QTimer(self)
        self.period_check_timer.timeout.connect(self._check_period_change)

    def start(self) -> None:
        """在应用启动后延迟触发一次启动问候，并启动时段变化检测。"""
        QTimer.singleShot(1200, self._startup_greeting)
        self.period_check_timer.start(60_000)

    def reload(self) -> None:
        """重置行为状态，供重新加载配置后继续使用。"""
        self.last_user_interaction = now_local()
        self.awaiting_user_reply = False
        self._last_time_key = self._time_greeting_key()
        self._last_season_key = self._season_key()

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
        """满足条件时发送启动问候，周期首日优先季节问候，其次时段问候。"""
        config = self.config_loader()
        behavior = config.get("behavior", {})
        if behavior.get("do_not_disturb") or not behavior.get("startup_greeting", True):
            return
        max_daily = int(behavior.get("max_local_lines_per_day", 10))
        if not self.usage_store.can_use_local(max_daily):
            return
        line = ""
        if self._is_cycle_start():
            line = self._random_line(self._season_key())
        if not line:
            time_key = self._time_greeting_key()
            line = self._random_line(time_key) if time_key else ""
        if not line:
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

        line_types = ["idle", "quiet", "encourage"]
        time_key = self._time_greeting_key()
        if time_key:
            line_types.append(time_key)
        line_type = random.choice(line_types)
        line = self._random_line(line_type)
        if not line:
            return
        self.usage_store.increment_local_line()
        self.notify_proactive_shown()
        self.speak_requested.emit(line, 6000, "waving")

    def _check_period_change(self) -> None:
        """检测时段或季节是否变化，变化时立即弹出新时段问候。"""
        config = self.config_loader()
        behavior = config.get("behavior", {})
        if behavior.get("do_not_disturb"):
            return
        max_daily = int(behavior.get("max_local_lines_per_day", 10))
        if not self.usage_store.can_use_local(max_daily):
            return

        time_key = self._time_greeting_key()
        season_key = self._season_key()
        if time_key != self._last_time_key or season_key != self._last_season_key:
            self._last_time_key = time_key
            self._last_season_key = season_key
            line = self._random_line(time_key) if time_key else ""
            if not line:
                line = self._random_line("startup")
            if line:
                self.usage_store.increment_local_line()
                self.notify_proactive_shown()
                self.speak_requested.emit(line, 7000, "waving")

    def trigger_test_speak(self) -> bool:
        """立即触发一次测试主动说话，不受冷却时间限制。"""
        line_types = ["startup", "idle", "quiet", "encourage"]
        time_key = self._time_greeting_key()
        if time_key:
            line_types.append(time_key)
        line_type = random.choice(line_types)
        line = self._random_line(line_type)
        if not line:
            return False
        self.notify_proactive_shown()
        self.speak_requested.emit(line, 6000, "waving")
        return True

    def pick_farewell_line(self) -> str:
        """从 farewell 分组中随机抽取一句道别话术。"""
        return self._random_line("farewell")

    def pick_reply_line(self) -> str:
        """从回复系分组中随机抽取一句回应话术。"""
        group = random.choice(["break_reminder", "comfort", "encourage"])
        return self._random_line(group)

    def pick_feedback_line(self) -> str:
        """从 feedback 分组中随机抽取一句反馈话术，用于用户回应主动问候时。"""
        return self._random_line("feedback")

    def is_within_proactive_reply_window(self, window_seconds: int = 60) -> bool:
        """判断当前是否在主动问候后的回复窗口内。"""
        if self.last_proactive_at is None:
            return False
        return now_local() - self.last_proactive_at < timedelta(seconds=window_seconds)

    def pick_ignored_line(self) -> str:
        """从 ignored 分组中随机抽取一句话术，用于关闭置顶时回应。"""
        return self._random_line("ignored")

    def pick_return_after_idle_line(self) -> str:
        """从 return_after_idle 分组中随机抽取一句话术，用于开启置顶时回应。"""
        return self._random_line("return_after_idle")

    def pick_waiting_line(self) -> str:
        """从 waiting 分组中随机抽取一句等待提示话术。"""
        return self._random_line("waiting")

    def pick_poetry_line(self) -> str:
        """从 poetry 分组中随机抽取一首诗。"""
        return self._random_line("poetry")

    def _time_greeting_key(self) -> str | None:
        """根据当前本地时间返回对应的时段问候分组 key。"""
        hour = now_local().hour
        if 5 <= hour < 11:
            return "greeting_morning"
        if 11 <= hour < 17:
            return "greeting_noon"
        if 17 <= hour < 22:
            return "greeting_evening"
        return "sleepy"

    def _season_key(self) -> str:
        """根据当前月份返回对应的季节分组 key。"""
        month = now_local().month
        if 3 <= month <= 5:
            return "greeting_spring"
        if 6 <= month <= 8:
            return "greeting_summer"
        if 9 <= month <= 11:
            return "greeting_autumn"
        return "greeting_winter"

    def _is_cycle_start(self) -> bool:
        """判断今天是否为 5 天周期的第一天。"""
        yday = now_local().timetuple().tm_yday
        return (yday - 1) % 5 == 0

    def _random_line(self, group_name: str) -> str:
        """从指定话术分组中随机抽取一句文本。"""
        payload = load_json(self.local_lines_path, {})
        lines = payload.get(group_name, [])
        if not lines:
            return ""
        return random.choice(lines)
