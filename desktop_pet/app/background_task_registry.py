from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from utils.logger import get_logger


logger = get_logger(__name__)


CleanupCallback = Callable[[], None]


@dataclass
class BackgroundTask:
    name: str
    thread: Any
    worker: Any
    cleanup: CleanupCallback | None = None
    wait_timeout_ms: int = 1000


class BackgroundTaskRegistry:
    """统一管理基于 QThread 的后台任务。"""

    # 初始化当前对象及其依赖。
    def __init__(self, default_wait_timeout_ms: int = 1000) -> None:
        """初始化当前对象及其依赖。"""
        self.default_wait_timeout_ms = max(0, int(default_wait_timeout_ms))
        self._tasks: dict[str, BackgroundTask] = {}

    # 根据 name、thread、worker 把register加入当前状态或持久化记录。
    def register(
        self,
        name: str,
        thread: Any,
        worker: Any,
        cleanup: CleanupCallback | None = None,
        wait_timeout_ms: int | None = None,
    ) -> bool:
        """根据 name、thread、worker 把register加入当前状态或持久化记录。"""
        if name in self._tasks:
            return False

        self._tasks[name] = BackgroundTask(
            name=name,
            thread=thread,
            worker=worker,
            cleanup=cleanup,
            wait_timeout_ms=self._timeout(wait_timeout_ms),
        )
        return True

    # 移除已结束的后台任务；仍在运行时只请求退出并保留注册信息。
    def remove(self, name: str, delete_later: bool = True) -> bool:
        """移除已结束的后台任务；仍在运行时只请求退出并保留注册信息。"""
        task = self._tasks.get(name)
        if task is None:
            return False

        if self._is_running(task.thread):
            self._quit_thread(task.thread)
            if not self._wait_thread(task):
                return False

        self._tasks.pop(name, None)
        if delete_later:
            self._delete_later(task.worker)
            self._delete_later(task.thread)
        if task.cleanup is not None:
            task.cleanup()
        return True

    # 根据 name、delete_later 移除unregister并清理关联状态。
    def unregister(self, name: str, delete_later: bool = True) -> bool:
        """根据 name、delete_later 移除unregister并清理关联状态。"""
        return self.remove(name, delete_later=delete_later)

    # 判断指定后台任务名称是否已经注册。
    def is_registered(self, name: str) -> bool:
        """判断指定后台任务名称是否已经注册。"""
        return name in self._tasks

    # 判断指定后台任务对应的线程是否仍在运行。
    def is_running(self, name: str) -> bool:
        """判断指定后台任务对应的线程是否仍在运行。"""
        task = self._tasks.get(name)
        return bool(task and self._is_running(task.thread))

    # 判断注册表内是否还有任一后台线程处于运行状态。
    def any_running(self) -> bool:
        """判断注册表内是否还有任一后台线程处于运行状态。"""
        return any(self._is_running(task.thread) for task in self._tasks.values())

    # 返回当前仍在注册表中的后台任务名称列表。
    def active_names(self) -> list[str]:
        """返回当前仍在注册表中的后台任务名称列表。"""
        return [name for name, task in self._tasks.items() if self._is_running(task.thread)]

    # 向所有已注册后台线程发送退出请求，并返回仍在运行的名称。
    def request_quit_all(self, timeout_ms: int | None = None) -> list[str]:
        """向所有已注册后台线程发送退出请求，并返回仍在运行的名称。"""
        still_running: list[str] = []
        for task in list(self._tasks.values()):
            if self._is_running(task.thread):
                self._quit_thread(task.thread)
                if timeout_ms is not None and not self._wait_thread(task, self._timeout(timeout_ms)):
                    still_running.append(task.name)
        return still_running

    # 移除已经停止的后台任务，并保留仍在运行的注册项。
    def clear_finished(self) -> None:
        """移除已经停止的后台任务，并保留仍在运行的注册项。"""
        for task in list(self._tasks.values()):
            if not self._is_running(task.thread):
                self.unregister(task.name)

    # 请求所有后台任务退出，清理已停止任务并返回仍在运行的任务名。
    def stop_all(self, wait_timeout_ms: int | None = None) -> list[str]:
        """请求所有后台任务退出，清理已停止任务并返回仍在运行的任务名。"""
        still_running: list[str] = []
        for task in list(self._tasks.values()):
            if self._is_running(task.thread):
                self._quit_thread(task.thread)
                if not self._wait_thread(
                    task,
                    None if wait_timeout_ms is None else self._timeout(wait_timeout_ms),
                ):
                    still_running.append(task.name)
                    continue
            self.remove(task.name)
        return still_running

    # 根据 wait_timeout_ms 整理timeout，并把结果交给调用方或写回状态。
    def _timeout(self, wait_timeout_ms: int | None) -> int:
        """根据 wait_timeout_ms 整理timeout，并把结果交给调用方或写回状态。"""
        if wait_timeout_ms is None:
            return self.default_wait_timeout_ms
        try:
            return max(0, int(wait_timeout_ms))
        except (TypeError, ValueError):
            return self.default_wait_timeout_ms

    # 根据 task、wait_timeout_ms 整理wait 线程，并把结果交给调用方或写回状态。
    def _wait_thread(self, task: BackgroundTask, wait_timeout_ms: int | None = None) -> bool:
        """根据 task、wait_timeout_ms 整理wait 线程，并把结果交给调用方或写回状态。"""
        wait = getattr(task.thread, "wait", None)
        if not callable(wait):
            return not self._is_running(task.thread)
        timeout = task.wait_timeout_ms if wait_timeout_ms is None else wait_timeout_ms
        try:
            return bool(wait(timeout))
        except RuntimeError:
            return True

    # 请求线程退出并等待指定时间，返回是否已停止。
    def _quit_thread(self, thread: Any) -> None:
        """请求线程退出并等待指定时间，返回是否已停止。"""
        quit_method = getattr(thread, "quit", None)
        if callable(quit_method):
            try:
                quit_method()
            except RuntimeError as exc:
                logger.warning("Failed to quit background thread: %s", exc)

    # 在线程安全的时机调用 QObject.deleteLater 清理对象。
    def _delete_later(self, obj: Any) -> None:
        """在线程安全的时机调用 QObject.deleteLater 清理对象。"""
        delete_later = getattr(obj, "deleteLater", None)
        if callable(delete_later):
            try:
                delete_later()
            except RuntimeError:
                pass

    # 根据 thread 判断running是否满足条件并返回布尔结果。
    def _is_running(self, thread: Any) -> bool:
        """根据 thread 判断running是否满足条件并返回布尔结果。"""
        is_running = getattr(thread, "isRunning", None)
        if not callable(is_running):
            return False
        try:
            return bool(is_running())
        except RuntimeError:
            return False
