from __future__ import annotations

import json
from typing import Any, Callable

from ai.deepseek_client import DeepSeekClient
from storage.memory_store import MemoryStore
from utils.log_sanitizer import safe_exception
from utils.logger import get_logger


logger = get_logger(__name__)


class MemorySummarizer:
    """根据单一模式的三条归档摘要重建长期记忆。"""

    # 初始化记忆总结器。
    def __init__(
        self,
        memory_store: MemoryStore,
        deepseek_client: DeepSeekClient,
        config_provider: Callable[[], dict[str, Any]],
    ) -> None:
        """初始化记忆总结器。"""
        self.memory_store = memory_store
        self.deepseek_client = deepseek_client
        self.config_provider = config_provider

    # 对指定模式的一个摘要批次生成并保存最新长期记忆。
    def summarize_batch(self, mode: str, entries: list[dict[str, Any]], sequence: int) -> bool:
        """对指定模式的一个摘要批次生成并保存最新长期记忆。"""
        if len(entries) != 3 or sequence <= 0:
            return False
        if not self.deepseek_client.is_configured():
            logger.info("Skip memory summary because chat API is not configured: mode=%s", mode)
            return False

        current = self.memory_store.load()
        try:
            content = self.deepseek_client.chat(self._messages(mode, entries, current))
            payload = json.loads(content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Memory summary generation failed: %s", safe_exception(exc))
            return False

        if not isinstance(payload, dict):
            logger.warning("Memory summary returned a non-object payload")
            return False
        operations = payload.get("operations")
        conclusion = payload.get("conclusion")
        if not isinstance(operations, list) or not isinstance(conclusion, dict):
            logger.warning("Memory summary returned an invalid operations payload")
            return False
        try:
            self.memory_store.apply_summary_operations(mode, sequence, operations)
            return True
        except (TypeError, ValueError) as exc:
            logger.warning("Memory summary operations were rejected: %s", safe_exception(exc))
            return False

    # 返回模式已经完成记忆总结的最大摘要序号。
    def completed_sequence(self, mode: str) -> int:
        """返回模式已经完成记忆总结的最大摘要序号。"""
        batches = self.memory_store.load().get("memory_meta", {}).get("summary_batches", {})
        if not isinstance(batches, dict):
            return 0
        try:
            return max(0, int(batches.get(mode, 0)))
        except (TypeError, ValueError):
            return 0

    # 构造只包含当前长期记忆和三条模式摘要的模型输入。
    def _messages(
        self,
        mode: str,
        entries: list[dict[str, Any]],
        current_memory: dict[str, Any],
    ) -> list[dict[str, str]]:
        """构造只包含当前长期记忆和三条模式摘要的模型输入。"""
        summaries = [
            {
                "sequence": item.get("sequence"),
                "summary": item.get("summary", ""),
                "highlights": item.get("highlights", []),
            }
            for item in entries
        ]
        source = json.dumps(
            {"mode": mode, "summaries": summaries, "current_memory": current_memory},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return [
            {
                "role": "system",
                "content": (
                    "请根据当前长期记忆和同一模式最近三条对话摘要，判断每条候选信息是否需要写入。"
                    "如果与已有记忆相似或重复，使用 update 合并为更准确的描述；"
                    "如果是新信息，使用 add；没有变化时使用 unchanged。"
                    "旧记忆与当前摘要无关或不相似时不要修改。只能保留用户明确表达的信息，不要猜测。"
                    "严格输出 JSON："
                    '{"operations":[{"action":"add|update|unchanged","field":"允许的字段路径",'
                    '"record_id":"仅 update 可用","description":["仅 add/update 必填"],"reason":"判断原因"}],'
                    '"conclusion":{"added":0,"updated":0,"unchanged":0}}。'
                    "字段路径只能是输入 memory 中已经出现的语义字段路径。"
                    "不要生成序号、timestamp、memory_meta 或 JSON 之外的内容。"
                ),
            },
            {"role": "user", "content": source},
        ]
