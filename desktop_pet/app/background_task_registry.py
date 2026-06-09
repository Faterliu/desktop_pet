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
    """Small registry for QThread-backed background tasks."""

    def __init__(self, default_wait_timeout_ms: int = 1000) -> None:
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
        task = self._tasks.pop(name, None)
        if task is None:
            return False

        if self._is_running(task.thread):
            self._wait_thread(task)
        if delete_later:
            self._delete_later(task.worker)
            self._delete_later(task.thread)
        if task.cleanup is not None:
            task.cleanup()
        return True

    def unregister(self, name: str, delete_later: bool = True) -> bool:
        """Remove a task from the registry and clear its owned references."""
        return self.remove(name, delete_later=delete_later)

    def is_registered(self, name: str) -> bool:
        return name in self._tasks

    def is_running(self, name: str) -> bool:
        task = self._tasks.get(name)
        return bool(task and self._is_running(task.thread))

    def any_running(self) -> bool:
        return any(self._is_running(task.thread) for task in self._tasks.values())

    def active_names(self) -> list[str]:
        return [name for name, task in self._tasks.items() if self._is_running(task.thread)]

    def request_quit_all(self, timeout_ms: int | None = None) -> list[str]:
        """Ask all running threads to quit and optionally wait for a bounded time."""
        still_running: list[str] = []
        for task in list(self._tasks.values()):
            if self._is_running(task.thread):
                self._quit_thread(task.thread)
                if timeout_ms is not None and not self._wait_thread(task, self._timeout(timeout_ms)):
                    still_running.append(task.name)
        return still_running

    def clear_finished(self) -> None:
        """Drop registry entries whose threads have already stopped."""
        for task in list(self._tasks.values()):
            if not self._is_running(task.thread):
                self.unregister(task.name)

    def stop_all(self, wait_timeout_ms: int | None = None) -> list[str]:
        stuck: list[str] = []
        for task in list(self._tasks.values()):
            if self._is_running(task.thread):
                self._quit_thread(task.thread)
                if not self._wait_thread(
                    task,
                    None if wait_timeout_ms is None else self._timeout(wait_timeout_ms),
                ):
                    stuck.append(task.name)
                    self._terminate_thread(task.thread)
                    self._wait_thread(task, 100)
            self.remove(task.name)
        return stuck

    def _timeout(self, wait_timeout_ms: int | None) -> int:
        if wait_timeout_ms is None:
            return self.default_wait_timeout_ms
        try:
            return max(0, int(wait_timeout_ms))
        except (TypeError, ValueError):
            return self.default_wait_timeout_ms

    def _wait_thread(self, task: BackgroundTask, wait_timeout_ms: int | None = None) -> bool:
        wait = getattr(task.thread, "wait", None)
        if not callable(wait):
            return not self._is_running(task.thread)
        timeout = task.wait_timeout_ms if wait_timeout_ms is None else wait_timeout_ms
        try:
            return bool(wait(timeout))
        except RuntimeError:
            return True

    def _quit_thread(self, thread: Any) -> None:
        quit_method = getattr(thread, "quit", None)
        if callable(quit_method):
            try:
                quit_method()
            except RuntimeError as exc:
                logger.warning("Failed to quit background thread: %s", exc)

    def _terminate_thread(self, thread: Any) -> None:
        terminate = getattr(thread, "terminate", None)
        if callable(terminate):
            try:
                terminate()
            except RuntimeError as exc:
                logger.warning("Failed to terminate background thread: %s", exc)

    def _delete_later(self, obj: Any) -> None:
        delete_later = getattr(obj, "deleteLater", None)
        if callable(delete_later):
            try:
                delete_later()
            except RuntimeError:
                pass

    def _is_running(self, thread: Any) -> bool:
        is_running = getattr(thread, "isRunning", None)
        if not callable(is_running):
            return False
        try:
            return bool(is_running())
        except RuntimeError:
            return False
