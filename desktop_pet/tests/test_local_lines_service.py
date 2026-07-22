from __future__ import annotations

import logging
import shutil
import sys
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
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

    qt_core.QObject = _FakeQObject
    qt_core.Signal = _FakeSignal
    qt_module.QtCore = qt_core
    sys.modules.setdefault("PySide6", qt_module)
    sys.modules.setdefault("PySide6.QtCore", qt_core)

from storage.json_store import load_json, save_json  # noqa: E402
from storage.local_lines_service import LocalLinesService  # noqa: E402

from app.desktop_pet_window import DesktopPetWindow, LocalLinesRefreshWorker  # noqa: E402


class FakeLlmClient:
    # 初始化当前对象及其依赖。
    def __init__(self, configured: bool = True, reply: str = "新开场一\n新开场二") -> None:
        """初始化当前对象及其依赖。"""
        self.configured = configured
        self.reply = reply
        self.calls = 0

    # 为 FakeLlmClient 测试替身提供isconfigured行为。
    def is_configured(self) -> bool:
        """为 FakeLlmClient 测试替身提供isconfigured行为。"""
        return self.configured

    # 为 FakeLlmClient 测试替身提供聊天行为。
    def chat(self, messages):  # type: ignore[no-untyped-def]
        """为 FakeLlmClient 测试替身提供聊天行为。"""
        self.calls += 1
        return self.reply


class LocalLinesServiceTests(unittest.TestCase):
    # 准备当前测试所需的环境和数据。
    def setUp(self) -> None:
        """准备当前测试所需的环境和数据。"""
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / "test_local_lines_service" / self._testMethodName
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.lines_path = self.temp_dir / "local_lines.json"
        self.meta_path = self.temp_dir / "local_lines_generated_meta.json"

    # 清理当前测试产生的环境和数据。
    def tearDown(self) -> None:
        """清理当前测试产生的环境和数据。"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    # 验证pick 台词 supports existing array shape场景下的预期结果。
    def test_pick_line_supports_existing_array_shape(self) -> None:
        """验证pick 台词 supports existing array shape场景下的预期结果。"""
        save_json(self.lines_path, {"knowledge_speak_intro": ["一句话", "另一句话"]})
        service = LocalLinesService(self.lines_path)

        with patch("storage.local_lines_service.random.choice", side_effect=lambda items: items[0]):
            self.assertEqual(service.pick_line("knowledge_speak_intro"), "一句话")

    # 验证pick 台词 returns 兜底 for missing group场景下的预期结果。
    def test_pick_line_returns_fallback_for_missing_group(self) -> None:
        """验证pick 台词 returns 兜底 for missing group场景下的预期结果。"""
        save_json(self.lines_path, {})
        service = LocalLinesService(self.lines_path)

        self.assertEqual(service.pick_line("missing", fallback="兜底"), "兜底")

    # 验证replace generated 台词 filters bad 台词 and records metadata场景下的预期结果。
    def test_replace_generated_lines_filters_bad_lines_and_records_metadata(self) -> None:
        """验证replace generated 台词 filters bad 台词 and records metadata场景下的预期结果。"""
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

    # 验证replace generated 台词 preserves first start shape场景下的预期结果。
    def test_replace_generated_lines_preserves_first_start_shape(self) -> None:
        """验证replace generated 台词 preserves first start shape场景下的预期结果。"""
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

    # 验证append manual 台词 dedupes without rewriting existing 台词场景下的预期结果。
    def test_append_manual_line_dedupes_without_rewriting_existing_line(self) -> None:
        """验证append manual 台词 dedupes without rewriting existing 台词场景下的预期结果。"""
        save_json(self.lines_path, {"idle": ["已有"]})
        service = LocalLinesService(self.lines_path)

        result = service.append_manual_line("idle", "已有")

        self.assertFalse(result.saved)
        self.assertEqual(load_json(self.lines_path, {})["idle"], ["已有"])

    # 验证consume first start 台词 disables flag场景下的预期结果。
    def test_consume_first_start_line_disables_flag(self) -> None:
        """验证consume first start 台词 disables flag场景下的预期结果。"""
        save_json(self.lines_path, {"first_start": {"enable": True, "data": ["你好"]}})
        service = LocalLinesService(self.lines_path)

        self.assertEqual(service.consume_first_start_line(), "你好")
        self.assertFalse(load_json(self.lines_path, {})["first_start"]["enable"])

    # 验证should refresh when seven day interval elapsed场景下的预期结果。
    def test_should_refresh_when_seven_day_interval_elapsed(self) -> None:
        """验证should refresh when seven day interval elapsed场景下的预期结果。"""
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

    # 验证should refresh when month changes even before interval场景下的预期结果。
    def test_should_refresh_when_month_changes_even_before_interval(self) -> None:
        """验证should refresh when month changes even before interval场景下的预期结果。"""
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

    # 验证should not refresh before interval in same month场景下的预期结果。
    def test_should_not_refresh_before_interval_in_same_month(self) -> None:
        """验证should not refresh before interval in same month场景下的预期结果。"""
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

    # 验证refresh 工作线程 updates due 知识问候 intro 台词场景下的预期结果。
    def test_refresh_worker_updates_due_knowledge_intro_lines(self) -> None:
        """验证refresh 工作线程 updates due 知识问候 intro 台词场景下的预期结果。"""
        save_json(self.lines_path, {"knowledge_speak_intro": ["人工"]})
        service = LocalLinesService(self.lines_path, self.meta_path)
        client = FakeLlmClient(reply="1. 新开场一\n- 新开场二\n根据记忆我想到一句")
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

    # 验证refresh 工作线程 skips when no group is enabled场景下的预期结果。
    def test_refresh_worker_skips_when_no_group_is_enabled(self) -> None:
        """验证refresh 工作线程 skips when no group is enabled场景下的预期结果。"""
        save_json(self.lines_path, {"idle": ["人工"]})
        service = LocalLinesService(self.lines_path, self.meta_path)
        client = FakeLlmClient()
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

    # 验证refresh 工作线程 updates multiple enabled groups场景下的预期结果。
    def test_refresh_worker_updates_multiple_enabled_groups(self) -> None:
        """验证refresh 工作线程 updates multiple enabled groups场景下的预期结果。"""
        save_json(self.lines_path, {"idle": ["旧空闲"], "reply": ["旧回应"]})
        service = LocalLinesService(self.lines_path, self.meta_path)
        client = FakeLlmClient(reply="新话术一\n新话术二")
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

    # 验证refresh 工作线程 skips when API is not configured场景下的预期结果。
    def test_refresh_worker_skips_when_api_is_not_configured(self) -> None:
        """验证refresh 工作线程 skips when API is not configured场景下的预期结果。"""
        save_json(self.lines_path, {"knowledge_speak_intro": ["人工"]})
        service = LocalLinesService(self.lines_path, self.meta_path)
        client = FakeLlmClient(configured=False)
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

    # 验证首次启动问候不会进入按问候类型生成的自动更新目标。
    def test_refresh_targets_exclude_first_start_from_arrival_type(self) -> None:
        """验证首次启动问候不会进入按问候类型生成的自动更新目标。"""
        window = SimpleNamespace(
            app_config={
                "local_lines_refresh": {
                    "greeting_types": {
                        "time": {"enabled": False},
                        "arrival": {"enabled": True},
                        "care": {"enabled": False},
                        "scenario": {"enabled": False},
                        "interaction": {"enabled": False},
                    },
                }
            }
        )

        targets = DesktopPetWindow._local_lines_refresh_targets(window)

        self.assertNotIn("first_start", [target["group"] for target in targets])
        self.assertEqual(
            [target["group"] for target in targets],
            ["startup", "return_after_idle", "farewell"],
        )

    # 验证旧版按具体分组的更新配置同样不会改写首次启动问候。
    def test_refresh_targets_exclude_first_start_from_legacy_groups(self) -> None:
        """验证旧版按具体分组的更新配置同样不会改写首次启动问候。"""
        window = SimpleNamespace(
            app_config={
                "local_lines_refresh": {
                    "greeting_types": None,
                    "groups": {
                        "first_start": {"enabled": True},
                        "startup": {"enabled": True},
                    },
                }
            }
        )

        targets = DesktopPetWindow._local_lines_refresh_targets(window)

        self.assertEqual([target["group"] for target in targets], ["startup"])


if __name__ == "__main__":
    unittest.main()
