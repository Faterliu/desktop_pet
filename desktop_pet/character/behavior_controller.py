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
        """Coordinate proactive greetings and time-based local behavior."""
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
        """Trigger the startup greeting and begin period checks."""
        QTimer.singleShot(1200, self._startup_greeting)
        self.period_check_timer.start(60_000)

    def reload(self) -> None:
        """Reset controller state after app config reload."""
        self.last_user_interaction = now_local()
        self.awaiting_user_reply = False
        self._consecutive_unanswered = 0
        self._last_proactive_type = ""
        self._last_time_key = self._time_greeting_key()
        self._last_season_key = self._season_key()

    def notify_user_interaction(self) -> None:
        """Mark that the user interacted and clear unanswered counters."""
        self.last_user_interaction = now_local()
        self.awaiting_user_reply = False
        self._consecutive_unanswered = 0

    def notify_proactive_shown(self, proactive_type: str = "regular_greeting") -> None:
        """Mark that a proactive message was shown and await a reply."""
        self.last_proactive_at = now_local()
        self.awaiting_user_reply = True
        self._last_proactive_type = proactive_type

    def notify_proactive_response(self) -> None:
        """Adjust proactive-content ratio after the user responds."""
        if self._last_proactive_type:
            self._adjust_ratio(self._last_proactive_type)

    def _proactive_ratio(self) -> dict[str, float]:
        """Read the proactive-content ratio configuration."""
        config = self.config_loader()
        default = {"extra_knowledge": 0.5, "regular_greeting": 0.5}
        return config.setdefault("proactive_content_ratio", default)

    def _adjust_ratio(self, responded_type: str) -> None:
        """Slightly bias future proactive content toward what got a response."""
        config = self.config_loader()
        ratio = self._proactive_ratio()
        other_type = "extra_knowledge" if responded_type == "regular_greeting" else "regular_greeting"
        ratio[responded_type] = min(0.7, round(ratio.get(responded_type, 0.5) + 0.005, 4))
        ratio[other_type] = max(0.3, round(ratio.get(other_type, 0.5) - 0.001, 4))
        config["proactive_content_ratio"] = ratio

    def set_do_not_disturb(self, enabled: bool) -> None:
        """Update the in-memory do-not-disturb flag."""
        config = self.config_loader()
        config.setdefault("behavior", {})["do_not_disturb"] = enabled

    def _bubble_duration_ms(self, key: str, default: int) -> int:
        """Read a positive bubble duration from ui.bubble_durations_ms."""
        config = self.config_loader()
        durations = config.setdefault("ui", {}).setdefault("bubble_durations_ms", {})
        try:
            value = int(durations.get(key, default))
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    def _startup_greeting(self) -> None:
        """Show the startup greeting when constraints allow it."""
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
            self.speak_requested.emit(
                line,
                self._bubble_duration_ms("startup_greeting", 7000),
                "waving",
            )

    def _dynamic_proactive_interval_minutes(self) -> int:
        """Increase the idle greeting interval after unanswered prompts."""
        if self._consecutive_unanswered <= 1:
            return 15
        if self._consecutive_unanswered == 2:
            return 30
        if self._consecutive_unanswered == 3:
            return random.randint(30, 60)
        return 60

    def _has_memory_content(self) -> bool:
        """Check whether memory.json has any useful stored user context."""
        memory = load_json(self.memory_path, {})
        user_profile = memory.get("user_profile", {})
        work_study = memory.get("work_study", {})
        if user_profile.get("preferences") or user_profile.get("important_personal_notes"):
            return True
        if work_study.get("current_learning_topics") or work_study.get("current_projects"):
            return True
        return False

    def _maybe_idle_prompt(self) -> None:
        """Try to show an idle-time proactive message."""
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

        ratio = self._proactive_ratio()
        extra_weight = ratio.get("extra_knowledge", 0.5)
        if self._has_memory_content() and random.random() < extra_weight:
            self.notify_proactive_shown("extra_knowledge")
            self.knowledge_speak_requested.emit()
            self._consecutive_unanswered = 0
            return

        line_types = ["idle", "quiet", "encourage", "break_reminder"]
        time_key = self._time_greeting_key()
        if time_key:
            line_types.append(time_key)
        line_type = random.choice(line_types)
        line = self._random_line(line_type)
        if not line:
            return

        self.usage_store.increment_local_line()
        self.notify_proactive_shown("regular_greeting")
        self.speak_requested.emit(
            line,
            self._bubble_duration_ms("proactive_greeting", 6000),
            "waving",
        )
        self._consecutive_unanswered = 0

    def _check_period_change(self) -> None:
        """Show a time-of-day greeting when the period changes."""
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
                self.speak_requested.emit(
                    line,
                    self._bubble_duration_ms("period_greeting", 7000),
                    "waving",
                )

    def trigger_test_speak(self) -> bool:
        """Immediately show a test proactive line."""
        line_types = ["startup", "idle", "quiet", "encourage"]
        time_key = self._time_greeting_key()
        if time_key:
            line_types.append(time_key)
        line_type = random.choice(line_types)
        line = self._random_line(line_type)
        if not line:
            return False

        self.notify_proactive_shown()
        self.speak_requested.emit(
            line,
            self._bubble_duration_ms("proactive_greeting", 6000),
            "waving",
        )
        return True

    def trigger_test_idle_prompt(self) -> str:
        """Run the idle-prompt logic once for testing and report the result."""
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
            return f"知识问候(比例 extra={extra:.2f} regular={regular:.2f})"
        if result_type == "regular_greeting":
            return f"普通问候(比例 extra={extra:.2f} regular={regular:.2f})"
        return (
            f"未触发(可能被免打扰/上限/无话术阻断; "
            f"比例 extra={extra:.2f} regular={regular:.2f})"
        )

    def pick_farewell_line(self) -> str:
        """Pick a farewell line for exit flow."""
        return self._random_line("farewell")

    def pick_reply_line(self) -> str:
        """Pick a reply line for the avatar double-click interaction."""
        group = random.choice(["break_reminder", "comfort", "encourage", "happy"])
        return self._random_line(group)

    def pick_feedback_line(self) -> str:
        """Pick feedback line used after a proactive greeting reply window."""
        return self._random_line("feedback")

    def is_within_proactive_reply_window(self, window_seconds: int = 60) -> bool:
        """Check whether we are still inside the proactive reply window."""
        if self.last_proactive_at is None:
            return False
        return now_local() - self.last_proactive_at < timedelta(seconds=window_seconds)

    def pick_ignored_line(self) -> str:
        """Pick a line used when turning off always-on-top."""
        return self._random_line("ignored")

    def pick_return_after_idle_line(self) -> str:
        """Pick a line used when turning on always-on-top."""
        return self._random_line("return_after_idle")

    def pick_waiting_line(self) -> str:
        """Pick a waiting prompt line."""
        return self._random_line("waiting")

    def pick_reply_ack_line(self) -> str:
        """Pick a short acknowledgment line for knowledge greeting reply bubble."""
        return self._random_line("reply")

    def pick_poetry_line(self) -> str:
        """Pick one poetry line from local config."""
        return self._random_line("poetry")

    def _time_greeting_key(self) -> str | None:
        """Return the current local time greeting bucket."""
        hour = now_local().hour
        if 7 <= hour < 11:
            return "greeting_morning"
        if 11 <= hour < 14:
            return "greeting_noon"
        if 14 <= hour < 18:
            return "greeting_afternoon"
        if 18 <= hour < 22:
            return "greeting_evening"
        return "sleepy"

    def _season_key(self) -> str:
        """Return the current season greeting bucket."""
        month = now_local().month
        if 3 <= month <= 5:
            return "greeting_spring"
        if 6 <= month <= 8:
            return "greeting_summer"
        if 9 <= month <= 11:
            return "greeting_autumn"
        return "greeting_winter"

    def _is_cycle_start(self) -> bool:
        """Return whether today is the first day of the 5-day cycle."""
        yday = now_local().timetuple().tm_yday
        return (yday - 1) % 5 == 0

    def _random_line(self, group_name: str) -> str:
        """Pick a random line from the given local-lines group."""
        payload = load_json(self.local_lines_path, {})
        lines = payload.get(group_name, [])
        if not lines:
            return ""
        return random.choice(lines)
