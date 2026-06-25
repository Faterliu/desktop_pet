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

from app.history_clear_worker import ChatHistoryClearWorker  # noqa: E402


class FakeSummarizer:
    # 初始化当前对象及其依赖。
    def __init__(self) -> None:
        """初始化当前对象及其依赖。"""
        self.calls: list[tuple[int, bool]] = []

    # 为 FakeSummarizer 测试替身提供maybesummarize行为。
    def maybe_summarize(self, trigger_rounds: int, force: bool = False) -> None:
        """为 FakeSummarizer 测试替身提供maybesummarize行为。"""
        self.calls.append((trigger_rounds, force))


class FakeChatStore:
    # 初始化当前对象及其依赖。
    def __init__(self) -> None:
        """初始化当前对象及其依赖。"""
        self.cleared = False
        self.cleaned_at = ""

    # 为 FakeChatStore 测试替身提供clear 历史记录行为。
    def clear_history(self) -> None:
        """为 FakeChatStore 测试替身提供clear 历史记录行为。"""
        self.cleared = True

    # 为 FakeChatStore 测试替身提供updatelastcleanedat行为。
    def update_last_cleaned_at(self, timestamp: str) -> None:
        """为 FakeChatStore 测试替身提供updatelastcleanedat行为。"""
        self.cleaned_at = timestamp


class FakeAtomicChatStore(FakeChatStore):
    # 初始化当前对象及其依赖。
    def __init__(self) -> None:
        """初始化当前对象及其依赖。"""
        super().__init__()
        self.atomic_clear_calls = 0
        self.update_calls = 0

    # 清空聊天记录并记录清理时间。
    def clear_history_with_timestamp(self, timestamp: str) -> None:
        """清空聊天记录并记录清理时间。"""
        self.atomic_clear_calls += 1
        self.cleared = True
        self.cleaned_at = timestamp

    # 记录旧式更新时间接口是否被调用。
    def update_last_cleaned_at(self, timestamp: str) -> None:
        """记录旧式更新时间接口是否被调用。"""
        self.update_calls += 1
        super().update_last_cleaned_at(timestamp)


class HistoryClearWorkerTests(unittest.TestCase):
    # 验证工作线程 runs 摘要 and clear without ui dependency场景下的预期结果。
    def test_worker_runs_summary_and_clear_without_ui_dependency(self) -> None:
        """验证工作线程 runs 摘要 and clear without ui dependency场景下的预期结果。"""
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

    # 存储支持合并清理时，worker 不再分两次写入。
    def test_worker_prefers_atomic_clear_when_available(self) -> None:
        """存储支持合并清理时，worker 不再分两次写入。"""
        summarizer = FakeSummarizer()
        store = FakeAtomicChatStore()
        worker = ChatHistoryClearWorker(
            mode="informal",
            summarizer=summarizer,
            chat_store=store,
            force_summarize=False,
        )

        worker.run()

        self.assertEqual(store.atomic_clear_calls, 1)
        self.assertEqual(store.update_calls, 0)
        self.assertTrue(store.cleared)
        self.assertTrue(store.cleaned_at)


if __name__ == "__main__":
    unittest.main()
