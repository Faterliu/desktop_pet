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
        def __init__(self, *args, **kwargs) -> None:  # noqa: D107
            self._callbacks = []

        def connect(self, callback) -> None:  # type: ignore[no-untyped-def]
            self._callbacks.append(callback)

        def emit(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            for callback in list(self._callbacks):
                callback(*args, **kwargs)

    class _FakeQObject:
        def __init__(self, *args, **kwargs) -> None:  # noqa: D107
            pass

    class _FakeQTimer:
        def __init__(self, *args, **kwargs) -> None:  # noqa: D107
            self.timeout = _FakeSignal()
            self.running = False

        def start(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.running = True

        def stop(self) -> None:
            self.running = False

    class QCoreApplication:  # type: ignore[no-redef]
        _instance = None

        def __init__(self, *args, **kwargs) -> None:  # noqa: D107
            QCoreApplication._instance = self

        @staticmethod
        def instance():  # type: ignore[no-untyped-def]
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
    def __init__(self) -> None:
        self.max_values: list[int] = []
        self.local_count = 0

    def can_use_local(self, max_per_day: int) -> bool:
        self.max_values.append(max_per_day)
        return True

    def increment_local_line(self) -> None:
        self.local_count += 1


class BehaviorControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def _controller(
        self,
        temp_dir: Path,
        config: dict,
        saver=None,
    ) -> BehaviorController:
        local_lines_path = temp_dir / "local_lines.json"
        local_lines_path.write_text(
            json.dumps({"idle": ["hello"], "first_start": {"enable": False, "data": []}}),
            encoding="utf-8",
        )
        controller = BehaviorController(
            temp_dir / "app_config.json",
            local_lines_path,
            FakeUsageStore(),  # type: ignore[arg-type]
            lambda: config,
            config_saver=saver,
        )
        controller.idle_check_timer.stop()
        controller.period_check_timer.stop()
        return controller

    def test_invalid_daily_limit_falls_back_to_default(self) -> None:
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

    def test_proactive_ratio_adjustment_calls_save_callback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = {
                "proactive_content_ratio": {
                    "extra_knowledge": 0.35,
                    "regular_greeting": 0.65,
                }
            }
            saved = 0

            def saver() -> None:
                nonlocal saved
                saved += 1

            controller = self._controller(Path(temp), config, saver=saver)
            controller.notify_proactive_shown("extra_knowledge")
            controller.notify_proactive_response()

            self.assertEqual(saved, 1)
            self.assertGreater(config["proactive_content_ratio"]["extra_knowledge"], 0.35)


if __name__ == "__main__":
    unittest.main()
