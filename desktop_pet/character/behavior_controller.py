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
    knowledge_speak_requested = Signal()

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
        self.memory_path = self.app_config_path.parent.parent / "data" / "memory.json"

        self.last_user_interaction = now_local()
        self.last_proactive_at = None
        self.awaiting_user_reply = False
        self._consecutive_unanswered = 0
        self._last_proactive_type = ""
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
        self._consecutive_unanswered = 0
        self._last_proactive_type = ""
        self._last_time_key = self._time_greeting_key()
        self._last_season_key = self._season_key()

    def notify_user_interaction(self) -> None:
        """记录用户刚刚发生过交互，取消等待回复状态，重置连续未回应计数。"""
        self.last_user_interaction = now_local()
        self.awaiting_user_reply = False
        self._consecutive_unanswered = 0

    def notify_proactive_shown(self, proactive_type: str = "regular_greeting") -> None:
        """记录刚展示过主动消息、类型，并标记等待用户回应。"""
        self.last_proactive_at = now_local()
        self.awaiting_user_reply = True
        self._last_proactive_type = proactive_type

    def notify_proactive_response(self) -> None:
        """用户回应主动问候后，调整对应问候类型的比例。"""
        if self._last_proactive_type:
            self._adjust_ratio(self._last_proactive_type)

    def _proactive_ratio(self) -> dict[str, float]:
        """读取当前主动问候内容比例配置。"""
        config = self.config_loader()
        default = {"extra_knowledge": 0.5, "regular_greeting": 0.5}
        return config.setdefault("proactive_content_ratio", default)

    def _adjust_ratio(self, responded_type: str) -> None:
        """用户回应对应类型后微调问候类型比例。"""
        config = self.config_loader()
        ratio = self._proactive_ratio()
        other_type = "extra_knowledge" if responded_type == "regular_greeting" else "regular_greeting"
        ratio[responded_type] = min(0.7, round(ratio.get(responded_type, 0.5) + 0.005, 4))
        ratio[other_type] = max(0.3, round(ratio.get(other_type, 0.5) - 0.001, 4))
        config["proactive_content_ratio"] = ratio

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
            self.notify_proactive_shown()
            self.speak_requested.emit(line, 7000, "waving")

    def _dynamic_proactive_interval_minutes(self) -> int:
        """根据连续未回应次数返回动态主动问候间隔（分钟）。"""
        if self._consecutive_unanswered <= 1:
            return 15
        if self._consecutive_unanswered == 2:
            return 30
        if self._consecutive_unanswered == 3:
            return random.randint(30, 60)
        return 60

    def _has_memory_content(self) -> bool:
        """检查 memory.json 中是否含有对用户有用的记忆信息。"""
        memory = load_json(self.memory_path, {})
        user_profile = memory.get("user_profile", {})
        work_study = memory.get("work_study", {})
        if user_profile.get("preferences") or user_profile.get("important_personal_notes"):
            return True
        if work_study.get("current_learning_topics") or work_study.get("current_projects"):
            return True
        return False

    def _maybe_idle_prompt(self) -> None:
        """在用户空闲足够久时尝试发送一条主动陪伴消息。"""
        config = self.config_loader()
        behavior = config.get("behavior", {})
        if behavior.get("do_not_disturb") or not behavior.get("proactive_chat", True):
            return

        max_daily = int(behavior.get("max_local_lines_per_day", 10))
        if not self.usage_store.can_use_local(max_daily):
            return

        interval_minutes = self._dynamic_proactive_interval_minutes()
        now = now_local()
        if now - self.last_user_interaction < timedelta(minutes=interval_minutes):
            return
        if self.last_proactive_at and now - self.last_proactive_at < timedelta(minutes=interval_minutes):
            return

        if self.awaiting_user_reply:
            self._consecutive_unanswered += 1

        # 根据比例选择问候类型
        ratio = self._proactive_ratio()
        extra_weight = ratio.get("extra_knowledge", 0.5)
        if self._has_memory_content() and random.random() < extra_weight:
            self.notify_proactive_shown("extra_knowledge")
            self.knowledge_speak_requested.emit()
            self._consecutive_unanswered = 0
            return

        line_types = ["idle", "quiet", "encourage","break_reminder"]
        time_key = self._time_greeting_key()
        if time_key:
            line_types.append(time_key)
        line_type = random.choice(line_types)
        line = self._random_line(line_type)
        if not line:
            return
        self.usage_store.increment_local_line()
        self.notify_proactive_shown("regular_greeting")
        self.speak_requested.emit(line, 6000, "waving")
        self._consecutive_unanswered = 0

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

    def trigger_test_idle_prompt(self) -> str:
        """立即触发一次空闲问候逻辑，绕过时间间隔限制，返回触发的问候类型。"""
        saved_interaction = self.last_user_interaction
        saved_proactive = self.last_proactive_at
        saved_type = self._last_proactive_type
        long_ago = now_local() - timedelta(hours=24)
        self.last_user_interaction = long_ago
        self.last_proactive_at = None
        self._last_proactive_type = ""
        try:
            self._maybe_idle_prompt()
            result_type = self._last_proactive_type
        finally:
            self._last_proactive_type = saved_type
            self.last_user_interaction = saved_interaction
            self.last_proactive_at = saved_proactive
        ratio = self._proactive_ratio()
        extra = ratio.get("extra_knowledge", 0.5)
        regular = ratio.get("regular_greeting", 0.5)
        if result_type == "extra_knowledge":
            return f"知识问候 (比例 extra={extra:.2f} regular={regular:.2f})"
        if result_type == "regular_greeting":
            return f"普通问候 (比例 extra={extra:.2f} regular={regular:.2f})"
        return f"未触发 (可能被免打扰/上限/无话术阻断, 比例 extra={extra:.2f} regular={regular:.2f})"

    def pick_farewell_line(self) -> str:
        """从 farewell 分组中随机抽取一句道别话术。"""
        return self._random_line("farewell")

    def pick_reply_line(self) -> str:
        """从回复系分组中随机抽取一句回应话术。"""
        group = random.choice(["break_reminder", "comfort", "encourage","happy"])
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

    def pick_reply_ack_line(self) -> str:
        """从 reply 分组中随机抽取一句简短应答话术。"""
        return self._random_line("reply")

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
