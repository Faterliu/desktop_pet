from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai.context_budget import clip_text, read_context_budget
from ai.deepseek_client import DeepSeekClient, DeepSeekError
from storage.chat_store import ChatStore
from storage.json_store import load_json, load_json_prefer_primary, save_json
from storage.memory_store import MemoryStore
from storage.path_lock import lock_for_path
from utils.log_sanitizer import safe_exception
from utils.logger import get_logger
from utils.time_utils import utc_iso


logger = get_logger(__name__)

DEFAULT_SUMMARY = {
    "summary": "",
    "covered_message_count": 0,
    "highlights": [],
    "last_updated": "",
    "summaries": [],
}


@dataclass(frozen=True)
class SummaryResult:
    """单次模式摘要的归档结果。"""

    mode: str
    sequence: int
    snapshot: list[dict[str, Any]]
    trigger_source: str


class Summarizer:
    # 初始化摘要器，关联摘要文件、聊天记录、记忆存储和模型客户端。
    def __init__(
        self,
        summary_path: str | Path,
        chat_store: ChatStore,
        memory_store: MemoryStore,
        deepseek_client: DeepSeekClient,
        mem0_memory_service: Any | None = None,
        user_id: str = "default_user",
        config_path: str | Path | None = None,
        fallback_config_path: str | Path | None = None,
    ) -> None:
        """初始化摘要器，关联摘要文件、聊天记录、记忆存储和模型客户端。"""
        self.summary_path = Path(summary_path)
        self.chat_store = chat_store
        self.memory_store = memory_store
        self.deepseek_client = deepseek_client
        self.mem0_memory_service = mem0_memory_service
        self.user_id = user_id
        self.config_path = Path(config_path) if config_path else None
        self.fallback_config_path = (
            Path(fallback_config_path) if fallback_config_path else self.config_path
        )
        self._summary_lock = lock_for_path(self.summary_path)

    # 读取当前对话摘要数据。
    def load_summary(self) -> dict[str, Any]:
        """读取当前对话摘要数据。"""
        with self._summary_lock:
            payload = load_json(self.summary_path, DEFAULT_SUMMARY)
            normalized, changed = self._normalize_archive(payload)
            if changed:
                save_json(self.summary_path, normalized)
            return normalized

    # 在达到轮数阈值或强制触发时尝试生成并保存摘要。
    def maybe_summarize(
        self,
        trigger_rounds: int,
        force: bool = False,
        trigger_source: str = "round_threshold",
    ) -> SummaryResult | None:
        """在达到轮数阈值或强制触发时尝试生成并保存摘要。"""
        with self._summary_lock:
            history = self.chat_store.all_messages()
            if not self._has_summarizable_history(history):
                logger.info("Skip summary because chat history has no user content")
                return None

            current_summary, migrated = self._normalize_archive(
                load_json(self.summary_path, DEFAULT_SUMMARY)
            )
            if not force and not self._should_summarize(history, trigger_rounds):
                if migrated:
                    save_json(self.summary_path, current_summary)
                return None

            try:
                payload = self._summarize_history(history)
            except Exception as exc:  # noqa: BLE001
                logger.error("Summary generation failed: %s", safe_exception(exc))
                return None

            sequence = len(current_summary["summaries"]) + 1
            created_at = utc_iso()
            entry = {
                "sequence": sequence,
                "summary": str(payload.get("summary", "")).strip(),
                "highlights": self._string_list(payload.get("highlights", []))[:3],
                "created_at": created_at,
                "trigger_source": str(trigger_source or "round_threshold"),
            }
            current_summary["summaries"].append(entry)
            current_summary["summary"] = entry["summary"]
            current_summary["highlights"] = entry["highlights"]
            # 该字段保留旧名称以兼容读取方，语义改为最新摘要序号。
            current_summary["covered_message_count"] = sequence
            current_summary["last_updated"] = created_at
            save_json(self.summary_path, current_summary)
            return SummaryResult(
                mode=str(getattr(self.chat_store, "mode", self._summary_mode())),
                sequence=sequence,
                snapshot=history,
                trigger_source=entry["trigger_source"],
            )

    # 返回当前模式最近若干条归档摘要，供记忆总结使用。
    def recent_summary_entries(self, limit: int = 3) -> list[dict[str, Any]]:
        """返回当前模式最近若干条归档摘要。"""
        summaries = self.load_summary().get("summaries", [])
        count = max(0, int(limit))
        if not isinstance(summaries, list) or count == 0:
            return []
        return [dict(item) for item in summaries[-count:] if isinstance(item, dict)]

    # 兼容旧版单摘要文件并规范化为追加式归档载荷。
    @staticmethod
    def _normalize_archive(payload: Any) -> tuple[dict[str, Any], bool]:
        """兼容旧版单摘要文件并规范化为追加式归档载荷。"""
        source = payload if isinstance(payload, dict) else {}
        raw_summaries = source.get("summaries", [])
        changed = not isinstance(raw_summaries, list)
        entries: list[dict[str, Any]] = []
        if isinstance(raw_summaries, list):
            for raw in raw_summaries:
                if not isinstance(raw, dict):
                    changed = True
                    continue
                text = str(raw.get("summary", "")).strip()
                highlights = raw.get("highlights", [])
                if not text and not highlights and not (
                    "sequence" in raw or "created_at" in raw or "trigger_source" in raw
                ):
                    changed = True
                    continue
                entries.append(
                    {
                        "sequence": len(entries) + 1,
                        "summary": text,
                        "highlights": [str(item).strip() for item in highlights if str(item).strip()][:3]
                        if isinstance(highlights, list)
                        else [],
                        "created_at": str(raw.get("created_at", raw.get("last_updated", ""))).strip(),
                        "trigger_source": str(raw.get("trigger_source", "legacy")).strip() or "legacy",
                    }
                )
        if not entries:
            legacy_text = str(source.get("summary", "")).strip()
            legacy_highlights = source.get("highlights", [])
            if legacy_text or legacy_highlights:
                entries.append(
                    {
                        "sequence": 1,
                        "summary": legacy_text,
                        "highlights": [str(item).strip() for item in legacy_highlights if str(item).strip()][:3]
                        if isinstance(legacy_highlights, list)
                        else [],
                        "created_at": str(source.get("last_updated", "")).strip(),
                        "trigger_source": "legacy",
                    }
                )
                changed = True
        latest = entries[-1] if entries else {}
        normalized = {
            "summary": str(latest.get("summary", "")),
            "covered_message_count": len(entries),
            "highlights": list(latest.get("highlights", [])),
            "last_updated": str(source.get("last_updated", latest.get("created_at", ""))),
            "summaries": entries,
        }
        return normalized, changed or source != normalized

    # 读取配置片段，缺失时返回安全默认配置。
    def _config(self) -> dict[str, Any]:
        """读取配置片段，缺失时返回安全默认配置。"""
        if self.config_path is None:
            return {}
        fallback = self.fallback_config_path or self.config_path
        return load_json_prefer_primary(self.config_path, fallback, {})

    # 读取预算配置，返回当前流程使用的限制值。
    def _budget(self) -> dict[str, int]:
        """读取预算配置，返回当前流程使用的限制值。"""
        return read_context_budget(self._config())

    # 根据 memory_updates 把记忆 updates to mem 0写入持久化存储并保持数据可恢复。
    def _write_memory_updates_to_mem0(self, memory_updates: dict[str, Any]) -> None:
        """根据 memory_updates 把记忆 updates to mem 0写入持久化存储并保持数据可恢复。"""
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
                logger.warning("Failed to shadow-write memory update to Mem0: %s", safe_exception(exc))

    # 根据 value 遍历嵌套数据中的文本项，过滤空值后逐条返回。
    def _iter_memory_texts(self, value: Any) -> list[str]:
        """根据 value 遍历嵌套数据中的文本项，过滤空值后逐条返回。"""
        texts: list[str] = []

        # 根据 node 整理visit，并把结果交给调用方或写回状态。
        def visit(node: Any) -> None:
            """根据 node 整理visit，并把结果交给调用方或写回状态。"""
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

    # 根据 value 判断记忆update文本是否满足条件并返回布尔结果。
    def _has_memory_update_text(self, value: Any) -> bool:
        """根据 value 判断记忆update文本是否满足条件并返回布尔结果。"""
        return bool(self._iter_memory_texts(value))

    # 根据正式问答开关返回当前摘要写入模式。
    def _summary_mode(self) -> str:
        """根据正式问答开关返回当前摘要写入模式。"""
        name = self.summary_path.name.lower()
        if "informal" in name:
            return "informal"
        if "formal" in name:
            return "formal"
        return "unknown"

    # 根据 history、trigger_rounds、covered_count 判断summarize是否满足条件并返回布尔结果。
    def _should_summarize(
        self,
        history: list[dict[str, Any]],
        trigger_rounds: int,
    ) -> bool:
        """根据 history、trigger_rounds、covered_count 判断summarize是否满足条件并返回布尔结果。"""
        trigger_rounds = max(1, int(trigger_rounds))
        total_user_rounds = self._count_user_messages(history)
        if total_user_rounds < trigger_rounds:
            return False
        return total_user_rounds >= trigger_rounds

    # 统计历史消息中的用户发言数量。
    def _count_user_messages(self, history: list[dict[str, Any]]) -> int:
        """统计历史消息中的用户发言数量。"""
        return len([item for item in history if item.get("role") == "user"])

    # 只有存在非空用户消息时才允许摘要和记忆更新。
    def _has_summarizable_history(self, history: list[dict[str, Any]]) -> bool:
        """只有存在非空用户消息时才允许摘要和记忆更新。"""
        return any(
            item.get("role") == "user" and str(item.get("content", "")).strip()
            for item in history
        )

    # 根据 history 压缩聊天历史，生成摘要与可合并的记忆更新。
    def _summarize_history(self, history: list[dict[str, Any]]) -> dict[str, Any]:
        """根据 history 压缩聊天历史，生成摘要与可合并的记忆更新。"""
        if not self.deepseek_client.is_configured():
            return self._local_summary(history)

        summary_payload = self._model_summary(history)
        if summary_payload is None:
            return self._local_summary(history)

        return summary_payload

    # 根据 history 请求模型生成摘要 JSON，失败时交给本地兜底。
    def _model_summary(self, history: list[dict[str, Any]]) -> dict[str, Any] | None:
        """根据 history 请求模型生成摘要 JSON，失败时交给本地兜底。"""
        try:
            content = self.deepseek_client.chat(self._summary_messages(history))
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                budget = self._budget()
                return {
                    "summary": clip_text(str(parsed.get("summary", "")).strip(), budget["max_summary_chars"]),
                    "highlights": [
                        clip_text(item, 120)
                        for item in self._string_list(parsed.get("highlights", []))[:3]
                    ],
                }
        except (DeepSeekError, json.JSONDecodeError) as exc:
            logger.warning("Falling back to local summary after model failure: %s", safe_exception(exc))
        return None

    # 仅从用户消息中提取记忆信息。
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
            logger.warning("Falling back to local memory extraction after model failure: %s", safe_exception(exc))

        return self._extract_memory(self._cap_user_messages(user_history, self._budget()["memory_extract_max_input_chars"]))

    # 从最近对话构建模型摘要输入，保留角色信息以便模型区分用户和助手发言。
    def _summary_messages(self, history: list[dict[str, Any]]) -> list[dict[str, str]]:
        """从最近对话构建模型摘要输入，保留角色信息以便模型区分用户和助手发言。"""
        transcript = self._build_transcript(
            history,
            char_budget=self._budget()["summary_max_input_chars"],
            role_prefix="role",
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

    # 仅从用户消息中构建记忆提取输入。
    def _memory_messages(self, history: list[dict[str, Any]]) -> list[dict[str, str]]:
        """仅从用户消息中构建记忆提取输入。"""
        transcript = self._build_transcript(
            history,
            char_budget=self._budget()["memory_extract_max_input_chars"],
            role_prefix="user_only",
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
                    "如果用户明确表达“不用频繁确认”“直接给方案”“不要像数据库工具”，"
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

    # 在没有模型可用时，根据最近对话生成简化本地摘要。
    def _local_summary(self, history: list[dict[str, Any]]) -> dict[str, Any]:
        """在没有模型可用时，根据最近对话生成简化本地摘要。"""
        budget = self._budget()
        recent = self._cap_messages(history, budget["summary_max_input_chars"])
        summary_lines = [
            f"{item.get('role', 'user')}: {item.get('content', '')}" for item in recent if item.get("content")
        ]
        summary = " | ".join(summary_lines[-6:])
        return {
            "summary": clip_text(summary, budget["max_summary_chars"]),
            "highlights": [clip_text(item.get("content", ""), 80) for item in recent[-3:]],
        }

    # 从用户最近几轮消息里提取可保存的偏好和学习工作信息。
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
                study_topics.append(clip_text(text, 60))
            if "喜欢" in text:
                preferences.append(clip_text(text, 50))
            if re.search(r"(项目|需求|实现|代码)", text):
                projects.append(clip_text(text, 60))
            if re.search(r"(学习|复习|知识|课程|算法|请问|怎么做|如何实现|如何|怎么|是什么|为什么|区别)", text):
                study_topics.append(clip_text(text, 60))
            if re.search(r"(简短|直接|详细|慢一点)", text):
                styles.append(clip_text(text, 40))
            if re.search(r"(我叫|我是|今天|最近)", text):
                personal_notes.append(clip_text(text, 60))
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

    # 根据 history、char_budget、role_prefix 组装transcript对象或消息并返回给调用方。
    def _build_transcript(
        self,
        history: list[dict[str, Any]],
        char_budget: int,
        role_prefix: str,
    ) -> str:
        """根据 history、char_budget、role_prefix 组装transcript对象或消息并返回给调用方。"""
        messages = self._cap_messages(history, char_budget)
        lines: list[str] = []
        for item in messages:
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            if role_prefix == "user_only":
                lines.append(f"user: {content}")
            else:
                lines.append(f"{item.get('role', 'user')}: {content}")
        return clip_text("\n".join(lines), char_budget)

    # 根据 history、char_budget 限制消息数量和长度，返回符合预算的消息列表。
    def _cap_messages(self, history: list[dict[str, Any]], char_budget: int) -> list[dict[str, Any]]:
        """根据 history、char_budget 限制消息数量和长度，返回符合预算的消息列表。"""
        kept: list[dict[str, Any]] = []
        used = 0
        per_message_limit = self._budget()["max_history_message_chars"]
        for item in reversed(history):
            content = clip_text(item.get("content", ""), per_message_limit)
            if not content:
                continue
            role = str(item.get("role", "user"))
            line = f"{role}: {content}"
            if used + len(line) > char_budget:
                remaining = char_budget - used
                if remaining > len(role) + 10:
                    clipped = clip_text(content, max(1, remaining - len(role) - 2))
                    if clipped:
                        kept.append({**item, "content": clipped})
                break
            kept.append({**item, "content": content})
            used += len(line)
        kept.reverse()
        return kept

    # 根据 history、char_budget 限制消息数量和长度，返回符合预算的消息列表。
    def _cap_user_messages(self, history: list[dict[str, Any]], char_budget: int) -> list[dict[str, Any]]:
        """根据 history、char_budget 限制消息数量和长度，返回符合预算的消息列表。"""
        users = self._user_history(history)
        return self._cap_messages(users, char_budget)

    # 仅返回非空的用户消息。
    def _user_history(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """仅返回非空的用户消息。"""
        return [
            item
            for item in history
            if item.get("role") == "user" and str(item.get("content", "")).strip()
        ]

    # 标准化记忆更新数据。
    def _normalize_memory_updates(self, payload: dict[str, Any]) -> dict[str, Any]:
        """标准化记忆更新数据。"""
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

    # 把关系记忆更新规范为固定分区和列表结构。
    def _normalize_relationship_memory_updates(self, value: Any) -> dict[str, Any]:
        """把关系记忆更新规范为固定分区和列表结构。"""
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

    # 处理记忆数据，保持本地记忆和外部索引一致。
    def _empty_relationship_memory_update(self) -> dict[str, Any]:
        """处理记忆数据，保持本地记忆和外部索引一致。"""
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

    # 根据 text、relationship_memory 处理记忆数据，保持本地记忆和外部索引一致。
    def _extract_relationship_memory_from_text(
        self, text: str, relationship_memory: dict[str, Any]
    ) -> None:
        """根据 text、relationship_memory 处理记忆数据，保持本地记忆和外部索引一致。"""
        stripped = text.strip()
        if not stripped:
            return
        evidence = clip_text(stripped, 80)
        communication = relationship_memory["communication_style"]
        companionship = relationship_memory["companionship_style"]

        if re.search(r"((不要|别|不用|不需要).{0,8}(确认|问我)|别总是问|不要总是问)", stripped):
            communication["confirmation_preference"] = "avoid_unnecessary_confirmation"
            self._append_unique(communication["evidence"], evidence)
        if re.search(r"(直接给|直接.*方案|给我可执行|可执行方案|可执行的)", stripped):
            communication["preferred_response_style"] = "direct_actionable"
            self._append_unique(communication["evidence"], evidence)
        if re.search(r"(详细一点|尽可能详细|写得完整|完整一点|展开一点)", stripped):
            communication["detail_level"] = "high"
            self._append_unique(communication["evidence"], evidence)
        if re.search(r"(数据库|数据存储器|机械化记忆|机械.*记忆|不像陪伴|像工具)", stripped):
            self._append_unique(communication["avoid_styles"], "避免机械化记忆表达")
            self._append_unique(companionship["avoid_behaviors"], "像数据存储器一样说话")
            self._append_unique(communication["evidence"], evidence)
            self._append_unique(companionship["evidence"], evidence)

    # 根据 items、value 把unique加入当前状态或持久化记录。
    def _append_unique(self, items: list[str], value: str) -> None:
        """根据 items、value 把unique加入当前状态或持久化记录。"""
        if value and value not in items:
            items.append(value)

    # 将任意输入标准化为去重的非空字符串列表。
    def _string_list(self, value: Any) -> list[str]:
        """将任意输入标准化为去重的非空字符串列表。"""
        if not isinstance(value, list):
            return []

        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in normalized:
                normalized.append(clip_text(text, 120))
        return normalized

    # 根据 value 提取文本值并去除空白，无法使用时返回空字符串。
    def _string_value(self, value: Any) -> str:
        """根据 value 提取文本值并去除空白，无法使用时返回空字符串。"""
        return clip_text(value, 120) if value not in (None, "") else ""
