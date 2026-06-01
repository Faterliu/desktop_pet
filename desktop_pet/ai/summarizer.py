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
        mem0_memory_service: Any | None = None,
        user_id: str = "default_user",
    ) -> None:
        """初始化摘要器，关联摘要文件、聊天记录、记忆存储和模型客户端。"""
        self.summary_path = Path(summary_path)
        self.chat_store = chat_store
        self.memory_store = memory_store
        self.deepseek_client = deepseek_client
        self.mem0_memory_service = mem0_memory_service
        self.user_id = user_id

    def load_summary(self) -> dict[str, Any]:
        """读取当前对话摘要数据。"""
        return load_json(self.summary_path, DEFAULT_SUMMARY)

    def maybe_summarize(self, trigger_rounds: int, force: bool = False) -> None:
        """在达到轮数阈值或强制触发时尝试生成并保存摘要。"""
        history = self.chat_store.all_messages()
        if not self._has_summarizable_history(history):
            logger.info("Skip summary because chat history has no user content")
            return

        current_summary = self.load_summary()
        covered_count = int(current_summary.get("covered_message_count", 0))
        if not force and not self._should_summarize(history, trigger_rounds, covered_count):
            return

        try:
            payload = self._summarize_history(history)
        except Exception as exc:  # noqa: BLE001
            logger.error("Summary generation failed: %s", exc)
            return

        extracted_memory = payload.pop("memory_updates", {})
        payload["covered_message_count"] = len(history)
        payload["last_updated"] = now_iso()
        save_json(self.summary_path, payload)
        if self._has_memory_update_text(extracted_memory):
            self.memory_store.merge(extracted_memory)
            self._write_memory_updates_to_mem0(extracted_memory)

    def _write_memory_updates_to_mem0(self, memory_updates: dict[str, Any]) -> None:
        """Best-effort shadow write of extracted memory updates into Mem0."""
        if self.mem0_memory_service is None:
            return

        mode = self._summary_mode()
        for memory_text in self._iter_memory_texts(memory_updates):
            try:
                self.mem0_memory_service.add_memory_text(
                    user_id=self.user_id,
                    text=memory_text,
                    metadata={
                        "source": "summarizer",
                        "mode": mode,
                        "backend": "mem0",
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to shadow-write memory update to Mem0: %s", exc)

    def _iter_memory_texts(self, value: Any) -> list[str]:
        """Flatten the structured memory update payload into unique text items."""
        texts: list[str] = []

        def visit(node: Any) -> None:
            if isinstance(node, dict):
                for item in node.values():
                    visit(item)
            elif isinstance(node, list):
                for item in node:
                    visit(item)
            elif isinstance(node, str):
                text = node.strip()
                if text and text not in texts:
                    texts.append(text)

        visit(value)
        return texts

    def _has_memory_update_text(self, value: Any) -> bool:
        """Return whether a memory update payload contains actual text."""
        return bool(self._iter_memory_texts(value))

    def _summary_mode(self) -> str:
        name = self.summary_path.name.lower()
        if "informal" in name:
            return "informal"
        if "formal" in name:
            return "formal"
        return "unknown"

    def _should_summarize(
        self,
        history: list[dict[str, Any]],
        trigger_rounds: int,
        covered_count: int,
    ) -> bool:
        """Only summarize after another full batch of user messages is uncovered."""
        trigger_rounds = max(1, int(trigger_rounds))
        total_user_rounds = self._count_user_messages(history)
        if total_user_rounds < trigger_rounds:
            return False
        if len(history) <= covered_count:
            return False

        covered_count = min(max(covered_count, 0), len(history))
        uncovered_user_rounds = self._count_user_messages(history[covered_count:])
        return uncovered_user_rounds >= trigger_rounds

    def _count_user_messages(self, history: list[dict[str, Any]]) -> int:
        return len([item for item in history if item.get("role") == "user"])

    def _has_summarizable_history(self, history: list[dict[str, Any]]) -> bool:
        """只有存在非空用户消息时才允许摘要和记忆更新。"""
        return any(
            item.get("role") == "user" and str(item.get("content", "")).strip()
            for item in history
        )

    def _summarize_history(self, history: list[dict[str, Any]]) -> dict[str, Any]:
        """Prefer model summary; fall back to local summary on failure."""
        if not self.deepseek_client.is_configured():
            return self._local_summary(history)

        summary_payload = self._model_summary(history)
        if summary_payload is None:
            return self._local_summary(history)

        summary_payload["memory_updates"] = self._model_memory_updates(history)
        return summary_payload

    def _model_summary(self, history: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Build summary and highlights from the full conversation."""
        try:
            content = self.deepseek_client.chat(self._summary_messages(history))
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return {
                    "summary": str(parsed.get("summary", "")).strip(),
                    "highlights": self._string_list(parsed.get("highlights", [])),
                }
        except (DeepSeekError, json.JSONDecodeError) as exc:
            logger.warning("Falling back to local summary after model failure: %s", exc)
        return None

    def _model_memory_updates(self, history: list[dict[str, Any]]) -> dict[str, Any]:
        """仅从用户消息中提取记忆信息。避免把助手说过的话当成用户事实。"""
        user_history = self._user_history(history)
        if not user_history:
            return {}

        try:
            content = self.deepseek_client.chat(self._memory_messages(user_history))
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                normalized = self._normalize_memory_updates(parsed)
                if self._has_memory_update_text(normalized):
                    return normalized
        except (DeepSeekError, json.JSONDecodeError) as exc:
            logger.warning("Falling back to local memory extraction after model failure: %s", exc)

        return self._extract_memory(user_history[-12:])

    def _summary_messages(self, history: list[dict[str, Any]]) -> list[dict[str, str]]:
        """从近期对话构建模型摘要输入，保留角色信息以便模型区分用户和助手发言。"""
        transcript = "\n".join(
            f"{item.get('role', 'user')}: {item.get('content', '')}" for item in history[-24:]
        )
        return [
            {
                "role": "system",
                "content": (
                    "请把以下对话总结成 JSON，不要输出 JSON 之外的任何内容。"
                    "这一轮只负责生成对话摘要和高光，不要提取用户记忆。"
                    '格式必须是：{"summary":"","highlights":[""]}'
                ),
            },
            {"role": "user", "content": transcript},
        ]

    def _memory_messages(self, history: list[dict[str, Any]]) -> list[dict[str, str]]:
        """仅从用户消息中构建记忆提取输入。"""
        transcript = "\n".join(
            f"user: {item.get('content', '')}" for item in history[-24:] if item.get("content")
        )
        return [
            {
                "role": "system",
                "content": (
                    "你现在只能根据用户自己的发言提取可长期保存的记忆。"
                    "不要使用助手回复，不要脑补，不要把助手说过的话当成用户事实。"
                    "只提取用户明确表达过的事实记忆、互动偏好和相处方式。"
                    "事实记忆包括偏好、个人备注、学习主题、当前项目等。"
                    "关系记忆只记录用户希望你如何回答、如何陪伴、如何控制打扰强度；"
                    "不要评价用户人格，不要输出心理诊断、医学判断或敏感标签。"
                    "如果用户明确表达“不要频繁确认”“直接给方案”“不要像数据库工具”，"
                    "应写入 relationship_memory。"
                    "如果证据不足就留空，不要强行生成字段。"
                    "如果不确定就留空，不要猜。"
                    "请严格输出 JSON："
                    '{"user_profile":{"preferences":[],"communication_style":[],"important_personal_notes":[]},'
                    '"work_study":{"current_learning_topics":[],"current_projects":[],"useful_context":[]},'
                    '"relationship_memory":{'
                    '"communication_style":{"preferred_response_style":"","detail_level":"",'
                    '"confirmation_preference":"","tone_preference":"","avoid_styles":[],"evidence":[]},'
                    '"companionship_style":{"preferred_companion_role":"","proactive_boundary":"",'
                    '"encouragement_style":"","avoid_behaviors":[],"evidence":[]},'
                    '"interaction_patterns":{"task_focus":[],"recent_interaction_mode":"",'
                    '"interruption_tolerance":""}}}'
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
        relationship_memory = self._empty_relationship_memory_update()

        for item in history:
            if item.get("role") != "user":
                continue
            text = str(item.get("content", ""))
            if self._summary_mode() == "formal" and text.strip():
                study_topics.append(text[:60])
            if "喜欢" in text:
                preferences.append(text[:50])
            if re.search(r"(项目|需求|实现|代码)", text):
                projects.append(text[:60])
            if re.search(r"(学习|复习|知识|课程|算法|请问|怎么做|如何实现|如何|怎么|是什么|为什么|区别)", text):
                study_topics.append(text[:60])
            if re.search(r"(简短|直接|详细|慢一点)", text):
                styles.append(text[:40])
            if re.search(r"(我叫|我是|今天|最近)", text):
                personal_notes.append(text[:60])
            self._extract_relationship_memory_from_text(text, relationship_memory)

        if projects:
            relationship_memory["interaction_patterns"]["task_focus"] = projects[:3]

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
            "relationship_memory": relationship_memory,
        }

    def _user_history(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """仅返回非空的用户消息."""
        return [
            item
            for item in history
            if item.get("role") == "user" and str(item.get("content", "")).strip()
        ]

    def _normalize_memory_updates(self, payload: dict[str, Any]) -> dict[str, Any]:
        """标准化记忆更新数据."""
        source = payload.get("memory_updates", payload)
        if not isinstance(source, dict):
            source = {}
        fact_source = source.get("fact_memory_updates", source)
        if not isinstance(fact_source, dict):
            fact_source = {}
        relationship_source = (
            source.get("relationship_memory")
            or source.get("relationship_memory_updates")
            or payload.get("relationship_memory_updates")
            or {}
        )
        user_profile = fact_source.get("user_profile", {})
        work_study = fact_source.get("work_study", {})
        return {
            "user_profile": {
                "preferences": self._string_list(user_profile.get("preferences", [])),
                "communication_style": self._string_list(
                    user_profile.get("communication_style", [])
                ),
                "important_personal_notes": self._string_list(
                    user_profile.get("important_personal_notes", [])
                ),
            },
            "work_study": {
                "current_learning_topics": self._string_list(
                    work_study.get("current_learning_topics", [])
                ),
                "current_projects": self._string_list(work_study.get("current_projects", [])),
                "useful_context": self._string_list(work_study.get("useful_context", [])),
            },
            "relationship_memory": self._normalize_relationship_memory_updates(
                relationship_source
            ),
        }

    def _normalize_relationship_memory_updates(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return self._empty_relationship_memory_update()

        communication = value.get("communication_style", {})
        companionship = value.get("companionship_style", {})
        interaction = value.get("interaction_patterns", {})
        if not isinstance(communication, dict):
            communication = {}
        if not isinstance(companionship, dict):
            companionship = {}
        if not isinstance(interaction, dict):
            interaction = {}

        return {
            "communication_style": {
                "preferred_response_style": self._string_value(
                    communication.get("preferred_response_style", "")
                ),
                "detail_level": self._string_value(communication.get("detail_level", "")),
                "confirmation_preference": self._string_value(
                    communication.get("confirmation_preference", "")
                ),
                "tone_preference": self._string_value(
                    communication.get("tone_preference", "")
                ),
                "avoid_styles": self._string_list(communication.get("avoid_styles", [])),
                "evidence": self._string_list(communication.get("evidence", [])),
            },
            "companionship_style": {
                "preferred_companion_role": self._string_value(
                    companionship.get("preferred_companion_role", "")
                ),
                "proactive_boundary": self._string_value(
                    companionship.get("proactive_boundary", "")
                ),
                "encouragement_style": self._string_value(
                    companionship.get("encouragement_style", "")
                ),
                "avoid_behaviors": self._string_list(companionship.get("avoid_behaviors", [])),
                "evidence": self._string_list(companionship.get("evidence", [])),
            },
            "interaction_patterns": {
                "task_focus": self._string_list(interaction.get("task_focus", [])),
                "recent_interaction_mode": self._string_value(
                    interaction.get("recent_interaction_mode", "")
                ),
                "interruption_tolerance": self._string_value(
                    interaction.get("interruption_tolerance", "")
                ),
            },
        }

    def _empty_relationship_memory_update(self) -> dict[str, Any]:
        return {
            "communication_style": {
                "preferred_response_style": "",
                "detail_level": "",
                "confirmation_preference": "",
                "tone_preference": "",
                "avoid_styles": [],
                "evidence": [],
            },
            "companionship_style": {
                "preferred_companion_role": "",
                "proactive_boundary": "",
                "encouragement_style": "",
                "avoid_behaviors": [],
                "evidence": [],
            },
            "interaction_patterns": {
                "task_focus": [],
                "recent_interaction_mode": "",
                "interruption_tolerance": "",
            },
        }

    def _extract_relationship_memory_from_text(
        self, text: str, relationship_memory: dict[str, Any]
    ) -> None:
        stripped = text.strip()
        if not stripped:
            return
        evidence = stripped[:80]
        communication = relationship_memory["communication_style"]
        companionship = relationship_memory["companionship_style"]

        if re.search(r"(不要|别|不用|不需要).{0,8}(确认|问我)|别总是问|不要总是问", stripped):
            communication["confirmation_preference"] = "avoid_unnecessary_confirmation"
            self._append_unique(communication["evidence"], evidence)
        if re.search(r"(直接给|直接.*方案|给我可执行|可执行方案|可执行的)", stripped):
            communication["preferred_response_style"] = "direct_actionable"
            self._append_unique(communication["evidence"], evidence)
        if re.search(r"(详细一点|尽可能详细|写得完整|完整一点|展开一点)", stripped):
            communication["detail_level"] = "high"
            self._append_unique(communication["evidence"], evidence)
        if re.search(r"(数据库|数据存储器|机械化记忆|机械.*记忆|不像陪伴|像工具)", stripped):
            self._append_unique(communication["avoid_styles"], "机械化记忆表达")
            self._append_unique(companionship["avoid_behaviors"], "像数据存储器一样说话")
            self._append_unique(communication["evidence"], evidence)
            self._append_unique(companionship["evidence"], evidence)

    def _append_unique(self, items: list[str], value: str) -> None:
        if value and value not in items:
            items.append(value)

    def _string_list(self, value: Any) -> list[str]:
        """将任意输入标准化为去重的非空字符串列表."""
        if not isinstance(value, list):
            return []

        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in normalized:
                normalized.append(text)
        return normalized

    def _string_value(self, value: Any) -> str:
        return str(value).strip() if value not in (None, "") else ""
