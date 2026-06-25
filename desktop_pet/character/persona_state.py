from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from character.emotion_state import EmotionState, parse_emotion_state


PERSONA_MODES = {"companion", "task", "emotional_support", "formal"}
ENERGY_LEVELS = {"low", "normal", "high"}


@dataclass(frozen=True, slots=True)
class PersonaState:
    """保存供后续人格调节使用的安全运行时状态。"""

    mood: EmotionState = EmotionState.CALM
    energy: str = "normal"
    closeness: float = 0.5
    mode: str = "companion"

    # 从字典读取人格状态字段，并构造 PersonaState 实例。
    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "PersonaState":
        """从字典读取人格状态字段，并构造 PersonaState 实例。"""
        source = value if isinstance(value, Mapping) else {}
        energy = _allowed_text(source.get("energy"), ENERGY_LEVELS, "normal")
        mode = _allowed_text(source.get("mode"), PERSONA_MODES, "companion")
        return cls(
            mood=parse_emotion_state(source.get("mood")),
            energy=energy,
            closeness=_closeness(source.get("closeness")),
            mode=mode,
        )

    # 把 PersonaState 转换为可写入 JSON 的字典结构。
    def to_dict(self) -> dict[str, Any]:
        """把 PersonaState 转换为可写入 JSON 的字典结构。"""
        result = asdict(self)
        result["mood"] = self.mood.value
        return result


# 根据 value 读取人格 状态并返回 PersonaState。
def read_persona_state(value: Mapping[str, Any] | PersonaState | None = None) -> PersonaState:
    """根据 value 读取人格 状态并返回 PersonaState。"""
    if isinstance(value, PersonaState):
        return value
    return PersonaState.from_mapping(value)


# 从角色配置中抽取行为策略字段，并压缩为提示词可用的短文本。
def compact_behavior_policy(character: Mapping[str, Any] | None) -> dict[str, str]:
    """从角色配置中抽取行为策略字段，并压缩为提示词可用的短文本。"""
    if not isinstance(character, Mapping):
        return {}
    behavior = character.get("behavior_policy")
    scenarios = character.get("scenario_reactions")
    result: dict[str, str] = {}
    if isinstance(behavior, Mapping):
        for key in ("proactive_style", "memory_usage", "boundary"):
            text = _text(behavior.get(key), 160)
            if text:
                result[key] = text
    if isinstance(scenarios, Mapping):
        quiet_rule = _text(scenarios.get("user_silent_long_time"), 160)
        if quiet_rule:
            result["user_silent_long_time"] = quiet_rule
    return result


# 根据 value、allowed、default 提取文本值并去除空白，无法使用时返回空字符串。
def _allowed_text(value: Any, allowed: set[str], default: str) -> str:
    """根据 value、allowed、default 提取文本值并去除空白，无法使用时返回空字符串。"""
    text = str(value or "").strip().lower()
    return text if text in allowed else default


# 根据 value 整理closeness，并把结果交给调用方或写回状态。
def _closeness(value: Any) -> float:
    """根据 value 整理closeness，并把结果交给调用方或写回状态。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    return min(max(number, 0.0), 1.0)


# 根据 value、limit 提取文本值并去除空白，无法使用时返回空字符串。
def _text(value: Any, limit: int) -> str:
    """根据 value、limit 提取文本值并去除空白，无法使用时返回空字符串。"""
    text = str(value or "").strip()
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "…"
