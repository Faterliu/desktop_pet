from __future__ import annotations

import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal

from character.proactive_context import (
    build_local_scenario_greeting,
    build_proactive_context,
    has_scenario_context,
)
from storage.json_store import load_json
from storage.local_lines_service import LocalLinesService
from storage.runtime_state_store import RuntimeStateStore
from storage.usage_store import UsageStore
from utils.time_utils import elapsed_seconds, now_local, now_utc, parse_iso_datetime, to_utc


class BehaviorController(QObject):
    speak_requested = Signal(str, int, str)
    knowledge_speak_requested = Signal()
    scenario_greeting_requested = Signal(dict)

    # 初始化当前对象及其依赖。
    def __init__(
        self,
        app_config_path: str | Path,
        local_lines_path: str | Path,
        usage_store: UsageStore,
        config_loader: Callable[[], dict[str, Any]],
        memory_checker: Callable[[], bool | None] | None = None,
        config_saver: Callable[[], None] | None = None,
        character_path: str | Path | None = None,
        runtime_state_path: str | Path | None = None,
        can_show_proactive: Callable[[], bool] | None = None,
    ) -> None:
        """初始化当前对象及其依赖。"""
        super().__init__()
        self.app_config_path = Path(app_config_path)
        self.local_lines_path = Path(local_lines_path)
        self.local_lines_service = LocalLinesService(self.local_lines_path)
        self.usage_store = usage_store
        self.config_loader = config_loader
        self.memory_checker = memory_checker
        self.config_saver = config_saver
        self.memory_path = self.app_config_path.parent.parent / "data" / "memory.json"
        self.character_path = (
            Path(character_path)
            if character_path
            else self.app_config_path.parent / "character_default.json"
        )
        self.runtime_state_store = RuntimeStateStore(
            runtime_state_path or self.app_config_path.parent.parent / "data" / "runtime_state.json"
        )
        self.can_show_proactive = can_show_proactive or (lambda: True)
        persisted = self.runtime_state_store.load()
        self.last_user_interaction_at = parse_iso_datetime(persisted["last_user_interaction_at"]) or now_utc()
        self.last_user_message_at = parse_iso_datetime(persisted["last_user_message_at"])
        self.last_proactive_shown_at = parse_iso_datetime(persisted["last_proactive_shown_at"])
        self.last_proactive_replied_at = parse_iso_datetime(persisted["last_proactive_replied_at"])
        self._last_user_interaction_monotonic: float | None = None
        self._last_proactive_shown_monotonic: float | None = None
        self.last_scenario_greeting_at = None
        self.awaiting_user_reply = False
        self._consecutive_unanswered = 0
        self._unanswered_counted_for = ""
        self._last_proactive_type = ""
        self._requested_proactive_type = ""
        self._last_time_key = self._time_greeting_key()
        self._last_season_key = self._season_key()

        self.idle_check_timer = QTimer(self)
        self.idle_check_timer.timeout.connect(self._maybe_idle_prompt)
        self.idle_check_timer.start(60_000)

        self.period_check_timer = QTimer(self)
        self.period_check_timer.timeout.connect(self._check_period_change)

        self._state_save_timer = QTimer(self)
        self._state_save_timer.setSingleShot(True)
        self._state_save_timer.timeout.connect(self.flush_runtime_state)

    # 启动主动问候定时器，并同步下一次主动检查状态。
    def start(self) -> None:
        """启动主动问候定时器，并同步下一次主动检查状态。"""
        QTimer.singleShot(1200, self._startup_greeting)
        self.period_check_timer.start(60_000)

    # 重载主动行为配置，并同步下一次主动检查状态。
    def reload(self) -> None:
        """重载主动行为配置，并同步下一次主动检查状态。"""
        self.last_scenario_greeting_at = None
        self._last_time_key = self._time_greeting_key()
        self._last_season_key = self._season_key()

    # 兼容旧调用方读取或设置最近互动时间；统一转换到 UTC 状态字段。
    @property
    def last_user_interaction(self) -> datetime:
        """兼容旧调用方读取最近互动时间。"""
        return self.last_user_interaction_at

    @last_user_interaction.setter
    def last_user_interaction(self, value: datetime) -> None:
        """兼容旧调用方设置最近互动时间。"""
        self.last_user_interaction_at = to_utc(value)
        self._last_user_interaction_monotonic = None

    # 兼容旧调用方读取或设置最近主动问候时间。
    @property
    def last_proactive_at(self) -> datetime | None:
        """兼容旧调用方读取最近主动问候时间。"""
        return self.last_proactive_shown_at

    @last_proactive_at.setter
    def last_proactive_at(self, value: datetime | None) -> None:
        """兼容旧调用方设置最近主动问候时间。"""
        self.last_proactive_shown_at = to_utc(value) if value else None
        self._last_proactive_shown_monotonic = None

    # 记录最近一次用户交互时间，并清除等待回复状态。
    def notify_user_interaction(self, source: str = "unknown") -> None:
        """记录最近一次用户交互时间，并清除等待回复状态。"""
        del source
        self.last_user_interaction_at = now_utc()
        self._last_user_interaction_monotonic = time.monotonic()
        self.awaiting_user_reply = False
        self._consecutive_unanswered = 0
        self._unanswered_counted_for = ""
        self._schedule_runtime_state_save()

    # 记录用户提交的聊天消息，同时保留统一互动时间。
    def notify_user_message(self) -> None:
        """记录用户提交的聊天消息。"""
        self.notify_user_interaction("chat_message")
        self.last_user_message_at = now_utc()
        self._schedule_runtime_state_save()

    # 记录主动问候展示时间和类型，并进入等待回复状态。
    def notify_proactive_shown(self, proactive_type: str = "regular_greeting") -> None:
        """记录主动问候展示时间和类型，并进入等待回复状态。"""
        self.last_proactive_shown_at = now_utc()
        self._last_proactive_shown_monotonic = time.monotonic()
        self.awaiting_user_reply = True
        self._last_proactive_type = proactive_type
        self._unanswered_counted_for = ""
        if proactive_type == "extra_knowledge":
            self.usage_store.increment_api_line()
        else:
            self.usage_store.increment_local_line()
        self._schedule_runtime_state_save()

    # 根据上一条主动问候类型调整后续内容比例。
    def notify_proactive_response(self) -> bool:
        """根据上一条主动问候类型调整后续内容比例。"""
        if not self.is_within_proactive_reply_window():
            return False
        self.last_proactive_replied_at = now_utc()
        self.notify_user_interaction("proactive_response")
        if self._last_proactive_type:
            self._adjust_ratio(self._last_proactive_type)
        self._schedule_runtime_state_save()
        return True

    # 将需要持久化的业务时间延迟写入，避免高频点击反复写盘。
    def _schedule_runtime_state_save(self) -> None:
        """将需要持久化的业务时间延迟写入。"""
        self._state_save_timer.start(1500)

    # 立即写入关键业务时间，供正常退出和测试调用。
    def flush_runtime_state(self) -> None:
        """立即写入关键业务时间。"""
        self._state_save_timer.stop()
        self.runtime_state_store.save(
            {
                "last_user_interaction_at": self.last_user_interaction_at,
                "last_user_message_at": self.last_user_message_at,
                "last_proactive_shown_at": self.last_proactive_shown_at,
                "last_proactive_replied_at": self.last_proactive_replied_at,
            }
        )

    # 返回当前主动问候类型，供窗口在实际显示成功后回写状态。
    def pending_proactive_type(self) -> str:
        """返回当前待显示主动问候类型。"""
        return self._requested_proactive_type or "regular_greeting"

    # 发出待展示的本地主动问候请求；展示成功后由窗口调用 notify_proactive_shown。
    def _request_proactive_line(
        self,
        line: str,
        duration_ms: int,
        action_name: str,
        proactive_type: str,
    ) -> None:
        """发出待展示的本地主动问候请求。"""
        self._requested_proactive_type = proactive_type
        self.speak_requested.emit(line, duration_ms, action_name)

    # 读取主动内容比例配置，缺失时写入普通问候和知识问候默认比例。
    def _proactive_ratio(self) -> dict[str, float]:
        """读取主动内容比例配置，缺失时写入普通问候和知识问候默认比例。"""
        config = self.config_loader()
        default = {"extra_knowledge": 0.35, "regular_greeting": 0.65}
        return config.setdefault("proactive_content_ratio", default)

    # 根据用户回应的主动内容类型，微调普通问候与知识问候比例。
    def _adjust_ratio(self, responded_type: str) -> None:
        """根据用户回应的主动内容类型，微调普通问候与知识问候比例。"""
        if responded_type not in {"regular_greeting", "extra_knowledge"}:
            return
        config = self.config_loader()
        ratio = self._proactive_ratio()
        other_type = "extra_knowledge" if responded_type == "regular_greeting" else "regular_greeting"
        ratio[responded_type] = min(0.7, round(ratio.get(responded_type, 0.5) + 0.005, 4))
        ratio[other_type] = max(0.3, round(ratio.get(other_type, 0.5) - 0.001, 4))
        config["proactive_content_ratio"] = ratio
        self._save_config_snapshot()

    # 调用保存回调持久化主动行为配置，失败时静默跳过。
    def _save_config_snapshot(self) -> None:
        """调用保存回调持久化主动行为配置，失败时静默跳过。"""
        if self.config_saver is None:
            return
        try:
            self.config_saver()
        except Exception:
            pass

    # 切换免打扰状态，并在启用时压低主动问候频率。
    def set_do_not_disturb(self, enabled: bool) -> None:
        """切换免打扰状态，并在启用时压低主动问候频率。"""
        config = self.config_loader()
        config.setdefault("behavior", {})["do_not_disturb"] = enabled

    # 读取指定气泡时长配置，无法转换时返回默认毫秒数。
    def _bubble_duration_ms(self, key: str, default: int) -> int:
        """读取指定气泡时长配置，无法转换时返回默认毫秒数。"""
        config = self.config_loader()
        durations = config.setdefault("ui", {}).setdefault("bubble_durations_ms", {})
        try:
            value = int(durations.get(key, default))
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    # 整理startup 问候，并把结果交给调用方或写回状态。
    def _startup_greeting(self) -> None:
        """整理startup 问候，并把结果交给调用方或写回状态。"""
        config = self.config_loader()
        behavior = config.get("behavior", {})
        if behavior.get("do_not_disturb") or not behavior.get("startup_greeting", True):
            return

        line = self._first_start_line()
        if not line and self._is_cycle_start():
            line = self._random_line(self._season_key())
        if not line:
            time_key = self._time_greeting_key()
            line = self._random_line(time_key) if time_key else ""
        if not line:
            line = self._random_line("startup")

        if line and self.can_show_proactive():
            self._request_proactive_line(
                line,
                self._bubble_duration_ms("startup_greeting", 7000),
                "waving",
                "startup_greeting",
            )

    # 根据连续未回应次数计算下一次主动问候间隔。
    def _dynamic_proactive_interval_minutes(self) -> int:
        """根据连续未回应次数计算下一次主动问候间隔。"""
        if self._consecutive_unanswered <= 1:
            return 15
        if self._consecutive_unanswered == 2:
            return 30
        if self._consecutive_unanswered == 3:
            return random.randint(30, 60)
        return 60

    # 读取主动问候最小间隔，配置无效时回退默认分钟数。
    def _minimum_proactive_interval_minutes(self, behavior: dict[str, Any]) -> int:
        """读取主动问候最小间隔，配置无效时回退默认分钟数。"""
        try:
            value = int(behavior.get("min_proactive_interval_minutes", 15))
        except (TypeError, ValueError):
            return 15
        return value if value > 0 else 15

    # 读取每日本地台词上限，配置无效时回退默认值。
    def _max_local_lines_per_day(self, behavior: dict[str, Any]) -> int:
        """读取每日本地台词上限，配置无效时回退默认值。"""
        try:
            value = int(behavior.get("max_local_lines_per_day", 10))
        except (TypeError, ValueError):
            return 10
        return value if value > 0 else 10

    # 读取每日 API 主动生成上限，配置无效时回退默认值。
    def _max_api_proactive_per_day(self, behavior: dict[str, Any]) -> int:
        """读取每日 API 主动生成上限，配置无效时回退默认值。"""
        try:
            value = int(behavior.get("max_api_proactive_per_day", 10))
        except (TypeError, ValueError):
            return 10
        return value if value > 0 else 10

    # 合并最小间隔和动态间隔，得到最终主动问候间隔。
    def _effective_proactive_interval_minutes(self, behavior: dict[str, Any]) -> int:
        """合并最小间隔和动态间隔，得到最终主动问候间隔。"""
        return max(
            self._minimum_proactive_interval_minutes(behavior),
            self._dynamic_proactive_interval_minutes(),
        )

    # 判断记忆content是否满足条件并返回布尔结果。
    def _has_memory_content(self) -> bool | None:
        """判断记忆content是否满足条件并返回布尔结果。"""
        memory_config = self.config_loader().get("memory", {})
        if memory_config.get("use_mem0_for_knowledge_speak", False) and self.memory_checker:
            try:
                memory_check_result = self.memory_checker()
                if memory_check_result is None:
                    return None
                if memory_check_result:
                    return True
            except Exception:
                pass

        memory = load_json(self.memory_path, {})
        user_profile = memory.get("user_profile", {})
        work_study = memory.get("work_study", {})
        if user_profile.get("preferences") or user_profile.get("important_personal_notes"):
            return True
        if work_study.get("current_learning_topics") or work_study.get("current_projects"):
            return True
        return False

    # 在用户空闲且限额允许时触发低打扰主动问候。
    def _maybe_idle_prompt(self) -> None:
        """在用户空闲且限额允许时触发低打扰主动问候。"""
        config = self.config_loader()
        behavior = config.get("behavior", {})
        if behavior.get("do_not_disturb") or not behavior.get("proactive_chat", True):
            return

        max_daily = self._max_local_lines_per_day(behavior)
        if not self.usage_store.can_use_local(max_daily):
            return

        interval_minutes = self._effective_proactive_interval_minutes(behavior)
        if not self.can_show_proactive():
            return
        now = now_local()
        if elapsed_seconds(self.last_user_interaction_at, self._last_user_interaction_monotonic) < interval_minutes * 60:
            return
        if elapsed_seconds(self.last_proactive_shown_at, self._last_proactive_shown_monotonic) < interval_minutes * 60:
            return

        shown_key = self.last_proactive_shown_at.isoformat() if self.last_proactive_shown_at else ""
        if self.awaiting_user_reply and shown_key and self._unanswered_counted_for != shown_key:
            self._consecutive_unanswered += 1
            self._unanswered_counted_for = shown_key

        if self._try_scenario_greeting(behavior, now):
            return

        ratio = self._proactive_ratio()
        extra_weight = ratio.get("extra_knowledge", 0.5)
        if random.random() < extra_weight:
            memory_available = self._has_memory_content()
            if memory_available is None:
                return
            if memory_available:
                self._requested_proactive_type = "extra_knowledge"
                self.knowledge_speak_requested.emit()
                return

        line_types = ["idle", "quiet", "encourage", "break_reminder"]
        time_key = self._time_greeting_key()
        if time_key:
            line_types.append(time_key)
        line_type = random.choice(line_types)
        line = self._random_line(line_type)
        if not line:
            return

        self._emit_local_proactive_line(line, "regular_greeting")

    # 在记忆、冷却和配置允许时触发场景化问候。
    def _try_scenario_greeting(self, behavior: dict[str, Any], now: Any) -> bool:
        """在记忆、冷却和配置允许时触发场景化问候。"""
        if not behavior.get("enable_scenario_greeting", False):
            return False

        local_lines = load_json(self.local_lines_path, {})
        max_chars = self._scenario_max_chars(behavior)
        if self._should_use_low_interrupt_greeting(behavior):
            line = build_local_scenario_greeting(
                {"runtime_state": {"consecutive_unanswered": self._consecutive_unanswered}},
                local_lines,
                max_chars=max_chars,
                greeting_type="low_interrupt_greeting",
            )
            if not line:
                return False
            self.last_scenario_greeting_at = now
            self._emit_local_proactive_line(line, "low_interrupt_greeting")
            return True

        if self._scenario_cooldown_active(behavior, now):
            return False

        memory = load_json(self.memory_path, {})
        character = load_json(self.character_path, {}) if self.character_path.exists() else {}
        context = build_proactive_context(
            memory,
            runtime_state={
                "consecutive_unanswered": self._consecutive_unanswered,
                "last_proactive_type": self._last_proactive_type,
            },
            time_period=self._time_period_label(),
            season=self._season_label(),
            character=character,
        )
        if not has_scenario_context(context, self._scenario_min_memory_items(behavior)):
            return False

        fallback_line = build_local_scenario_greeting(
            context,
            local_lines,
            max_chars=max_chars,
            greeting_type="memory_context_greeting",
        )
        if not fallback_line:
            return False

        self.last_scenario_greeting_at = now
        if behavior.get("scenario_greeting_api_enabled", True) and self._can_use_api(behavior):
            self._requested_proactive_type = "memory_context_greeting"
            self.scenario_greeting_requested.emit(
                {
                    "greeting_type": "memory_context_greeting",
                    "proactive_type": "memory_context_greeting",
                    "context": context,
                    "fallback_line": fallback_line,
                    "max_chars": max_chars,
                }
            )
            return True

        self._emit_local_proactive_line(fallback_line, "memory_context_greeting")
        return True

    # 发送本地主动台词请求；仅窗口实际展示成功后才记录展示状态。
    def _emit_local_proactive_line(self, line: str, proactive_type: str) -> None:
        """发送本地主动台词信号，并记录展示类型。"""
        action_name = "idle" if proactive_type == "low_interrupt_greeting" else "waving"
        self._request_proactive_line(
            line,
            self._bubble_duration_ms("proactive_greeting", 6000),
            action_name,
            proactive_type,
        )

    # 根据 behavior 判断useAPI是否满足条件并返回布尔结果。
    def _can_use_api(self, behavior: dict[str, Any]) -> bool:
        """根据 behavior 判断useAPI是否满足条件并返回布尔结果。"""
        if not hasattr(self.usage_store, "can_use_api"):
            return True
        return bool(self.usage_store.can_use_api(self._max_api_proactive_per_day(behavior)))

    # 根据 behavior 整理场景 max chars，并把结果交给调用方或写回状态。
    def _scenario_max_chars(self, behavior: dict[str, Any]) -> int:
        """根据 behavior 整理场景 max chars，并把结果交给调用方或写回状态。"""
        try:
            value = int(behavior.get("scenario_greeting_max_chars", 80))
        except (TypeError, ValueError):
            return 80
        return min(max(value, 20), 120)

    # 根据 behavior 处理记忆数据，保持本地记忆和外部索引一致。
    def _scenario_min_memory_items(self, behavior: dict[str, Any]) -> int:
        """根据 behavior 处理记忆数据，保持本地记忆和外部索引一致。"""
        try:
            value = int(behavior.get("scenario_greeting_min_memory_items", 1))
        except (TypeError, ValueError):
            return 1
        return value if value > 0 else 1

    # 根据 behavior 整理场景 cooldown minutes，并把结果交给调用方或写回状态。
    def _scenario_cooldown_minutes(self, behavior: dict[str, Any]) -> int:
        """根据 behavior 整理场景 cooldown minutes，并把结果交给调用方或写回状态。"""
        try:
            value = int(behavior.get("scenario_greeting_cooldown_minutes", 60))
        except (TypeError, ValueError):
            return 60
        return max(value, 0)

    # 根据 behavior、now 整理场景 cooldown active，并把结果交给调用方或写回状态。
    def _scenario_cooldown_active(self, behavior: dict[str, Any], now: Any) -> bool:
        """根据 behavior、now 整理场景 cooldown active，并把结果交给调用方或写回状态。"""
        if self.last_scenario_greeting_at is None:
            return False
        cooldown = self._scenario_cooldown_minutes(behavior)
        if cooldown <= 0:
            return False
        return now - self.last_scenario_greeting_at < timedelta(minutes=cooldown)

    # 根据 behavior 判断uselowinterrupt问候是否满足条件并返回布尔结果。
    def _should_use_low_interrupt_greeting(self, behavior: dict[str, Any]) -> bool:
        """根据 behavior 判断uselowinterrupt问候是否满足条件并返回布尔结果。"""
        try:
            threshold = int(behavior.get("scenario_greeting_low_interrupt_after_ignored", 2))
        except (TypeError, ValueError):
            threshold = 2
        threshold = max(threshold, 1)
        return self._consecutive_unanswered >= threshold

    # 根据当前本地时间返回早中晚等时间段标签。
    def _time_period_label(self) -> str:
        """根据当前本地时间返回早中晚等时间段标签。"""
        mapping = {
            "greeting_morning": "morning",
            "greeting_noon": "noon",
            "greeting_afternoon": "afternoon",
            "greeting_evening": "evening",
            "sleepy": "night",
        }
        return mapping.get(self._time_greeting_key() or "", "")

    # 根据当前月份返回季节中文标签。
    def _season_label(self) -> str:
        """根据当前月份返回季节中文标签。"""
        mapping = {
            "greeting_spring": "spring",
            "greeting_summer": "summer",
            "greeting_autumn": "autumn",
            "greeting_winter": "winter",
        }
        return mapping.get(self._season_key(), "")

    # 检查时间段或季节是否变化，并触发对应问候。
    def _check_period_change(self) -> None:
        """检查时间段或季节是否变化，并触发对应问候。"""
        config = self.config_loader()
        behavior = config.get("behavior", {})
        if behavior.get("do_not_disturb"):
            return
        max_daily = self._max_local_lines_per_day(behavior)
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
            if line and self.can_show_proactive():
                self._request_proactive_line(
                    line,
                    self._bubble_duration_ms("period_greeting", 7000),
                    "waving",
                    "period_greeting",
                )

    # 按指定台词组触发测试气泡展示，并返回是否成功。
    def trigger_test_speak(self) -> bool:
        """按指定台词组触发测试气泡展示，并返回是否成功。"""
        line_types = ["startup", "idle", "quiet", "encourage"]
        time_key = self._time_greeting_key()
        if time_key:
            line_types.append(time_key)
        line_type = random.choice(line_types)
        line = self._random_line(line_type)
        if not line:
            return False

        self._request_proactive_line(
            line,
            self._bubble_duration_ms("proactive_greeting", 6000),
            "waving",
            "regular_greeting",
        )
        return True

    # 手动触发空闲问候测试，绕过正常等待时间。
    def trigger_test_idle_prompt(self) -> str:
        """手动触发空闲问候测试，绕过正常等待时间。"""
        saved_interaction = self.last_user_interaction
        saved_proactive = self.last_proactive_at
        saved_type = self._last_proactive_type
        saved_requested_type = self._requested_proactive_type
        long_ago = now_local() - timedelta(hours=24)
        self.last_user_interaction = long_ago
        self.last_proactive_at = None
        self._last_proactive_type = ""
        try:
            self._maybe_idle_prompt()
            result_type = self._requested_proactive_type
        finally:
            self._last_proactive_type = saved_type
            self._requested_proactive_type = saved_requested_type
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

    # 从退出告别台词组中随机选择一条可展示文本。
    def pick_farewell_line(self) -> str:
        """从退出告别台词组中随机选择一条可展示文本。"""
        return self._random_line("farewell")

    # 从回复台词组中随机选择一条可展示文本。
    def pick_reply_line(self) -> str:
        """从回复台词组中随机选择一条可展示文本。"""
        group = random.choice(["break_reminder", "comfort", "encourage", "happy"])
        return self._random_line(group)

    # 从主动反馈台词组中随机选择一条可展示文本。
    def pick_feedback_line(self) -> str:
        """从主动反馈台词组中随机选择一条可展示文本。"""
        return self._random_line("feedback")

    # 根据 window_seconds 判断within主动行为回复窗口是否满足条件并返回布尔结果。
    def is_within_proactive_reply_window(self, window_seconds: int = 60) -> bool:
        """根据 window_seconds 判断within主动行为回复窗口是否满足条件并返回布尔结果。"""
        if not self.awaiting_user_reply or self.last_proactive_shown_at is None:
            return False
        return elapsed_seconds(
            self.last_proactive_shown_at,
            self._last_proactive_shown_monotonic,
        ) < window_seconds

    # 从取消置顶提示台词组中随机选择一条可展示文本。
    def pick_ignored_line(self) -> str:
        """从取消置顶提示台词组中随机选择一条可展示文本。"""
        return self._random_line("ignored")

    # 从恢复置顶提示台词组中随机选择一条可展示文本。
    def pick_return_after_idle_line(self) -> str:
        """从恢复置顶提示台词组中随机选择一条可展示文本。"""
        return self._random_line("return_after_idle")

    # 从输入等待台词组中随机选择一条可展示文本。
    def pick_waiting_line(self) -> str:
        """从输入等待台词组中随机选择一条可展示文本。"""
        return self._random_line("waiting")

    # 从右键菜单打开台词组中随机选择一条可展示文本。
    def pick_context_menu_line(self) -> str:
        """从右键菜单打开台词组中随机选择一条可展示文本。"""
        return self._random_line("context_menu")

    # 从知识问候确认台词组中随机选择一条可展示文本。
    def pick_reply_ack_line(self) -> str:
        """从知识问候确认台词组中随机选择一条可展示文本。"""
        return self._random_line("reply")

    # 从诗歌台词组中随机选择一条可展示文本。
    def pick_poetry_line(self) -> str:
        """从诗歌台词组中随机选择一条可展示文本。"""
        return self._random_line("poetry")

    # 根据当前本地时间返回对应时间段问候 key。
    def _time_greeting_key(self) -> str | None:
        """根据当前本地时间返回对应时间段问候 key。"""
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

    # 根据当前月份返回季节问候台词组 key。
    def _season_key(self) -> str:
        """根据当前月份返回季节问候台词组 key。"""
        month = now_local().month
        if 3 <= month <= 5:
            return "greeting_spring"
        if 6 <= month <= 8:
            return "greeting_summer"
        if 9 <= month <= 11:
            return "greeting_autumn"
        return "greeting_winter"

    # 判断cyclestart是否满足条件并返回布尔结果。
    def _is_cycle_start(self) -> bool:
        """判断cyclestart是否满足条件并返回布尔结果。"""
        yday = now_local().timetuple().tm_yday
        return (yday - 1) % 5 == 0

    # 读取并消费首次启动问候台词。
    def _first_start_line(self) -> str:
        """读取并消费首次启动问候台词。"""
        return self.local_lines_service.consume_first_start_line()

    # 从指定本地台词组随机取一条可展示文本。
    def _random_line(self, group_name: str) -> str:
        """从指定本地台词组随机取一条可展示文本。"""
        return self.local_lines_service.pick_line(group_name)
