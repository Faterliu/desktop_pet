from __future__ import annotations

from pathlib import Path
from typing import Any

from storage.json_store import load_json


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

DEFAULT_MEMORY = {
    "user_profile": {
        "preferences": [],
        "communication_style": [],
        "important_personal_notes": [],
    },
    "work_study": {
        "current_learning_topics": [],
        "current_projects": [],
        "useful_context": [],
    },
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
        memory = load_json(self.memory_path, DEFAULT_MEMORY)
        summary_path = self.summary_path_formal if formal_qa_mode else self.summary_path_informal
        summary = load_json(summary_path, DEFAULT_SUMMARY)

        safety_rules = "\n".join(f"- {rule}" for rule in safety.get("rules", []))
        personality = "、".join(character.get("personality", []))
        speaking = character.get("speaking_style", {})
        catchphrases = " / ".join(speaking.get("catchphrases", []))
        memory_text = self._memory_text(memory)
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

        if summary_text:
            system_messages.append(
                {"role": "system", "content": f"以下是之前对话摘要，请按需参考：\n{summary_text}"}
            )
        if memory_text:
            system_messages.append(
                {"role": "system", "content": f"以下是你记得的用户信息，请自然参考：\n{memory_text}"}
            )

        if relevant_memories:
            system_messages.append(
                {
                    "role": "system",
                    "content": (
                        "以下是与当前用户输入相关的长期记忆，仅在有帮助时自然参考：\n"
                        f"{relevant_memories}\n\n"
                        "使用这些长期记忆时必须遵守：\n"
                        "- 不要向用户暴露记忆系统、Mem0、JSON、数据库等实现细节。\n"
                        "- 不要频繁说“我记得”。\n"
                        "- 如果长期记忆与用户当前表达冲突，以用户当前表达为准。\n"
                        "- 涉及敏感内容时，不要主动展开；只有用户当前主动提到时才谨慎参考。\n"
                    ),
                }
            )

        if formal_qa_mode:
            system_messages.append(
                {
                    "role": "system",
                    "content": (
                        "当前开启正式问答模式。"
                        "对于用户的问题，请优先给出完整、清晰、有条理的回答，"
                        "不要刻意压缩成两三句；必要时可以分点说明、补充步骤或例子，"
                        "但仍然保持温柔自然。"
                    ),
                }
            )

        conversation_messages = [
            {"role": item.get("role", "user"), "content": str(item.get("content", ""))}
            for item in (recent_messages or [])
            if item.get("content")
        ]
        conversation_messages.append({"role": "user", "content": user_message})
        return system_messages + conversation_messages

    def _memory_text(self, memory: dict[str, Any]) -> str:
        """把结构化记忆整理成可注入提示词的自然语言片段。"""
        fragments: list[str] = []
        user_profile = memory.get("user_profile", {})
        work_study = memory.get("work_study", {})
        if user_profile.get("preferences"):
            fragments.append("用户偏好：" + "、".join(user_profile["preferences"]))
        if user_profile.get("communication_style"):
            fragments.append("沟通风格：" + "、".join(user_profile["communication_style"]))
        if user_profile.get("important_personal_notes"):
            fragments.append("个人备注：" + "、".join(user_profile["important_personal_notes"]))
        if work_study.get("current_learning_topics"):
            fragments.append("近期学习：" + "、".join(work_study["current_learning_topics"]))
        if work_study.get("current_projects"):
            fragments.append("当前项目：" + "、".join(work_study["current_projects"]))
        if work_study.get("useful_context"):
            fragments.append("有用上下文：" + "、".join(work_study["useful_context"]))
        return "\n".join(fragments)
