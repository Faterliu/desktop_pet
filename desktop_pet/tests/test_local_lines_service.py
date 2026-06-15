from __future__ import annotations

import logging
import shutil
import sys
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

logger_module = types.ModuleType("utils.logger")
logger_module.get_logger = logging.getLogger
sys.modules.setdefault("utils.logger", logger_module)

try:
    from PySide6.QtCore import QObject, Signal
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

    qt_core.QObject = _FakeQObject
    qt_core.Signal = _FakeSignal
    qt_module.QtCore = qt_core
    sys.modules.setdefault("PySide6", qt_module)
    sys.modules.setdefault("PySide6.QtCore", qt_core)

from storage.json_store import load_json, save_json  # noqa: E402
from storage.local_lines_service import LocalLinesService  # noqa: E402

from app.desktop_pet_window import LocalLinesRefreshWorker  # noqa: E402


class FakeDeepSeekClient:
    def __init__(self, configured: bool = True, reply: str = "新开场一\n新开场二") -> None:
        self.configured = configured
        self.reply = reply
        self.calls = 0

    def is_configured(self) -> bool:
        return self.configured

    def chat(self, messages):  # type: ignore[no-untyped-def]
        self.calls += 1
        return self.reply


class LocalLinesServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / "test_local_lines_service" / self._testMethodName
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.lines_path = self.temp_dir / "local_lines.json"
        self.meta_path = self.temp_dir / "local_lines_generated_meta.json"

    def tearDown(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_pick_line_supports_existing_array_shape(self) -> None:
        save_json(self.lines_path, {"knowledge_speak_intro": ["一句话", "另一句话"]})
        service = LocalLinesService(self.lines_path)

        with patch("storage.local_lines_service.random.choice", side_effect=lambda items: items[0]):
            self.assertEqual(service.pick_line("knowledge_speak_intro"), "一句话")

    def test_pick_line_returns_fallback_for_missing_group(self) -> None:
        save_json(self.lines_path, {})
        service = LocalLinesService(self.lines_path)

        self.assertEqual(service.pick_line("missing", fallback="兜底"), "兜底")

    def test_replace_generated_lines_filters_bad_lines_and_records_metadata(self) -> None:
        save_json(self.lines_path, {"knowledge_speak_intro": ["人工话术"]})
        service = LocalLinesService(self.lines_path, self.meta_path)

        result = service.replace_generated_lines(
            "knowledge_speak_intro",
            [
                "新话术一",
                "新话术一",
                "",
                "根据记忆我想说一句话",
                "这句话太长了",
            ],
            source="deepseek",
            max_chars=5,
            max_items=5,
        )

        self.assertEqual(result.accepted, ["新话术一"])
        self.assertTrue(result.saved)
        self.assertEqual(load_json(self.lines_path, {})["knowledge_speak_intro"], ["人工话术", "新话术一"])
        metadata = load_json(self.meta_path, {})
        self.assertEqual(metadata["groups"]["knowledge_speak_intro"]["source"], "deepseek")
        self.assertEqual(metadata["groups"]["knowledge_speak_intro"]["count"], 1)

    def test_replace_generated_lines_preserves_first_start_shape(self) -> None:
        save_json(self.lines_path, {"first_start": {"enable": True, "data": ["人工"]}})
        service = LocalLinesService(self.lines_path, self.meta_path)

        result = service.replace_generated_lines(
            "first_start",
            ["新首次问候"],
            source="deepseek",
            max_chars=20,
            max_items=5,
        )

        self.assertTrue(result.saved)
        payload = load_json(self.lines_path, {})
        self.assertEqual(payload["first_start"]["data"], ["人工", "新首次问候"])
        self.assertTrue(payload["first_start"]["enable"])

    def test_append_manual_line_dedupes_without_rewriting_existing_line(self) -> None:
        save_json(self.lines_path, {"idle": ["已有"]})
        service = LocalLinesService(self.lines_path)

        result = service.append_manual_line("idle", "已有")

        self.assertFalse(result.saved)
        self.assertEqual(load_json(self.lines_path, {})["idle"], ["已有"])

    def test_consume_first_start_line_disables_flag(self) -> None:
        save_json(self.lines_path, {"first_start": {"enable": True, "data": ["你好"]}})
        service = LocalLinesService(self.lines_path)

        self.assertEqual(service.consume_first_start_line(), "你好")
        self.assertFalse(load_json(self.lines_path, {})["first_start"]["enable"])

    def test_should_refresh_when_seven_day_interval_elapsed(self) -> None:
        save_json(self.lines_path, {"knowledge_speak_intro": ["人工"]})
        save_json(
            self.meta_path,
            {
                "groups": {
                    "knowledge_speak_intro": {
                        "last_refreshed_at": (datetime(2026, 6, 1, 9, 0, 0)).isoformat(),
                        "last_monthly_refresh": "2026-06",
                    }
                }
            },
        )
        service = LocalLinesService(self.lines_path, self.meta_path)

        self.assertTrue(
            service.should_refresh_generated_lines(
                "knowledge_speak_intro",
                interval_days=7,
                monthly_refresh=True,
                now=datetime(2026, 6, 8, 9, 0, 0),
            )
        )

    def test_should_refresh_when_month_changes_even_before_interval(self) -> None:
        save_json(self.lines_path, {"knowledge_speak_intro": ["人工"]})
        save_json(
            self.meta_path,
            {
                "groups": {
                    "knowledge_speak_intro": {
                        "last_refreshed_at": (datetime(2026, 5, 29, 9, 0, 0)).isoformat(),
                        "last_monthly_refresh": "2026-05",
                    }
                }
            },
        )
        service = LocalLinesService(self.lines_path, self.meta_path)

        self.assertTrue(
            service.should_refresh_generated_lines(
                "knowledge_speak_intro",
                interval_days=7,
                monthly_refresh=True,
                now=datetime(2026, 6, 1, 9, 0, 0),
            )
        )

    def test_should_not_refresh_before_interval_in_same_month(self) -> None:
        save_json(self.lines_path, {"knowledge_speak_intro": ["人工"]})
        last = datetime.now() - timedelta(days=2)
        save_json(
            self.meta_path,
            {
                "groups": {
                    "knowledge_speak_intro": {
                        "last_refreshed_at": last.isoformat(),
                        "last_monthly_refresh": datetime.now().strftime("%Y-%m"),
                    }
                }
            },
        )
        service = LocalLinesService(self.lines_path, self.meta_path)

        self.assertFalse(
            service.should_refresh_generated_lines(
                "knowledge_speak_intro",
                interval_days=7,
                monthly_refresh=True,
            )
        )

    def test_refresh_worker_updates_due_knowledge_intro_lines(self) -> None:
        save_json(self.lines_path, {"knowledge_speak_intro": ["人工"]})
        service = LocalLinesService(self.lines_path, self.meta_path)
        client = FakeDeepSeekClient(reply="1. 新开场一\n- 新开场二\n根据记忆我想到一句")
        worker = LocalLinesRefreshWorker(
            client,  # type: ignore[arg-type]
            service,
            targets=[
                {
                    "group": "knowledge_speak_intro",
                    "label": "知识问候前置提示",
                    "interval_days": 7,
                    "monthly_refresh": True,
                    "max_chars": 20,
                    "max_items": 5,
                }
            ],
        )
        results: list[dict] = []
        worker.finished.connect(lambda result: results.append(result))

        worker.run()

        self.assertEqual(client.calls, 1)
        self.assertTrue(results[0]["refreshed"])
        self.assertEqual(load_json(self.lines_path, {})["knowledge_speak_intro"], ["人工", "新开场一", "新开场二"])

    def test_refresh_worker_skips_when_no_group_is_enabled(self) -> None:
        save_json(self.lines_path, {"idle": ["人工"]})
        service = LocalLinesService(self.lines_path, self.meta_path)
        client = FakeDeepSeekClient()
        worker = LocalLinesRefreshWorker(
            client,  # type: ignore[arg-type]
            service,
            targets=[],
        )
        results: list[dict] = []
        worker.finished.connect(lambda result: results.append(result))

        worker.run()

        self.assertEqual(client.calls, 0)
        self.assertEqual(results[0]["reason"], "no_enabled_groups")

    def test_refresh_worker_updates_multiple_enabled_groups(self) -> None:
        save_json(self.lines_path, {"idle": ["旧空闲"], "reply": ["旧回应"]})
        service = LocalLinesService(self.lines_path, self.meta_path)
        client = FakeDeepSeekClient(reply="新话术一\n新话术二")
        worker = LocalLinesRefreshWorker(
            client,  # type: ignore[arg-type]
            service,
            targets=[
                {
                    "group": "idle",
                    "label": "空闲主动问候",
                    "interval_days": 14,
                    "monthly_refresh": False,
                    "max_chars": 20,
                    "max_items": 5,
                },
                {
                    "group": "reply",
                    "label": "知识问候回应气泡",
                    "interval_days": 14,
                    "monthly_refresh": False,
                    "max_chars": 20,
                    "max_items": 5,
                },
            ],
        )
        results: list[dict] = []
        worker.finished.connect(lambda result: results.append(result))

        worker.run()

        self.assertEqual(client.calls, 2)
        payload = load_json(self.lines_path, {})
        self.assertEqual(payload["idle"], ["旧空闲", "新话术一", "新话术二"])
        self.assertEqual(payload["reply"], ["旧回应", "新话术一", "新话术二"])

    def test_refresh_worker_skips_when_api_is_not_configured(self) -> None:
        save_json(self.lines_path, {"knowledge_speak_intro": ["人工"]})
        service = LocalLinesService(self.lines_path, self.meta_path)
        client = FakeDeepSeekClient(configured=False)
        worker = LocalLinesRefreshWorker(
            client,  # type: ignore[arg-type]
            service,
            targets=[
                {
                    "group": "knowledge_speak_intro",
                    "label": "知识问候前置提示",
                    "interval_days": 7,
                    "monthly_refresh": True,
                    "max_chars": 20,
                    "max_items": 5,
                }
            ],
        )
        results: list[dict] = []
        worker.finished.connect(lambda result: results.append(result))

        worker.run()

        self.assertEqual(client.calls, 0)
        self.assertEqual(results[0]["reason"], "api_not_configured")


if __name__ == "__main__":
    unittest.main()
