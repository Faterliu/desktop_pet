from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

try:
    from PySide6.QtCore import QCoreApplication
except ModuleNotFoundError:
    qt_module = types.ModuleType("PySide6")
    qt_core = types.ModuleType("PySide6.QtCore")

    class _FakeSignal:
        # 初始化当前对象及其依赖。
        def __init__(self, *args, **kwargs) -> None:  # noqa: D107
            """初始化当前对象及其依赖。"""
            self._callbacks = []

        # 模拟 _FakeSignal 的信号connect行为，记录或触发测试回调。
        def connect(self, callback) -> None:  # type: ignore[no-untyped-def]
            """模拟 _FakeSignal 的信号connect行为，记录或触发测试回调。"""
            self._callbacks.append(callback)

        # 模拟 _FakeSignal 的信号emit行为，记录或触发测试回调。
        def emit(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            """模拟 _FakeSignal 的信号emit行为，记录或触发测试回调。"""
            for callback in list(self._callbacks):
                callback(*args, **kwargs)

    class _FakeQObject:
        # 初始化当前对象及其依赖。
        def __init__(self, *args, **kwargs) -> None:  # noqa: D107
            """初始化当前对象及其依赖。"""
            pass

    class _FakeQTimer:
        # 初始化当前对象及其依赖。
        def __init__(self, *args, **kwargs) -> None:  # noqa: D107
            """初始化当前对象及其依赖。"""
            self.timeout = _FakeSignal()
            self.running = False

        # 为 _FakeQTimer 测试替身提供start行为。
        def start(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            """为 _FakeQTimer 测试替身提供start行为。"""
            self.running = True

        # 为 _FakeQTimer 测试替身提供stop行为。
        def stop(self) -> None:
            """为 _FakeQTimer 测试替身提供stop行为。"""
            self.running = False

    class QCoreApplication:  # type: ignore[no-redef]
        _instance = None

        # 初始化当前对象及其依赖。
        def __init__(self, *args, **kwargs) -> None:  # noqa: D107
            """初始化当前对象及其依赖。"""
            QCoreApplication._instance = self

        # 为测试准备instance数据或断言辅助结果。
        @staticmethod
        def instance():  # type: ignore[no-untyped-def]
            """为测试准备instance数据或断言辅助结果。"""
            return QCoreApplication._instance

    qt_core.QObject = _FakeQObject
    qt_core.QTimer = _FakeQTimer
    qt_core.Signal = _FakeSignal
    qt_core.QCoreApplication = QCoreApplication
    qt_module.QtCore = qt_core
    sys.modules.setdefault("PySide6", qt_module)
    sys.modules.setdefault("PySide6.QtCore", qt_core)

from character.behavior_controller import BehaviorController  # noqa: E402
from utils.time_utils import now_local  # noqa: E402


class FakeUsageStore:
    # 初始化当前对象及其依赖。
    def __init__(self) -> None:
        """初始化当前对象及其依赖。"""
        self.max_values: list[int] = []
        self.local_count = 0
        self.api_count = 0

    # 为 FakeUsageStore 测试替身提供canuse本地行为。
    def can_use_local(self, max_per_day: int) -> bool:
        """为 FakeUsageStore 测试替身提供canuse本地行为。"""
        self.max_values.append(max_per_day)
        return True

    # 为 FakeUsageStore 测试替身提供canuseAPI行为。
    def can_use_api(self, max_per_day: int) -> bool:
        """为 FakeUsageStore 测试替身提供canuseAPI行为。"""
        return True

    # 为 FakeUsageStore 测试替身提供increment本地台词行为。
    def increment_local_line(self) -> None:
        """为 FakeUsageStore 测试替身提供increment本地台词行为。"""
        self.local_count += 1

    # 为 FakeUsageStore 测试替身提供incrementAPI台词行为。
    def increment_api_line(self) -> None:
        """为 FakeUsageStore 测试替身提供incrementAPI台词行为。"""
        self.api_count += 1


class BehaviorControllerTests(unittest.TestCase):
    # 准备当前测试类共用的环境和数据。
    @classmethod
    def setUpClass(cls) -> None:
        """准备当前测试类共用的环境和数据。"""
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    # 为测试准备控制器数据或断言辅助结果。
    def _controller(
        self,
        temp_dir: Path,
        config: dict,
        saver=None,
        local_lines: dict | None = None,
        memory: dict | None = None,
        character: dict | None = None,
    ) -> BehaviorController:
        """为测试准备控制器数据或断言辅助结果。"""
        config_dir = temp_dir / "config"
        data_dir = temp_dir / "data"
        config_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        local_lines_path = config_dir / "local_lines.json"
        local_lines_path.write_text(
            json.dumps(
                local_lines
                or {
                    "idle": ["hello"],
                    "first_start": {"enable": False, "data": []},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (data_dir / "memory.json").write_text(
            json.dumps(memory or {}, ensure_ascii=False),
            encoding="utf-8",
        )
        (config_dir / "character_default.json").write_text(
            json.dumps(character or {}, ensure_ascii=False),
            encoding="utf-8",
        )
        controller = BehaviorController(
            config_dir / "app_config.json",
            local_lines_path,
            FakeUsageStore(),  # type: ignore[arg-type]
            lambda: config,
            config_saver=saver,
        )
        controller.idle_check_timer.stop()
        controller.period_check_timer.stop()
        return controller

    # 验证invalid daily limit falls back to 默认值场景下的预期结果。
    def test_invalid_daily_limit_falls_back_to_default(self) -> None:
        """验证invalid daily limit falls back to 默认值场景下的预期结果。"""
        with tempfile.TemporaryDirectory() as temp:
            config = {
                "behavior": {
                    "proactive_chat": True,
                    "do_not_disturb": False,
                    "max_local_lines_per_day": "not-a-number",
                    "min_proactive_interval_minutes": 1,
                },
                "proactive_content_ratio": {"extra_knowledge": 0.0, "regular_greeting": 1.0},
            }
            controller = self._controller(Path(temp), config)
            usage = controller.usage_store  # type: ignore[assignment]
            controller.last_user_interaction = now_local().replace(year=2000)

            with patch("character.behavior_controller.random.choice", side_effect=lambda items: items[0]):
                controller._maybe_idle_prompt()

            self.assertEqual(usage.max_values[-1], 10)

    # 验证主动行为 ratio adjustment calls save callback场景下的预期结果。
    def test_proactive_ratio_adjustment_calls_save_callback(self) -> None:
        """验证主动行为 ratio adjustment calls save callback场景下的预期结果。"""
        with tempfile.TemporaryDirectory() as temp:
            config = {
                "proactive_content_ratio": {
                    "extra_knowledge": 0.35,
                    "regular_greeting": 0.65,
                }
            }
            saved = 0

            # 为测试准备saver数据或断言辅助结果。
            def saver() -> None:
                """为测试准备saver数据或断言辅助结果。"""
                nonlocal saved
                saved += 1

            controller = self._controller(Path(temp), config, saver=saver)
            controller.notify_proactive_shown("extra_knowledge")
            controller.notify_proactive_response()

            self.assertEqual(saved, 1)
            self.assertGreater(config["proactive_content_ratio"]["extra_knowledge"], 0.35)

    # 验证场景 问候 响应 does not add ratio bucket场景下的预期结果。
    def test_scenario_greeting_response_does_not_add_ratio_bucket(self) -> None:
        """验证场景 问候 响应 does not add ratio bucket场景下的预期结果。"""
        with tempfile.TemporaryDirectory() as temp:
            config = {
                "proactive_content_ratio": {
                    "extra_knowledge": 0.35,
                    "regular_greeting": 0.65,
                }
            }
            controller = self._controller(Path(temp), config)

            controller.notify_proactive_shown("memory_context_greeting")
            controller.notify_proactive_response()

            self.assertNotIn("memory_context_greeting", config["proactive_content_ratio"])
            self.assertEqual(config["proactive_content_ratio"]["regular_greeting"], 0.65)

    # 验证low interrupt 问候 takes priority after ignored prompts场景下的预期结果。
    def test_low_interrupt_greeting_takes_priority_after_ignored_prompts(self) -> None:
        """验证low interrupt 问候 takes priority after ignored prompts场景下的预期结果。"""
        with tempfile.TemporaryDirectory() as temp:
            config = {
                "behavior": {
                    "proactive_chat": True,
                    "do_not_disturb": False,
                    "max_local_lines_per_day": 10,
                    "min_proactive_interval_minutes": 1,
                    "enable_scenario_greeting": True,
                    "scenario_greeting_low_interrupt_after_ignored": 2,
                },
                "proactive_content_ratio": {"extra_knowledge": 0.0, "regular_greeting": 1.0},
            }
            local_lines = {
                "idle": ["hello"],
                "low_interrupt": ["看你可能在忙，我先安静一会儿，需要我就点我。"],
                "first_start": {"enable": False, "data": []},
            }
            controller = self._controller(Path(temp), config, local_lines=local_lines)
            controller.last_user_interaction = now_local().replace(year=2000)
            controller.awaiting_user_reply = True
            controller._consecutive_unanswered = 1
            spoken: list[tuple[str, int, str]] = []
            controller.speak_requested.connect(lambda *args: spoken.append(args))

            controller._maybe_idle_prompt()

            self.assertEqual(spoken[0][0], "看你可能在忙，我先安静一会儿，需要我就点我。")
            self.assertEqual(controller._last_proactive_type, "low_interrupt_greeting")

    # 验证场景 问候 emits API 请求 when 记忆 上下文 exists场景下的预期结果。
    def test_scenario_greeting_emits_api_request_when_memory_context_exists(self) -> None:
        """验证场景 问候 emits API 请求 when 记忆 上下文 exists场景下的预期结果。"""
        with tempfile.TemporaryDirectory() as temp:
            config = {
                "behavior": {
                    "proactive_chat": True,
                    "do_not_disturb": False,
                    "max_local_lines_per_day": 10,
                    "min_proactive_interval_minutes": 1,
                    "enable_scenario_greeting": True,
                    "scenario_greeting_api_enabled": True,
                    "scenario_greeting_cooldown_minutes": 0,
                    "scenario_greeting_min_memory_items": 1,
                    "scenario_greeting_max_chars": 80,
                },
                "proactive_content_ratio": {"extra_knowledge": 0.0, "regular_greeting": 1.0},
            }
            local_lines = {
                "idle": ["hello"],
                "scenario_greeting_templates": ["{task}这块先抓最关键的一小步就行。"],
                "first_start": {"enable": False, "data": []},
            }
            memory = {"work_study": {"current_projects": ["桌宠记忆系统"]}}
            character = {
                "behavior_policy": {
                    "proactive_style": "轻量出现，不要求回应。",
                    "memory_usage": "只在直接相关时参考。",
                    "boundary": "不制造依赖。",
                }
            }
            controller = self._controller(
                Path(temp),
                config,
                local_lines=local_lines,
                memory=memory,
                character=character,
            )
            controller.last_user_interaction = now_local().replace(year=2000)
            requested: list[dict] = []
            controller.scenario_greeting_requested.connect(lambda payload: requested.append(payload))

            controller._maybe_idle_prompt()

            self.assertTrue(requested)
            self.assertEqual(requested[0]["greeting_type"], "memory_context_greeting")
            self.assertIn("桌宠记忆系统", requested[0]["context"]["recent_task_focus"])
            self.assertEqual(
                requested[0]["context"]["character_behavior"]["proactive_style"],
                "轻量出现，不要求回应。",
            )
            self.assertEqual(controller._last_proactive_type, "memory_context_greeting")

    # 验证场景 问候 uses 本地 template when API disabled场景下的预期结果。
    def test_scenario_greeting_uses_local_template_when_api_disabled(self) -> None:
        """验证场景 问候 uses 本地 template when API disabled场景下的预期结果。"""
        with tempfile.TemporaryDirectory() as temp:
            config = {
                "behavior": {
                    "proactive_chat": True,
                    "do_not_disturb": False,
                    "max_local_lines_per_day": 10,
                    "min_proactive_interval_minutes": 1,
                    "enable_scenario_greeting": True,
                    "scenario_greeting_api_enabled": False,
                    "scenario_greeting_cooldown_minutes": 0,
                    "scenario_greeting_min_memory_items": 1,
                    "scenario_greeting_max_chars": 80,
                },
                "proactive_content_ratio": {"extra_knowledge": 0.0, "regular_greeting": 1.0},
            }
            local_lines = {
                "idle": ["hello"],
                "scenario_greeting_templates": ["{task}这块先抓最关键的一小步就行。"],
                "first_start": {"enable": False, "data": []},
            }
            memory = {"work_study": {"current_projects": ["桌宠记忆系统"]}}
            controller = self._controller(Path(temp), config, local_lines=local_lines, memory=memory)
            controller.last_user_interaction = now_local().replace(year=2000)
            spoken: list[tuple[str, int, str]] = []
            controller.speak_requested.connect(lambda *args: spoken.append(args))

            controller._maybe_idle_prompt()

            self.assertEqual(spoken[0][0], "桌宠记忆系统这块先抓最关键的一小步就行。")
            self.assertEqual(controller._last_proactive_type, "memory_context_greeting")


if __name__ == "__main__":
    unittest.main()
