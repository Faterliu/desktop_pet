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

    def __init__(self, default_wait_timeout_ms: int = 1000) -> None:
        """初始化当前对象及其依赖。"""
        self.default_wait_timeout_ms = max(0, int(default_wait_timeout_ms))
        self._tasks: dict[str, BackgroundTask] = {}

    def register(
        self,
        name: str,
        thread: Any,
        worker: Any,
        cleanup: CleanupCallback | None = None,
        wait_timeout_ms: int | None = None,
    ) -> bool:
        """处理 `register` 对应的业务逻辑。"""
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

    def unregister(self, name: str, delete_later: bool = True) -> bool:
        """处理 `unregister` 对应的业务逻辑。"""
        return self.remove(name, delete_later=delete_later)

    def is_registered(self, name: str) -> bool:
        """判断 `is_registered` 对应的条件是否成立。"""
        return name in self._tasks

    def is_running(self, name: str) -> bool:
        """判断 `is_running` 对应的条件是否成立。"""
        task = self._tasks.get(name)
        return bool(task and self._is_running(task.thread))

    def any_running(self) -> bool:
        """处理 `any_running` 对应的业务逻辑。"""
        return any(self._is_running(task.thread) for task in self._tasks.values())

    def active_names(self) -> list[str]:
        """处理 `active_names` 对应的业务逻辑。"""
        return [name for name, task in self._tasks.items() if self._is_running(task.thread)]

    def request_quit_all(self, timeout_ms: int | None = None) -> list[str]:
        """处理 `request_quit_all` 对应的业务逻辑。"""
        still_running: list[str] = []
        for task in list(self._tasks.values()):
            if self._is_running(task.thread):
                self._quit_thread(task.thread)
                if timeout_ms is not None and not self._wait_thread(task, self._timeout(timeout_ms)):
                    still_running.append(task.name)
        return still_running

    def clear_finished(self) -> None:
        """移除 `clear_finished` 对应的内容。"""
        for task in list(self._tasks.values()):
            if not self._is_running(task.thread):
                self.unregister(task.name)

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

    def _timeout(self, wait_timeout_ms: int | None) -> int:
        """处理 `_timeout` 对应的业务逻辑。"""
        if wait_timeout_ms is None:
            return self.default_wait_timeout_ms
        try:
            return max(0, int(wait_timeout_ms))
        except (TypeError, ValueError):
            return self.default_wait_timeout_ms

    def _wait_thread(self, task: BackgroundTask, wait_timeout_ms: int | None = None) -> bool:
        """处理 `_wait_thread` 对应的业务逻辑。"""
        wait = getattr(task.thread, "wait", None)
        if not callable(wait):
            return not self._is_running(task.thread)
        timeout = task.wait_timeout_ms if wait_timeout_ms is None else wait_timeout_ms
        try:
            return bool(wait(timeout))
        except RuntimeError:
            return True

    def _quit_thread(self, thread: Any) -> None:
        """结束 `_quit_thread` 对应的流程并清理资源。"""
        quit_method = getattr(thread, "quit", None)
        if callable(quit_method):
            try:
                quit_method()
            except RuntimeError as exc:
                logger.warning("Failed to quit background thread: %s", exc)

    def _delete_later(self, obj: Any) -> None:
        """移除 `_delete_later` 对应的内容。"""
        delete_later = getattr(obj, "deleteLater", None)
        if callable(delete_later):
            try:
                delete_later()
            except RuntimeError:
                pass

    def _is_running(self, thread: Any) -> bool:
        """判断 `_is_running` 对应的条件是否成立。"""
        is_running = getattr(thread, "isRunning", None)
        if not callable(is_running):
            return False
        try:
            return bool(is_running())
        except RuntimeError:
            return False
