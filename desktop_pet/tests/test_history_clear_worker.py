from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

try:
    import PySide6.QtCore  # noqa: F401
except ModuleNotFoundError:
    qt_module = types.ModuleType("PySide6")
    qt_core = types.ModuleType("PySide6.QtCore")

    class _FakeSignal:
        def __init__(self, *args, **kwargs) -> None:  # noqa: D107
            """初始化当前对象及其依赖。"""
            self._callbacks = []

        def connect(self, callback) -> None:  # type: ignore[no-untyped-def]
            """处理 `connect` 对应的业务逻辑。"""
            self._callbacks.append(callback)

        def emit(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            """处理 `emit` 对应的业务逻辑。"""
            for callback in list(self._callbacks):
                callback(*args, **kwargs)

    class _FakeQObject:
        def __init__(self, *args, **kwargs) -> None:  # noqa: D107
            """初始化当前对象及其依赖。"""
            pass

    qt_core.QObject = _FakeQObject
    qt_core.Signal = _FakeSignal
    qt_module.QtCore = qt_core
    sys.modules.setdefault("PySide6", qt_module)
    sys.modules.setdefault("PySide6.QtCore", qt_core)

from app.history_clear_worker import ChatHistoryClearWorker  # noqa: E402


class FakeSummarizer:
    def __init__(self) -> None:
        """初始化当前对象及其依赖。"""
        self.calls: list[tuple[int, bool]] = []

    def maybe_summarize(self, trigger_rounds: int, force: bool = False) -> None:
        """处理 `maybe_summarize` 对应的业务逻辑。"""
        self.calls.append((trigger_rounds, force))


class FakeChatStore:
    def __init__(self) -> None:
        """初始化当前对象及其依赖。"""
        self.cleared = False
        self.cleaned_at = ""

    def clear_history(self) -> None:
        """移除 `clear_history` 对应的内容。"""
        self.cleared = True

    def update_last_cleaned_at(self, timestamp: str) -> None:
        """更新 `update_last_cleaned_at` 对应的状态。"""
        self.cleaned_at = timestamp


class HistoryClearWorkerTests(unittest.TestCase):
    def test_worker_runs_summary_and_clear_without_ui_dependency(self) -> None:
        """验证 `test_worker_runs_summary_and_clear_without_ui_dependency` 对应的行为。"""
        summarizer = FakeSummarizer()
        store = FakeChatStore()
        worker = ChatHistoryClearWorker(
            mode="informal",
            summarizer=summarizer,
            chat_store=store,
            force_summarize=True,
        )

        worker.run()

        self.assertEqual(summarizer.calls, [(0, True)])
        self.assertTrue(store.cleared)
        self.assertTrue(store.cleaned_at)


if __name__ == "__main__":
    unittest.main()
