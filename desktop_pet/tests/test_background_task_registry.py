from __future__ import annotations

import sys
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from app.background_task_registry import BackgroundTaskRegistry  # noqa: E402


class FakeQtObject:
    # 初始化当前对象及其依赖。
    def __init__(self) -> None:
        """初始化当前对象及其依赖。"""
        self.deleted = False

    # 模拟线程的 deleteLater 行为，便于测试生命周期处理。
    def deleteLater(self) -> None:  # noqa: N802
        """模拟线程的 deleteLater 行为，便于测试生命周期处理。"""
        self.deleted = True


class FakeThread(FakeQtObject):
    # 初始化当前对象及其依赖。
    def __init__(self, running: bool = False, wait_result: bool = True) -> None:
        """初始化当前对象及其依赖。"""
        super().__init__()
        self.running = running
        self.wait_result = wait_result
        self.quit_calls = 0
        self.wait_calls: list[int] = []
        self.terminate_calls = 0

    # 模拟线程的 isRunning 行为，便于测试生命周期处理。
    def isRunning(self) -> bool:  # noqa: N802
        """模拟线程的 isRunning 行为，便于测试生命周期处理。"""
        return self.running

    # 模拟线程的 quit 行为，便于测试生命周期处理。
    def quit(self) -> None:
        """模拟线程的 quit 行为，便于测试生命周期处理。"""
        self.quit_calls += 1
        if self.wait_result:
            self.running = False

    # 模拟线程的 wait 行为，便于测试生命周期处理。
    def wait(self, timeout_ms: int) -> bool:
        """模拟线程的 wait 行为，便于测试生命周期处理。"""
        self.wait_calls.append(timeout_ms)
        if self.wait_result:
            self.running = False
            return True
        return False

    # 模拟线程的 terminate 行为，便于测试生命周期处理。
    def terminate(self) -> None:
        """模拟线程的 terminate 行为，便于测试生命周期处理。"""
        self.terminate_calls += 1
        self.running = False


class BackgroundTaskRegistryTests(unittest.TestCase):
    # 验证register and remove clears 任务 and calls cleanup场景下的预期结果。
    def test_register_and_remove_clears_task_and_calls_cleanup(self) -> None:
        """验证register and remove clears 任务 and calls cleanup场景下的预期结果。"""
        registry = BackgroundTaskRegistry(default_wait_timeout_ms=250)
        thread = FakeThread(running=False)
        worker = FakeQtObject()
        cleaned = False

        # 为测试准备cleanup数据或断言辅助结果。
        def cleanup() -> None:
            """为测试准备cleanup数据或断言辅助结果。"""
            nonlocal cleaned
            cleaned = True

        self.assertTrue(registry.register("chat", thread, worker, cleanup=cleanup))
        self.assertTrue(registry.is_registered("chat"))

        self.assertTrue(registry.remove("chat"))

        self.assertFalse(registry.is_registered("chat"))
        self.assertTrue(thread.deleted)
        self.assertTrue(worker.deleted)
        self.assertTrue(cleaned)

    # 验证duplicate registered 任务 is blocked before 线程 starts场景下的预期结果。
    def test_duplicate_registered_task_is_blocked_before_thread_starts(self) -> None:
        """验证duplicate registered 任务 is blocked before 线程 starts场景下的预期结果。"""
        registry = BackgroundTaskRegistry()

        self.assertTrue(registry.register("mem0_search", FakeThread(), FakeQtObject()))
        self.assertFalse(registry.register("mem0_search", FakeThread(), FakeQtObject()))

    # 验证stop all quits waits and removes active threads场景下的预期结果。
    def test_stop_all_quits_waits_and_removes_active_threads(self) -> None:
        """验证stop all quits waits and removes active threads场景下的预期结果。"""
        registry = BackgroundTaskRegistry(default_wait_timeout_ms=500)
        thread = FakeThread(running=True)
        worker = FakeQtObject()

        registry.register("memory_maintenance", thread, worker)
        stuck = registry.stop_all()

        self.assertEqual(stuck, [])
        self.assertEqual(thread.quit_calls, 1)
        self.assertEqual(thread.wait_calls, [500])
        self.assertTrue(thread.deleted)
        self.assertTrue(worker.deleted)
        self.assertFalse(registry.is_registered("memory_maintenance"))

    # 卡住的线程只报告并保留，普通退出路径不强制终止。
    def test_stop_all_keeps_stuck_threads_registered_without_terminating(self) -> None:
        """卡住的线程只报告并保留，普通退出路径不强制终止。"""
        registry = BackgroundTaskRegistry(default_wait_timeout_ms=100)
        thread = FakeThread(running=True, wait_result=False)
        worker = FakeQtObject()

        registry.register("mem0_init", thread, worker, wait_timeout_ms=200)
        stuck = registry.stop_all()

        self.assertEqual(stuck, ["mem0_init"])
        self.assertEqual(thread.quit_calls, 1)
        self.assertEqual(thread.wait_calls, [200])
        self.assertEqual(thread.terminate_calls, 0)
        self.assertTrue(thread.running)
        self.assertFalse(thread.deleted)
        self.assertFalse(worker.deleted)
        self.assertTrue(registry.is_registered("mem0_init"))

    # 直接移除运行中的任务失败时，不删除仍在线程中的对象。
    def test_remove_keeps_running_task_when_wait_times_out(self) -> None:
        """直接移除运行中的任务失败时，不删除仍在线程中的对象。"""
        registry = BackgroundTaskRegistry(default_wait_timeout_ms=100)
        thread = FakeThread(running=True, wait_result=False)
        worker = FakeQtObject()

        registry.register("chat", thread, worker)

        self.assertFalse(registry.remove("chat"))
        self.assertTrue(registry.is_registered("chat"))
        self.assertEqual(thread.quit_calls, 1)
        self.assertEqual(thread.terminate_calls, 0)
        self.assertFalse(thread.deleted)
        self.assertFalse(worker.deleted)

    # 验证unregister alias removes 任务场景下的预期结果。
    def test_unregister_alias_removes_task(self) -> None:
        """验证unregister alias removes 任务场景下的预期结果。"""
        registry = BackgroundTaskRegistry()

        registry.register("chat", FakeThread(), FakeQtObject())

        self.assertTrue(registry.unregister("chat"))
        self.assertFalse(registry.is_registered("chat"))

    # 验证请求 quit all waits without terminating场景下的预期结果。
    def test_request_quit_all_waits_without_terminating(self) -> None:
        """验证请求 quit all waits without terminating场景下的预期结果。"""
        registry = BackgroundTaskRegistry(default_wait_timeout_ms=500)
        thread = FakeThread(running=True, wait_result=False)

        registry.register("mem0_search", thread, FakeQtObject())
        still_running = registry.request_quit_all(timeout_ms=50)

        self.assertEqual(still_running, ["mem0_search"])
        self.assertEqual(thread.quit_calls, 1)
        self.assertEqual(thread.wait_calls, [50])
        self.assertEqual(thread.terminate_calls, 0)
        self.assertTrue(registry.is_registered("mem0_search"))

    # 验证clear finished removes only stopped threads场景下的预期结果。
    def test_clear_finished_removes_only_stopped_threads(self) -> None:
        """验证clear finished removes only stopped threads场景下的预期结果。"""
        registry = BackgroundTaskRegistry()
        stopped = FakeThread(running=False)
        running = FakeThread(running=True)

        registry.register("clear_history", stopped, FakeQtObject())
        registry.register("memory_maintenance", running, FakeQtObject())

        registry.clear_finished()

        self.assertFalse(registry.is_registered("clear_history"))
        self.assertTrue(registry.is_registered("memory_maintenance"))


if __name__ == "__main__":
    unittest.main()
