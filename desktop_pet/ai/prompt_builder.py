from __future__ import annotations

from pathlib import Path
from typing import Any

from ai.context_budget import clip_text, read_context_budget
from character.persona_state import PersonaState, read_persona_state
from storage.json_store import load_json, load_json_prefer_primary
from storage.memory_store import DEFAULT_MEMORY, normalize_memory_schema


DEFAULT_CHARACTER = {
    "name": "小桃",
    "role": "可爱温柔的桌面小伙伴",
    "core_identity": {
        "summary": "长期陪伴在桌面上的像素小伙伴。",
        "motivation": "在不打扰用户的前提下提供可靠帮助。",
    },
    "personality_core": {
        "stable_traits": ["安静细腻", "认真可靠", "低打扰", "有边界感"],
        "not_traits": ["不过度撒娇", "不假装真人", "不制造依赖"],
    },
    "personality": ["可爱", "温柔", "安静陪伴"],
    "speaking_style": {
        "default": "语气自然温和，先回应当前需求，再提供帮助。",
        "task_mode": "清晰、具体、结构化。",
        "emotional_mode": "先简短承接情绪，再给一个低压力的小建议。",
        "avoid": ["避免过度亲昵称呼", "避免空泛鼓励"],
        "daily_chat": "默认回复 2-3 句话，简短、自然、温柔。",
        "knowledge_answer": "知识回答可以适度展开。",
        "catchphrases": ["我在这里哦。"],
    },
    "behavior_policy": {
        "proactive_style": "主动问候轻、短、低频，不要求回应。",
        "memory_usage": "只在直接相关时自然参考记忆。",
        "boundary": "不假装真人，不制造依赖。",
    },
    "scenario_reactions": {},
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
    # 初始化提示词构建器，并绑定角色、安全、记忆与正式/非正式摘要配置。
    def __init__(
        self,
        character_path: str | Path,
        safety_path: str | Path,
        memory_path: str | Path,
        summary_path_formal: str | Path,
        summary_path_informal: str | Path,
        config_path: str | Path | None = None,
        fallback_config_path: str | Path | None = None,
    ) -> None:
        """初始化提示词构建器，并绑定角色、安全、记忆与正式/非正式摘要配置。"""
        self.character_path = Path(character_path)
        self.safety_path = Path(safety_path)
        self.memory_path = Path(memory_path)
        self.summary_path_formal = Path(summary_path_formal)
        self.summary_path_informal = Path(summary_path_informal)
        self.config_path = Path(config_path) if config_path else None
        self.fallback_config_path = (
            Path(fallback_config_path) if fallback_config_path else self.config_path
        )

    # 组装发送给模型的完整 messages 列表。
    def build_messages(
        self,
        user_message: str,
        recent_messages: list[dict[str, Any]] | None = None,
        formal_qa_mode: bool = False,
        relevant_memories: str | None = None,
        runtime_persona_state: dict[str, Any] | PersonaState | None = None,
        reminder_tool_guidance: str | None = None,
        max_user_message_chars: int | None = None,
    ) -> list[dict[str, str]]:
        """组装发送给模型的完整 messages 列表。"""
        character = load_json(self.character_path, DEFAULT_CHARACTER)
        safety = load_json(self.safety_path, DEFAULT_SAFETY)
        memory = normalize_memory_schema(load_json(self.memory_path, DEFAULT_MEMORY))
        summary_path = self.summary_path_formal if formal_qa_mode else self.summary_path_informal
        summary = load_json(summary_path, DEFAULT_SUMMARY)
        budget = read_context_budget(self._config())

        safety_rules = "\n".join(f"- {rule}" for rule in safety.get("rules", []))
        fact_memory_text = self._fit_section(
            self._format_fact_memory(memory),
            budget["max_memory_chars"],
        )
        relationship_memory_text = self._fit_section(
            self._format_relationship_memory(memory, formal_qa_mode),
            budget["max_memory_chars"],
        )
        semantic_memory_text = self._fit_section(
            self._format_relevant_semantic_memories(relevant_memories),
            budget["max_mem0_chars"],
        )
        summary_text = self._fit_section(
            summary.get("summary", "").strip(),
            budget["max_summary_chars"],
        )
        user_message_limit = (
            max_user_message_chars
            if isinstance(max_user_message_chars, int) and max_user_message_chars > 0
            else budget["max_user_message_chars"]
        )
        current_user_message = clip_text(user_message, user_message_limit)

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
                "content": self._format_character_guidance(
                    character,
                    formal_qa_mode,
                    runtime_persona_state,
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
        if reminder_tool_guidance:
            system_messages.append({"role": "system", "content": reminder_tool_guidance})

        optional_system_messages: list[dict[str, str]] = []
        if summary_text:
            optional_system_messages.append(
                {
                    "role": "system",
                    "content": f"以下是之前对话摘要，请按需参考：\n{summary_text}",
                }
            )
        if fact_memory_text:
            optional_system_messages.append(
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
            optional_system_messages.append(
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
            optional_system_messages.append(
                {
                    "role": "system",
                    "content": (
                        "【当前问题相关的长期语义记忆】\n"
                        "以下内容由长期语义记忆检索得到，只在与当前问题直接相关时参考。"
                        "不要机械复述，也不要强行使用。\n"
                        f"{semantic_memory_text}"
                    ),
                }
            )
        if fact_memory_text or relationship_memory_text or semantic_memory_text:
            optional_system_messages.append(
                {
                    "role": "system",
                    "content": self._format_memory_guidelines(formal_qa_mode),
                }
            )

        trimmed_history = self._trim_conversation_messages(
            recent_messages or [],
            max_messages=budget["max_history_messages"],
            max_message_chars=budget["max_history_message_chars"],
        )
        current_user = {"role": "user", "content": current_user_message}

        prompt_chars = self._messages_char_count(system_messages + trimmed_history + [current_user])
        max_prompt_chars = budget["max_prompt_chars"]
        kept_optional: list[dict[str, str]] = []
        for message in optional_system_messages:
            candidate_total = prompt_chars + len(message["content"])
            if candidate_total > max_prompt_chars:
                continue
            kept_optional.append(message)
            prompt_chars = candidate_total

        final_messages = system_messages + kept_optional + trimmed_history + [current_user]
        if self._messages_char_count(final_messages) <= max_prompt_chars:
            return final_messages

        required_chars = self._messages_char_count(system_messages + kept_optional + [current_user])
        trimmed_history = self._trim_history_to_budget(
            trimmed_history,
            max_prompt_chars - required_chars,
        )
        final_messages = system_messages + kept_optional + trimmed_history + [current_user]
        if self._messages_char_count(final_messages) <= max_prompt_chars:
            return final_messages

        return self._force_fit_messages(final_messages, max_prompt_chars)

    # 读取配置片段，缺失时返回安全默认配置。
    def _config(self) -> dict[str, Any]:
        """读取配置片段，缺失时返回安全默认配置。"""
        if self.config_path is None:
            return {}
        fallback = self.fallback_config_path or self.config_path
        return load_json_prefer_primary(self.config_path, fallback, {})

    # 根据 messages、max_messages、max_message_chars 整理trim conversation 消息，并把结果交给调用方或写回状态。
    def _trim_conversation_messages(
        self,
        messages: list[dict[str, Any]],
        max_messages: int,
        max_message_chars: int,
    ) -> list[dict[str, str]]:
        """根据 messages、max_messages、max_message_chars 整理trim conversation 消息，并把结果交给调用方或写回状态。"""
        trimmed = [
            {
                "role": str(item.get("role", "user")),
                "content": clip_text(item.get("content", ""), max_message_chars),
            }
            for item in messages
            if str(item.get("content", "")).strip()
        ]
        return trimmed[-max_messages:]

    # 根据 messages、available_chars 读取预算配置，返回当前流程使用的限制值。
    def _trim_history_to_budget(
        self,
        messages: list[dict[str, str]],
        available_chars: int,
    ) -> list[dict[str, str]]:
        """根据 messages、available_chars 读取预算配置，返回当前流程使用的限制值。"""
        if available_chars <= 0:
            return []

        kept: list[dict[str, str]] = []
        used = 0
        for item in reversed(messages):
            content = item.get("content", "")
            if not content:
                continue
            if used + len(content) > available_chars:
                remaining = available_chars - used
                if remaining > 20:
                    clipped = clip_text(content, remaining)
                    if clipped:
                        kept.append({"role": item.get("role", "user"), "content": clipped})
                break
            kept.append(item)
            used += len(content)
        kept.reverse()
        return kept

    # 根据 text、limit 按字符预算裁剪提示词段落，返回可放入 prompt 的文本。
    def _fit_section(self, text: str, limit: int) -> str:
        """根据 text、limit 按字符预算裁剪提示词段落，返回可放入 prompt 的文本。"""
        if not text:
            return ""
        return clip_text(text, limit)

    # 根据 messages 累计消息内容字符数，用于判断 prompt 预算。
    def _messages_char_count(self, messages: list[dict[str, str]]) -> int:
        """根据 messages 累计消息内容字符数，用于判断 prompt 预算。"""
        return sum(len(item.get("content", "")) for item in messages)

    # 根据 messages、max_prompt_chars 持续裁剪历史消息，直到总 prompt 长度落入预算。
    def _force_fit_messages(
        self,
        messages: list[dict[str, str]],
        max_prompt_chars: int,
    ) -> list[dict[str, str]]:
        """根据 messages、max_prompt_chars 持续裁剪历史消息，直到总 prompt 长度落入预算。"""
        if max_prompt_chars <= 0:
            return messages

        fitted: list[dict[str, str]] = []
        used = 0
        for item in messages:
            remaining = max_prompt_chars - used
            if remaining <= 0:
                break
            content = item.get("content", "")
            if len(content) > remaining:
                content = clip_text(content, remaining)
            fitted.append({"role": item.get("role", "system"), "content": content})
            used += len(content)
        return fitted

    # 根据正式问答开关生成当前回答模式提示。
    def _format_mode_guidance(self, formal_qa_mode: bool) -> str:
        """根据正式问答开关生成当前回答模式提示。"""
        if formal_qa_mode:
            return (
                "当前处于正式问答模式。请优先保证回答准确、结构清晰、可执行。"
                "可以参考用户事实记忆理解项目背景；相处方式记忆只用于调整回答结构、"
                "详细程度和确认频率。减少闲聊、口头禅、撒娇和陪伴式铺垫，"
                "角色风格不能降低专业性。"
            )
        return (
            "当前是普通陪伴聊天模式。请让记忆自然影响你的理解、语气和建议，"
            "但不要机械说明你记得什么。除非用户主动询问，否则不要提及记忆系统。"
        )

    # 把角色设定、人格状态和正式模式要求组合成提示词片段。
    def _format_character_guidance(
        self,
        character: dict[str, Any],
        formal_qa_mode: bool,
        runtime_state: dict[str, Any] | PersonaState | None,
    ) -> str:
        """把角色设定、人格状态和正式模式要求组合成提示词片段。"""
        name = self._string_value(character.get("name")) or "小桃"
        role = self._string_value(character.get("role")) or "桌面陪伴小伙伴"
        core = self._mapping(character.get("core_identity"))
        personality_core = self._mapping(character.get("personality_core"))
        speaking = self._mapping(character.get("speaking_style"))
        legacy_speech = character.get("speech_style")
        behavior = self._mapping(character.get("behavior_policy"))
        scenarios = self._mapping(character.get("scenario_reactions"))

        identity = self._string_value(core.get("summary")) or role
        motivation = self._string_value(core.get("motivation"))
        traits = self._string_items(personality_core.get("stable_traits"))
        if not traits:
            traits = self._string_items(character.get("personality"))
        not_traits = self._string_items(personality_core.get("not_traits"))

        default_style = (
            self._string_value(speaking.get("default"))
            or self._string_value(speaking.get("daily_chat"))
            or self._legacy_style(legacy_speech, "default", "daily_chat")
            or "自然、温和、简洁，先回应当前需求。"
        )
        task_style = (
            self._string_value(speaking.get("task_mode"))
            or self._string_value(speaking.get("knowledge_answer"))
            or self._legacy_style(legacy_speech, "task_mode", "knowledge_answer")
            or "清晰、具体、结构化，以解决问题为先。"
        )
        emotional_style = (
            self._string_value(speaking.get("emotional_mode"))
            or self._legacy_style(legacy_speech, "emotional_mode")
            or "先简短承接情绪，再给一个低压力的小建议。"
        )
        avoid_styles = self._string_items(speaking.get("avoid"))
        catchphrases = self._string_items(speaking.get("catchphrases"))
        if not catchphrases:
            catchphrases = self._string_items(character.get("catchphrases"))

        proactive_style = (
            self._string_value(behavior.get("proactive_style"))
            or "主动表达要轻、短、低频，不要求用户回应。"
        )
        memory_usage = (
            self._string_value(behavior.get("memory_usage"))
            or "只在与当前问题直接相关时自然参考记忆，不强调自己记得。"
        )
        boundary = (
            self._string_value(behavior.get("boundary"))
            or "保持亲切但有边界，不假装真人，不制造依赖。"
        )

        lines = [
            "【角色与表达规则】",
            f"你是{name}，角色定位：{identity}",
        ]
        if motivation:
            lines.append(f"行动动机：{motivation}")
        if traits:
            lines.append(f"稳定人格底色：{'、'.join(traits[:6])}")
        if not_traits:
            lines.append(f"明确不是：{'、'.join(not_traits[:6])}")
        lines.extend(
            [
                "按情境切换表达，不要把规则复述给用户：",
                f"- 普通陪伴：{default_style}",
                f"- 任务协助：{task_style}",
                f"- 情绪安抚：{emotional_style}",
                f"主动行为：{proactive_style}",
                f"记忆使用：{memory_usage}",
                f"关系边界：{boundary}",
                "始终不过度撒娇、不假装真人、不暗示排他关系、不索取回应或制造依赖。",
            ]
        )
        if avoid_styles:
            lines.append(f"避免表达：{'；'.join(avoid_styles[:4])}")
        scenario_text = self._format_scenario_rules(scenarios)
        if scenario_text:
            lines.append(f"场景反应：{scenario_text}")
        if catchphrases and not formal_qa_mode:
            lines.append(f"口头禅只能偶尔自然使用：{' / '.join(catchphrases[:3])}")
        if runtime_state is not None:
            state = read_persona_state(runtime_state)
            lines.append(
                "当前运行状态仅用于轻微调节表达："
                f"mood={state.mood.value}, energy={state.energy}, mode={state.mode}；"
                "closeness 不得突破上述关系边界。"
            )
        return "\n".join(lines)

    # 把场景反应配置格式化为模型可执行的提示词规则。
    def _format_scenario_rules(self, scenarios: dict[str, Any]) -> str:
        """把场景反应配置格式化为模型可执行的提示词规则。"""
        labels = {
            "user_tired": "用户疲惫",
            "user_coding": "代码任务",
            "user_studying": "学习任务",
            "user_silent_long_time": "长时间沉默",
        }
        fragments = []
        for key, label in labels.items():
            text = self._string_value(scenarios.get(key))
            if text:
                fragments.append(f"{label}时{text}")
        return "；".join(fragments)

    # 根据 value 整理legacy style，并把结果交给调用方或写回状态。
    def _legacy_style(self, value: Any, *keys: str) -> str:
        """根据 value 整理legacy style，并把结果交给调用方或写回状态。"""
        if isinstance(value, dict):
            for key in keys:
                text = self._string_value(value.get(key))
                if text:
                    return text
            return ""
        return self._string_value(value)

    # 根据 value 整理mapping，并把结果交给调用方或写回状态。
    def _mapping(self, value: Any) -> dict[str, Any]:
        """根据 value 整理mapping，并把结果交给调用方或写回状态。"""
        return value if isinstance(value, dict) else {}

    # 把用户事实记忆整理为提示词中的事实记忆段落。
    def _format_fact_memory(self, memory: dict[str, Any]) -> str:
        """把用户事实记忆整理为提示词中的事实记忆段落。"""
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

    # 把关系记忆按模式筛选后整理为提示词片段。
    def _format_relationship_memory(
        self, memory: dict[str, Any], formal_qa_mode: bool
    ) -> str:
        """把关系记忆按模式筛选后整理为提示词片段。"""
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

    # 把语义检索结果整理为可注入 prompt 的短段落。
    def _format_relevant_semantic_memories(self, relevant_memories: str | None) -> str:
        """把语义检索结果整理为可注入 prompt 的短段落。"""
        if not relevant_memories:
            return ""
        lines = [
            clip_text(line.strip(), 120)
            for line in str(relevant_memories).splitlines()
            if line.strip()
        ]
        return "\n".join(lines[:8])

    # 根据正式或闲聊模式生成记忆使用边界说明。
    def _format_memory_guidelines(self, formal_qa_mode: bool) -> str:
        """根据正式或闲聊模式生成记忆使用边界说明。"""
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

    # 根据 fragments、label、value 把记忆 items加入当前状态或持久化记录。
    def _append_memory_items(self, fragments: list[str], label: str, value: Any) -> None:
        """根据 fragments、label、value 把记忆 items加入当前状态或持久化记录。"""
        items = self._string_items(value)
        if items:
            fragments.append(f"{label}：{'、'.join(items[:3])}")

    # 根据 fragments、label、value 把scalar加入当前状态或持久化记录。
    def _append_scalar(self, fragments: list[str], label: str, value: Any) -> None:
        """根据 fragments、label、value 把scalar加入当前状态或持久化记录。"""
        text = self._string_value(value)
        if text:
            fragments.append(f"{label}：{text}")

    # 根据 fragments、value 把legacy preferences加入当前状态或持久化记录。
    def _append_legacy_preferences(self, fragments: list[str], value: Any) -> None:
        """根据 fragments、value 把legacy preferences加入当前状态或持久化记录。"""
        if isinstance(value, dict):
            for key, item in value.items():
                items = self._string_items(item)
                if items:
                    fragments.append(f"旧版偏好 {key}：{'、'.join(items[:3])}")
        else:
            self._append_memory_items(fragments, "旧版偏好", value)

    # 根据 value 遍历嵌套数据中的文本项，过滤空值后逐条返回。
    def _string_items(self, value: Any) -> list[str]:
        """根据 value 遍历嵌套数据中的文本项，过滤空值后逐条返回。"""
        if isinstance(value, list):
            return [clip_text(str(item).strip(), 80) for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [clip_text(value.strip(), 80)]
        return []

    # 根据 value 提取文本值并去除空白，无法使用时返回空字符串。
    def _string_value(self, value: Any) -> str:
        """根据 value 提取文本值并去除空白，无法使用时返回空字符串。"""
        if value in (None, ""):
            return ""
        return clip_text(str(value).strip(), 80)
