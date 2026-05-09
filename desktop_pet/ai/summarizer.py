from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ai.deepseek_client import DeepSeekClient, DeepSeekError
from storage.chat_store import ChatStore
from storage.json_store import load_json, save_json
from storage.memory_store import MemoryStore
from utils.logger import get_logger
from utils.time_utils import now_iso


logger = get_logger(__name__)

DEFAULT_SUMMARY = {
    "summary": "",
    "covered_message_count": 0,
    "highlights": [],
    "last_updated": "",
}


class Summarizer:
    def __init__(
        self,
        summary_path: str | Path,
        chat_store: ChatStore,
        memory_store: MemoryStore,
        deepseek_client: DeepSeekClient,
    ) -> None:
        """初始化摘要器，关联摘要文件、聊天记录、记忆存储和模型客户端。"""
        self.summary_path = Path(summary_path)
        self.chat_store = chat_store
        self.memory_store = memory_store
        self.deepseek_client = deepseek_client

    def load_summary(self) -> dict[str, Any]:
        """读取当前对话摘要数据。"""
        return load_json(self.summary_path, DEFAULT_SUMMARY)

    def maybe_summarize(self, trigger_rounds: int) -> None:
        """在达到轮数阈值时尝试生成并保存摘要。"""
        history = self.chat_store.all_messages()
        user_rounds = len([item for item in history if item.get("role") == "user"])
        current_summary = self.load_summary()
        covered_count = int(current_summary.get("covered_message_count", 0))
        if user_rounds < trigger_rounds or len(history) <= covered_count:
            return

        try:
            payload = self._summarize_history(history)
        except Exception as exc:  # noqa: BLE001
            logger.error("Summary generation failed: %s", exc)
            return

        payload["covered_message_count"] = len(history)
        payload["last_updated"] = now_iso()
        save_json(self.summary_path, payload)
        extracted_memory = payload.pop("memory_updates", {})
        if extracted_memory:
            self.memory_store.merge(extracted_memory)

    def _summarize_history(self, history: list[dict[str, Any]]) -> dict[str, Any]:
        """优先调用模型生成结构化摘要，失败时退回本地摘要。"""
        if self.deepseek_client.is_configured():
            try:
                content = self.deepseek_client.chat(self._summary_messages(history))
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    return {
                        "summary": str(parsed.get("summary", "")).strip(),
                        "highlights": parsed.get("highlights", []),
                        "memory_updates": parsed.get("memory_updates", {}),
                    }
            except (DeepSeekError, json.JSONDecodeError) as exc:
                logger.warning("Falling back to local summary after model failure: %s", exc)

        return self._local_summary(history)

    def _summary_messages(self, history: list[dict[str, Any]]) -> list[dict[str, str]]:
        """把历史对话包装成用于摘要任务的提示词消息。"""
        transcript = "\n".join(
            f"{item.get('role', 'user')}: {item.get('content', '')}" for item in history[-24:]
        )
        return [
            {
                "role": "system",
                "content": (
                    "请把以下对话总结成 JSON，不要输出 JSON 之外的任何内容。"
                    "格式必须是："
                    '{"summary":"",'
                    '"highlights":[""],'
                    '"memory_updates":{"user_profile":{"preferences":[],"communication_style":[],"important_personal_notes":[]},'
                    '"work_study":{"current_learning_topics":[],"current_projects":[],"useful_context":[]}}}'
                ),
            },
            {"role": "user", "content": transcript},
        ]

    def _local_summary(self, history: list[dict[str, Any]]) -> dict[str, Any]:
        """在没有模型可用时，根据近期对话生成简化本地摘要。"""
        recent = history[-12:]
        summary_lines = [
            f"{item.get('role', 'user')}: {item.get('content', '')}" for item in recent if item.get("content")
        ]
        summary = " | ".join(summary_lines[-6:])
        return {
            "summary": summary[:500],
            "highlights": [item.get("content", "")[:80] for item in recent[-3:]],
            "memory_updates": self._extract_memory(recent),
        }

    def _extract_memory(self, history: list[dict[str, Any]]) -> dict[str, Any]:
        """从用户最近几轮消息里提取可保存的偏好和学习工作信息。"""
        preferences: list[str] = []
        projects: list[str] = []
        study_topics: list[str] = []
        styles: list[str] = []
        personal_notes: list[str] = []

        for item in history:
            if item.get("role") != "user":
                continue
            text = str(item.get("content", ""))
            if "喜欢" in text:
                preferences.append(text[:50])
            if re.search(r"(项目|需求|实现|代码)", text):
                projects.append(text[:60])
            if re.search(r"(学习|复习|知识|课程|算法)", text):
                study_topics.append(text[:60])
            if re.search(r"(简短|直接|详细|慢一点)", text):
                styles.append(text[:40])
            if re.search(r"(我叫|我是|今天|最近)", text):
                personal_notes.append(text[:60])

        return {
            "user_profile": {
                "preferences": preferences[:5],
                "communication_style": styles[:5],
                "important_personal_notes": personal_notes[:5],
            },
            "work_study": {
                "current_learning_topics": study_topics[:5],
                "current_projects": projects[:5],
                "useful_context": [],
            },
        }
