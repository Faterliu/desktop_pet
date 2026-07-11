from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from ai.memory_summarizer import MemorySummarizer
from ai.summarizer import Summarizer
from storage.json_store import load_json, save_json
from utils.log_sanitizer import safe_exception
from utils.logger import get_logger
from utils.time_utils import now_local, utc_iso


logger = get_logger(__name__)

DEFAULT_MAINTENANCE_STATE = {"last_daily_summary_date": ""}


def should_run_daily_catchup(now, last_daily_summary_date: str, has_history: bool) -> bool:
    """判断启动后是否需要补跑当日凌晨一点的维护任务。"""
    return bool(has_history and now.hour >= 1 and str(last_daily_summary_date) != now.date().isoformat())


class ConversationMaintenanceWorker(QObject):
    """在单个后台线程内完成模式摘要、快照清理与记忆批处理。"""

    finished = Signal(object)
    failed = Signal(str)

    # 初始化维护任务依赖。
    def __init__(
        self,
        summarizers: dict[str, Summarizer],
        memory_summarizer: MemorySummarizer,
        state_path: str | Path,
        trigger_rounds: int,
        modes: list[str],
        trigger_source: str,
        force: bool = False,
        reconcile_memory: bool = True,
    ) -> None:
        """初始化维护任务依赖。"""
        super().__init__()
        self.summarizers = dict(summarizers)
        self.memory_summarizer = memory_summarizer
        self.state_path = Path(state_path)
        self.trigger_rounds = max(1, int(trigger_rounds))
        self.modes = [mode for mode in modes if mode in self.summarizers]
        self.trigger_source = trigger_source
        self.force = force
        self.reconcile_memory = reconcile_memory

    # 执行一次维护任务。
    def run(self) -> None:
        """执行一次维护任务。"""
        try:
            summarized: dict[str, int] = {}
            removed: dict[str, int] = {}
            for mode in self.modes:
                summarizer = self.summarizers[mode]
                result = summarizer.maybe_summarize(
                    self.trigger_rounds,
                    force=self.force,
                    trigger_source=self.trigger_source,
                )
                if result is None:
                    continue
                summarized[mode] = result.sequence
                removed[mode] = summarizer.chat_store.remove_snapshot(result.snapshot)

            memory_batches: dict[str, list[int]] = {}
            if self.reconcile_memory:
                for mode, summarizer in self.summarizers.items():
                    completed = self.memory_summarizer.completed_sequence(mode)
                    entries = summarizer.recent_summary_entries(10_000)
                    latest_sequence = len(entries)
                    next_sequence = completed + 3
                    while next_sequence <= latest_sequence:
                        batch = entries[next_sequence - 3 : next_sequence]
                        if len(batch) != 3 or not self.memory_summarizer.summarize_batch(
                            mode, batch, next_sequence
                        ):
                            break
                        memory_batches.setdefault(mode, []).append(next_sequence)
                        next_sequence += 3

            if self.trigger_source == "daily" and summarized:
                state = load_json(self.state_path, DEFAULT_MAINTENANCE_STATE)
                if not isinstance(state, dict):
                    state = dict(DEFAULT_MAINTENANCE_STATE)
                state["last_daily_summary_date"] = now_local().date().isoformat()
                state["last_updated"] = utc_iso()
                save_json(self.state_path, state)

            self.finished.emit(
                {
                    "trigger_source": self.trigger_source,
                    "summarized": summarized,
                    "removed": removed,
                    "memory_batches": memory_batches,
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Conversation maintenance failed: %s", safe_exception(exc))
            self.failed.emit(str(exc))
