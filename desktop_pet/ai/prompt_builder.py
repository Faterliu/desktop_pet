from __future__ import annotations

from pathlib import Path
from typing import Any

from storage.json_store import load_json
from storage.memory_store import DEFAULT_MEMORY, normalize_memory_schema


DEFAULT_CHARACTER = {
    "name": "小胡",
    "role": "可爱温柔的桌面小伙伴",
    "personality": ["可爱", "温柔", "安静陪伴"],
    "speaking_style": {
        "daily_chat": "默认回复 2-3 句话，简短、自然、温柔。",
        "knowledge_answer": "知识回答可以适度展开。",
        "catchphrases": ["我在这里哦。"],
    },
    "custom_prompt": "",
}

DEFAULT_SAFETY = {
    "rules": [
        "不要生成成人内容。",
        "不要提供危险、违法或自我伤害的具体指导。",
        "不要冒充真实人类。",
    ]
}

DEFAULT_SUMMARY = {
    "summary": "",
    "highlights": [],
}


class PromptBuilder:
    def __init__(
        self,
        character_path: str | Path,
        safety_path: str | Path,
        memory_path: str | Path,
        summary_path_formal: str | Path,
        summary_path_informal: str | Path,
    ) -> None:
        """初始化提示词构建器，并绑定角色、安全、记忆与正式/非正式摘要配置。"""
        self.character_path = Path(character_path)
        self.safety_path = Path(safety_path)
        self.memory_path = Path(memory_path)
        self.summary_path_formal = Path(summary_path_formal)
        self.summary_path_informal = Path(summary_path_informal)

    def build_messages(
        self,
        user_message: str,
        recent_messages: list[dict[str, Any]] | None = None,
        formal_qa_mode: bool = False,
        relevant_memories: str | None = None,
    ) -> list[dict[str, str]]:
        """组装发送给模型的完整 messages 列表。"""
        character = load_json(self.character_path, DEFAULT_CHARACTER)
        safety = load_json(self.safety_path, DEFAULT_SAFETY)
        memory = normalize_memory_schema(load_json(self.memory_path, DEFAULT_MEMORY))
        summary_path = self.summary_path_formal if formal_qa_mode else self.summary_path_informal
        summary = load_json(summary_path, DEFAULT_SUMMARY)

        safety_rules = "\n".join(f"- {rule}" for rule in safety.get("rules", []))
        personality = "、".join(character.get("personality", []))
        speaking = character.get("speaking_style", {})
        catchphrases = " / ".join(speaking.get("catchphrases", []))
        fact_memory_text = self._format_fact_memory(memory)
        relationship_memory_text = self._format_relationship_memory(memory, formal_qa_mode)
        semantic_memory_text = self._format_relevant_semantic_memories(relevant_memories)
        summary_text = summary.get("summary", "").strip()

        system_messages = [
            {
                "role": "system",
                "content": (
                    "你必须优先遵守以下安全规则：\n"
                    f"{safety_rules}\n"
                    "如果用户请求可能有风险，请温柔拒绝并提供更安全的替代建议。"
                ),
            },
            {
                "role": "system",
                "content": (
                    f"你是{character.get('name', '小胡')}，角色定位是{character.get('role', '桌面陪伴小伙伴')}。"
                    f"你的性格关键词：{personality}。\n"
                    f"日常聊天风格：{speaking.get('daily_chat', '')}\n"
                    f"知识问答风格：{speaking.get('knowledge_answer', '')}\n"
                    f"常用口头禅：{catchphrases}\n"
                    "保持自然、温柔、可爱，不要太啰嗦，也不要像客服。"
                ),
            },
        ]

        custom_prompt = str(character.get("custom_prompt", "")).strip()
        if custom_prompt:
            system_messages.append({"role": "system", "content": custom_prompt})

        system_messages.append(
            {
                "role": "system",
                "content": self._format_mode_guidance(formal_qa_mode),
            }
        )

        if fact_memory_text:
            system_messages.append(
                {
                    "role": "system",
                    "content": (
                        "【用户事实记忆】\n"
                        "以下信息用于理解用户的长期项目、偏好和背景。"
                        "回答时可以自然参考，但不要机械复述。\n"
                        f"{fact_memory_text}"
                    ),
                }
            )
        if relationship_memory_text:
            system_messages.append(
                {
                    "role": "system",
                    "content": (
                        "【相处方式记忆】\n"
                        "以下信息用于调整你的语气、详细程度和陪伴方式，"
                        "不要直接复述给用户。\n"
                        f"{relationship_memory_text}"
                    ),
                }
            )

        if semantic_memory_text:
            system_messages.append(
                {
                    "role": "system",
                    "content": (
                        "【当前问题相关的长期语义记忆】\n"
                        "以下内容由长期语义记忆检索得到，"
                        "只在与当前问题直接相关时参考。不要机械复述，也不要强行使用。\n"
                        f"{semantic_memory_text}"
                    ),
                }
            )

        if fact_memory_text or relationship_memory_text or semantic_memory_text:
            system_messages.append(
                {
                    "role": "system",
                    "content": self._format_memory_guidelines(formal_qa_mode),
                }
            )

        if summary_text:
            system_messages.append(
                {"role": "system", "content": f"以下是之前对话摘要，请按需参考：\n{summary_text}"}
            )

        conversation_messages = [
            {"role": item.get("role", "user"), "content": str(item.get("content", ""))}
            for item in (recent_messages or [])
            if item.get("content")
        ]
        conversation_messages.append({"role": "user", "content": user_message})
        return system_messages + conversation_messages

    def _format_mode_guidance(self, formal_qa_mode: bool) -> str:
        if formal_qa_mode:
            return (
                "当前处于正式问答模式。请优先保证回答准确、结构清晰、可执行。"
                "可以参考用户事实记忆理解项目背景；相处方式记忆只用于调整结构、"
                "详细程度和确认频率。减少闲聊和陪伴式铺垫。"
            )
        return (
            "当前是普通陪伴聊天模式。请让记忆自然影响你的理解、语气和建议，"
            "但不要机械说明你记得什么。除非用户主动询问，否则不要提及记忆系统。"
        )

    def _format_fact_memory(self, memory: dict[str, Any]) -> str:
        """Format factual memory separately from style guidance."""
        fragments: list[str] = []
        user_profile = memory.get("user_profile", {})
        work_study = memory.get("work_study", {})
        self._append_memory_items(fragments, "用户偏好", user_profile.get("preferences", []))
        self._append_memory_items(
            fragments, "个人备注", user_profile.get("important_personal_notes", [])
        )
        self._append_memory_items(
            fragments, "近期学习", work_study.get("current_learning_topics", [])
        )
        self._append_memory_items(fragments, "当前项目", work_study.get("current_projects", []))
        self._append_memory_items(fragments, "有用上下文", work_study.get("useful_context", []))
        self._append_legacy_preferences(fragments, memory.get("preferences"))
        return "\n".join(f"- {item}" for item in fragments[:8])

    def _format_relationship_memory(
        self, memory: dict[str, Any], formal_qa_mode: bool
    ) -> str:
        fragments: list[str] = []
        relationship = memory.get("relationship_memory", {})
        communication = relationship.get("communication_style", {})
        companionship = relationship.get("companionship_style", {})
        interaction = relationship.get("interaction_patterns", {})
        user_profile = memory.get("user_profile", {})

        if isinstance(user_profile, dict):
            self._append_memory_items(
                fragments, "历史沟通风格", user_profile.get("communication_style", [])
            )
        if isinstance(communication, dict):
            self._append_scalar(
                fragments, "偏好回复方式", communication.get("preferred_response_style")
            )
            self._append_scalar(fragments, "详细程度", communication.get("detail_level"))
            self._append_scalar(
                fragments, "确认偏好", communication.get("confirmation_preference")
            )
            self._append_scalar(fragments, "语气偏好", communication.get("tone_preference"))
            self._append_memory_items(fragments, "避免表达风格", communication.get("avoid_styles", []))

        if not formal_qa_mode:
            if isinstance(companionship, dict):
                self._append_scalar(
                    fragments, "陪伴角色", companionship.get("preferred_companion_role")
                )
                self._append_scalar(
                    fragments, "主动边界", companionship.get("proactive_boundary")
                )
                self._append_scalar(
                    fragments, "鼓励方式", companionship.get("encouragement_style")
                )
                self._append_scalar(
                    fragments, "称呼偏好", companionship.get("addressing_preference")
                )
                self._append_memory_items(
                    fragments, "避免陪伴行为", companionship.get("avoid_behaviors", [])
                )
            if isinstance(interaction, dict):
                self._append_memory_items(fragments, "近期任务关注", interaction.get("task_focus", []))
                self._append_scalar(
                    fragments, "近期互动模式", interaction.get("recent_interaction_mode")
                )
                self._append_scalar(
                    fragments, "打扰容忍度", interaction.get("interruption_tolerance")
                )
                self._append_scalar(
                    fragments,
                    "主动问候回应",
                    interaction.get("response_to_proactive_greetings"),
                )

        return "\n".join(f"- {item}" for item in fragments[:8])

    def _format_relevant_semantic_memories(self, relevant_memories: str | None) -> str:
        if not relevant_memories:
            return ""
        lines = [
            self._clip_text(line.strip())
            for line in str(relevant_memories).splitlines()
            if line.strip()
        ]
        return "\n".join(lines[:8])

    def _format_memory_guidelines(self, formal_qa_mode: bool) -> str:
        mode_line = (
            "- 正式问答模式下，风格记忆只用于让回答更清晰、直接、结构化。"
            if formal_qa_mode
            else "- 普通聊天模式下，可以让记忆自然影响陪伴语气，但不要像读档案。"
        )
        return (
            "【表达约束】\n"
            "- 记忆主要用于理解用户，不要把用户偏好列表复述出来。\n"
            "- 不要频繁使用“你之前说过”。\n"
            "- 不要暴露记忆系统、memory.json、Mem0、数据库等技术细节，"
            "除非用户正在讨论项目实现。\n"
            "- 如果记忆与当前问题无关，不要强行使用。\n"
            "- 如果用户当前表达与旧记忆冲突，以当前表达为准。\n"
            f"{mode_line}"
        )

    def _append_memory_items(self, fragments: list[str], label: str, value: Any) -> None:
        items = self._string_items(value)
        if items:
            fragments.append(f"{label}：" + "、".join(items[:3]))

    def _append_scalar(self, fragments: list[str], label: str, value: Any) -> None:
        text = self._string_value(value)
        if text:
            fragments.append(f"{label}：{text}")

    def _append_legacy_preferences(self, fragments: list[str], value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                items = self._string_items(item)
                if items:
                    fragments.append(f"旧版偏好 {key}：" + "、".join(items[:3]))
        else:
            self._append_memory_items(fragments, "旧版偏好", value)

    def _string_items(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [self._clip_text(str(item).strip()) for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [self._clip_text(value.strip())]
        return []

    def _string_value(self, value: Any) -> str:
        if value in (None, ""):
            return ""
        return self._clip_text(str(value).strip())

    def _clip_text(self, text: str, limit: int = 80) -> str:
        text = text.strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1] + "..."
