from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal

from utils.logger import get_logger
from utils.time_utils import now_iso


logger = get_logger(__name__)


class ChatHistoryClearWorker(QObject):
    finished = Signal(str)
    failed = Signal(str, str)

    # 初始化当前对象及其依赖。
    def __init__(
        self,
        mode: str,
        summarizer: Any,
        chat_store: Any,
        force_summarize: bool,
    ) -> None:
        """初始化当前对象及其依赖。"""
        super().__init__()
        self.mode = mode
        self.summarizer = summarizer
        self.chat_store = chat_store
        self.force_summarize = force_summarize

    # 在线程中执行 ChatHistoryClearWorker 的后台任务，并通过信号返回结果。
    def run(self) -> None:
        """在线程中执行 ChatHistoryClearWorker 的后台任务，并通过信号返回结果。"""
        try:
            if self.force_summarize:
                self.summarizer.maybe_summarize(0, force=True)
            timestamp = now_iso()
            clear_with_timestamp = getattr(self.chat_store, "clear_history_with_timestamp", None)
            if callable(clear_with_timestamp):
                clear_with_timestamp(timestamp)
            else:
                self.chat_store.clear_history()
                self.chat_store.update_last_cleaned_at(timestamp)
            self.finished.emit(self.mode)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to clear %s chat history", self.mode)
            self.failed.emit(self.mode, str(exc))
