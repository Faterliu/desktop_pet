from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from character.emotion_state import EmotionState
from character.persona_state import PersonaState


_TIRED_PHRASES = (
    "好累",
    "很累",
    "累死",
    "疲惫",
    "困了",
    "好困",
    "很困",
    "想睡",
    "没精神",
    "精疲力尽",
    "tired",
    "sleepy",
    "exhausted",
)

_DISTRESS_PHRASES = (
    "焦虑",
    "难过",
    "伤心",
    "低落",
    "烦躁",
    "崩溃",
    "压力很大",
    "好烦",
    "很烦",
    "沮丧",
    "绝望",
    "anxious",
    "sad",
    "upset",
    "stressed",
    "depressed",
)

_TASK_PHRASES = (
    "bug",
    "报错",
    "错误",
    "代码",
    "实现",
    "怎么",
    "如何",
    "为什么",
    "帮我",
    "分析",
    "解释",
    "修复",
    "测试",
    "项目",
    "论文",
    "学习",
    "考试",
    "整理",
    "翻译",
    "总结",
    "写一个",
    "写个",
    "请问",
    "error",
    "exception",
    "traceback",
)

_POSITIVE_PHRASES = (
    "终于成功",
    "成功了",
    "搞定了",
    "完成了",
    "太好了",
    "好开心",
    "开心",
    "通过了",
    "解决了",
    "真棒",
    "great",
    "awesome",
    "worked",
    "passed",
)

_GREETING_PHRASES = (
    "你好",
    "嗨",
    "在吗",
    "早上好",
    "中午好",
    "下午好",
    "晚上好",
    "谢谢",
    "感谢",
    "辛苦了",
    "hello",
    "hi",
    "hey",
    "thanks",
    "thank you",
)

_FRIENDLY_PHRASES = (
    "喜欢你",
    "想你了",
    "你真好",
    "陪陪我",
)

_BOUNDARY_PHRASES = (
    "别烦我",
    "不要烦我",
    "别打扰我",
    "不要打扰我",
    "别这么叫我",
    "不要这么叫我",
    "别撒娇",
    "不要撒娇",
    "离我远点",
    "安静一点",
    "stop bothering me",
    "don't call me",
    "do not call me",
    "leave me alone",
)

_NEGATION_PREFIXES = ("不", "没", "没有", "并不", "不是", "不再", "not ")


@dataclass(frozen=True, slots=True)
class ConversationActionPlan:
    """描述当前对话状态对应的角色动作请求。"""

    action_name: str
    fallback_action: str = "idle"
    force_single_cycle: bool = False


class ConversationStateController:
    """使用保守本地规则维护当前应用会话中的动态人格状态。"""

    MIN_CLOSENESS = 0.35
    MAX_CLOSENESS = 0.65
    FRIENDLY_DELTA = 0.02
    BOUNDARY_DELTA = -0.05

    def __init__(self) -> None:
        """以平静、自然的默认状态开始一次新的应用会话。"""
        self._state = PersonaState()

    @property
    def current_state(self) -> PersonaState:
        """返回最近一次用户消息产生的不可变状态快照。"""
        return self._state

    def reset(self) -> PersonaState:
        """把会话状态恢复为安全默认值。"""
        self._state = PersonaState()
        return self._state

    def update(
        self,
        message: str,
        formal_qa_mode: bool,
        proactive_response: bool = False,
    ) -> PersonaState:
        """根据当前消息更新状态，每条消息最多调整一次亲近度。"""
        text = str(message or "").strip().lower()
        closeness = self._updated_closeness(text, proactive_response)

        if formal_qa_mode:
            state = PersonaState(EmotionState.THINKING, "normal", closeness, "formal")
        elif self._contains_explicit(text, _TIRED_PHRASES):
            state = PersonaState(EmotionState.SLEEPY, "low", closeness, "emotional_support")
        elif self._contains_explicit(text, _DISTRESS_PHRASES):
            state = PersonaState(EmotionState.SAD, "low", closeness, "emotional_support")
        elif self._contains_explicit(text, _TASK_PHRASES):
            state = PersonaState(EmotionState.THINKING, "normal", closeness, "task")
        elif self._contains_explicit(text, _POSITIVE_PHRASES):
            state = PersonaState(EmotionState.HAPPY, "high", closeness, "companion")
        elif self._contains_explicit(text, _GREETING_PHRASES):
            state = PersonaState(EmotionState.HAPPY, "normal", closeness, "companion")
        else:
            state = PersonaState(EmotionState.CALM, "normal", closeness, "companion")

        self._state = state
        return state

    def action_plan(
        self,
        state: PersonaState,
        waiting_for_api: bool,
    ) -> ConversationActionPlan:
        """把状态映射为现有精灵动作，不引入新的动作名称。"""
        if state.mode in {"formal", "task"}:
            action_name = "review"
        elif state.mode == "emotional_support":
            action_name = "waiting"
        elif state.mood == EmotionState.HAPPY and state.energy == "high":
            action_name = "jumping"
        elif state.mood == EmotionState.HAPPY:
            action_name = "waving"
        else:
            action_name = "running"

        if not waiting_for_api:
            return ConversationActionPlan(action_name, "idle", True)
        if action_name in {"waving", "jumping"}:
            return ConversationActionPlan(action_name, "waiting", True)
        return ConversationActionPlan(action_name, "idle", False)

    def _updated_closeness(self, text: str, proactive_response: bool) -> float:
        """按明确边界或友好信号保守调整亲近度。"""
        closeness = self._state.closeness
        if self._contains_explicit(text, _BOUNDARY_PHRASES):
            closeness += self.BOUNDARY_DELTA
        elif (
            proactive_response
            or self._contains_explicit(text, _POSITIVE_PHRASES)
            or self._contains_explicit(text, _GREETING_PHRASES)
            or self._contains_explicit(text, _FRIENDLY_PHRASES)
        ):
            closeness += self.FRIENDLY_DELTA
        return round(min(max(closeness, self.MIN_CLOSENESS), self.MAX_CLOSENESS), 2)

    @classmethod
    def _contains_explicit(cls, text: str, phrases: tuple[str, ...]) -> bool:
        """只匹配显式词组，并过滤常见否定表达。"""
        for phrase in phrases:
            for match in cls._matches(text, phrase):
                prefix = text[max(0, match.start() - 4) : match.start()]
                if any(prefix.endswith(negation) for negation in _NEGATION_PREFIXES):
                    continue
                return True
        return False

    @staticmethod
    def _matches(text: str, phrase: str) -> Iterator[re.Match[str]]:
        """英文按单词边界匹配，中文和混合词组按原文匹配。"""
        if phrase.isascii() and phrase.replace(" ", "").isalpha():
            return re.finditer(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", text)
        return re.finditer(re.escape(phrase), text)
